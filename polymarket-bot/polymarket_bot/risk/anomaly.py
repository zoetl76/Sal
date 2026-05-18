"""Anomaly detection for fishy resolution, volume spikes, and manipulation."""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import structlog

from polymarket_bot.data.models import Tick

logger = structlog.get_logger(__name__)


@dataclass
class AnomalyConfig:
    """Anomaly detection configuration.

    Attributes:
        resolution_tolerance: Tolerance for fishy resolution detection (cents).
        volume_spike_multiplier: Multiplier over mean volume to flag spike.
        price_spike_std_devs: Number of std devs for price manipulation flag.
        nsf_rate_threshold: NSF error rate threshold for auto-pause.
        lookback_window: Number of ticks to consider for statistics.
        auto_pause_enabled: Whether to auto-pause on anomaly detection.
    """

    resolution_tolerance: float = 0.01
    volume_spike_multiplier: float = 5.0
    price_spike_std_devs: float = 4.0
    nsf_rate_threshold: float = 0.10
    lookback_window: int = 100
    auto_pause_enabled: bool = True


@dataclass
class Anomaly:
    """Detected anomaly record.

    Attributes:
        anomaly_type: Type of anomaly detected.
        timestamp: When the anomaly was detected.
        details: Additional context about the anomaly.
        severity: Severity level (low, medium, high, critical).
    """

    anomaly_type: str
    timestamp: float
    details: dict[str, Any]
    severity: str = "medium"


