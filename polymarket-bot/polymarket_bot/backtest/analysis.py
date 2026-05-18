"""Analysis utilities for backtest results."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import structlog

from polymarket_bot.backtest.engine import Trade

logger = structlog.get_logger(__name__)

# Time segment definitions (UTC offsets from ET)
# US hours: 9:30-16:00 ET = 13:30-20:00 UTC (EST) or 14:30-21:00 UTC (EDT)
# Asian hours: 21:00-06:00 ET = 01:00-10:00 UTC (EST+1day) or 02:00-11:00 UTC (EDT+1day)
US_OPEN_HOUR = 13  # 9:30 ET approx in UTC (using EST)
US_OPEN_MINUTE = 30
US_CLOSE_HOUR = 20  # 16:00 ET in UTC (using EST)
US_CLOSE_MINUTE = 0

ASIAN_OPEN_HOUR = 1  # 21:00 ET prev day in UTC (EST)
ASIAN_CLOSE_HOUR = 10  # 06:00 ET in UTC (EST)


@dataclass
class TimeSegmentStats:
    """Statistics for a time segment."""

    segment_name: str
    total_trades: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0


@dataclass
class AnalysisReport:
    """Complete analysis report for backtest results."""

    win_rate_by_entry_price: list[dict[str, float]] = field(default_factory=list)
    break_even_price: Optional[float] = None
    time_segments: list[TimeSegmentStats] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    max_drawdown: float = 0.0
    drawdown_curve: list[float] = field(default_factory=list)
    nsf_adjusted_pnl: float = 0.0


class BacktestAnalysis:
    """Analysis utilities for backtest results.

    Provides:
        - Win rate vs entry price curves
        - Break-even calculations
        - Time-of-day segmentation (US, Asian, weekday/weekend)
        - NSF error incorporation
        - Equity curve and drawdown analysis
    """

    def __init__(self, nsf_penalty: float = 0.02) -> None:
        """Initialize analysis.

        Args:
            nsf_penalty: Penalty per NSF error as fraction of trade size.
        """
        self.nsf_penalty = nsf_penalty
        self._logger = logger.bind(component="analysis")

    def analyze(
        self,
        trades: list[Trade],
        nsf_count: int = 0,
    ) -> AnalysisReport:
        """Run full analysis on trade list.

        Args:
            trades: List of trades from backtest.
            nsf_count: Number of NSF (insufficient funds) errors.

        Returns:
            AnalysisReport with all analysis results.
        """
        report = AnalysisReport()

        if not trades:
            return report

        # Win rate by entry price
        report.win_rate_by_entry_price = self._win_rate_by_entry_price(trades)

        # Break-even calculation
        report.break_even_price = self._calculate_break_even(trades)

        # Time segmentation
        report.time_segments = self._time_segmentation(trades)

        # Equity curve and drawdown
        report.equity_curve = self._compute_equity_curve(trades)
        report.drawdown_curve = self._compute_drawdown_curve(report.equity_curve)
        report.max_drawdown = min(report.drawdown_curve) if report.drawdown_curve else 0.0

        # NSF adjustment
        total_pnl = sum(t.pnl for t in trades)
        nsf_cost = nsf_count * self.nsf_penalty
        report.nsf_adjusted_pnl = total_pnl - nsf_cost

        return report

    def _win_rate_by_entry_price(
        self, trades: list[Trade], n_buckets: int = 10
    ) -> list[dict[str, float]]:
        """Calculate win rate grouped by entry price buckets.

        Args:
            trades: List of trades.
            n_buckets: Number of price buckets.

        Returns:
            List of dicts with 'price_bucket', 'win_rate', 'count'.
        """
        if not trades:
            return []

        entry_prices = np.array([t.entry_price for t in trades])
        wins = np.array([1.0 if t.pnl > 0 else 0.0 for t in trades])

        min_price = entry_prices.min()
        max_price = entry_prices.max()

        if min_price == max_price:
            win_rate = float(wins.mean()) if len(wins) > 0 else 0.0
            return [{"price_bucket": float(min_price), "win_rate": win_rate, "count": float(len(trades))}]

        bucket_edges = np.linspace(min_price, max_price, n_buckets + 1)
        results = []

        for i in range(n_buckets):
            mask = (entry_prices >= bucket_edges[i]) & (entry_prices < bucket_edges[i + 1])
            if i == n_buckets - 1:
                mask = (entry_prices >= bucket_edges[i]) & (entry_prices <= bucket_edges[i + 1])

            count = mask.sum()
            if count > 0:
                win_rate = float(wins[mask].mean())
            else:
                win_rate = 0.0

            results.append({
                "price_bucket": float((bucket_edges[i] + bucket_edges[i + 1]) / 2),
                "win_rate": win_rate,
                "count": float(count),
            })

        return results

    def _calculate_break_even(self, trades: list[Trade]) -> Optional[float]:
        """Calculate break-even entry price.

        Finds the entry price where expected PnL crosses zero.

        Returns:
            Break-even price or None if cannot be determined.
        """
        if not trades:
            return None

        # Sort trades by entry price
        sorted_trades = sorted(trades, key=lambda t: t.entry_price)
        entry_prices = [t.entry_price for t in sorted_trades]
        pnls = [t.pnl for t in sorted_trades]

        # Compute cumulative average PnL moving through entry prices
        cum_pnl = np.cumsum(pnls)
        avg_pnl = cum_pnl / np.arange(1, len(pnls) + 1)

        # Find where average PnL crosses zero
        for i in range(1, len(avg_pnl)):
            if avg_pnl[i - 1] <= 0 <= avg_pnl[i] or avg_pnl[i - 1] >= 0 >= avg_pnl[i]:
                # Linear interpolation
                if avg_pnl[i] != avg_pnl[i - 1]:
                    frac = -avg_pnl[i - 1] / (avg_pnl[i] - avg_pnl[i - 1])
                    return entry_prices[i - 1] + frac * (entry_prices[i] - entry_prices[i - 1])
                return entry_prices[i]

        return None

    def _time_segmentation(self, trades: list[Trade]) -> list[TimeSegmentStats]:
        """Segment trades by time of day and day of week.

        Segments:
            - US hours (9:30-16:00 ET)
            - Asian hours (21:00-06:00 ET)
            - Weekday
            - Weekend
        """
        us_trades: list[Trade] = []
        asian_trades: list[Trade] = []
        weekday_trades: list[Trade] = []
        weekend_trades: list[Trade] = []

        for trade in trades:
            dt = datetime.fromtimestamp(trade.entry_time, tz=timezone.utc)
            hour = dt.hour
            minute = dt.minute
            weekday = dt.weekday()

            # US hours check (13:30-20:00 UTC for EST)
            time_minutes = hour * 60 + minute
            us_open_minutes = US_OPEN_HOUR * 60 + US_OPEN_MINUTE
            us_close_minutes = US_CLOSE_HOUR * 60 + US_CLOSE_MINUTE

            if us_open_minutes <= time_minutes < us_close_minutes:
                us_trades.append(trade)

            # Asian hours check (01:00-10:00 UTC for EST)
            if ASIAN_OPEN_HOUR <= hour < ASIAN_CLOSE_HOUR:
                asian_trades.append(trade)

            # Weekday vs weekend
            if weekday < 5:
                weekday_trades.append(trade)
            else:
                weekend_trades.append(trade)

        segments = [
            self._make_segment_stats("us_hours", us_trades),
            self._make_segment_stats("asian_hours", asian_trades),
            self._make_segment_stats("weekday", weekday_trades),
            self._make_segment_stats("weekend", weekend_trades),
        ]

        return segments

    @staticmethod
    def _make_segment_stats(name: str, trades: list[Trade]) -> TimeSegmentStats:
        """Compute stats for a trade segment."""
        if not trades:
            return TimeSegmentStats(segment_name=name)

        pnls = [t.pnl for t in trades]
        wins = sum(1 for p in pnls if p > 0)

        return TimeSegmentStats(
            segment_name=name,
            total_trades=len(trades),
            win_rate=wins / len(trades),
            avg_pnl=sum(pnls) / len(pnls),
            total_pnl=sum(pnls),
        )

    @staticmethod
    def _compute_equity_curve(trades: list[Trade]) -> list[float]:
        """Compute equity curve from trades."""
        equity = [0.0]
        cumulative = 0.0
        for trade in trades:
            cumulative += trade.pnl
            equity.append(cumulative)
        return equity

    @staticmethod
    def _compute_drawdown_curve(equity_curve: list[float]) -> list[float]:
        """Compute drawdown curve from equity curve."""
        if not equity_curve:
            return []

        equity = np.array(equity_curve)
        running_max = np.maximum.accumulate(equity)
        drawdown = equity - running_max
        return drawdown.tolist()
