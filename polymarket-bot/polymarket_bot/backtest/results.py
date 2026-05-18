"""Backtest result dataclass and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from polymarket_bot.backtest.engine import Trade


@dataclass
class BacktestResult:
    """Complete backtest result with performance metrics.

    Attributes:
        trades: List of individual trades.
        total_pnl: Total profit and loss.
        equity_curve: List of cumulative PnL values.
        initial_capital: Starting capital.
        params: Strategy parameters used.
        timestamps: Timestamps corresponding to equity curve.
    """

    trades: list[Any] = field(default_factory=list)
    total_pnl: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    initial_capital: float = 10000.0
    params: dict[str, Any] = field(default_factory=dict)
    timestamps: list[float] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        """Total number of trades executed."""
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        """Fraction of profitable trades."""
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def avg_pnl(self) -> float:
        """Average PnL per trade."""
        if not self.trades:
            return 0.0
        return self.total_pnl / len(self.trades)

    @property
    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio from equity curve returns."""
        if len(self.equity_curve) < 2:
            return 0.0

        equity = np.array(self.equity_curve)
        returns = np.diff(equity)

        if returns.std() == 0:
            return 0.0

        # Assume daily frequency, annualize with sqrt(252)
        return float(returns.mean() / returns.std() * np.sqrt(252))

    @property
    def max_drawdown(self) -> float:
        """Maximum drawdown from peak."""
        if not self.equity_curve:
            return 0.0

        equity = np.array(self.equity_curve)
        running_max = np.maximum.accumulate(equity)
        drawdowns = equity - running_max
        return float(drawdowns.min())

    @property
    def profit_factor(self) -> float:
        """Ratio of gross profit to gross loss."""
        if not self.trades:
            return 0.0

        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def summary(self) -> dict[str, Any]:
        """Generate summary report dictionary."""
        return {
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "total_pnl": self.total_pnl,
            "avg_pnl": self.avg_pnl,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "profit_factor": self.profit_factor,
            "initial_capital": self.initial_capital,
            "params": self.params,
        }

    def __repr__(self) -> str:
        """String representation with key metrics."""
        return (
            f"BacktestResult(trades={self.total_trades}, "
            f"pnl={self.total_pnl:.4f}, "
            f"win_rate={self.win_rate:.2%}, "
            f"sharpe={self.sharpe_ratio:.2f}, "
            f"max_dd={self.max_drawdown:.4f})"
        )
