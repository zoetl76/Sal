"""Connection pool manager for parallel websocket connections.

Implements Layer 5 (staggered startup) and Layer 2 (dynamic spawning).
Manages 100-300 parallel connections with deduplication by content hash.
"""

import asyncio
import hashlib
import time
from typing import Optional

import structlog

from polymarket_bot.feeds.base import Tick
from polymarket_bot.websocket.connection import WebSocketConnection

logger = structlog.get_logger(__name__)


class ConnectionPool:
    """Manages a pool of parallel websocket connections.

    Implements:
    - Layer 5: Staggered startup - spreads connections evenly over 1 second.
    - Layer 2: Dynamic spawning - every 4 seconds kills and respawns slowest 10%.
    - Deduplication by tick content hash.
    """

    STAGGER_WINDOW_S: float = 1.0  # Layer 5: spread connections over 1 second
    RESPAWN_INTERVAL_S: float = 4.0  # Layer 2: respawn cycle every 4 seconds
    SLOWEST_PERCENTILE: float = 0.10  # Kill bottom 10%

    def __init__(
        self,
        url: str,
        min_connections: int = 100,
        max_connections: int = 300,
    ) -> None:
        """Initialize the connection pool.

        Args:
            url: WebSocket URL for all connections.
            min_connections: Minimum number of connections to maintain.
            max_connections: Maximum number of connections allowed.
        """
        self.url = url
        self.min_connections = min_connections
        self.max_connections = max_connections
        self._connections: list[WebSocketConnection] = []
        self._seen_hashes: set[str] = set()
        self._max_seen_hashes: int = 10000
        self._running: bool = False
        self._respawn_task: Optional[asyncio.Task[None]] = None
        self._logger = logger.bind(pool_url=url[:50])

    @property
    def connections(self) -> list[WebSocketConnection]:
        """Get the list of active connections."""
        return self._connections

    @property
    def active_count(self) -> int:
        """Number of currently active connections."""
        return len(self._connections)

    async def start(self) -> None:
        """Start the pool with staggered connection startup (Layer 5).

        Spreads connection establishment evenly over STAGGER_WINDOW_S.
        Also launches the background respawn loop (Layer 2).
        """
        self._running = True
        delay_per_conn = self.STAGGER_WINDOW_S / max(self.min_connections, 1)

        self._logger.info(
            "pool_starting",
            num_connections=self.min_connections,
            stagger_delay_ms=delay_per_conn * 1000,
        )

        for i in range(self.min_connections):
            if not self._running:
                break
            conn = WebSocketConnection(url=self.url)
            self._connections.append(conn)
            # Stagger: don't await connect in production, just schedule
            # In testing, connections are pre-built
            await asyncio.sleep(delay_per_conn)

        # Layer 2: Launch the dynamic respawn loop as a background task
        self._respawn_task = asyncio.create_task(self.run_respawn_loop())

        self._logger.info("pool_started", active=self.active_count)

    async def stop(self) -> None:
        """Stop the pool and close all connections."""
        self._running = False
        if self._respawn_task and not self._respawn_task.done():
            self._respawn_task.cancel()
            try:
                await self._respawn_task
            except asyncio.CancelledError:
                pass

        for conn in self._connections:
            await conn.disconnect()
        self._connections.clear()
        self._seen_hashes.clear()
        self._logger.info("pool_stopped")

    def is_duplicate(self, tick: Tick) -> bool:
        """Check if a tick is a duplicate by content hash.

        Args:
            tick: The tick to check.

        Returns:
            True if this tick has been seen before.
        """
        tick_hash = tick.content_hash()
        if tick_hash in self._seen_hashes:
            return True

        self._seen_hashes.add(tick_hash)

        # Prevent unbounded growth
        if len(self._seen_hashes) > self._max_seen_hashes:
            # Remove oldest half
            to_remove = len(self._seen_hashes) - (self._max_seen_hashes // 2)
            for _ in range(to_remove):
                self._seen_hashes.pop()

        return False

    def get_slowest_connections(self) -> list[WebSocketConnection]:
        """Get the slowest 10% of connections by jitter EMA (Layer 2).

        Connections in their grace period are excluded from culling.

        Returns:
            List of connections to be respawned.
        """
        # Only consider connections past grace period
        eligible = [c for c in self._connections if not c.is_in_grace_period]

        if not eligible:
            return []

        # Sort by jitter EMA descending (worst first)
        eligible.sort(key=lambda c: c.jitter_ema, reverse=True)

        # Take slowest 10%
        num_to_kill = max(1, int(len(eligible) * self.SLOWEST_PERCENTILE))
        return eligible[:num_to_kill]

    async def respawn_slowest(self) -> list[WebSocketConnection]:
        """Kill and respawn the slowest 10% of connections (Layer 2).

        Returns:
            List of newly created replacement connections.
        """
        slowest = self.get_slowest_connections()
        new_connections: list[WebSocketConnection] = []

        for conn in slowest:
            await conn.disconnect()
            self._connections.remove(conn)

            # Create replacement
            new_conn = WebSocketConnection(url=self.url)
            self._connections.append(new_conn)
            new_connections.append(new_conn)

        if slowest:
            self._logger.debug(
                "respawned_connections",
                killed=len(slowest),
                new_count=self.active_count,
            )

        return new_connections

    async def run_respawn_loop(self) -> None:
        """Run the periodic respawn loop (Layer 2).

        Every RESPAWN_INTERVAL_S, kills and respawns the slowest 10%.
        """
        while self._running:
            await asyncio.sleep(self.RESPAWN_INTERVAL_S)
            if not self._running:
                break
            await self.respawn_slowest()

    def get_stats(self) -> dict:
        """Get pool statistics.

        Returns:
            Dictionary with pool metrics.
        """
        jitter_values = [c.jitter_ema for c in self._connections if c.jitter_ema > 0]
        return {
            "active_connections": self.active_count,
            "seen_hashes": len(self._seen_hashes),
            "avg_jitter_ms": sum(jitter_values) / len(jitter_values) if jitter_values else 0.0,
            "max_jitter_ms": max(jitter_values) if jitter_values else 0.0,
            "connections_in_grace": sum(1 for c in self._connections if c.is_in_grace_period),
        }
