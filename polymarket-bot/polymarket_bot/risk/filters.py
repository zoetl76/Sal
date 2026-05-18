"""Risk filters for position sizing, loss limits, and adverse selection."""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from polymarket_bot.data.models import Fill
from polymarket_bot.strategy.base import Direction, Signal

logger = structlog.get_logger(__name__)


@dataclass
class RiskLimits:
    """Risk limit configuration.

    Attributes:
        max_position_size: Maximum position size per market.
        max_daily_loss: Maximum daily loss before trading halts.
        max_concurrent_positions: Maximum number of open positions.
        correlation_limit: Max correlated positions in same direction.
        adverse_selection_threshold: Fill-side imbalance threshold for filter.
    """

    max_position_size: float = 100.0
    max_daily_loss: float = 500.0
    max_concurrent_positions: int = 10
    correlation_limit: int = 3
    adverse_selection_threshold: float = 0.7


class RiskFilter:
    """Risk filters that gate signal execution.

    Checks position limits, daily loss, concurrent positions,
    correlation constraints, and adverse selection patterns.
    """

    def __init__(self, limits: Optional[RiskLimits] = None) -> None:
        """Initialize risk filters.

        Args:
            limits: Risk limit configuration.
        """
        self._limits = limits or RiskLimits()
        self._positions: dict[str, dict[str, Any]] = {}
        self._daily_pnl: float = 0.0
        self._day_start: float = self._get_day_start()
        self._fills: deque[Fill] = deque(maxlen=1000)
        self._buy_fills: int = 0
        self._sell_fills: int = 0
        self._blocked_signals: int = 0
        self._logger = logger.bind(component="risk_filter")

    def _get_day_start(self) -> float:
        """Get the start of the current day as unix timestamp."""
        now = time.time()
        return now - (now % 86400)

    def check_signal(self, signal: Signal) -> tuple[bool, str]:
        """Check if a signal passes all risk filters.

        Args:
            signal: Trading signal to validate.

        Returns:
            Tuple of (passed, reason). If passed is False, reason explains why.
        """
        # Reset daily counters if new day
        current_day = self._get_day_start()
        if current_day != self._day_start:
            self._daily_pnl = 0.0
            self._day_start = current_day

        # Check max position size
        if signal.size > self._limits.max_position_size:
            self._blocked_signals += 1
            return False, f"size {signal.size} exceeds max {self._limits.max_position_size}"

        # Check max daily loss
        if self._daily_pnl <= -self._limits.max_daily_loss:
            self._blocked_signals += 1
            return False, f"daily loss {self._daily_pnl} exceeds max {self._limits.max_daily_loss}"

        # Check max concurrent positions
        if len(self._positions) >= self._limits.max_concurrent_positions:
            # Allow closing signals through
            if signal.token_id not in self._positions:
                self._blocked_signals += 1
                return False, f"max concurrent positions ({self._limits.max_concurrent_positions}) reached"

        # Check correlation limits
        if not self._check_correlation(signal):
            self._blocked_signals += 1
            return False, "correlation limit exceeded"

        # Check adverse selection
        if not self._check_adverse_selection(signal):
            self._blocked_signals += 1
            return False, "adverse selection filter triggered"

        return True, "passed"

    def _check_correlation(self, signal: Signal) -> bool:
        """Check if adding this signal would exceed correlation limits.

        Args:
            signal: Signal to check.

        Returns:
            True if within limits.
        """
        same_direction_count = sum(
            1 for pos in self._positions.values()
            if pos["direction"] == signal.direction.value
        )
        return same_direction_count < self._limits.correlation_limit

    def _check_adverse_selection(self, signal: Signal) -> bool:
        """Check for adverse selection pattern.

        If fills consistently happen on the wrong side (e.g., only our buys
        get filled right before price drops), the filter triggers.

        Args:
            signal: Signal to check.

        Returns:
            True if no adverse selection detected.
        """
        total_fills = self._buy_fills + self._sell_fills
        if total_fills < 10:
            return True  # Not enough data

        # Check if one side dominates fills (adverse selection indicator)
        buy_ratio = self._buy_fills / total_fills
        threshold = self._limits.adverse_selection_threshold

        if signal.direction == Direction.BUY and buy_ratio > threshold:
            self._logger.warning(
                "adverse_selection_detected",
                direction="BUY",
                buy_ratio=buy_ratio,
            )
            return False

        if signal.direction == Direction.SELL and (1 - buy_ratio) > threshold:
            self._logger.warning(
                "adverse_selection_detected",
                direction="SELL",
                sell_ratio=1 - buy_ratio,
            )
            return False

        return True

    def record_fill(self, fill: Fill) -> None:
        """Record a fill for adverse selection analysis.

        Args:
            fill: Fill to record.
        """
        self._fills.append(fill)
        if fill.side == "buy":
            self._buy_fills += 1
        else:
            self._sell_fills += 1

    def open_position(self, token_id: str, direction: Direction, size: float) -> None:
        """Record a new open position.

        Args:
            token_id: Token identifier.
            direction: Trade direction.
            size: Position size.
        """
        self._positions[token_id] = {
            "direction": direction.value,
            "size": size,
            "opened_at": time.time(),
        }

    def close_position(self, token_id: str, pnl: float = 0.0) -> None:
        """Record a position closure and update daily PnL.

        Args:
            token_id: Token identifier.
            pnl: Realized PnL from this position.
        """
        if token_id in self._positions:
            del self._positions[token_id]
        self._daily_pnl += pnl

    def get_state(self) -> dict[str, Any]:
        """Get risk filter state for monitoring."""
        return {
            "open_positions": len(self._positions),
            "daily_pnl": self._daily_pnl,
            "blocked_signals": self._blocked_signals,
            "buy_fills": self._buy_fills,
            "sell_fills": self._sell_fills,
            "limits": {
                "max_position_size": self._limits.max_position_size,
                "max_daily_loss": self._limits.max_daily_loss,
                "max_concurrent_positions": self._limits.max_concurrent_positions,
            },
        }
