"""Guards for tick validation and connection health.

Layer 3: Stale tick guard - rejects ticks with price delta > 15 cents from warmup.
Layer 6: Anti-jitter reaper - culls most erratic connections, respects grace period
and respawn budget.
"""

import time
from typing import Optional

import structlog

from polymarket_bot.feeds.base import Tick
from polymarket_bot.websocket.connection import WebSocketConnection

logger = structlog.get_logger(__name__)


class StaleTickGuard:
    """Layer 3: Stale tick rejection guard.

    Compares every tick against the warmup price for its token.
    Rejects any tick with price delta > 15 cents from the warmup reference.
    """

    MAX_DELTA: float = 0.15  # 15 cents

    def __init__(self, warmup_prices: Optional[dict[str, float]] = None) -> None:
        """Initialize the stale tick guard.

        Args:
            warmup_prices: Dictionary of token_id to warmup reference price.
        """
        self._warmup_prices: dict[str, float] = warmup_prices or {}
        self._rejected_count: int = 0
        self._accepted_count: int = 0
        self._logger = logger.bind(component="stale_tick_guard")

    def set_warmup_prices(self, prices: dict[str, float]) -> None:
        """Update warmup reference prices.

        Args:
            prices: Dictionary of token_id to reference price.
        """
        self._warmup_prices = prices.copy()

    def check(self, tick: Tick) -> bool:
        """Check if a tick passes the stale tick guard.

        Args:
            tick: The tick to validate.

        Returns:
            True if tick is valid, False if rejected as stale.
        """
        # If no warmup price for this token, allow it through
        if tick.token_id not in self._warmup_prices:
            self._accepted_count += 1
            return True

        warmup_price = self._warmup_prices[tick.token_id]
        delta = abs(tick.price - warmup_price)

        if delta > self.MAX_DELTA:
            self._rejected_count += 1
            self._logger.warning(
                "STALE TICK REJECTED",
                token_id=tick.token_id,
                tick_price=tick.price,
                warmup_price=warmup_price,
                delta=delta,
            )
            return False

        self._accepted_count += 1
        return True

    @property
    def rejected_count(self) -> int:
        """Number of ticks rejected as stale."""
        return self._rejected_count

    @property
    def accepted_count(self) -> int:
        """Number of ticks that passed."""
        return self._accepted_count

    def get_stats(self) -> dict:
        """Get guard statistics."""
        return {
            "rejected": self._rejected_count,
            "accepted": self._accepted_count,
            "warmup_tokens": len(self._warmup_prices),
        }


class JitterReaper:
    """Layer 6: Anti-jitter reaper.

    Culls the most erratic connections based on jitter EMA.
    Respects:
    - 8-second grace period for new sockets
    - Budget of max 20 respawns per minute
    - Max 2 culls per cycle

    Culled replicas lose all tracking data (full reset).
    """

    MAX_RESPAWNS_PER_MINUTE: int = 20
    MAX_CULLS_PER_CYCLE: int = 2
    GRACE_PERIOD_S: float = 8.0

    def __init__(self) -> None:
        """Initialize the jitter reaper."""
        self._respawn_timestamps: list[float] = []
        self._total_culled: int = 0
        self._logger = logger.bind(component="jitter_reaper")

    @property
    def respawns_this_minute(self) -> int:
        """Number of respawns in the last 60 seconds."""
        now = time.time()
        cutoff = now - 60.0
        self._respawn_timestamps = [t for t in self._respawn_timestamps if t > cutoff]
        return len(self._respawn_timestamps)

    @property
    def budget_remaining(self) -> int:
        """How many more respawns are allowed this minute."""
        return max(0, self.MAX_RESPAWNS_PER_MINUTE - self.respawns_this_minute)

    def get_cull_candidates(
        self, connections: list[WebSocketConnection]
    ) -> list[WebSocketConnection]:
        """Identify connections to cull based on jitter EMA.

        Excludes connections in their grace period. Returns at most
        MAX_CULLS_PER_CYCLE connections, limited by budget.

        Args:
            connections: All active connections.

        Returns:
            List of connections to cull (worst jitter first).
        """
        # Filter out connections in grace period
        eligible = [c for c in connections if not c.is_in_grace_period]

        if not eligible:
            return []

        # Sort by jitter EMA descending (worst first)
        eligible.sort(key=lambda c: c.jitter_ema, reverse=True)

        # Limit by per-cycle max and budget
        max_allowed = min(self.MAX_CULLS_PER_CYCLE, self.budget_remaining)
        return eligible[:max_allowed]

    def record_cull(self, count: int = 1) -> None:
        """Record that connections were culled.

        Args:
            count: Number of connections culled.
        """
        now = time.time()
        for _ in range(count):
            self._respawn_timestamps.append(now)
        self._total_culled += count
        self._logger.debug("connections_culled", count=count, budget_remaining=self.budget_remaining)

    def get_stats(self) -> dict:
        """Get reaper statistics."""
        return {
            "total_culled": self._total_culled,
            "respawns_this_minute": self.respawns_this_minute,
            "budget_remaining": self.budget_remaining,
        }
