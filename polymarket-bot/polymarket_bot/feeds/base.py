"""Base feed class and Tick dataclass definition."""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Tick:
    """Normalized tick data from any feed source.

    Attributes:
        source: Feed source identifier (e.g., 'polymarket', 'binance', 'coinbase').
        token_id: Token or market identifier.
        price: Current price.
        timestamp: Unix timestamp of the tick.
        volume: Trade volume (if available).
        bid: Best bid price (if available).
        ask: Best ask price (if available).
        sequence_number: Sequence number for ordering.
    """

    source: str
    token_id: str
    price: float
    timestamp: float
    volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    sequence_number: int = 0

    def content_hash(self) -> str:
        """Generate a hash for deduplication based on tick content."""
        content = f"{self.source}:{self.token_id}:{self.price}:{self.timestamp}:{self.sequence_number}"
        return hashlib.md5(content.encode()).hexdigest()


class BaseFeed:
    """Base class for all feed implementations.

    Subclasses must implement connect(), disconnect(), and _listen().
    """

    def __init__(self, source_name: str) -> None:
        """Initialize the base feed.

        Args:
            source_name: Identifier for this feed source.
        """
        self.source_name = source_name
        self._running = False
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue()
        self._logger = logger.bind(feed=source_name)

    async def connect(self) -> None:
        """Establish connection to the feed. Override in subclass."""
        raise NotImplementedError

    async def disconnect(self) -> None:
        """Close connection to the feed. Override in subclass."""
        raise NotImplementedError

    async def _listen(self) -> AsyncIterator[Tick]:
        """Listen for ticks from the feed. Override in subclass."""
        raise NotImplementedError
        yield  # type: ignore[misc]

    async def start(self) -> None:
        """Start the feed and begin producing ticks."""
        self._running = True
        await self.connect()
        self._logger.info("feed_started")

    async def stop(self) -> None:
        """Stop the feed and close connections."""
        self._running = False
        await self.disconnect()
        self._logger.info("feed_stopped")

    @property
    def is_running(self) -> bool:
        """Whether the feed is currently active."""
        return self._running
