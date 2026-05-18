"""Data models for historical data storage."""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Tick:
    """Tick data for persistence.

    Attributes:
        source: Feed source identifier.
        token_id: Token or market identifier.
        price: Current price.
        timestamp: Unix timestamp.
        volume: Trade volume.
        bid: Best bid price.
        ask: Best ask price.
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
