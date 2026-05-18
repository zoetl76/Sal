"""Parameter sweep engine with cross-validation and overfitting detection."""

import itertools
import random
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import structlog

from polymarket_bot.backtest.engine import BacktestEngine, StrategyType1
from polymarket_bot.backtest.results import BacktestResult

logger = structlog.get_logger(__name__)


@dataclass
class SweepResult:
    """Result of a single parameter combination evaluation.

    Attributes:
        params: Parameter combination tested.
        in_sample: In-sample backtest result.
        out_of_sample: Out-of-sample backtest result.
        is_win_rate: In-sample win rate.
        oos_win_rate: Out-of-sample win rate.
        is_pnl: In-sample total PnL.
        oos_pnl: Out-of-sample total PnL.
        is_sharpe: In-sample Sharpe ratio.
        oos_sharpe: Out-of-sample Sharpe ratio.
        max_drawdown: Maximum drawdown (out-of-sample).
        overfitting_flag: True if OOS degrades >20% from IS.
        degradation_pct: Percentage degradation from IS to OOS.
    """

    params: dict[str, Any]
    in_sample: BacktestResult
    out_of_sample: BacktestResult
    is_win_rate: float = 0.0
    oos_win_rate: float = 0.0
    is_pnl: float = 0.0
    oos_pnl: float = 0.0
    is_sharpe: float = 0.0
    oos_sharpe: float = 0.0
    max_drawdown: float = 0.0
    overfitting_flag: bool = False
    degradation_pct: float = 0.0


@dataclass
class CrossValidationResult:
    """Result of k-fold cross-validation for a parameter set."""

    params: dict[str, Any]
    fold_results: list[SweepResult] = field(default_factory=list)
    mean_is_pnl: float = 0.0
    mean_oos_pnl: float = 0.0
    mean_is_win_rate: float = 0.0
    mean_oos_win_rate: float = 0.0
    overfitting_flag: bool = False
    mean_degradation_pct: float = 0.0


