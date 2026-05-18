"""Concrete strategy templates for Polymarket trading."""

import time
from collections import deque
from typing import Any, Optional

import numpy as np
import structlog

from polymarket_bot.config import Config
from polymarket_bot.data.models import Fill, Tick
from polymarket_bot.strategy.base import Direction, Signal, Strategy, StrategyState

logger = structlog.get_logger(__name__)


class MarketMakerStrategy(Strategy):
    """Places symmetric bids/asks around mid price, manages inventory.

    Aims to capture the spread by placing orders on both sides of the market.
    Adjusts quotes based on inventory to reduce risk.
    """

    def __init__(self) -> None:
        super().__init__(
            name="market_maker",
            description="Symmetric bid/ask around mid with inventory management",
        )
        self._params = {
            "spread": 0.02,
            "order_size": 10.0,
            "max_inventory": 50.0,
            "skew_factor": 0.5,
        }
        self._inventory: float = 0.0
        self._last_mid: float = 0.0

    def setup(self, config: Config) -> None:
        """Setup market maker parameters."""
        super().setup(config)
        trading = config.get("trading", {})
        self._params["max_inventory"] = trading.get("max_position_size", 50.0)

    def on_tick(self, tick: Tick) -> Optional[Signal]:
        """Generate market making signals based on mid price and inventory."""
        if self._state != StrategyState.ACTIVE:
            return None

        if tick.bid <= 0 or tick.ask <= 0:
            return None

        mid = (tick.bid + tick.ask) / 2.0
        self._last_mid = mid

        spread = self._params["spread"]
        skew = self._params["skew_factor"] * (self._inventory / self._params["max_inventory"])

        # Adjust quotes based on inventory
        bid_price = mid - spread / 2.0 - skew
        ask_price = mid + spread / 2.0 - skew

        # If inventory is too long, prefer selling
        if self._inventory > self._params["max_inventory"] * 0.8:
            return Signal(
                direction=Direction.SELL,
                token_id=tick.token_id,
                price=ask_price,
                size=self._params["order_size"],
                confidence=0.6,
            )

        # If inventory is too short, prefer buying
        if self._inventory < -self._params["max_inventory"] * 0.8:
            return Signal(
                direction=Direction.BUY,
                token_id=tick.token_id,
                price=bid_price,
                size=self._params["order_size"],
                confidence=0.6,
            )

        # Default: place on the side with better opportunity
        if mid < self._last_mid:
            return Signal(
                direction=Direction.BUY,
                token_id=tick.token_id,
                price=bid_price,
                size=self._params["order_size"],
                confidence=0.5,
            )

        return None

    def on_fill(self, fill: Fill) -> None:
        """Track inventory from fills."""
        if fill.side == "buy":
            self._inventory += fill.size
        else:
            self._inventory -= fill.size

    def get_state(self) -> dict[str, Any]:
        """Get market maker state."""
        state = super().get_state()
        state["inventory"] = self._inventory
        state["last_mid"] = self._last_mid
        return state


class LadderStrategy(Strategy):
    """Places orders at price ladder levels.

    Distributes orders across multiple price levels to capture
    price movement in either direction.
    """

    def __init__(self) -> None:
        super().__init__(
            name="ladder",
            description="Orders at multiple price ladder levels",
        )
        self._params = {
            "num_levels": 5,
            "level_spacing": 0.01,
            "size_per_level": 5.0,
            "base_price": 0.0,
        }
        self._filled_levels: set[int] = set()

    def setup(self, config: Config) -> None:
        """Setup ladder parameters."""
        super().setup(config)

    def on_tick(self, tick: Tick) -> Optional[Signal]:
        """Generate signals when price hits ladder levels."""
        if self._state != StrategyState.ACTIVE:
            return None

        if self._params["base_price"] == 0.0:
            self._params["base_price"] = tick.price
            return None

        base = self._params["base_price"]
        spacing = self._params["level_spacing"]

        # Check each ladder level
        for level in range(1, self._params["num_levels"] + 1):
            if level in self._filled_levels:
                continue

            buy_level = base - level * spacing
            sell_level = base + level * spacing

            if tick.price <= buy_level:
                self._filled_levels.add(level)
                return Signal(
                    direction=Direction.BUY,
                    token_id=tick.token_id,
                    price=buy_level,
                    size=self._params["size_per_level"],
                    confidence=0.5 + level * 0.05,
                )

            if tick.price >= sell_level:
                self._filled_levels.add(level)
                return Signal(
                    direction=Direction.SELL,
                    token_id=tick.token_id,
                    price=sell_level,
                    size=self._params["size_per_level"],
                    confidence=0.5 + level * 0.05,
                )

        return None

    def get_state(self) -> dict[str, Any]:
        """Get ladder state."""
        state = super().get_state()
        state["filled_levels"] = list(self._filled_levels)
        state["base_price"] = self._params["base_price"]
        return state


