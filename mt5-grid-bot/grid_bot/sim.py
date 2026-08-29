"""Moteur de simulation d'ordres.

Sert a deux choses :
  * le mode papier (`dry_run`) : prix reels de MT5, ordres simules ;
  * le backtest : prix historiques rejoues, ordres simules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .broker import Account, Bar, Broker, PendingOrder, Position, SymbolSpec, Tick


@dataclass
class ClosedTrade:
    ticket: int
    side: str
    volume: float
    price_open: float
    price_close: float
    profit: float
    opened_at: datetime
    closed_at: datetime
    reason: str          # "tp" | "sl" | "manual"
    comment: str = ""


@dataclass
class SimCore:
    """Carnet d'ordres et de positions simule, aligne sur la semantique MT5."""

    spec: SymbolSpec
    balance: float = 10_000.0
    magic: int = 0
    commission_per_lot: float = 0.0     # aller-retour, dans la devise du compte
    positions: list[Position] = field(default_factory=list)
    orders: list[PendingOrder] = field(default_factory=list)
    closed: list[ClosedTrade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    _next_ticket: int = 1
    _last: Tick | None = None

    # ------------------------------------------------------------------ #

    def ticket(self) -> int:
        self._next_ticket += 1
        return self._next_ticket

    def place_pending(self, side: str, volume: float, price: float,
                      tp: float, sl: float, comment: str) -> int:
        order = PendingOrder(
            ticket=self.ticket(), side=side, volume=volume, price=price,
            tp=tp, sl=sl, comment=comment, magic=self.magic,
        )
        self.orders.append(order)
        return order.ticket

    def cancel_order(self, ticket: int) -> bool:
        before = len(self.orders)
        self.orders = [o for o in self.orders if o.ticket != ticket]
        return len(self.orders) < before

    def set_tp_sl(self, position: Position, tp: float, sl: float) -> bool:
        for p in self.positions:
            if p.ticket == position.ticket:
                p.tp, p.sl = tp, sl
                return True
        return False

    # ------------------------------------------------------------------ #

    def money(self, volume: float, price_delta: float) -> float:
        return price_delta * self.spec.money_per_price_unit(volume)

    def _pnl(self, pos: Position, price: float) -> float:
        delta = (price - pos.price_open) if pos.side == "buy" else (pos.price_open - price)
        return self.money(pos.volume, delta)

    def close_position(self, position: Position, price: float, when: datetime,
                       reason: str = "manual") -> bool:
        for i, p in enumerate(self.positions):
            if p.ticket != position.ticket:
                continue
            profit = self._pnl(p, price) - self.commission_per_lot * p.volume
            self.balance += profit
            self.closed.append(ClosedTrade(
                ticket=p.ticket, side=p.side, volume=p.volume,
                price_open=p.price_open, price_close=price, profit=profit,
                opened_at=p.time, closed_at=when, reason=reason, comment=p.comment,
            ))
            self.positions.pop(i)
            return True
        return False

    def snapshot_positions(self, tick: Tick | None) -> list[Position]:
        """Copie des positions avec leur PnL flottant valorise au tick courant."""
        tick = tick or self._last
        out: list[Position] = []
        for p in self.positions:
            price = (tick.bid if p.side == "buy" else tick.ask) if tick else p.price_open
            out.append(Position(
                ticket=p.ticket, side=p.side, volume=p.volume, price_open=p.price_open,
                tp=p.tp, sl=p.sl, profit=self._pnl(p, price), comment=p.comment,
                magic=p.magic, time=p.time,
            ))
        return out

    def floating(self, tick: Tick) -> float:
        total = 0.0
        for p in self.positions:
            price = tick.bid if p.side == "buy" else tick.ask
            total += self._pnl(p, price)
        return total

    def equity(self, tick: Tick | None = None) -> float:
        tick = tick or self._last
        return self.balance + (self.floating(tick) if tick else 0.0)

    # ------------------------------------------------------------------ #

    def on_tick(self, tick: Tick) -> None:
        """Declenche les executions d'ordres en attente puis les TP/SL."""
        self._last = tick
        self._match_pending(tick)
        self._match_exits(tick)
        self.equity_curve.append((tick.time, self.equity(tick)))

    def _match_pending(self, tick: Tick) -> None:
        remaining: list[PendingOrder] = []
        for o in self.orders:
            hit = (o.side == "buy" and tick.ask <= o.price) or \
                  (o.side == "sell" and tick.bid >= o.price)
            if not hit:
                remaining.append(o)
                continue
            self.positions.append(Position(
                ticket=o.ticket, side=o.side, volume=o.volume,
                price_open=o.price, tp=o.tp, sl=o.sl,
                comment=o.comment, magic=o.magic, time=tick.time,
            ))
        self.orders = remaining

    def _match_exits(self, tick: Tick) -> None:
        for pos in list(self.positions):
            price = tick.bid if pos.side == "buy" else tick.ask
            if pos.tp:
                hit = price >= pos.tp if pos.side == "buy" else price <= pos.tp
                if hit:
                    self.close_position(pos, pos.tp, tick.time, "tp")
                    continue
            if pos.sl:
                hit = price <= pos.sl if pos.side == "buy" else price >= pos.sl
                if hit:
                    self.close_position(pos, pos.sl, tick.time, "sl")


def bar_to_ticks(bar: Bar, spread: float) -> list[Tick]:
    """Chemin intra-barre approxime : O -> extreme oppose -> extreme -> C.

    Convention prudente : sur une bougie haussiere on visite le bas avant le haut,
    ce qui evite de surestimer les executions favorables d'une grille.
    """
    path = ([bar.open, bar.low, bar.high, bar.close]
            if bar.close >= bar.open else
            [bar.open, bar.high, bar.low, bar.close])
    return [Tick(time=bar.time, bid=p, ask=p + spread) for p in path]


class SimBroker(Broker):
    """Courtier simule pilote par une liste de bougies (backtest)."""

    def __init__(self, spec: SymbolSpec, bars: list[Bar], balance: float = 10_000.0,
                 spread: float = 20.0, commission_per_lot: float = 0.0,
                 magic: int = 0, atr_bars: list[Bar] | None = None) -> None:
        self.spec = spec
        self.bars = bars
        self.spread = spread
        self.core = SimCore(spec=spec, balance=balance, magic=magic,
                            commission_per_lot=commission_per_lot)
        self._tick: Tick | None = None
        self._history: list[Bar] = []
        self._atr_bars = atr_bars

    # -- lecture ------------------------------------------------------- #

    def now(self) -> datetime:
        return self._tick.time if self._tick else datetime.now(timezone.utc)

    def symbol_spec(self) -> SymbolSpec:
        return self.spec

    def tick(self) -> Tick | None:
        return self._tick

    def account(self) -> Account:
        eq = self.core.equity(self._tick)
        return Account(balance=self.core.balance, equity=eq, margin=0.0,
                       margin_free=eq, currency="USD")

    def rates(self, timeframe: str, count: int) -> list[Bar]:
        source = self._atr_bars if self._atr_bars is not None else self._history
        return source[-count:] if source else []

    def positions(self) -> list[Position]:
        return self.core.snapshot_positions(self._tick)

    def orders(self) -> list[PendingOrder]:
        return list(self.core.orders)

    # -- ecriture ------------------------------------------------------ #

    def place_pending(self, side: str, volume: float, price: float,
                      tp: float, sl: float, comment: str) -> int | None:
        return self.core.place_pending(side, volume, price, tp, sl, comment)

    def cancel_order(self, ticket: int) -> bool:
        return self.core.cancel_order(ticket)

    def set_tp_sl(self, position: Position, tp: float, sl: float) -> bool:
        return self.core.set_tp_sl(position, tp, sl)

    def close_position(self, position: Position) -> bool:
        if self._tick is None:
            return False
        price = self._tick.bid if position.side == "buy" else self._tick.ask
        return self.core.close_position(position, price, self._tick.time, "manual")

    # -- deroulement --------------------------------------------------- #

    def feed(self, bar: Bar) -> None:
        """Rejoue une bougie : execute les ordres puis expose son close comme tick."""
        self._history.append(bar)
        for tick in bar_to_ticks(bar, self.spread):
            self._tick = tick
            self.core.on_tick(tick)
