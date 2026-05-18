"""Layer 1: Warmup system for websocket connections.

Starts connections 15 seconds before trading window. In the final 5 seconds,
runs a quality gate requiring 3+ ticks per token with no single price jump
exceeding 5 cents.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from polymarket_bot.feeds.base import Tick

logger = structlog.get_logger(__name__)


@dataclass
class WarmupStats:
    """Statistics from a warmup period.

    Attributes:
        token_id: The token being monitored.
        tick_count: Number of ticks received during quality gate window.
        max_jump: Maximum single price jump observed (cents).
        prices: List of prices seen during quality gate.
        passed: Whether the quality gate passed.
    """

    token_id: str
    tick_count: int = 0
    max_jump: float = 0.0
    prices: list[float] = field(default_factory=list)
    passed: bool = False


class WarmupManager:
    """Manages the 15-second warmup period with quality gate.

    Layer 1 implementation:
    - Total warmup duration: 15 seconds
    - Quality gate window: final 5 seconds
    - Quality gate requirements:
      - 3+ ticks per token
      - No single price jump > 5 cents (0.05)
    """

    WARMUP_DURATION_S: float = 15.0
    QUALITY_GATE_WINDOW_S: float = 5.0
    MIN_TICKS_REQUIRED: int = 3
    MAX_PRICE_JUMP: float = 0.05  # 5 cents

    def __init__(self, token_ids: Optional[list[str]] = None) -> None:
        """Initialize the warmup manager.

        Args:
            token_ids: List of token IDs to monitor during warmup.
        """
        self.token_ids = token_ids or []
        self._start_time: float = 0.0
        self._gate_start_time: float = 0.0
        self._warmup_active: bool = False
        self._gate_active: bool = False
        self._token_stats: dict[str, WarmupStats] = {}
        self._warmup_prices: dict[str, float] = {}  # Final warmup prices per token
        self._logger = logger.bind(component="warmup")

    @property
    def is_warming_up(self) -> bool:
        """Whether warmup is currently active."""
        return self._warmup_active

    @property
    def is_in_quality_gate(self) -> bool:
        """Whether the quality gate window is active."""
        return self._gate_active

    @property
    def warmup_prices(self) -> dict[str, float]:
        """Get the final warmup prices per token."""
        return self._warmup_prices.copy()

    def start(self) -> None:
        """Begin the warmup period."""
        self._start_time = time.time()
        self._gate_start_time = self._start_time + (
            self.WARMUP_DURATION_S - self.QUALITY_GATE_WINDOW_S
        )
        self._warmup_active = True
        self._gate_active = False
        self._token_stats = {
            token_id: WarmupStats(token_id=token_id) for token_id in self.token_ids
        }
        self._warmup_prices = {}
        self._logger.info(
            "warmup_started",
            duration_s=self.WARMUP_DURATION_S,
            gate_window_s=self.QUALITY_GATE_WINDOW_S,
            tokens=len(self.token_ids),
        )

    def process_tick(self, tick: Tick) -> None:
        """Process a tick during warmup.

        Ticks received during the quality gate window are tracked for
        the pass/fail decision.

        Args:
            tick: The incoming tick.
        """
        if not self._warmup_active:
            return

        now = time.time()

        # Check if we've entered the quality gate window
        if now >= self._gate_start_time:
            self._gate_active = True

        # Always track the latest price per token for warmup reference
        self._warmup_prices[tick.token_id] = tick.price

        # Only count ticks during quality gate for pass/fail
        if not self._gate_active:
            return

        # Get or create stats for this token
        if tick.token_id not in self._token_stats:
            self._token_stats[tick.token_id] = WarmupStats(token_id=tick.token_id)

        stats = self._token_stats[tick.token_id]
        stats.tick_count += 1

        # Track price jumps
        if stats.prices:
            jump = abs(tick.price - stats.prices[-1])
            if jump > stats.max_jump:
                stats.max_jump = jump

        stats.prices.append(tick.price)

    def check_quality_gate(self) -> bool:
        """Evaluate the quality gate at the end of warmup.

        Requirements:
        - 3+ ticks per token during the quality gate window
        - No single price jump > 5 cents

        Returns:
            True if quality gate passes, False otherwise.
        """
        all_passed = True

        for token_id, stats in self._token_stats.items():
            # Check minimum tick count
            if stats.tick_count < self.MIN_TICKS_REQUIRED:
                stats.passed = False
                all_passed = False
                self._logger.warning(
                    "quality_gate_fail_ticks",
                    token_id=token_id,
                    tick_count=stats.tick_count,
                    required=self.MIN_TICKS_REQUIRED,
                )
                continue

            # Check price jumps
            if stats.max_jump > self.MAX_PRICE_JUMP:
                stats.passed = False
                all_passed = False
                self._logger.warning(
                    "quality_gate_fail_jump",
                    token_id=token_id,
                    max_jump=stats.max_jump,
                    threshold=self.MAX_PRICE_JUMP,
                )
                continue

            stats.passed = True

        self._warmup_active = False
        self._gate_active = False

        self._logger.info(
            "quality_gate_result",
            passed=all_passed,
            stats={tid: {"ticks": s.tick_count, "max_jump": s.max_jump, "passed": s.passed}
                   for tid, s in self._token_stats.items()},
        )

        return all_passed

    def finish(self) -> bool:
        """End warmup and return quality gate result.

        Returns:
            True if quality gate passes.
        """
        return self.check_quality_gate()

    def get_stats(self) -> dict[str, WarmupStats]:
        """Get warmup statistics per token.

        Returns:
            Dictionary of token_id to WarmupStats.
        """
        return self._token_stats.copy()
