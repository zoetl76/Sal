"""Tests for the strategy framework: base class, DirectionalStrategy, ExternalSignalStrategy."""

import pytest

from polymarket_bot.config import Config
from polymarket_bot.data.models import Fill, Tick
from polymarket_bot.strategy.base import Direction, Signal, Strategy, StrategyState
from polymarket_bot.strategy.executor import StrategyExecutor
from polymarket_bot.strategy.templates import (
    DirectionalStrategy,
    ExternalSignalStrategy,
    LadderStrategy,
    MarketMakerStrategy,
    MeanReversionStrategy,
)


class TestStrategyBaseClass:
    """Tests for the abstract Strategy base class interface."""

    def test_strategy_cannot_be_instantiated(self):
        """Verify that Strategy ABC cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Strategy("test", "test strategy")

    def test_strategy_interface_has_required_attributes(self):
        """Verify Strategy subclass exposes name, description, params, state."""
        strategy = DirectionalStrategy()
        assert hasattr(strategy, "name")
        assert hasattr(strategy, "description")
        assert hasattr(strategy, "params")
        assert hasattr(strategy, "state")
        assert hasattr(strategy, "on_tick")
        assert hasattr(strategy, "on_fill")
        assert hasattr(strategy, "get_state")
        assert hasattr(strategy, "setup")

    def test_strategy_lifecycle_states(self):
        """Verify lifecycle: init -> warmup -> active -> cooldown -> done."""
        strategy = DirectionalStrategy()
        assert strategy.state == StrategyState.INIT

        config = Config()
        strategy.setup(config)
        assert strategy.state == StrategyState.WARMUP

        strategy.activate()
        assert strategy.state == StrategyState.ACTIVE

        strategy.cooldown()
        assert strategy.state == StrategyState.COOLDOWN

        strategy.done()
        assert strategy.state == StrategyState.DONE

    def test_signal_dataclass(self):
        """Verify Signal dataclass fields."""
        signal = Signal(
            direction=Direction.BUY,
            token_id="token123",
            price=0.65,
            size=10.0,
            confidence=0.8,
            stop_loss_price=0.60,
            take_profit_price=0.75,
        )
        assert signal.direction == Direction.BUY
        assert signal.token_id == "token123"
        assert signal.price == 0.65
        assert signal.size == 10.0
        assert signal.confidence == 0.8
        assert signal.stop_loss_price == 0.60
        assert signal.take_profit_price == 0.75

    def test_signal_defaults(self):
        """Verify Signal optional fields have defaults."""
        signal = Signal(
            direction=Direction.SELL,
            token_id="abc",
            price=0.50,
            size=5.0,
        )
        assert signal.confidence == 0.5
        assert signal.stop_loss_price is None
        assert signal.take_profit_price is None

    def test_get_state_returns_dict(self):
        """Verify get_state returns a dictionary with expected keys."""
        strategy = DirectionalStrategy()
        state = strategy.get_state()
        assert isinstance(state, dict)
        assert "name" in state
        assert "lifecycle_state" in state
        assert state["name"] == "directional"

    def test_on_fill_does_not_raise(self):
        """Verify on_fill base implementation handles fill without error."""
        strategy = DirectionalStrategy()
        fill = Fill(
            timestamp=1000.0,
            token_id="token123",
            price=0.65,
            size=10.0,
            side="buy",
        )
        strategy.on_fill(fill)  # Should not raise


class TestDirectionalStrategy:
    """Tests for DirectionalStrategy signal generation."""

    def _create_tick(self, price: float, token_id: str = "token123") -> Tick:
        """Helper to create a tick."""
        return Tick(
            source="polymarket",
            token_id=token_id,
            price=price,
            timestamp=1000.0,
            volume=100.0,
        )

    def test_no_signal_during_warmup(self):
        """Strategy should not emit signals before activation."""
        strategy = DirectionalStrategy()
        tick = self._create_tick(0.50)
        assert strategy.on_tick(tick) is None

    def test_no_signal_with_insufficient_history(self):
        """Strategy needs enough price history before emitting signals."""
        strategy = DirectionalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        # With lookback=10, first 9 ticks should produce no signal
        for i in range(9):
            tick = self._create_tick(0.50)
            assert strategy.on_tick(tick) is None

    def test_buy_signal_on_upward_momentum(self):
        """Strategy should emit BUY when price momentum exceeds threshold."""
        strategy = DirectionalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        # Set threshold low for testing
        strategy._params["threshold"] = 0.01
        strategy._params["lookback"] = 5

        # Feed flat prices to fill history
        for _ in range(5):
            strategy.on_tick(self._create_tick(0.50))

        # Now feed a higher price to trigger momentum
        signal = strategy.on_tick(self._create_tick(0.55))
        assert signal is not None
        assert signal.direction == Direction.BUY
        assert signal.token_id == "token123"
        assert signal.stop_loss_price is not None
        assert signal.take_profit_price is not None

    def test_sell_signal_on_downward_momentum(self):
        """Strategy should emit SELL when price drops below threshold."""
        strategy = DirectionalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        strategy._params["threshold"] = 0.01
        strategy._params["lookback"] = 5

        # Feed prices then a drop
        for _ in range(5):
            strategy.on_tick(self._create_tick(0.50))

        signal = strategy.on_tick(self._create_tick(0.45))
        assert signal is not None
        assert signal.direction == Direction.SELL

    def test_no_signal_within_threshold(self):
        """No signal when momentum is within threshold."""
        strategy = DirectionalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        strategy._params["threshold"] = 0.05
        strategy._params["lookback"] = 5

        # Feed flat prices
        for _ in range(5):
            strategy.on_tick(self._create_tick(0.50))

        # Small change within threshold
        signal = strategy.on_tick(self._create_tick(0.51))
        assert signal is None


class TestExternalSignalStrategy:
    """Tests for ExternalSignalStrategy responding to Binance feed."""

    def _create_tick(
        self, price: float, source: str = "binance", token_id: str = "token123"
    ) -> Tick:
        """Helper to create a tick with specified source."""
        return Tick(
            source=source,
            token_id=token_id,
            price=price,
            timestamp=1000.0,
            volume=100.0,
        )

    def test_responds_to_external_source(self):
        """Strategy should track prices from external source."""
        strategy = ExternalSignalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        # Configure for binance
        strategy._params["external_source"] = "binance"
        strategy._params["signal_threshold"] = 0.01
        strategy._params["cooldown_ticks"] = 0

        # Feed some binance prices to build history
        for _ in range(5):
            strategy.on_tick(self._create_tick(100.0, source="binance"))

        # Strong upward move on binance
        signal = strategy.on_tick(self._create_tick(105.0, source="binance"))
        assert signal is not None
        assert signal.direction == Direction.BUY

    def test_ignores_polymarket_source(self):
        """Strategy should not generate signal from polymarket ticks."""
        strategy = ExternalSignalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        strategy._params["external_source"] = "binance"

        # Feed polymarket ticks - should not generate signal
        for _ in range(10):
            signal = strategy.on_tick(self._create_tick(0.50, source="polymarket"))
            assert signal is None

    def test_sell_signal_on_external_drop(self):
        """Strategy should emit SELL on external price drop."""
        strategy = ExternalSignalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        strategy._params["external_source"] = "binance"
        strategy._params["signal_threshold"] = 0.01
        strategy._params["cooldown_ticks"] = 0

        # Build history
        for _ in range(5):
            strategy.on_tick(self._create_tick(100.0, source="binance"))

        # Drop
        signal = strategy.on_tick(self._create_tick(95.0, source="binance"))
        assert signal is not None
        assert signal.direction == Direction.SELL

    def test_cooldown_prevents_repeated_signals(self):
        """Strategy should respect cooldown between signals."""
        strategy = ExternalSignalStrategy()
        config = Config()
        strategy.setup(config)
        strategy.activate()

        strategy._params["external_source"] = "binance"
        strategy._params["signal_threshold"] = 0.01
        strategy._params["cooldown_ticks"] = 0

        # Build history
        for _ in range(5):
            strategy.on_tick(self._create_tick(100.0, source="binance"))

        # First strong move - should generate signal
        signal = strategy.on_tick(self._create_tick(105.0, source="binance"))
        assert signal is not None

        # Now set a high cooldown - next signal should be blocked
        strategy._params["cooldown_ticks"] = 10

        # Second move within cooldown - should not generate signal
        signal = strategy.on_tick(self._create_tick(90.0, source="binance"))
        assert signal is None


class TestStrategyExecutor:
    """Tests for the StrategyExecutor."""

    def test_register_and_feed_tick(self):
        """Executor should route ticks to registered strategies."""
        executor = StrategyExecutor()
        strategy = DirectionalStrategy()
        executor.register_strategy(strategy)

        config = Config()
        executor.setup_all(config)
        executor.activate_all()

        tick = Tick(
            source="polymarket",
            token_id="token123",
            price=0.50,
            timestamp=1000.0,
        )
        signals = executor.on_tick(tick)
        assert isinstance(signals, list)

    def test_multiple_strategies(self):
        """Executor should handle multiple registered strategies."""
        executor = StrategyExecutor()
        executor.register_strategy(DirectionalStrategy())
        executor.register_strategy(MeanReversionStrategy())

        assert len(executor.strategies) == 2

    def test_get_state(self):
        """Executor state should include all strategy states."""
        executor = StrategyExecutor()
        executor.register_strategy(DirectionalStrategy())

        state = executor.get_state()
        assert "strategies" in state
        assert "directional" in state["strategies"]
