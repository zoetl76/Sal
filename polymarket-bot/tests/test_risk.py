"""Tests for risk controls: stop-loss, price filters, anomaly detection, auto-pause."""

import time

import numpy as np
import pytest

from polymarket_bot.data.models import Tick
from polymarket_bot.risk.anomaly import Anomaly, AnomalyConfig, AnomalyDetector
from polymarket_bot.risk.filters import RiskFilter, RiskLimits
from polymarket_bot.risk.stop_loss import (
    Direction,
    Position,
    StopLossConfig,
    StopLossEngine,
)
from polymarket_bot.strategy.base import Signal


class TestStopLossEngine:
    """Tests for StopLossEngine."""

    def _create_tick(self, price: float, token_id: str = "token123") -> Tick:
        """Helper to create a tick."""
        return Tick(
            source="polymarket",
            token_id=token_id,
            price=price,
            timestamp=time.time(),
        )

    def test_stop_loss_triggers_at_correct_price(self):
        """Stop-loss should trigger when price falls below stop level."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=True, stop_loss_pct=0.10)
        engine.configure_strategy("test_strategy", config)

        # Open a BUY position at 0.50, stop at 0.45 (10% below)
        engine.open_position(
            token_id="token123",
            entry_price=0.50,
            direction=Direction.BUY,
            size=10.0,
            strategy_name="test_strategy",
        )

        # Price above stop - should not trigger
        signals = engine.on_tick(self._create_tick(0.48))
        assert len(signals) == 0

        # Price at stop - should trigger
        signals = engine.on_tick(self._create_tick(0.45))
        assert len(signals) == 1
        assert signals[0].direction == Direction.SELL
        assert signals[0].token_id == "token123"
        assert signals[0].size == 10.0

    def test_stop_loss_sell_position(self):
        """Stop-loss should trigger for short positions when price rises."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=True, stop_loss_pct=0.10)
        engine.configure_strategy("test_strategy", config)

        # Open a SELL position at 0.50, stop at 0.55 (10% above)
        engine.open_position(
            token_id="token123",
            entry_price=0.50,
            direction=Direction.SELL,
            size=10.0,
            strategy_name="test_strategy",
        )

        # Price below stop - should not trigger
        signals = engine.on_tick(self._create_tick(0.53))
        assert len(signals) == 0

        # Price above stop - should trigger
        signals = engine.on_tick(self._create_tick(0.56))
        assert len(signals) == 1
        assert signals[0].direction == Direction.BUY

    def test_trailing_stop(self):
        """Trailing stop should move up as price increases."""
        engine = StopLossEngine()
        config = StopLossConfig(
            enabled=True,
            stop_loss_pct=0.10,
            trailing_stop=True,
            trailing_distance=0.05,
        )
        engine.configure_strategy("test_strategy", config)

        engine.open_position(
            token_id="token123",
            entry_price=0.50,
            direction=Direction.BUY,
            size=10.0,
            strategy_name="test_strategy",
        )

        # Price goes up - trailing stop should follow
        engine.on_tick(self._create_tick(0.60))

        # New stop should be at 0.60 * 0.95 = 0.57
        position = engine.positions["test_strategy:token123"]
        assert position.stop_price == pytest.approx(0.57, rel=1e-3)

        # Price drops but above new stop - no trigger
        signals = engine.on_tick(self._create_tick(0.58))
        assert len(signals) == 0

        # Price drops below trailing stop
        signals = engine.on_tick(self._create_tick(0.56))
        assert len(signals) == 1

    def test_disabled_stop_loss(self):
        """Disabled stop-loss should not open positions."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=False)
        engine.configure_strategy("no_stop", config)

        result = engine.open_position(
            token_id="token123",
            entry_price=0.50,
            direction=Direction.BUY,
            size=10.0,
            strategy_name="no_stop",
        )
        assert result is None
        assert len(engine.positions) == 0


class TestMaxEntryPriceFilter:
    """Tests for the 85-cent max entry price filter."""

    def test_blocks_trades_above_85_cents(self):
        """Price filter should block entries above 85 cents."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=True, max_entry_price=0.85)
        engine.configure_strategy("test_strategy", config)

        # Attempting to enter at 0.90 should be blocked
        result = engine.open_position(
            token_id="token123",
            entry_price=0.90,
            direction=Direction.BUY,
            size=10.0,
            strategy_name="test_strategy",
        )
        assert result is None
        assert len(engine.positions) == 0

    def test_allows_trades_at_85_cents(self):
        """Price filter should allow entries at exactly 85 cents."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=True, max_entry_price=0.85)
        engine.configure_strategy("test_strategy", config)

        result = engine.open_position(
            token_id="token123",
            entry_price=0.85,
            direction=Direction.BUY,
            size=10.0,
            strategy_name="test_strategy",
        )
        assert result is not None

    def test_allows_trades_below_85_cents(self):
        """Price filter should allow entries below 85 cents."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=True, max_entry_price=0.85)
        engine.configure_strategy("test_strategy", config)

        result = engine.open_position(
            token_id="token123",
            entry_price=0.50,
            direction=Direction.BUY,
            size=10.0,
            strategy_name="test_strategy",
        )
        assert result is not None

    def test_blocks_trades_below_min_price(self):
        """Price filter should block entries below min price."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=True, min_entry_price=0.05)
        engine.configure_strategy("test_strategy", config)

        result = engine.open_position(
            token_id="token123",
            entry_price=0.02,
            direction=Direction.BUY,
            size=10.0,
            strategy_name="test_strategy",
        )
        assert result is None

    def test_check_entry_price_method(self):
        """check_entry_price should return True/False based on price."""
        engine = StopLossEngine()
        config = StopLossConfig(enabled=True, max_entry_price=0.85, min_entry_price=0.05)
        engine.configure_strategy("test_strategy", config)

        assert engine.check_entry_price(0.50, "test_strategy") is True
        assert engine.check_entry_price(0.85, "test_strategy") is True
        assert engine.check_entry_price(0.90, "test_strategy") is False
        assert engine.check_entry_price(0.03, "test_strategy") is False


class TestAnomalyDetection:
    """Tests for anomaly detection."""

    def _create_tick(
        self, price: float, token_id: str = "token123", volume: float = 100.0
    ) -> Tick:
        """Helper to create a tick."""
        return Tick(
            source="polymarket",
            token_id=token_id,
            price=price,
            timestamp=time.time(),
            volume=volume,
        )

    def test_detects_fishy_resolution(self):
        """Anomaly detector should flag 1-cent discrepancy (price near 0 or 1)."""
        config = AnomalyConfig(resolution_tolerance=0.01, auto_pause_enabled=True)
        detector = AnomalyDetector(config)

        # Build normal price history
        for price in [0.50, 0.51, 0.49, 0.50, 0.52]:
            detector.on_tick(self._create_tick(price))

        # Sudden jump to near-zero (fishy resolution)
        anomaly = detector.on_tick(self._create_tick(0.005))
        assert anomaly is not None
        assert anomaly.anomaly_type == "fishy_resolution"
        assert anomaly.severity == "high"

    def test_detects_price_manipulation(self):
        """Anomaly detector should flag flash crashes/spikes."""
        config = AnomalyConfig(price_spike_std_devs=3.0, auto_pause_enabled=True)
        detector = AnomalyDetector(config)

        # Build stable price history
        for _ in range(15):
            detector.on_tick(self._create_tick(0.50))

        # Flash crash - massive deviation
        anomaly = detector.on_tick(self._create_tick(0.10))
        assert anomaly is not None
        assert anomaly.anomaly_type == "price_manipulation"

    def test_detects_volume_spike(self):
        """Anomaly detector should flag unusual volume."""
        config = AnomalyConfig(volume_spike_multiplier=3.0, auto_pause_enabled=False)
        detector = AnomalyDetector(config)

        # Normal volume history
        for _ in range(15):
            detector.on_tick(self._create_tick(0.50, volume=100.0))

        # Volume spike
        anomaly = detector.on_tick(self._create_tick(0.50, volume=500.0))
        assert anomaly is not None
        assert anomaly.anomaly_type == "volume_spike"

    def test_no_false_positive_on_normal_data(self):
        """Anomaly detector should not flag normal price movement."""
        config = AnomalyConfig(
            price_spike_std_devs=4.0,
            volume_spike_multiplier=5.0,
        )
        detector = AnomalyDetector(config)

        # Normal price movement
        prices = [0.50, 0.51, 0.49, 0.52, 0.48, 0.50, 0.51, 0.49, 0.50, 0.51,
                  0.50, 0.49, 0.51, 0.50, 0.52]
        for price in prices:
            anomaly = detector.on_tick(self._create_tick(price, volume=100.0))

        # Last tick should not be anomalous
        anomaly = detector.on_tick(self._create_tick(0.50, volume=100.0))
        assert anomaly is None


class TestAutoPause:
    """Tests for auto-pause functionality."""

    def _create_tick(self, price: float, token_id: str = "token123") -> Tick:
        """Helper to create a tick."""
        return Tick(
            source="polymarket",
            token_id=token_id,
            price=price,
            timestamp=time.time(),
            volume=100.0,
        )

    def test_auto_pause_on_high_severity_anomaly(self):
        """Trading should auto-pause on high severity anomaly."""
        config = AnomalyConfig(
            price_spike_std_devs=3.0,
            auto_pause_enabled=True,
        )
        detector = AnomalyDetector(config)

        # Build history
        for _ in range(15):
            detector.on_tick(self._create_tick(0.50))

        assert detector.is_paused is False

        # Trigger high-severity anomaly
        detector.on_tick(self._create_tick(0.10))
        assert detector.is_paused is True

    def test_auto_pause_disabled(self):
        """Auto-pause should not trigger when disabled."""
        config = AnomalyConfig(
            price_spike_std_devs=3.0,
            auto_pause_enabled=False,
        )
        detector = AnomalyDetector(config)

        # Build history
        for _ in range(15):
            detector.on_tick(self._create_tick(0.50))

        # Trigger anomaly but auto-pause is disabled
        detector.on_tick(self._create_tick(0.10))
        assert detector.is_paused is False

    def test_resume_after_pause(self):
        """Trading should be resumable after auto-pause."""
        config = AnomalyConfig(
            price_spike_std_devs=3.0,
            auto_pause_enabled=True,
        )
        detector = AnomalyDetector(config)

        for _ in range(15):
            detector.on_tick(self._create_tick(0.50))

        detector.on_tick(self._create_tick(0.10))
        assert detector.is_paused is True

        detector.resume()
        assert detector.is_paused is False

    def test_nsf_rate_triggers_pause(self):
        """High NSF error rate should trigger pause."""
        config = AnomalyConfig(
            nsf_rate_threshold=0.10,
            auto_pause_enabled=True,
        )
        detector = AnomalyDetector(config)

        # Record mostly failures
        for _ in range(8):
            detector.record_order_success()
        for _ in range(3):
            detector.record_nsf_error()

        # NSF rate = 3/11 = 27% > 10% threshold, with 11 orders
        assert detector.is_paused is True


class TestRiskFilter:
    """Tests for risk filter checks."""

    def test_blocks_oversized_position(self):
        """Risk filter should block signals exceeding max position size."""
        limits = RiskLimits(max_position_size=50.0)
        risk_filter = RiskFilter(limits)

        signal = Signal(
            direction=Direction.BUY,
            token_id="token123",
            price=0.50,
            size=100.0,
        )
        passed, reason = risk_filter.check_signal(signal)
        assert passed is False
        assert "size" in reason

    def test_allows_within_limits(self):
        """Risk filter should pass signals within all limits."""
        limits = RiskLimits(max_position_size=100.0, max_concurrent_positions=10)
        risk_filter = RiskFilter(limits)

        signal = Signal(
            direction=Direction.BUY,
            token_id="token123",
            price=0.50,
            size=10.0,
        )
        passed, reason = risk_filter.check_signal(signal)
        assert passed is True

    def test_blocks_on_max_daily_loss(self):
        """Risk filter should block when daily loss exceeded."""
        limits = RiskLimits(max_daily_loss=100.0)
        risk_filter = RiskFilter(limits)

        # Simulate daily loss
        risk_filter._daily_pnl = -101.0

        signal = Signal(
            direction=Direction.BUY,
            token_id="token123",
            price=0.50,
            size=10.0,
        )
        passed, reason = risk_filter.check_signal(signal)
        assert passed is False
        assert "daily loss" in reason