class ParameterSweep:
    """Multivariate grid/random parameter sweep with cross-validation.

    Features:
        - Grid search: exhaustive search over all parameter combinations
        - Random search: sample N random combinations from the grid
        - 3-fold cross-validation with train/validate/test splits
        - Overfitting detection (flags >20% OOS degradation vs IS)
    """

    def __init__(
        self,
        engine: Optional[BacktestEngine] = None,
        n_folds: int = 3,
        overfitting_threshold: float = 0.20,
    ) -> None:
        """Initialize parameter sweep.

        Args:
            engine: BacktestEngine instance. Creates one if None.
            n_folds: Number of cross-validation folds.
            overfitting_threshold: Degradation threshold for overfitting flag.
        """
        self.engine = engine or BacktestEngine()
        self.n_folds = n_folds
        self.overfitting_threshold = overfitting_threshold
        self._logger = logger.bind(component="param_sweep")

    def grid_search(
        self,
        strategy: StrategyType1,
        prices: np.ndarray,
        param_grid: dict[str, list[Any]],
        timestamps: Optional[np.ndarray] = None,
    ) -> list[CrossValidationResult]:
        """Run exhaustive grid search over all parameter combinations.

        Args:
            strategy: Type 1 strategy to evaluate.
            prices: Full price array.
            param_grid: Dictionary mapping param names to lists of values.
            timestamps: Optional timestamps array.

        Returns:
            List of CrossValidationResult sorted by mean OOS PnL (descending).
        """
        combos = self._generate_grid(param_grid)
        return self._run_sweep(strategy, prices, combos, timestamps)

    def random_search(
        self,
        strategy: StrategyType1,
        prices: np.ndarray,
        param_grid: dict[str, list[Any]],
        n_samples: int = 50,
        timestamps: Optional[np.ndarray] = None,
        seed: Optional[int] = None,
    ) -> list[CrossValidationResult]:
        """Run random parameter search.

        Args:
            strategy: Type 1 strategy to evaluate.
            prices: Full price array.
            param_grid: Dictionary mapping param names to lists of values.
            n_samples: Number of random combinations to test.
            timestamps: Optional timestamps array.
            seed: Random seed for reproducibility.

        Returns:
            List of CrossValidationResult sorted by mean OOS PnL (descending).
        """
        if seed is not None:
            random.seed(seed)

        all_combos = self._generate_grid(param_grid)
        n_samples = min(n_samples, len(all_combos))
        combos = random.sample(all_combos, n_samples)
        return self._run_sweep(strategy, prices, combos, timestamps)

    def _run_sweep(
        self,
        strategy: StrategyType1,
        prices: np.ndarray,
        combos: list[dict[str, Any]],
        timestamps: Optional[np.ndarray] = None,
    ) -> list[CrossValidationResult]:
        """Run sweep for given parameter combinations."""
        if timestamps is None:
            timestamps = np.arange(len(prices), dtype=np.float64)

        results: list[CrossValidationResult] = []

        for params in combos:
            cv_result = self._cross_validate(strategy, prices, timestamps, params)
            results.append(cv_result)

        # Sort by mean OOS PnL descending
        results.sort(key=lambda r: r.mean_oos_pnl, reverse=True)

        self._logger.info(
            "sweep_complete",
            combos_tested=len(combos),
            overfitting_flagged=sum(1 for r in results if r.overfitting_flag),
        )

        return results

    def _cross_validate(
        self,
        strategy: StrategyType1,
        prices: np.ndarray,
        timestamps: np.ndarray,
        params: dict[str, Any],
    ) -> CrossValidationResult:
        """Run k-fold cross-validation for a parameter set.

        Uses rolling window splits: for each fold, the training set is the
        earlier portion and the test set is the later portion.
        """
        folds = self._create_folds(len(prices))
        fold_results: list[SweepResult] = []

        for train_idx, test_idx in folds:
            train_prices = prices[train_idx]
            train_timestamps = timestamps[train_idx]
            test_prices = prices[test_idx]
            test_timestamps = timestamps[test_idx]

            # Run in-sample
            is_result = self.engine.run_type1(strategy, train_prices, train_timestamps, params)

            # Run out-of-sample
            oos_result = self.engine.run_type1(strategy, test_prices, test_timestamps, params)

            # Compute metrics
            is_win_rate = is_result.win_rate
            oos_win_rate = oos_result.win_rate
            is_pnl = is_result.total_pnl
            oos_pnl = oos_result.total_pnl

            # Check degradation
            degradation = self._compute_degradation(is_pnl, oos_pnl)
            overfitting = degradation > self.overfitting_threshold

            fold_results.append(SweepResult(
                params=params,
                in_sample=is_result,
                out_of_sample=oos_result,
                is_win_rate=is_win_rate,
                oos_win_rate=oos_win_rate,
                is_pnl=is_pnl,
                oos_pnl=oos_pnl,
                is_sharpe=is_result.sharpe_ratio,
                oos_sharpe=oos_result.sharpe_ratio,
                max_drawdown=oos_result.max_drawdown,
                overfitting_flag=overfitting,
                degradation_pct=degradation,
            ))

        # Aggregate fold results
        mean_is_pnl = np.mean([r.is_pnl for r in fold_results])
        mean_oos_pnl = np.mean([r.oos_pnl for r in fold_results])
        mean_is_wr = np.mean([r.is_win_rate for r in fold_results])
        mean_oos_wr = np.mean([r.oos_win_rate for r in fold_results])
        mean_degradation = np.mean([r.degradation_pct for r in fold_results])

        # Overall overfitting flag
        overall_overfitting = float(mean_degradation) > self.overfitting_threshold

        return CrossValidationResult(
            params=params,
            fold_results=fold_results,
            mean_is_pnl=float(mean_is_pnl),
            mean_oos_pnl=float(mean_oos_pnl),
            mean_is_win_rate=float(mean_is_wr),
            mean_oos_win_rate=float(mean_oos_wr),
            overfitting_flag=overall_overfitting,
            mean_degradation_pct=float(mean_degradation),
        )

    def _create_folds(self, n: int) -> list[tuple[np.ndarray, np.ndarray]]:
        """Create time-series aware cross-validation folds.

        Uses expanding window: each fold uses progressively more training data
        with a fixed-size test set.
        """
        folds: list[tuple[np.ndarray, np.ndarray]] = []
        fold_size = n // (self.n_folds + 1)

        for i in range(self.n_folds):
            train_end = fold_size * (i + 1)
            test_start = train_end
            test_end = min(test_start + fold_size, n)

            if test_end <= test_start:
                continue

            train_idx = np.arange(0, train_end)
            test_idx = np.arange(test_start, test_end)
            folds.append((train_idx, test_idx))

        return folds

    @staticmethod
    def _compute_degradation(is_pnl: float, oos_pnl: float) -> float:
        """Compute performance degradation from IS to OOS.

        Returns fraction of degradation (e.g., 0.25 = 25% worse OOS).
        """
        if is_pnl <= 0:
            # If IS is not profitable, no meaningful degradation
            return 0.0

        degradation = (is_pnl - oos_pnl) / abs(is_pnl)
        return max(0.0, degradation)

    @staticmethod
    def _generate_grid(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
        """Generate all combinations from parameter grid."""
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combos = []
        for combo in itertools.product(*values):
            combos.append(dict(zip(keys, combo)))
        return combos
