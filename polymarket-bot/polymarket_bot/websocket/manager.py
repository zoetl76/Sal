"""Top-level WebSocket manager orchestrating all 6 layers.

Provides async iterator interface for consuming validated ticks.
Coordinates warmup -> active trading -> shutdown lifecycle.
"""

import asyncio
import time
from typing import AsyncIterator, Optional

import structlog

from polymarket_bot.feeds.base import Tick
from polymarket_bot.websocket.connection import WebSocketConnection
from polymarket_bot.websocket.guards import JitterReaper, StaleTickGuard
from polymarket_bot.websocket.pool import ConnectionPool
from polymarket_bot.websocket.warmup import WarmupManager

logger = structlog.get_logger(__name__)


class WebSocketManager:
    """Orchestrates the 6-layer websocket system.

    Layers:
        1. Warmup (15s pre-trade, 5s quality gate)
        2. Dynamic spawning (kill/respawn slowest 10% every 4s)
        3. Stale tick guard (reject >15c delta from warmup)
        4. First-tick skip (drop first tick per connection)
        5. Staggered startup (spread connections over 1s)
        6. Anti-jitter reaper (EMA tracking, grace period, budget)

    Methods:
        start(token_ids): Begin the lifecycle (warmup -> active).
        stop(): Shut down all connections.
        get_tick_stream(): Async iterator of validated ticks.
        get_stats(): Current system statistics.
    """

    def __init__(
        self,
        url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market",
        num_connections: int = 100,
        max_connections: int = 300,
    ) -> None:
        """Initialize the WebSocket manager.

        Args:
            url: WebSocket URL for connections.
            num_connections: Number of parallel connections.
            max_connections: Maximum connections allowed.
        """
        self.url = url
        self.num_connections = num_connections
        self.max_connections = max_connections

        self._pool = ConnectionPool(
            url=url,
            min_connections=num_connections,
            max_connections=max_connections,
        )
        self._warmup: Optional[WarmupManager] = None
        self._stale_guard = StaleTickGuard()
        self._jitter_reaper = JitterReaper()
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue()
        self._running = False
        self._warmup_complete = False
        self._respawn_task: Optional[asyncio.Task[None]] = None
        self._reaper_task: Optional[asyncio.Task[None]] = None
        self._logger = logger.bind(component="ws_manager")

    @property
    def is_running(self) -> bool:
        """Whether the manager is actively running."""
        return self._running

    @property
    def is_warmed_up(self) -> bool:
        """Whether warmup has completed successfully."""
        return self._warmup_complete

    async def start(self, token_ids: Optional[list[str]] = None) -> bool:
        """Start the websocket system lifecycle.

        Performs warmup, then transitions to active trading mode.

        Args:
            token_ids: List of token IDs to subscribe to.

        Returns:
            True if warmup passed and system is active, False otherwise.
        """
        token_ids = token_ids or []
        self._running = True

        self._logger.info("manager_starting", tokens=len(token_ids))

        # Layer 1: Warmup
        self._warmup = WarmupManager(token_ids=token_ids)
        self._warmup.start()

        # Layer 5: Staggered startup
        await self._pool.start()

        self._logger.info("manager_started", pool_size=self._pool.active_count)
        return True

    async def complete_warmup(self) -> bool:
        """Complete the warmup phase and transition to active trading.

        Returns:
            True if quality gate passed.
        """
        if not self._warmup:
            return False

        passed = self._warmup.finish()

        if passed:
            self._warmup_complete = True
            # Set warmup prices for stale tick guard (Layer 3)
            self._stale_guard.set_warmup_prices(self._warmup.warmup_prices)
            self._logger.info("warmup_passed", prices=self._warmup.warmup_prices)
        else:
            self._logger.warning("warmup_failed")

        return passed

    def process_tick(self, tick: Tick, connection: WebSocketConnection) -> Optional[Tick]:
        """Process a tick through all validation layers.

        Args:
            tick: The incoming tick.
            connection: The connection that produced this tick.

        Returns:
            The validated tick, or None if rejected by any layer.
        """
        # During warmup, feed ticks to warmup manager
        if self._warmup and self._warmup.is_warming_up:
            self._warmup.process_tick(tick)
            # During warmup, still apply first-tick skip
            tick_result = connection.process_tick(tick)
            return tick_result

        # Layer 4: First-tick skip (handled by connection)
        tick_result = connection.process_tick(tick)
        if tick_result is None:
            return None

        # Deduplication
        if self._pool.is_duplicate(tick_result):
            return None

        # Layer 3: Stale tick guard
        if not self._stale_guard.check(tick_result):
            return None

        return tick_result

    async def get_tick_stream(self) -> AsyncIterator[Tick]:
        """Async iterator that yields validated ticks.

        Yields:
            Validated Tick objects that passed all layers.
        """
        while self._running:
            try:
                tick = await asyncio.wait_for(
                    self._tick_queue.get(), timeout=1.0
                )
                yield tick
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        """Shut down the websocket system."""
        self._running = False

        if self._respawn_task and not self._respawn_task.done():
            self._respawn_task.cancel()
            try:
                await self._respawn_task
            except asyncio.CancelledError:
                pass

        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

        await self._pool.stop()
        self._logger.info("manager_stopped")

    def get_stats(self) -> dict:
        """Get comprehensive system statistics.

        Returns:
            Dictionary with stats from all layers.
        """
        return {
            "running": self._running,
            "warmed_up": self._warmup_complete,
            "pool": self._pool.get_stats(),
            "stale_guard": self._stale_guard.get_stats(),
            "jitter_reaper": self._jitter_reaper.get_stats(),
            "tick_queue_size": self._tick_queue.qsize(),
        }
