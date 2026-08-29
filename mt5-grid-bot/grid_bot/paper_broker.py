"""Mode papier : cotations reelles du broker, ordres simules en memoire.

Aucun ordre n'est transmis au serveur. C'est le mode par defaut (`dry_run: true`)
et l'etape obligatoire avant de passer en reel.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .broker import Account, Bar, Broker, PendingOrder, Position, SymbolSpec, Tick
from .sim import SimCore


class PaperBroker(Broker):
    def __init__(self, market: Broker, logger: logging.Logger, balance: float = 10_000.0,
                 magic: int = 0, commission_per_lot: float = 0.0) -> None:
        self.market = market
        self.log = logger
        self.spec = market.symbol_spec()
        self.core = SimCore(spec=self.spec, balance=balance, magic=magic,
                            commission_per_lot=commission_per_lot)
        self._closed_seen = 0

    # -- lecture ------------------------------------------------------- #

    def now(self) -> datetime:
        return self.market.now()

    def symbol_spec(self) -> SymbolSpec:
        return self.spec

    def tick(self) -> Tick | None:
        tick = self.market.tick()
        if tick is not None:
            self.core.on_tick(tick)
            self._report_closed()
        return tick

    def account(self) -> Account:
        eq = self.core.equity()
        return Account(balance=self.core.balance, equity=eq, margin=0.0,
                       margin_free=eq, currency="USD")

    def rates(self, timeframe: str, count: int) -> list[Bar]:
        return self.market.rates(timeframe, count)

    def positions(self) -> list[Position]:
        return self.core.snapshot_positions(self.market.tick())

    def orders(self) -> list[PendingOrder]:
        return list(self.core.orders)

    # -- ecriture ------------------------------------------------------ #

    def place_pending(self, side: str, volume: float, price: float,
                      tp: float, sl: float, comment: str) -> int | None:
        ticket = self.core.place_pending(side, volume, price, tp, sl, comment)
        self.log.info("[PAPIER] %s-limit %.3f @ %.2f (TP %.2f) -> #%s",
                      side, volume, price, tp, ticket)
        return ticket

    def cancel_order(self, ticket: int) -> bool:
        self.log.info("[PAPIER] annulation ordre #%s", ticket)
        return self.core.cancel_order(ticket)

    def set_tp_sl(self, position: Position, tp: float, sl: float) -> bool:
        return self.core.set_tp_sl(position, tp, sl)

    def close_position(self, position: Position) -> bool:
        tick = self.market.tick()
        if tick is None:
            return False
        price = tick.bid if position.side == "buy" else tick.ask
        self.log.info("[PAPIER] cloture #%s @ %.2f", position.ticket, price)
        return self.core.close_position(position, price, tick.time, "manual")

    # ------------------------------------------------------------------ #

    def _report_closed(self) -> None:
        while self._closed_seen < len(self.core.closed):
            t = self.core.closed[self._closed_seen]
            self._closed_seen += 1
            self.log.info(
                "[PAPIER] %s %s %.3f @ %.2f -> %.2f | %+.2f | solde %.2f",
                t.reason.upper(), t.side, t.volume, t.price_open, t.price_close,
                t.profit, self.core.balance,
            )