class DirectionalStrategy(Strategy):
    """Takes directional bets based on signal threshold.

    Uses price momentum to determine direction and only trades
    when conviction exceeds a configurable threshold.
    """

    def __init__(self) -> None:
        super().__init__(
            name="directional",
            description="Directional bets based on momentum threshold",
        )
        self._params = {
            "lookback": 10,
            "threshold": 0.02,
            "size": 10.0,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.10,
        }
        self._price_history: deque[float] = deque(maxlen=50)

    def setup(self, config: Config) -> None:
        """Setup directional parameters."""
        super().setup(config)

    def on_tick(self, tick: Tick) -> Optional[Signal]:
        """Generate directional signal based on momentum."""
        if self._state != StrategyState.ACTIVE:
            return None

        self._price_history.append(tick.price)

        lookback = self._params["lookback"]
        if len(self._price_history) < lookback:
            return None

        prices = list(self._price_history)
        current = prices[-1]
        past = prices[-lookback]

        if past == 0:
            return None

        momentum = (current - past) / past
        threshold = self._params["threshold"]

        if momentum > threshold:
            stop_loss = current * (1.0 - self._params["stop_loss_pct"])
            take_profit = current * (1.0 + self._params["take_profit_pct"])
            confidence = min(1.0, abs(momentum) / (threshold * 3))
            return Signal(
                direction=Direction.BUY,
                token_id=tick.token_id,
                price=current,
                size=self._params["size"],
                confidence=confidence,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
            )

        if momentum < -threshold:
            stop_loss = current * (1.0 + self._params["stop_loss_pct"])
            take_profit = current * (1.0 - self._params["take_profit_pct"])
            confidence = min(1.0, abs(momentum) / (threshold * 3))
            return Signal(
                direction=Direction.SELL,
                token_id=tick.token_id,
                price=current,
                size=self._params["size"],
                confidence=confidence,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
            )

        return None

    def get_state(self) -> dict[str, Any]:
        """Get directional strategy state."""
        state = super().get_state()
        state["price_history_len"] = len(self._price_history)
        return state


class MeanReversionStrategy(Strategy):
    """Bets on price returning to mean after deviation.

    Monitors price deviation from a rolling mean and trades
    when deviation exceeds a threshold, betting on reversion.
    """

    def __init__(self) -> None:
        super().__init__(
            name="mean_reversion",
            description="Bet on price reverting to rolling mean",
        )
        self._params = {
            "window": 20,
            "entry_std_devs": 2.0,
            "exit_std_devs": 0.5,
            "size": 10.0,
        }
        self._price_history: deque[float] = deque(maxlen=100)
        self._in_position: bool = False
        self._position_direction: Optional[Direction] = None

    def setup(self, config: Config) -> None:
        """Setup mean reversion parameters."""
        super().setup(config)

    def on_tick(self, tick: Tick) -> Optional[Signal]:
        """Generate mean reversion signal on deviation from rolling mean."""
        if self._state != StrategyState.ACTIVE:
            return None

        self._price_history.append(tick.price)

        window = self._params["window"]
        if len(self._price_history) < window:
            return None

        prices = np.array(list(self._price_history)[-window:])
        mean = float(np.mean(prices))
        std = float(np.std(prices))

        if std == 0:
            return None

        z_score = (tick.price - mean) / std
        entry_threshold = self._params["entry_std_devs"]
        exit_threshold = self._params["exit_std_devs"]

        # Exit logic
        if self._in_position:
            if abs(z_score) < exit_threshold:
                self._in_position = False
                direction = (
                    Direction.SELL
                    if self._position_direction == Direction.BUY
                    else Direction.BUY
                )
                self._position_direction = None
                return Signal(
                    direction=direction,
                    token_id=tick.token_id,
                    price=tick.price,
                    size=self._params["size"],
                    confidence=0.6,
                )
            return None

        # Entry logic: price deviated too far from mean
        if z_score > entry_threshold:
            # Price too high, bet on reversion down
            self._in_position = True
            self._position_direction = Direction.SELL
            return Signal(
                direction=Direction.SELL,
                token_id=tick.token_id,
                price=tick.price,
                size=self._params["size"],
                confidence=min(1.0, abs(z_score) / (entry_threshold * 2)),
                stop_loss_price=tick.price * 1.05,
            )

        if z_score < -entry_threshold:
            # Price too low, bet on reversion up
            self._in_position = True
            self._position_direction = Direction.BUY
            return Signal(
                direction=Direction.BUY,
                token_id=tick.token_id,
                price=tick.price,
                size=self._params["size"],
                confidence=min(1.0, abs(z_score) / (entry_threshold * 2)),
                stop_loss_price=tick.price * 0.95,
            )

        return None

    def get_state(self) -> dict[str, Any]:
        """Get mean reversion state."""
        state = super().get_state()
        state["in_position"] = self._in_position
        state["price_history_len"] = len(self._price_history)
        if len(self._price_history) >= self._params["window"]:
            prices = np.array(list(self._price_history)[-self._params["window"]:])
            state["current_mean"] = float(np.mean(prices))
            state["current_std"] = float(np.std(prices))
        return state


