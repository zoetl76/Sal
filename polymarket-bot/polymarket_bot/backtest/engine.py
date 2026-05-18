"""Backtesting engine supporting Type 1 (vectorized) and Type 2 (event-driven) strategies."""

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import numpy as np
import structlog

from polymarket_bot.backtest.results import BacktestResult

logger = structlog.get_logger(__name__)


class StrategyType1(Protocol):
    """Protocol for Type 1 (simple, vectorized) strategies.

    Type 1 strategies use strike/close price + signal and are AI-backtestable.
    They return a signal array where:
        1 = buy, -1 = sell, 0 = hold
    """

    def generate_signals(self, prices: np.ndarray, **params: Any) -> np.ndarray:
        """Generate trading signals from price data.

        Args:
            prices: Array of prices.
            **params: Strategy parameters.

        Returns:
            Array of signals (1=buy, -1=sell, 0=hold).
        """
        ...


class StrategyType2(Protocol):
    """Protocol for Type 2 (complex, event-driven) strategies.

    Type 2 strategies model GTC bids, stops, and order-book interaction.
    They process tick-by-tick and manage their own order state.
    """

    def on_tick(self, timestamp: float, price: float, bid: float, ask: float, volume: float) -> list[dict[str, Any]]:
        """Process a single tick event.

        Args:
            timestamp: Tick timestamp.
            price: Current price.
            bid: Best bid.
            ask: Best ask.
            volume: Trade volume.

        Returns:
            List of order actions: {'action': 'buy'|'sell', 'price': float, 'size': float}
        """
        ...

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Get currently open orders."""
        ...

    def reset(self) -> None:
        """Reset strategy state for new backtest run."""
        ...


@dataclass
class Trade:
    """Represents a single trade in the backtest."""

    entry_time: float
    entry_price: float
    exit_time: float
    exit_price: float
    side: str  # 'buy' or 'sell'
    size: float = 1.0
    pnl: float = 0.0


class BacktestEngine:
    """Backtesting engine with support for vectorized and event-driven strategies.

    Supports:
        - Type 1: Simple vectorized backtest using NumPy
        - Type 2: Complex event-driven simulation with order book modeling
        - Parameter sweeps via run_sweep()
    """

    def __init__(self, initial_capital: float = 10000.0) -> None:
        """Initialize the backtest engine.

        Args:
            initial_capital: Starting capital for the backtest.
        """
        self.initial_capital = initial_capital
        self._logger = logger.bind(component="backtest_engine")

    def run_type1(
        self,
        strategy: StrategyType1,
        prices: np.ndarray,
        timestamps: Optional[np.ndarray] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> BacktestResult:
        """Run a Type 1 vectorized backtest.

        Uses NumPy for fast computation. Suitable for parameter sweeps.

        Args:
            strategy: Strategy implementing StrategyType1 protocol.
            prices: Array of prices.
            timestamps: Optional array of timestamps.
            params: Strategy parameters.

        Returns:
            BacktestResult with performance metrics.
        """
        params = params or {}
        if timestamps is None:
            timestamps = np.arange(len(prices), dtype=np.float64)

        signals = strategy.generate_signals(prices, **params)

        # Vectorized PnL computation
        # Returns at each time step
        returns = np.diff(prices) / prices[:-1]

        # Position: signal determines direction, shifted by 1 (trade on signal, get next return)
        positions = signals[:-1]

        # PnL per period
        pnl_per_period = positions * returns

        # Cumulative PnL
        cumulative_pnl = np.cumsum(pnl_per_period)

        # Extract trades from signal changes
        trades = self._extract_trades_type1(signals, prices, timestamps)

        # Compute metrics
        total_pnl = float(cumulative_pnl[-1]) if len(cumulative_pnl) > 0 else 0.0
        equity_curve = np.concatenate([[0.0], cumulative_pnl])

        return BacktestResult(
            trades=trades,
            total_pnl=total_pnl,
            equity_curve=equity_curve.tolist(),
            initial_capital=self.initial_capital,
            params=params,
            timestamps=timestamps.tolist(),
        )

    def run_type2(
        self,
        strategy: StrategyType2,
        prices: np.ndarray,
        timestamps: np.ndarray,
        bids: Optional[np.ndarray] = None,
        asks: Optional[np.ndarray] = None,
        volumes: Optional[np.ndarray] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> BacktestResult:
        """Run a Type 2 event-driven backtest.

        Processes tick-by-tick with full order book modeling.

        Args:
            strategy: Strategy implementing StrategyType2 protocol.
            prices: Array of prices.
            timestamps: Array of timestamps.
            bids: Array of bid prices.
            asks: Array of ask prices.
            volumes: Array of volumes.
            params: Strategy parameters (used to init strategy state).

        Returns:
            BacktestResult with performance metrics.
        """
        strategy.reset()

        if bids is None:
            bids = prices.copy()
        if asks is None:
            asks = prices.copy()
        if volumes is None:
            volumes = np.ones(len(prices))

        trades: list[Trade] = []
        open_position: Optional[dict[str, Any]] = None
        equity: list[float] = [0.0]

        for i in range(len(prices)):
            actions = strategy.on_tick(
                timestamp=float(timestamps[i]),
                price=float(prices[i]),
                bid=float(bids[i]),
                ask=float(asks[i]),
                volume=float(volumes[i]),
            )

            for action in actions:
                if action["action"] == "buy" and open_position is None:
                    open_position = {
                        "entry_time": float(timestamps[i]),
                        "entry_price": float(action.get("price", prices[i])),
                        "side": "buy",
                        "size": float(action.get("size", 1.0)),
                    }
                elif action["action"] == "sell" and open_position is not None:
                    exit_price = float(action.get("price", prices[i]))
                    pnl = (exit_price - open_position["entry_price"]) * open_position["size"]
                    trades.append(Trade(
                        entry_time=open_position["entry_time"],
                        entry_price=open_position["entry_price"],
                        exit_time=float(timestamps[i]),
                        exit_price=exit_price,
                        side=open_position["side"],
                        size=open_position["size"],
                        pnl=pnl,
                    ))
                    open_position = None

            current_pnl = sum(t.pnl for t in trades)
            if open_position is not None:
                unrealized = (float(prices[i]) - open_position["entry_price"]) * open_position["size"]
                current_pnl += unrealized
            equity.append(current_pnl)

        total_pnl = sum(t.pnl for t in trades)

        return BacktestResult(
            trades=trades,
            total_pnl=total_pnl,
            equity_curve=equity,
            initial_capital=self.initial_capital,
            params=params or {},
            timestamps=timestamps.tolist(),
        )

    def _extract_trades_type1(
        self,
        signals: np.ndarray,
        prices: np.ndarray,
        timestamps: np.ndarray,
    ) -> list[Trade]:
        """Extract trades from signal array.

        A trade is opened when signal goes from 0 to 1/-1 and closed
        when it returns to 0 or reverses.
        """
        trades: list[Trade] = []
        position = 0  # 0=flat, 1=long, -1=short
        entry_idx = 0

        for i in range(len(signals)):
            sig = int(signals[i])

            if position == 0 and sig != 0:
                # Open position
                position = sig
                entry_idx = i
            elif position != 0 and (sig == 0 or sig == -position):
                # Close position
                if position == 1:
                    pnl = prices[i] - prices[entry_idx]
                else:
                    pnl = prices[entry_idx] - prices[i]

                trades.append(Trade(
                    entry_time=float(timestamps[entry_idx]),
                    entry_price=float(prices[entry_idx]),
                    exit_time=float(timestamps[i]),
                    exit_price=float(prices[i]),
                    side="buy" if position == 1 else "sell",
                    pnl=float(pnl),
                ))

                # If reversing, open new position
                if sig == -position:
                    position = sig
                    entry_idx = i
                else:
                    position = 0

        return trades
