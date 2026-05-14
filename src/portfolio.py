"""Gestion du portefeuille: positions, P&L, historique des trades."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class Side(str, Enum):
    LONG = "LONG"
    FLAT = "FLAT"


@dataclass
class Trade:
    date: str
    action: str          # BUY / SELL
    price: float
    shares: float
    cost: float          # prix * shares (+ frais)
    reason: str = ""


@dataclass
class Position:
    side: Side = Side.FLAT
    entry_price: float = 0.0
    shares: float = 0.0
    entry_date: str = ""

    @property
    def is_open(self) -> bool:
        return self.side == Side.LONG and self.shares > 0

    def unrealized_pnl(self, current_price: float) -> float:
        if not self.is_open:
            return 0.0
        return (current_price - self.entry_price) * self.shares

    def unrealized_pct(self, current_price: float) -> float:
        if not self.is_open or self.entry_price == 0:
            return 0.0
        return (current_price - self.entry_price) / self.entry_price * 100


class Portfolio:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position = Position()
        self.trades: list[Trade] = []
        self.realized_pnl = 0.0

    # ── Ordres ────────────────────────────────────────────────────────────────

    def buy(self, price: float, pct_capital: float, date: str, reason: str = "") -> Optional[Trade]:
        """Achète avec un pourcentage du capital disponible."""
        if self.position.is_open:
            return None

        amount = self.cash * min(pct_capital, 0.99)
        shares = amount / price
        cost = shares * price

        if cost > self.cash:
            return None

        self.cash -= cost
        self.position = Position(
            side=Side.LONG,
            entry_price=price,
            shares=shares,
            entry_date=date,
        )

        trade = Trade(date=date, action="BUY", price=price, shares=shares, cost=cost, reason=reason)
        self.trades.append(trade)
        return trade

    def sell(self, price: float, date: str, reason: str = "") -> Optional[Trade]:
        """Ferme la position entière."""
        if not self.position.is_open:
            return None

        proceeds = self.position.shares * price
        pnl = (price - self.position.entry_price) * self.position.shares
        self.cash += proceeds
        self.realized_pnl += pnl

        trade = Trade(date=date, action="SELL", price=price, shares=self.position.shares, cost=proceeds, reason=reason)
        self.trades.append(trade)
        self.position = Position()
        return trade

    # ── Métriques ─────────────────────────────────────────────────────────────

    def total_value(self, current_price: float) -> float:
        position_value = self.position.shares * current_price if self.position.is_open else 0.0
        return self.cash + position_value

    def total_return_pct(self, current_price: float) -> float:
        return (self.total_value(current_price) - self.initial_capital) / self.initial_capital * 100

    def max_drawdown(self, price_series: list[float]) -> float:
        """Calcule le drawdown maximum sur une série de prix."""
        if not self.trades:
            return 0.0
        peak = self.initial_capital
        max_dd = 0.0
        equity = self.initial_capital
        for price in price_series:
            equity = self.total_value(price)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd * 100

    def win_rate(self) -> float:
        sell_trades = [t for t in self.trades if t.action == "SELL"]
        if not sell_trades:
            return 0.0
        buys = {i: t for i, t in enumerate(self.trades) if t.action == "BUY"}
        wins = 0
        buy_iter = iter(buys.values())
        for sell in sell_trades:
            try:
                buy = next(buy_iter)
                if sell.price > buy.price:
                    wins += 1
            except StopIteration:
                break
        return wins / len(sell_trades) * 100

    def summary(self, current_price: float) -> dict:
        return {
            "capital_initial": self.initial_capital,
            "cash": round(self.cash, 2),
            "valeur_totale": round(self.total_value(current_price), 2),
            "pnl_realise": round(self.realized_pnl, 2),
            "pnl_non_realise": round(self.position.unrealized_pnl(current_price), 2),
            "rendement_pct": round(self.total_return_pct(current_price), 2),
            "position_ouverte": self.position.is_open,
            "nb_trades": len([t for t in self.trades if t.action == "BUY"]),
            "taux_reussite": round(self.win_rate(), 1),
        }