class ExternalSignalStrategy(Strategy):
    """Trades Polymarket based on Binance/Coinbase price movements.

    Monitors external feeds for directional signals (candle patterns,
    momentum) and applies them to Polymarket positions.
    """

    def __init__(self) -> None:
        super().__init__(
            name="external_signal",
            description="Trade Polymarket based on external feed signals",
        )
        self._params = {
            "external_source": "binance",
            "correlation_threshold": 0.7,
            "signal_threshold": 0.015,
            "size": 10.0,
            "cooldown_ticks": 5,
        }
        self._external_prices: deque[float] = deque(maxlen=50)
        self._polymarket_prices: deque[float] = deque(maxlen=50)
        self._ticks_since_signal: int = 0
        self._last_signal_direction: Optional[Direction] = None

    def setup(self, config: Config) -> None:
        """Setup external signal parameters."""
        super().setup(config)

    def on_tick(self, tick: Tick) -> Optional[Signal]:
        """Process tick from either external or Polymarket source."""
        if self._state != StrategyState.ACTIVE:
            return None

        self._ticks_since_signal += 1

        # Route tick to the appropriate price history
        if tick.source == self._params["external_source"]:
            self._external_prices.append(tick.price)
            return self._check_external_signal(tick)
        else:
            self._polymarket_prices.append(tick.price)
            return None

    def _check_external_signal(self, tick: Tick) -> Optional[Signal]:
        """Check if external price movement generates a signal."""
        lookback = 5
        if len(self._external_prices) < lookback:
            return None

        # Cooldown check
        if self._ticks_since_signal < self._params["cooldown_ticks"]:
            return None

        prices = list(self._external_prices)
        current = prices[-1]
        past = prices[-lookback]

        if past == 0:
            return None

        momentum = (current - past) / past
        threshold = self._params["signal_threshold"]

        if abs(momentum) < threshold:
            return None

        # Generate signal based on external momentum
        if momentum > threshold:
            direction = Direction.BUY
        else:
            direction = Direction.SELL

        # Avoid repeated signals in same direction
        if direction == self._last_signal_direction:
            return None

        self._last_signal_direction = direction
        self._ticks_since_signal = 0

        # Use latest polymarket token_id if available
        target_token = tick.token_id

        confidence = min(1.0, abs(momentum) / (threshold * 2))

        return Signal(
            direction=direction,
            token_id=target_token,
            price=tick.price,
            size=self._params["size"],
            confidence=confidence,
        )

    def get_state(self) -> dict[str, Any]:
        """Get external signal strategy state."""
        state = super().get_state()
        state["external_prices_len"] = len(self._external_prices)
        state["polymarket_prices_len"] = len(self._polymarket_prices)
        state["ticks_since_signal"] = self._ticks_since_signal
        return state
