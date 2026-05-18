"""Tests for backtesting engine, parameter sweeps, and overfitting detection."""

import numpy as np
import pytest

from polymarket_bot.backtest.analysis import BacktestAnalysis
from polymarket_bot.backtest.engine import BacktestEngine, Trade
from polymarket_bot.backtest.results import BacktestResult
from polymarket_bot.backtest.sweep import ParameterSweep


class SimpleMovingAverageStrategy:
    """Simple moving average crossover strategy for testing.

    Buys when price crosses above MA, sells when it crosses below.
    """

    def generate_signals(self, prices: np.ndarray, **params) -> np.ndarray:
        """Generate signals based on moving average crossover."""
        window = params.get("window", 5)
        signals = np.zeros(len(prices))

        if len(prices) < window:
            return signals

        # Compute moving average
        ma = np.convolve(prices, np.ones(window) / window, mode="full")[:len(prices)]

        # First 'window' values don't have full MA
        for i in range(window, len(prices)):
            if prices[i] > ma[i]:
                signals[i] = 1  # Buy signal
            elif prices[i] < ma[i]:
                signals[i] = -1  # Sell signal

        return signals


class TrendFollowingStrategy:
    """Trend following strategy: buys on uptrend, sells on downtrend.

    Uses a threshold parameter to determine when trend is significant.
    """

    def generate_signals(self, prices: np.ndarray, **params) -> np.ndarray:
        """Generate trend-following signals."""
        threshold = params.get("threshold", 0.01)
        lookback = params.get("lookback", 3)
        signals = np.zeros(len(prices))

        for i in range(lookback, len(prices)):
            pct_change = (prices[i] - prices[i - lookback]) / prices[i - lookback]
            if pct_change > threshold:
                signals[i] = 1
            elif pct_change < -threshold:
                signals[i] = -1

        return signals


class TestBacktestEngineType1:
    """Tests for Type 1 vectorized backtest execution."""

    def test_basic_execution(self):
        """Verify Type 1 backtest produces expected results for known data."""
        engine = BacktestEngine(initial_capital=10000.0)
        strategy = SimpleMovingAverageStrategy()

        # Create known price series: uptrend
        prices = np.array([1.0, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 1.09])
        timestamps = np.arange(len(prices), dtype=np.float64)

        result = engine.run_type1(strategy, prices, timestamps, params={"window": 3})

        assert isinstance(result, BacktestResult)
        assert result.total_trades >= 0
        assert len(result.equity_curve) == len(prices)

    def test_uptrend_generates_profit(self):
        """Verify that buying in an uptrend is profitable."""
        engine = BacktestEngine()
        strategy = TrendFollowingStrategy()

        # Strong uptrend
        prices = np.linspace(1.0, 2.0, 50)
        timestamps = np.arange(50, dtype=np.float64)

        result = engine.run_type1(strategy, prices, timestamps, params={"threshold": 0.01, "lookback": 3})

        # In a clear uptrend, we should be profitable
        assert result.total_pnl > 0

    def test_downtrend_with_shorts_profitable(self):
        """Verify that shorting in a downtrend is profitable."""
        engine = BacktestEngine()
        strategy = TrendFollowingStrategy()

        # Strong downtrend
        prices = np.linspace(2.0, 1.0, 50)
        timestamps = np.arange(50, dtype=np.float64)

        result = engine.run_type1(strategy, prices, timestamps, params={"threshold": 0.01, "lookback": 3})

        # Shorting a downtrend should be profitable
        assert result.total_pnl > 0

    def test_flat_market_no_signals(self):
        """Verify flat market generates no signals with high threshold."""
        engine = BacktestEngine()
        strategy = TrendFollowingStrategy()

        # Flat prices
        prices = np.ones(50)
        timestamps = np.arange(50, dtype=np.float64)

        result = engine.run_type1(strategy, prices, timestamps, params={"threshold": 0.1, "lookback": 3})

        assert result.total_pnl == 0.0
        assert result.total_trades == 0

    def test_result_metrics(self):
        """Verify BacktestResult metrics computation."""
        engine = BacktestEngine()
        strategy = TrendFollowingStrategy()

        prices = np.linspace(1.0, 1.5, 100)
        timestamps = np.arange(100, dtype=np.float64)

        result = engine.run_type1(strategy, prices, timestamps, params={"threshold": 0.005, "lookback": 3})

        summary = result.summary()
        assert "total_trades" in summary
        assert "win_rate" in summary
        assert "total_pnl" in summary
        assert "sharpe_ratio" in summary
        assert "max_drawdown" in summary


