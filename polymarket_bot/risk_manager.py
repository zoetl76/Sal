"""
Risk Management Module
======================
Controls risk across the entire portfolio:
- Position sizing
- Stop loss / take profit
- Maximum exposure limits
- Daily loss tracking
- Order validation
"""

import time
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from config import Config
from strategy import Signal


@dataclass
class Position:
    """Tracks an open position."""
    token_id: str
    market_id: str
    question: str
    side: str
    entry_price: float
    size: float
    current_price: float = 0.0
    entry_time: float = field(default_factory=time.time)
    unrealized_pnl: float = 0.0

    @property
    def exposure(self) -> float:
        """Total exposure for this position."""
        return self.size * self.entry_price

    def update_pnl(self, current_price: float):
        """Update unrealized PnL."""
        self.current_price = current_price
        if self.side == "BUY":
            self.unrealized_pnl = (current_price - self.entry_price) * self.size
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.size


@dataclass
class DailyStats:
    """Tracks daily trading statistics."""
    date: str = ""
    trades_count: int = 0
    realized_pnl: float = 0.0
    total_volume: float = 0.0
    max_drawdown: float = 0.0
    peak_value: float = 0.0


class RiskManager:
    """
    Manages risk for the trading bot.
    Validates orders, monitors positions, and enforces limits.
    """

    def __init__(self, config: Config):
        self.config = config
        self.positions: dict[str, Position] = {}
        self.daily_stats = DailyStats()
        self.total_exposure = 0.0
        self.is_trading_allowed = True
        self._daily_reset_time = time.time()

    # =========================================================================
    # ORDER VALIDATION
    # =========================================================================

    def validate_signal(self, signal: Signal) -> tuple[bool, str]:
        """
        Validate whether a signal should be executed.
        Returns (approved, reason).
        """
        # Check if trading is allowed
        if not self.is_trading_allowed:
            return False, "Trading is halted (daily loss limit hit)"

        # Check daily loss limit
        if abs(self.daily_stats.realized_pnl) >= self.config.risk.daily_loss_limit:
            self.is_trading_allowed = False
            return False, f"Daily loss limit reached: ${self.daily_stats.realized_pnl:.2f}"

        # Check total exposure
        new_exposure = signal.size * signal.price
        if self.total_exposure + new_exposure > self.config.risk.max_total_exposure:
            return False, (
                f"Would exceed max exposure: "
                f"current=${self.total_exposure:.2f} + new=${new_exposure:.2f} "
                f"> max=${self.config.risk.max_total_exposure:.2f}"
            )

        # Check position size limit
        existing = self.positions.get(signal.token_id)
        if existing:
            total_size = existing.size + signal.size
            if total_size * signal.price > self.config.strategy.max_position_size:
                return False, (
                    f"Would exceed max position size: "
                    f"${total_size * signal.price:.2f} > ${self.config.strategy.max_position_size:.2f}"
                )

        # Check confidence threshold
        if signal.confidence < 0.3:
            return False, f"Confidence too low: {signal.confidence:.2f} < 0.30"

        # Check price sanity
        if signal.price <= 0 or signal.price >= 1:
            return False, f"Invalid price: {signal.price}"

        # Check minimum order size
        if signal.size * signal.price < 1.0:
            return False, f"Order too small: ${signal.size * signal.price:.2f} < $1.00"

        return True, "Signal approved"

    def calculate_position_size(self, signal: Signal) -> float:
        """
        Calculate optimal position size based on confidence and risk budget.
        Uses a modified Kelly criterion approach.
        """
        base_size = self.config.strategy.order_size

        # Scale by confidence (0.3 to 1.0 maps to 0.3x to 1.0x)
        confidence_factor = signal.confidence

        # Scale down if approaching exposure limit
        remaining_budget = self.config.risk.max_total_exposure - self.total_exposure
        budget_factor = min(1.0, remaining_budget / (base_size * signal.price * 2))

        # Final size
        adjusted_size = base_size * confidence_factor * budget_factor

        # Ensure minimum viable order size
        min_size = 1.0 / signal.price if signal.price > 0 else 1.0
        adjusted_size = max(min_size, adjusted_size)

        # Cap at max position size
        max_size = self.config.strategy.max_position_size / signal.price if signal.price > 0 else base_size
        adjusted_size = min(adjusted_size, max_size)

        return round(adjusted_size, 2)

    # =========================================================================
    # POSITION MANAGEMENT
    # =========================================================================

    def open_position(self, signal: Signal, filled_price: float = None):
        """Record a new open position."""
        price = filled_price or signal.price
        position = Position(
            token_id=signal.token_id,
            market_id=signal.market_id,
            question=signal.question,
            side=signal.side,
            entry_price=price,
            size=signal.size,
            current_price=price,
        )
        self.positions[signal.token_id] = position
        self.total_exposure += position.exposure
        self.daily_stats.trades_count += 1
        self.daily_stats.total_volume += position.exposure

        logger.info(
            f"Position opened: {signal.side} {signal.size:.1f}@{price:.3f} "
            f"'{signal.question[:40]}...' | Total exposure: ${self.total_exposure:.2f}"
        )

    def close_position(self, token_id: str, exit_price: float):
        """Close a position and record PnL."""
        position = self.positions.pop(token_id, None)
        if not position:
            return

        position.update_pnl(exit_price)
        realized_pnl = position.unrealized_pnl

        self.total_exposure -= position.exposure
        self.total_exposure = max(0, self.total_exposure)
        self.daily_stats.realized_pnl += realized_pnl

        logger.info(
            f"Position closed: {position.side} {position.size:.1f} "
            f"entry={position.entry_price:.3f} exit={exit_price:.3f} "
            f"PnL=${realized_pnl:.2f} | Total exposure: ${self.total_exposure:.2f}"
        )

    def check_stop_loss(self, token_id: str, current_price: float) -> bool:
        """Check if a position should be stopped out."""
        position = self.positions.get(token_id)
        if not position:
            return False

        position.update_pnl(current_price)

        # Calculate loss percentage
        if position.side == "BUY":
            loss_pct = (position.entry_price - current_price) / position.entry_price
        else:
            loss_pct = (current_price - position.entry_price) / position.entry_price

        if loss_pct >= self.config.risk.stop_loss:
            logger.warning(
                f"STOP LOSS triggered for {token_id[:16]}... "
                f"Loss: {loss_pct*100:.1f}% >= {self.config.risk.stop_loss*100:.1f}%"
            )
            return True

        return False

    def check_take_profit(self, token_id: str, current_price: float) -> bool:
        """Check if a position should take profit."""
        position = self.positions.get(token_id)
        if not position:
            return False

        # Calculate profit percentage
        if position.side == "BUY":
            profit_pct = (current_price - position.entry_price) / position.entry_price
        else:
            profit_pct = (position.entry_price - current_price) / position.entry_price

        if profit_pct >= self.config.risk.take_profit:
            logger.info(
                f"TAKE PROFIT triggered for {token_id[:16]}... "
                f"Profit: {profit_pct*100:.1f}% >= {self.config.risk.take_profit*100:.1f}%"
            )
            return True

        return False

    # =========================================================================
    # DAILY MANAGEMENT
    # =========================================================================

    def reset_daily_stats(self):
        """Reset daily tracking stats (call at midnight)."""
        logger.info(
            f"Daily stats reset. Previous day: "
            f"trades={self.daily_stats.trades_count}, "
            f"PnL=${self.daily_stats.realized_pnl:.2f}, "
            f"volume=${self.daily_stats.total_volume:.2f}"
        )
        self.daily_stats = DailyStats()
        self.is_trading_allowed = True
        self._daily_reset_time = time.time()

    def check_daily_reset(self):
        """Check if 24h have passed and reset if needed."""
        if time.time() - self._daily_reset_time >= 86400:
            self.reset_daily_stats()

    # =========================================================================
    # PORTFOLIO SUMMARY
    # =========================================================================

    def get_portfolio_summary(self) -> dict:
        """Get a summary of the current portfolio state."""
        total_unrealized_pnl = sum(p.unrealized_pnl for p in self.positions.values())

        return {
            "open_positions": len(self.positions),
            "total_exposure": self.total_exposure,
            "max_exposure": self.config.risk.max_total_exposure,
            "exposure_pct": self.total_exposure / self.config.risk.max_total_exposure * 100,
            "unrealized_pnl": total_unrealized_pnl,
            "realized_pnl_today": self.daily_stats.realized_pnl,
            "trades_today": self.daily_stats.trades_count,
            "volume_today": self.daily_stats.total_volume,
            "trading_allowed": self.is_trading_allowed,
        }
