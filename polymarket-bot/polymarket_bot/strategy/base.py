"""Strategy base class and Signal dataclass."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import structlog

from polymarket_bot.config import Config
from polymarket_bot.data.models import Fill, Tick

logger = structlog.get_logger(__name__)


class Direction(str, Enum):
    """Trade direction."""

    BUY = "BUY"
    SELL = "SELL"


class StrategyState(str, Enum):
    """Strategy lifecycle states."""

    INIT = "init"
    WARMUP = "warmup"
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    DONE = "done"


@dataclass
class Signal:
    """Trading signal emitted by a strategy.

    Attributes:
        direction: BUY or SELL.
        token_id: Token or market to trade.
        price: Target execution price.
        size: Position size.
        confidence: Signal confidence (0.0 to 1.0).
        stop_loss_price: Price at which to cut losses.
        take_profit_price: Price at which to take profit.
    """

    direction: Direction
    token_id: str
    price: float
    size: float
    confidence: float = 0.5
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None


class Strategy(ABC):
    """Abstract base class for all trading strategies.

    Lifecycle: init -> warmup -> active -> cooldown -> done.
    """

    def __init__(self, name: str, description: str = "") -> None:
        """Initialize the strategy.

        Args:
            name: Strategy name identifier.
            description: Human-readable description.
        """
        self._name = name
        self._description = description
        self._params: dict[str, Any] = {}
        self._state = StrategyState.INIT
        self._logger = logger.bind(strategy=name)

    @property
    def name(self) -> str:
        """Strategy name."""
        return self._name

    @property
    def description(self) -> str:
        """Strategy description."""
        return self._description

    @property
    def params(self) -> dict[str, Any]:
        """Strategy parameters."""
        return self._params

    @property
    def state(self) -> StrategyState:
        """Current lifecycle state."""
        return self._state

    def setup(self, config: Config) -> None:
        """Setup strategy with configuration.

        Override to load strategy-specific parameters from config.

        Args:
            config: Bot configuration.
        """
        self._state = StrategyState.WARMUP
        self._logger.info("strategy_setup", state=self._state.value)

    def activate(self) -> None:
        """Transition strategy to active state."""
        self._state = StrategyState.ACTIVE
        self._logger.info("strategy_activated")

    def cooldown(self) -> None:
        """Transition strategy to cooldown state."""
        self._state = StrategyState.COOLDOWN
        self._logger.info("strategy_cooldown")

    def done(self) -> None:
        """Transition strategy to done state."""
        self._state = StrategyState.DONE
        self._logger.info("strategy_done")

    @abstractmethod
    def on_tick(self, tick: Tick) -> Optional[Signal]:
        """Process a new tick and optionally emit a signal.

        Args:
            tick: Normalized tick data.

        Returns:
            A Signal if the strategy wants to trade, None otherwise.
        """
        ...

    def on_fill(self, fill: Fill) -> None:
        """Handle a trade fill notification.

        Override in subclass if the strategy needs to track fills.

        Args:
            fill: Fill record.
        """
        pass

    def get_state(self) -> dict[str, Any]:
        """Get current strategy state for monitoring/serialization.

        Returns:
            Dictionary of strategy state.
        """
        return {
            "name": self._name,
            "description": self._description,
            "params": self._params,
            "lifecycle_state": self._state.value,
        }