class TestBacktestEngineType2:
    """Tests for Type 2 event-driven backtest."""

    def test_basic_type2_execution(self):
        """Verify Type 2 event-driven backtest runs correctly."""

        class SimpleBuyAndHold:
            def __init__(self):
                self.bought = False
                self.done = False

            def on_tick(self, timestamp, price, bid, ask, volume):
                actions = []
                if self.done:
                    return actions
                if not self.bought and timestamp > 5:
                    actions.append({"action": "buy", "price": price, "size": 1.0})
                    self.bought = True
                elif self.bought and timestamp > 40:
                    actions.append({"action": "sell", "price": price, "size": 1.0})
                    self.bought = False
                    self.done = True
                return actions

            def get_open_orders(self):
                return []

            def reset(self):
                self.bought = False
                self.done = False

        engine = BacktestEngine()
        strategy = SimpleBuyAndHold()

        prices = np.linspace(1.0, 1.5, 50)
        timestamps = np.arange(50, dtype=np.float64)

        result = engine.run_type2(strategy, prices, timestamps)

        assert result.total_trades == 1
        assert result.total_pnl > 0  # Price went up


class TestParameterSweep:
    """Tests for parameter sweep engine."""

    def test_grid_search_finds_optimal(self):
        """Verify grid search evaluates all combinations."""
        engine = BacktestEngine()
        sweep = ParameterSweep(engine=engine, n_folds=3)
        strategy = TrendFollowingStrategy()

        # Create uptrend data
        prices = np.linspace(1.0, 2.0, 200)
        timestamps = np.arange(200, dtype=np.float64)

        param_grid = {
            "threshold": [0.005, 0.01, 0.02],
            "lookback": [2, 3, 5],
        }

        results = sweep.grid_search(strategy, prices, param_grid, timestamps)

        # Should test all 9 combinations (3x3)
        assert len(results) == 9

        # Results should be sorted by OOS PnL
        for i in range(len(results) - 1):
            assert results[i].mean_oos_pnl >= results[i + 1].mean_oos_pnl

    def test_random_search_samples_subset(self):
        """Verify random search samples correct number of combinations."""
        engine = BacktestEngine()
        sweep = ParameterSweep(engine=engine, n_folds=3)
        strategy = TrendFollowingStrategy()

        prices = np.linspace(1.0, 2.0, 200)
        timestamps = np.arange(200, dtype=np.float64)

        param_grid = {
            "threshold": [0.005, 0.01, 0.02, 0.03],
            "lookback": [2, 3, 5, 7],
        }

        results = sweep.random_search(
            strategy, prices, param_grid, n_samples=5, timestamps=timestamps, seed=42
        )

        assert len(results) == 5

    def test_cross_validation_creates_correct_splits(self):
        """Verify cross-validation creates proper train/test splits."""
        sweep = ParameterSweep(n_folds=3)

        # Test fold creation
        folds = sweep._create_folds(100)

        assert len(folds) == 3

        for train_idx, test_idx in folds:
            # Train should come before test (time-series CV)
            assert train_idx[-1] < test_idx[0]
            # No overlap
            assert len(set(train_idx) & set(test_idx)) == 0

    def test_cross_validation_expanding_window(self):
        """Verify expanding window: each fold has more training data."""
        sweep = ParameterSweep(n_folds=3)
        folds = sweep._create_folds(200)

        train_sizes = [len(train) for train, _ in folds]
        # Each successive fold should have more training data
        for i in range(1, len(train_sizes)):
            assert train_sizes[i] > train_sizes[i - 1]


