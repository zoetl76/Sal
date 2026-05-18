"""Data models for historical data storage."""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Re-export the canonical Tick from feeds.base to avoid dual Tick classes.
from polymarket_bot.feeds.base import Tick


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Order book depth snapshot.

    Attributes:
        timestamp: Unix timestamp of snapshot.
        token_id: Token or market identifier.
        bids: List of [price, size] pairs.
        asks: List of [price, size] pairs.
    """

    timestamp: float
    token_id: str
    bids: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    asks: tuple[tuple[float, float], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot to dictionary."""
        return {
            "timestamp": self.timestamp,
            "token_id": self.token_id,
            "bids": [list(b) for b in self.bids],
            "asks": [list(a) for a in self.asks],
        }

    def to_json(self) -> str:
        """Serialize snapshot to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderBookSnapshot":
        """Deserialize snapshot from dictionary."""
        return cls(
            timestamp=float(data["timestamp"]),
            token_id=data["token_id"],
            bids=tuple(tuple(b) for b in data.get("bids", [])),
            asks=tuple(tuple(a) for a in data.get("asks", [])),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "OrderBookSnapshot":
        """Deserialize snapshot from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class Fill:
    """Trade fill record.

    Attributes:
        timestamp: Unix timestamp of fill.
        token_id: Token or market identifier.
        price: Execution price.
        size: Fill size.
        side: Trade side ('buy' or 'sell').
        slippage: Price slippage from expected.
    """

    timestamp: float
    token_id: str
    price: float
    size: float
    side: str
    slippage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize fill to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize fill to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fill":
        """Deserialize fill from dictionary."""
        return cls(
            timestamp=float(data["timestamp"]),
            token_id=data["token_id"],
            price=float(data["price"]),
            size=float(data["size"]),
            side=data["side"],
            slippage=float(data.get("slippage", 0.0)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "Fill":
        """Deserialize fill from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class SlippageRecord:
    """Record of observed slippage for analysis.

    Attributes:
        timestamp: Unix timestamp.
        token_id: Token or market identifier.
        expected_price: Expected execution price.
        actual_price: Actual execution price.
        size: Order size.
        side: Trade side.
        slippage_bps: Slippage in basis points.
    """

    timestamp: float
    token_id: str
    expected_price: float
    actual_price: float
    size: float
    side: str
    slippage_bps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize slippage record to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize slippage record to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlippageRecord":
        """Deserialize slippage record from dictionary."""
        return cls(
            timestamp=float(data["timestamp"]),
            token_id=data["token_id"],
            expected_price=float(data["expected_price"]),
            actual_price=float(data["actual_price"]),
            size=float(data["size"]),
            side=data["side"],
            slippage_bps=float(data.get("slippage_bps", 0.0)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "SlippageRecord":
        """Deserialize slippage record from JSON string."""
        return cls.from_dict(json.loads(json_str))
