"""Issue handling: stale data recovery, adverse selection, over-optimistic detection."""

import time
from collections import deque
from typing import Any, Optional

import numpy as np
import structlog

from polymarket_bot.data.models import Tick

logger = structlog.get_logger(__name__)


class IssueHandler:
    """Handles operational issues during trading.

    Features:
    - Stale/jittery data detection and recovery
    - Adverse selection tracking (fill-side analysis)
    - Over-optimistic result detection (live vs backtest divergence)
    """

    def __init__(
        self,
        stale_threshold_s: float = 10.0,
        jitter_threshold_ms: float = 50.0,
        divergence_std_devs: float = 2.0,
    ) -> None:
        """Initialize issue handler.

        Args:
            stale_threshold_s: Seconds without tick to flag stale data.
            jitter_threshold_ms: Threshold in ms for jitter detection.
            divergence_std_devs: Std devs for over-optimistic detection.
        """
        self._stale_threshold = stale_threshold_s
        self._jitter_threshold_ms = jitter_threshold_ms
        self._divergence_std_devs = divergence_std_devs

        # Stale data tracking
        self._last_tick_time: dict[str, float] = {}
        self._stale_flags: dict[str, bool] = {}
        self._reconnect_count: int = 0

        # Jitter tracking
        self._tick_intervals: dict[str, deque[float]] = {}

        # Adverse selection tracking
        self._fill_sides: deque[str] = deque(maxlen=100)
        self._fill_outcomes: deque[float] = deque(maxlen=100)

        # Over-optimistic detection
        self._backtest_pnl: Optional[float] = None
        self._backtest_std: Optional[float] = None
        self._live_pnl: float = 0.0
        self._live_trades: int = 0

        self._issues: list[dict[str, Any]] = []
        self._logger = logger.bind(component="issue_handler")

    def on_tick(self, tick: Tick) -> Optional[dict[str, Any]]:
        """Process a tick for issue detection.

        Args:
            tick: Current tick.

        Returns:
            Issue dict if one is detected, None otherwise.
        """
        now = time.time()
        source_key = f"{tick.source}:{tick.token_id}"

        # Check stale data
        if source_key in self._last_tick_time:
            gap = now - self._last_tick_time[source_key]
            if gap > self._stale_threshold:
                issue = {
                    "type": "stale_data",
                    "source": tick.source,
                    "token_id": tick.token_id,
                    "gap_seconds": gap,
                    "timestamp": now,
                }
                self._issues.append(issue)
                self._stale_flags[source_key] = True
                self._logger.warning("stale_data_detected", **issue)
                return issue
            else:
                self._stale_flags[source_key] = False

        # Check jitter
        if source_key not in self._tick_intervals:
            self._tick_intervals[source_key] = deque(maxlen=50)

        if source_key in self._last_tick_time:
            interval_ms = (now - self._last_tick_time[source_key]) * 1000
            self._tick_intervals[source_key].append(interval_ms)

            if len(self._tick_intervals[source_key]) >= 10:
                intervals = np.array(list(self._tick_intervals[source_key]))
                std_ms = float(np.std(intervals))
                if std_ms > self._jitter_threshold_ms:
                    issue = {
                        "type": "jittery_data",
                        "source": tick.source,
                        "token_id": tick.token_id,
                        "jitter_std_ms": std_ms,
                        "timestamp": now,
                    }
                    self._issues.append(issue)
                    self._logger.warning("jittery_data_detected", **issue)

        self._last_tick_time[source_key] = now
        return None

    def record_fill_outcome(self, side: str, pnl: float) -> None:
        """Record a fill outcome for adverse selection analysis.

        Args:
            side: Trade side ('buy' or 'sell').
            pnl: PnL from the trade.
        """
        self._fill_sides.append(side)
        self._fill_outcomes.append(pnl)
        self._live_pnl += pnl
        self._live_trades += 1

    def get_adverse_selection_stats(self) -> dict[str, Any]:
        """Get adverse selection statistics.

        Returns:
            Dictionary with fill-side analysis.
        """
        if len(self._fill_sides) == 0:
            return {"total_fills": 0}

        buy_count = sum(1 for s in self._fill_sides if s == "buy")
        sell_count = sum(1 for s in self._fill_sides if s == "sell")

        buy_pnl = sum(
            pnl for side, pnl in zip(self._fill_sides, self._fill_outcomes)
            if side == "buy"
        )
        sell_pnl = sum(
            pnl for side, pnl in zip(self._fill_sides, self._fill_outcomes)
            if side == "sell"
        )

        return {
            "total_fills": len(self._fill_sides),
            "buy_fills": buy_count,
            "sell_fills": sell_count,
            "buy_pnl": buy_pnl,
            "sell_pnl": sell_pnl,
            "avg_buy_pnl": buy_pnl / buy_count if buy_count > 0 else 0,
            "avg_sell_pnl": sell_pnl / sell_count if sell_count > 0 else 0,
        }

    def set_backtest_baseline(self, expected_pnl: float, pnl_std: float) -> None:
        """Set backtest performance baseline for over-optimistic detection.

        Args:
            expected_pnl: Expected PnL per N trades from backtest.
            pnl_std: Standard deviation of PnL from backtest.
        """
        self._backtest_pnl = expected_pnl
        self._backtest_std = pnl_std
        self._logger.info(
            "backtest_baseline_set",
            expected_pnl=expected_pnl,
            pnl_std=pnl_std,
        )

    def check_over_optimistic(self) -> Optional[dict[str, Any]]:
        """Check if live performance significantly diverges from backtest.

        Returns:
            Issue dict if over-optimistic detected (>2 std dev divergence).
        """
        if self._backtest_pnl is None or self._backtest_std is None:
            return None

        if self._live_trades < 10:
            return None

        if self._backtest_std == 0:
            return None

        divergence = (self._backtest_pnl - self._live_pnl) / self._backtest_std

        if abs(divergence) > self._divergence_std_devs:
            issue = {
                "type": "over_optimistic",
                "backtest_pnl": self._backtest_pnl,
                "live_pnl": self._live_pnl,
                "divergence_std_devs": divergence,
                "live_trades": self._live_trades,
                "timestamp": time.time(),
            }
            self._issues.append(issue)
            self._logger.warning("over_optimistic_detected", **issue)
            return issue

        return None

    def request_reconnect(self, source: str) -> None:
        """Request reconnection for a degraded source.

        Args:
            source: Source identifier to reconnect.
        """
        self._reconnect_count += 1
        self._logger.info("reconnect_requested", source=source, count=self._reconnect_count)

    def get_state(self) -> dict[str, Any]:
        """Get issue handler state."""
        return {
            "total_issues": len(self._issues),
            "stale_sources": [k for k, v in self._stale_flags.items() if v],
            "reconnect_count": self._reconnect_count,
            "live_pnl": self._live_pnl,
            "live_trades": self._live_trades,
            "adverse_selection": self.get_adverse_selection_stats(),
        }
