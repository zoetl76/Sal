"""Strategy executor that manages strategy lifecycle and signal routing."""

import asyncio
import time
from typing import Any, Optional

import structlog

from polymarket_bot.config import Config
from polymarket_bot.data.models import Fill, Tick
from polymarket_bot.strategy.base import Signal, Strategy, StrategyState

logger = structlog.get_logger(__name__)


class StrategyExecutor:
    """Manages strategy lifecycle, feeds ticks, collects signals.

    Supports multiple concurrent strategies with per-strategy PnL tracking.
    Routes signals to order execution.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialize the strategy executor.

        Args:
            config: Bot configuration.
        """
        self._config = config
        self._strategies: dict[str, Strategy] = {}
        self._pnl: dict[str, float] = {}
        self._signal_count: dict[str, int] = {}
        self._active = False
        self._logger = logger.bind(component="strategy_executor")

    def register_strategy(self, strategy: Strategy) -> None:
        """Register a strategy for execution.

        Args:
            strategy: Strategy instance to register.
        """
        self._strategies[strategy.name] = strategy
        self._pnl[strategy.name] = 0.0
        self._signal_count[strategy.name] = 0
        self._logger.info("strategy_registered", strategy=strategy.name)

    def unregister_strategy(self, name: str) -> None:
        """Remove a strategy from execution.

        Args:
            name: Strategy name to remove.
        """
        if name in self._strategies:
            del self._strategies[name]
            self._logger.info("strategy_unregistered", strategy=name)

    def setup_all(self, config: Config) -> None:
        """Setup all registered strategies with configuration.

        Args:
            config: Bot configuration.
        """
        self._config = config
        for strategy in self._strategies.values():
            strategy.setup(config)
        self._logger.info("all_strategies_setup", count=len(self._strategies))

    def activate_all(self) -> None:
        """Activate all strategies that are in warmup state."""
        for strategy in self._strategies.values():
            if strategy.state == StrategyState.WARMUP:
                strategy.activate()
        self._active = True
        self._logger.info("all_strategies_activated")

    def on_tick(self, tick: Tick) -> list[Signal]:
        """Feed a tick to all active strategies and collect signals.

        Args:
            tick: Normalized tick data.

        Returns:
            List of signals from all strategies.
        """
        signals: list[Signal] = []

        for name, strategy in self._strategies.items():
            if strategy.state != StrategyState.ACTIVE:
                continue

            try:
                signal = strategy.on_tick(tick)
                if signal is not None:
                    signals.append(signal)
                    self._signal_count[name] = self._signal_count.get(name, 0) + 1
                    self._logger.debug(
                        "signal_generated",
                        strategy=name,
                        direction=signal.direction.value,
                        token_id=signal.token_id,
                        price=signal.price,
                    )
            except Exception as e:
                self._logger.error("strategy_tick_error", strategy=name, error=str(e))

        return signals

    def on_fill(self, fill: Fill, strategy_name: Optional[str] = None) -> None:
        """Route a fill notification to strategies.

        Args:
            fill: Fill record.
            strategy_name: Optional specific strategy to notify. If None, notifies all.
        """
        if strategy_name and strategy_name in self._strategies:
            self._strategies[strategy_name].on_fill(fill)
            self._update_pnl(strategy_name, fill)
        else:
            for name, strategy in self._strategies.items():
                strategy.on_fill(fill)

    def _update_pnl(self, strategy_name: str, fill: Fill) -> None:
        """Update PnL tracking for a strategy.

        Args:
            strategy_name: Strategy name.
            fill: Fill to account for.
        """
        # Simple PnL tracking based on fill side and slippage
        pnl_change = -fill.slippage * fill.size
        self._pnl[strategy_name] = self._pnl.get(strategy_name, 0.0) + pnl_change

    def get_pnl(self, strategy_name: Optional[str] = None) -> dict[str, float]:
        """Get PnL for one or all strategies.

        Args:
            strategy_name: Optional strategy name. If None, returns all.

        Returns:
            Dictionary of strategy name to PnL.
        """
        if strategy_name:
            return {strategy_name: self._pnl.get(strategy_name, 0.0)}
        return dict(self._pnl)

    def get_state(self) -> dict[str, Any]:
        """Get executor state including all strategy states.

        Returns:
            Dictionary with executor and per-strategy state.
        """
        return {
            "active": self._active,
            "strategy_count": len(self._strategies),
            "strategies": {
                name: strategy.get_state()
                for name, strategy in self._strategies.items()
            },
            "pnl": dict(self._pnl),
            "signal_counts": dict(self._signal_count),
        }

    @property
    def strategies(self) -> dict[str, Strategy]:
        """Registered strategies."""
        return dict(self._strategies)

    @property
    def is_active(self) -> bool:
        """Whether the executor is active."""
        return self._active