class AnomalyDetector:
    """Detects trading anomalies and triggers auto-pause.

    Monitors for:
    - Fishy resolution: 1-cent discrepancies between expected and actual
    - Volume spikes: Unusual volume relative to history
    - Price manipulation: Flash crashes/spikes
    - NSF error rate: Too many insufficient funds errors
    """

    def __init__(self, config: Optional[AnomalyConfig] = None) -> None:
        """Initialize anomaly detector.

        Args:
            config: Anomaly detection configuration.
        """
        self._config = config or AnomalyConfig()
        self._price_history: dict[str, deque[float]] = {}
        self._volume_history: dict[str, deque[float]] = {}
        self._anomalies: list[Anomaly] = []
        self._paused = False
        self._nsf_count: int = 0
        self._total_orders: int = 0
        self._logger = logger.bind(component="anomaly_detector")

    def on_tick(self, tick: Tick) -> Optional[Anomaly]:
        """Process a tick and check for anomalies.

        Args:
            tick: Tick data to analyze.

        Returns:
            Anomaly if detected, None otherwise.
        """
        # Initialize history for new tokens
        if tick.token_id not in self._price_history:
            self._price_history[tick.token_id] = deque(
                maxlen=self._config.lookback_window
            )
            self._volume_history[tick.token_id] = deque(
                maxlen=self._config.lookback_window
            )

        prices = self._price_history[tick.token_id]
        volumes = self._volume_history[tick.token_id]

        # Check for anomalies before updating history
        anomaly = None

        # Check price manipulation (flash crash/spike)
        if len(prices) >= 10:
            anomaly = self._check_price_manipulation(tick, prices)

        # Check volume spike
        if anomaly is None and len(volumes) >= 10:
            anomaly = self._check_volume_spike(tick, volumes)

        # Check fishy resolution
        if anomaly is None and len(prices) >= 2:
            anomaly = self._check_fishy_resolution(tick, prices)

        # Update history
        prices.append(tick.price)
        volumes.append(tick.volume)

        if anomaly is not None:
            self._anomalies.append(anomaly)
            if self._config.auto_pause_enabled and anomaly.severity in ("high", "critical"):
                self._paused = True
                self._logger.warning(
                    "auto_pause_triggered",
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                )

        return anomaly

    def _check_price_manipulation(
        self, tick: Tick, prices: deque[float]
    ) -> Optional[Anomaly]:
        """Detect flash crashes or spikes.

        Args:
            tick: Current tick.
            prices: Price history.

        Returns:
            Anomaly if price manipulation detected.
        """
        price_array = np.array(list(prices))
        mean = float(np.mean(price_array))
        std = float(np.std(price_array))

        # If std is zero (all prices identical) but new price differs significantly,
        # treat as manipulation (use mean-based percentage check)
        if std == 0:
            if mean == 0:
                return None
            pct_deviation = abs(tick.price - mean) / mean
            if pct_deviation > 0.10:  # >10% deviation from constant price
                return Anomaly(
                    anomaly_type="price_manipulation",
                    timestamp=tick.timestamp,
                    details={
                        "token_id": tick.token_id,
                        "price": tick.price,
                        "mean": mean,
                        "std": 0.0,
                        "pct_deviation": pct_deviation,
                    },
                    severity="high",
                )
            return None

        z_score = abs(tick.price - mean) / std

        if z_score > self._config.price_spike_std_devs:
            return Anomaly(
                anomaly_type="price_manipulation",
                timestamp=tick.timestamp,
                details={
                    "token_id": tick.token_id,
                    "price": tick.price,
                    "mean": mean,
                    "std": std,
                    "z_score": z_score,
                },
                severity="high",
            )
        return None

    def _check_volume_spike(
        self, tick: Tick, volumes: deque[float]
    ) -> Optional[Anomaly]:
        """Detect unusual volume spikes.

        Args:
            tick: Current tick.
            volumes: Volume history.

        Returns:
            Anomaly if volume spike detected.
        """
        volume_array = np.array(list(volumes))
        mean_volume = float(np.mean(volume_array))

        if mean_volume == 0:
            return None

        if tick.volume > mean_volume * self._config.volume_spike_multiplier:
            return Anomaly(
                anomaly_type="volume_spike",
                timestamp=tick.timestamp,
                details={
                    "token_id": tick.token_id,
                    "volume": tick.volume,
                    "mean_volume": mean_volume,
                    "multiplier": tick.volume / mean_volume,
                },
                severity="medium",
            )
        return None

    def _check_fishy_resolution(
        self, tick: Tick, prices: deque[float]
    ) -> Optional[Anomaly]:
        """Detect 1-cent discrepancies suggesting fishy resolution.

        Flags when price suddenly moves to within 1 cent of 0 or 1 (resolution).

        Args:
            tick: Current tick.
            prices: Price history.

        Returns:
            Anomaly if fishy resolution detected.
        """
        tolerance = self._config.resolution_tolerance
        last_price = prices[-1]

        # Check if price just jumped near 0 or 1 (market resolution)
        near_zero = tick.price <= tolerance
        near_one = tick.price >= (1.0 - tolerance)

        if near_zero or near_one:
            # Only flag if previous price was not near resolution
            last_near_resolution = last_price <= tolerance or last_price >= (1.0 - tolerance)
            if not last_near_resolution:
                return Anomaly(
                    anomaly_type="fishy_resolution",
                    timestamp=tick.timestamp,
                    details={
                        "token_id": tick.token_id,
                        "price": tick.price,
                        "previous_price": last_price,
                        "resolution_value": 0.0 if near_zero else 1.0,
                    },
                    severity="high",
                )
        return None

    def record_nsf_error(self) -> Optional[Anomaly]:
        """Record an NSF (insufficient funds) error.

        Returns:
            Anomaly if NSF rate exceeds threshold.
        """
        self._nsf_count += 1
        self._total_orders += 1

        nsf_rate = self._nsf_count / self._total_orders if self._total_orders > 0 else 0

        if nsf_rate > self._config.nsf_rate_threshold and self._total_orders >= 10:
            anomaly = Anomaly(
                anomaly_type="nsf_rate_high",
                timestamp=time.time(),
                details={
                    "nsf_count": self._nsf_count,
                    "total_orders": self._total_orders,
                    "nsf_rate": nsf_rate,
                },
                severity="critical",
            )
            self._anomalies.append(anomaly)
            if self._config.auto_pause_enabled:
                self._paused = True
            return anomaly
        return None

    def record_order_success(self) -> None:
        """Record a successful order (for NSF rate calculation)."""
        self._total_orders += 1

    def resume(self) -> None:
        """Resume trading after auto-pause."""
        self._paused = False
        self._logger.info("trading_resumed")

    @property
    def is_paused(self) -> bool:
        """Whether trading is auto-paused due to anomaly."""
        return self._paused

    @property
    def anomalies(self) -> list[Anomaly]:
        """List of all detected anomalies."""
        return list(self._anomalies)

    def get_state(self) -> dict[str, Any]:
        """Get detector state for monitoring."""
        return {
            "paused": self._paused,
            "total_anomalies": len(self._anomalies),
            "nsf_count": self._nsf_count,
            "total_orders": self._total_orders,
            "monitored_tokens": list(self._price_history.keys()),
        }