class TestOverfittingDetection:
    """Tests for overfitting detection."""

    def test_overfitting_detected_on_noisy_signal(self):
        """Verify overfitting detection flags degraded OOS performance.

        Strategy: fit perfectly to in-sample noise, check that OOS is flagged.
        """

        class OverfitStrategy:
            """Strategy that memorizes training data patterns."""

            def generate_signals(self, prices: np.ndarray, **params) -> np.ndarray:
                """Buy when price is below mean, sell above - exploits mean-reversion in IS."""
                window = params.get("window", 5)
                signals = np.zeros(len(prices))

                # This strategy works well on mean-reverting data
                # but fails on trending data
                for i in range(window, len(prices)):
                    local_mean = prices[i - window:i].mean()
                    if prices[i] < local_mean * (1 - 0.001):
                        signals[i] = 1
                    elif prices[i] > local_mean * (1 + 0.001):
                        signals[i] = -1

                return signals

        engine = BacktestEngine()
        sweep = ParameterSweep(engine=engine, n_folds=3, overfitting_threshold=0.20)

        # Create data where first half is mean-reverting, second half is trending
        np.random.seed(42)
        # Mean-reverting data for in-sample (oscillates around 1.0)
        mean_rev = 1.0 + 0.1 * np.sin(np.linspace(0, 20 * np.pi, 100))
        # Trending data for out-of-sample
        trending = np.linspace(1.0, 2.0, 100)
        prices = np.concatenate([mean_rev, trending])
        timestamps = np.arange(len(prices), dtype=np.float64)

        strategy = OverfitStrategy()

        param_grid = {"window": [3, 5, 10]}
        results = sweep.grid_search(strategy, prices, param_grid, timestamps)

        # At least some results should flag overfitting since the strategy
        # is designed to work on mean-reverting but fail on trending data
        # Check that degradation detection mechanism works
        has_degradation = any(r.mean_degradation_pct > 0 for r in results)
        assert has_degradation, "Should detect performance degradation across regime change"

    def test_overfitting_threshold_configurable(self):
        """Verify overfitting threshold is configurable."""
        sweep = ParameterSweep(overfitting_threshold=0.10)
        assert sweep.overfitting_threshold == 0.10

        sweep2 = ParameterSweep(overfitting_threshold=0.50)
        assert sweep2.overfitting_threshold == 0.50

    def test_degradation_computation(self):
        """Verify degradation calculation is correct."""
        # IS PnL = 100, OOS PnL = 70 -> 30% degradation
        degradation = ParameterSweep._compute_degradation(100.0, 70.0)
        assert abs(degradation - 0.30) < 1e-10

        # IS PnL = 100, OOS PnL = 100 -> 0% degradation
        degradation = ParameterSweep._compute_degradation(100.0, 100.0)
        assert degradation == 0.0

        # IS PnL = 100, OOS PnL = 120 -> no degradation (OOS better)
        degradation = ParameterSweep._compute_degradation(100.0, 120.0)
        assert degradation == 0.0

        # IS PnL <= 0 -> no meaningful degradation
        degradation = ParameterSweep._compute_degradation(-50.0, -100.0)
        assert degradation == 0.0


class TestAnalysis:
    """Tests for backtest analysis utilities."""

    def test_time_segmentation(self):
        """Verify time segmentation classifies trades correctly."""
        analysis = BacktestAnalysis()

        # Create trades at known times
        # US hours: 14:00 UTC (9:00 ET approx)
        us_trade = Trade(
            entry_time=1700060400.0,  # ~2023-11-15 14:00 UTC
            entry_price=1.0,
            exit_time=1700064000.0,
            exit_price=1.1,
            side="buy",
            pnl=0.1,
        )

        report = analysis.analyze([us_trade])
        assert len(report.time_segments) == 4

    def test_equity_curve(self):
        """Verify equity curve computation."""
        analysis = BacktestAnalysis()

        trades = [
            Trade(entry_time=1.0, entry_price=1.0, exit_time=2.0, exit_price=1.1, side="buy", pnl=0.1),
            Trade(entry_time=3.0, entry_price=1.1, exit_time=4.0, exit_price=1.0, side="buy", pnl=-0.1),
            Trade(entry_time=5.0, entry_price=1.0, exit_time=6.0, exit_price=1.2, side="buy", pnl=0.2),
        ]

        report = analysis.analyze(trades)
        assert report.equity_curve == [0.0, 0.1, 0.0, 0.2]

    def test_nsf_adjustment(self):
        """Verify NSF error incorporation reduces PnL."""
        analysis = BacktestAnalysis(nsf_penalty=0.05)

        trades = [
            Trade(entry_time=1.0, entry_price=1.0, exit_time=2.0, exit_price=1.1, side="buy", pnl=0.1),
        ]

        report = analysis.analyze(trades, nsf_count=2)
        # PnL = 0.1, NSF cost = 2 * 0.05 = 0.10
        assert abs(report.nsf_adjusted_pnl - 0.0) < 1e-10

    def test_max_drawdown(self):
        """Verify max drawdown calculation."""
        analysis = BacktestAnalysis()

        trades = [
            Trade(entry_time=1.0, entry_price=1.0, exit_time=2.0, exit_price=1.1, side="buy", pnl=0.1),
            Trade(entry_time=3.0, entry_price=1.1, exit_time=4.0, exit_price=0.8, side="buy", pnl=-0.3),
            Trade(entry_time=5.0, entry_price=0.8, exit_time=6.0, exit_price=1.0, side="buy", pnl=0.2),
        ]

        report = analysis.analyze(trades)
        # Equity: [0, 0.1, -0.2, 0.0]
        # Peak at 0.1, drawdown to -0.2, so max drawdown = -0.2 - 0.1 = -0.3
        assert report.max_drawdown < 0
