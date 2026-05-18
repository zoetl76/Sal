"""Base feed class and Tick dataclass definition."""

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Optional

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

    def to_dict(self) -> dict[str, Any]:
        """Serialize tick to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize tick to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tick":
        """Deserialize tick from dictionary."""
        return cls(
            source=data["source"],
            token_id=data["token_id"],
            price=float(data["price"]),
            timestamp=float(data["timestamp"]),
            volume=float(data.get("volume", 0.0)),
            bid=float(data.get("bid", 0.0)),
            ask=float(data.get("ask", 0.0)),
            sequence_number=int(data.get("sequence_number", 0)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "Tick":
        """Deserialize tick from JSON string."""
        return cls.from_dict(json.loads(json_str))


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
