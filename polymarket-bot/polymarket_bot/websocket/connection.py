"""Single WebSocket connection wrapper.

Tracks connection-level metrics including jitter EMA and implements
Layer 4 (first-tick skip) by dropping the very first tick from any
new connection.
"""

import asyncio
import time
import uuid
from typing import Any, Optional

import structlog

from polymarket_bot.feeds.base import Tick

logger = structlog.get_logger(__name__)


class WebSocketConnection:
    """Single websocket connection with jitter tracking and first-tick skip.

    Attributes:
        connection_id: Unique identifier for this connection.
        created_at: Timestamp when this connection was created.
        last_tick_time: Timestamp of the last received tick.
        tick_count: Total number of ticks received (including skipped first tick).
        jitter_ema: Exponential moving average of inter-tick jitter (ms).
        is_in_grace_period: Whether the connection is within 8s grace period.
    """

    GRACE_PERIOD_SECONDS: float = 8.0
    JITTER_EMA_ALPHA: float = 0.3  # EMA smoothing factor
    INTERVAL_EMA_ALPHA: float = 0.1  # Smoothing factor for expected interval

    def __init__(self, url: str, connection_id: Optional[str] = None) -> None:
        """Initialize a websocket connection wrapper.

        Args:
            url: WebSocket URL to connect to.
            connection_id: Optional identifier; auto-generated if not provided.
        """
        self.url = url
        self.connection_id = connection_id or str(uuid.uuid4())[:8]
        self.created_at: float = time.time()
        self.last_tick_time: float = 0.0
        self.tick_count: int = 0
        self.jitter_ema: float = 0.0
        self._interval_ema: float = 0.0  # Expected (mean) interval for jitter calc
        self._first_tick_skipped: bool = False
        self._ws: Any = None
        self._connected: bool = False
        self._logger = logger.bind(conn_id=self.connection_id)

    @property
    def is_in_grace_period(self) -> bool:
        """Check if connection is still within the 8-second grace period."""
        return (time.time() - self.created_at) < self.GRACE_PERIOD_SECONDS

    @property
    def age_seconds(self) -> float:
        """Get the age of this connection in seconds."""
        return time.time() - self.created_at

    @property
    def is_connected(self) -> bool:
        """Whether the underlying websocket is connected."""
        return self._connected

    async def connect(self) -> None:
        """Establish the websocket connection."""
        try:
            import websockets

            self._ws = await websockets.connect(self.url)
            self._connected = True
            self.created_at = time.time()
            self._logger.debug("connection_established", url=self.url)
        except Exception as e:
            self._connected = False
            self._logger.error("connection_failed", url=self.url, error=str(e))
            raise

    async def disconnect(self) -> None:
        """Close the websocket connection and reset state."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        self._ws = None
        self._logger.debug("connection_closed")

    async def send(self, message: str) -> None:
        """Send a message over the websocket.

        Args:
            message: String message to send.
        """
        if self._ws:
            await self._ws.send(message)

    async def receive(self) -> Optional[str]:
        """Receive a message from the websocket.

        Returns:
            Received message string, or None if disconnected.
        """
        if not self._ws:
            return None
        try:
            return await self._ws.recv()
        except Exception:
            self._connected = False
            return None

    def update_jitter_ema(self, tick_time: float) -> None:
        """Update the jitter EMA based on inter-tick timing.

        Jitter is the absolute deviation from the expected (mean) tick interval.
        Uses exponential moving average for smoothing both the expected interval
        and the jitter itself.

        Args:
            tick_time: Timestamp of the current tick.
        """
        if self.last_tick_time > 0:
            interval_ms = (tick_time - self.last_tick_time) * 1000.0
            # Update the expected interval EMA
            if self._interval_ema == 0.0:
                self._interval_ema = interval_ms
            else:
                self._interval_ema = (
                    self.INTERVAL_EMA_ALPHA * interval_ms
                    + (1 - self.INTERVAL_EMA_ALPHA) * self._interval_ema
                )
            # Jitter is deviation from expected interval
            jitter = abs(interval_ms - self._interval_ema)
            if self.jitter_ema == 0.0:
                self.jitter_ema = jitter
            else:
                self.jitter_ema = (
                    self.JITTER_EMA_ALPHA * jitter
                    + (1 - self.JITTER_EMA_ALPHA) * self.jitter_ema
                )
        self.last_tick_time = tick_time

    def process_tick(self, tick: Tick) -> Optional[Tick]:
        """Process an incoming tick through Layer 4 (first-tick skip).

        The very first tick from a new connection is dropped to avoid
        stale/cached data that exchanges often send on connect.

        Args:
            tick: The incoming tick to process.

        Returns:
            The tick if it passes, None if it was the first tick (skipped).
        """
        self.tick_count += 1
        self.update_jitter_ema(tick.timestamp)

        # Layer 4: First-tick skip
        if not self._first_tick_skipped:
            self._first_tick_skipped = True
            self._logger.debug("first_tick_skipped", tick_price=tick.price)
            return None

        return tick

    def reset(self) -> None:
        """Reset connection tracking state (used after respawn)."""
        self.created_at = time.time()
        self.last_tick_time = 0.0
        self.tick_count = 0
        self.jitter_ema = 0.0
        self._interval_ema = 0.0
        self._first_tick_skipped = False
