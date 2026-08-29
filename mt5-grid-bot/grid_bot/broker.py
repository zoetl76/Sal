"""Types communs et interface courtier.

Le moteur de grille ne parle qu'a cette interface : la meme logique tourne donc
sur MetaTrader 5 (`MT5Broker`) et sur le simulateur du backtest (`SimBroker`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SymbolSpec:
    name: str
    digits: int
    point: float
    tick_size: float
    tick_value: float          # valeur d'un tick pour 1 lot, dans la devise du compte
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: float         # distance minimale ordre/marche, en unites de prix

    def normalize_price(self, price: float) -> float:
        return round(price, self.digits)

    def normalize_volume(self, volume: float) -> float:
        step = self.volume_step or 0.01
        vol = round(round(volume / step) * step, 8)
        vol = max(self.volume_min, min(self.volume_max, vol))
        # Le pas de volume porte rarement plus de 3 decimales chez les brokers CFD.
        return round(vol, 3)

    def money_per_price_unit(self, volume: float) -> float:
        """Gain/perte (devise du compte) pour 1 unite de prix sur `volume` lots."""
        if self.tick_size > 0 and self.tick_value > 0:
            return volume * self.tick_value / self.tick_size
        return volume * self.contract_size


@dataclass
class Tick:
    time: datetime
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2.0


@dataclass
class Account:
    balance: float
    equity: float
    margin: float
    margin_free: float
    currency: str = "USD"


@dataclass
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class Position:
    ticket: int
    side: str                  # "buy" | "sell"
    volume: float
    price_open: float
    tp: float = 0.0
    sl: float = 0.0
    profit: float = 0.0        # PnL flottant, swap et commission inclus si dispo
    comment: str = ""
    magic: int = 0
    time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PendingOrder:
    ticket: int
    side: str                  # "buy" | "sell"
    volume: float
    price: float
    tp: float = 0.0
    sl: float = 0.0
    comment: str = ""
    magic: int = 0


class BrokerError(RuntimeError):
    """Erreur non recuperable cote courtier."""


class Broker:
    """Interface minimale attendue par le moteur de grille."""

    def now(self) -> datetime:                       # pragma: no cover - interface
        raise NotImplementedError

    def symbol_spec(self) -> SymbolSpec:             # pragma: no cover - interface
        raise NotImplementedError

    def tick(self) -> Tick | None:                   # pragma: no cover - interface
        raise NotImplementedError

    def account(self) -> Account:                    # pragma: no cover - interface
        raise NotImplementedError

    def rates(self, timeframe: str, count: int) -> list[Bar]:   # pragma: no cover
        raise NotImplementedError

    def positions(self) -> list[Position]:           # pragma: no cover - interface
        raise NotImplementedError

    def orders(self) -> list[PendingOrder]:          # pragma: no cover - interface
        raise NotImplementedError

    def place_pending(self, side: str, volume: float, price: float,
                      tp: float, sl: float, comment: str) -> int | None:
        raise NotImplementedError                    # pragma: no cover - interface

    def cancel_order(self, ticket: int) -> bool:     # pragma: no cover - interface
        raise NotImplementedError

    def set_tp_sl(self, position: Position, tp: float, sl: float) -> bool:
        raise NotImplementedError                    # pragma: no cover - interface

    def close_position(self, position: Position) -> bool:   # pragma: no cover
        raise NotImplementedError
