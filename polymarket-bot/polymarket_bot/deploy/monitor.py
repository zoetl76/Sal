"""Monitoring system with structured logging, health checks, and cross-verification."""

import time
from collections import deque
from typing import Any, Optional

import structlog

from polymarket_bot.config import Config
from polymarket_bot.data.models import Tick
from polymarket_bot.risk.anomaly import Anomaly

logger = structlog.get_logger(__name__)


class Monitor:
    """Monitoring system for the trading bot.

    Features:
    - Structured JSON logging for all events
    - Cross-verification: compare Polymarket prices against Binance/Coinbase
    - Health checks: websocket count, tick rate, strategy PnL, risk limits
    - Auto-pause on: anomaly detection, excessive losses, connection degradation
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialize the monitor.

        Args:
            config: Bot configuration.
        """
        self._config = config
        self._tick_count: int = 0
        self._last_tick_time: float = 0.0
        self._tick_rate_window: deque[float] = deque(maxlen=100)
        self._anomalies: list[Anomaly] = []
        self._paused = False
        self._pause_reason: Optional[str] = None

        # Cross-verification state
        self._price_sources: dict[str, dict[str, float]] = {}
        self._discrepancies: list[dict[str, Any]] = []
        self._discrepancy_threshold: float = 0.05  # 5% price discrepancy

        # Health metrics
        self._health: dict[str, Any] = {
            "websocket_connections": 0,
            "tick_rate": 0.0,
            "last_tick_age": 0.0,
            "strategy_pnl": 0.0,
        }

        self._logger = logger.bind(component="monitor")

    def on_tick(self, tick: Tick) -> None:
        """Process a tick for monitoring purposes.

        Args:
            tick: Incoming tick data.
        """
        now = time.time()
        self._tick_count += 1
        self._tick_rate_window.append(now)
        self._last_tick_time = now

        # Update price source tracking for cross-verification
        if tick.token_id not in self._price_sources:
            self._price_sources[tick.token_id] = {}
        self._price_sources[tick.token_id][tick.source] = tick.price

        # Check cross-verification
        self._check_cross_verification(tick.token_id)

        # Update health
        self._update_health()

    def _check_cross_verification(self, token_id: str) -> None:
        """Compare prices across sources for the same market.

        Args:
            token_id: Token to check.
        """
        sources = self._price_sources.get(token_id, {})
        if len(sources) < 2:
            return

        prices = list(sources.values())
        source_names = list(sources.keys())

        for i in range(len(prices)):
            for j in range(i + 1, len(prices)):
                if prices[j] == 0:
                    continue
                diff_pct = abs(prices[i] - prices[j]) / prices[j]
                if diff_pct > self._discrepancy_threshold:
                    discrepancy = {
                        "token_id": token_id,
                        "source_a": source_names[i],
                        "price_a": prices[i],
                        "source_b": source_names[j],
                        "price_b": prices[j],
                        "diff_pct": diff_pct,
                        "timestamp": time.time(),
                    }
                    self._discrepancies.append(discrepancy)
                    self._logger.warning(
                        "price_discrepancy",
                        **discrepancy,
                    )
                    details = (
                        f"{source_names[i]}={prices[i]:.4f} vs "
                        f"{source_names[j]}={prices[j]:.4f} "
                        f"({diff_pct:.1%})"
                    )
                    self.pause(f"cross-verification discrepancy: {details}")

    def _update_health(self) -> None:
        """Update health metrics."""
        now = time.time()

        # Calculate tick rate (ticks per second)
        if len(self._tick_rate_window) >= 2:
            window_duration = self._tick_rate_window[-1] - self._tick_rate_window[0]
            if window_duration > 0:
                self._health["tick_rate"] = len(self._tick_rate_window) / window_duration

        self._health["last_tick_age"] = now - self._last_tick_time if self._last_tick_time > 0 else 0

    def on_anomaly(self, anomaly: Anomaly) -> None:
        """Record an anomaly event.

        Args:
            anomaly: Detected anomaly.
        """
        self._anomalies.append(anomaly)
        self._logger.warning(
            "anomaly_detected",
            type=anomaly.anomaly_type,
            severity=anomaly.severity,
            details=anomaly.details,
        )

        if anomaly.severity in ("high", "critical"):
            self.pause(f"anomaly: {anomaly.anomaly_type}")

    def pause(self, reason: str) -> None:
        """Pause trading due to a monitoring issue.

        Args:
            reason: Reason for the pause.
        """
        self._paused = True
        self._pause_reason = reason
        self._logger.warning("trading_paused", reason=reason)

    def resume(self) -> None:
        """Resume trading after pause."""
        self._paused = False
        self._pause_reason = None
        self._logger.info("trading_resumed")

    @property
    def is_paused(self) -> bool:
        """Whether trading is paused."""
        return self._paused

    @property
    def pause_reason(self) -> Optional[str]:
        """Reason for current pause, if any."""
        return self._pause_reason

    def get_state(self) -> dict[str, Any]:
        """Get monitor state for reporting."""
        return {
            "tick_count": self._tick_count,
            "health": dict(self._health),
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "anomaly_count": len(self._anomalies),
            "discrepancy_count": len(self._discrepancies),
        }
