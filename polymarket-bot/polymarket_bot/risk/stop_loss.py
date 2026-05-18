"""Stop-loss engine with zero added latency and per-strategy configuration."""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from polymarket_bot.data.models import Tick
from polymarket_bot.strategy.base import Direction, Signal

logger = structlog.get_logger(__name__)


@dataclass
class StopLossConfig:
    """Per-strategy stop-loss configuration.

    Attributes:
        enabled: Whether stop-loss is active.
        stop_loss_pct: Percentage below entry to trigger stop.
        trailing_stop: Whether to use trailing stop.
        trailing_distance: Trailing stop distance as percentage.
        max_entry_price: Maximum allowed entry price (default 85 cents).
        min_entry_price: Minimum allowed entry price.
    """

    enabled: bool = True
    stop_loss_pct: float = 0.10
    trailing_stop: bool = False
    trailing_distance: float = 0.05
    max_entry_price: float = 0.85
    min_entry_price: float = 0.05


@dataclass
class Position:
    """Tracked position for stop-loss monitoring.

    Attributes:
        token_id: Token or market identifier.
        entry_price: Entry price.
        direction: BUY or SELL.
        size: Position size.
        strategy_name: Name of the strategy that opened this position.
        stop_price: Current stop-loss trigger price.
        highest_price: Highest price seen since entry (for trailing).
        lowest_price: Lowest price seen since entry (for trailing).
        entry_time: Unix timestamp of entry.
    """

    token_id: str
    entry_price: float
    direction: Direction
    size: float
    strategy_name: str
    stop_price: float
    highest_price: float
    lowest_price: float
    entry_time: float = field(default_factory=time.time)


class StopLossEngine:
    """Custom stop-loss engine with zero added latency.

    Monitors price stream and triggers market sell immediately when stop hit.
    Supports per-strategy configuration with optional trailing stops.
    """

    def __init__(self) -> None:
        """Initialize the stop-loss engine."""
        self._positions: dict[str, Position] = {}
        self._configs: dict[str, StopLossConfig] = {}
        self._default_config = StopLossConfig()
        self._triggered_stops: list[dict[str, Any]] = []
        self._logger = logger.bind(component="stop_loss_engine")

    def configure_strategy(self, strategy_name: str, config: StopLossConfig) -> None:
        """Set stop-loss configuration for a strategy.

        Args:
            strategy_name: Strategy name.
            config: Stop-loss configuration.
        """
        self._configs[strategy_name] = config
        self._logger.info(
            "stop_loss_configured",
            strategy=strategy_name,
            enabled=config.enabled,
            pct=config.stop_loss_pct,
            trailing=config.trailing_stop,
        )

    def get_config(self, strategy_name: str) -> StopLossConfig:
        """Get stop-loss config for a strategy.

        Args:
            strategy_name: Strategy name.

        Returns:
            StopLossConfig for the strategy.
        """
        return self._configs.get(strategy_name, self._default_config)

    def check_entry_price(self, price: float, strategy_name: str = "") -> bool:
        """Check if an entry price is within allowed bounds.

        Args:
            price: Proposed entry price.
            strategy_name: Strategy name for config lookup.

        Returns:
            True if the price is acceptable, False if it should be blocked.
        """
        config = self.get_config(strategy_name)
        if price > config.max_entry_price:
            self._logger.warning(
                "entry_price_too_high",
                price=price,
                max_allowed=config.max_entry_price,
                strategy=strategy_name,
            )
            return False
        if price < config.min_entry_price:
            self._logger.warning(
                "entry_price_too_low",
                price=price,
                min_allowed=config.min_entry_price,
                strategy=strategy_name,
            )
            return False
        return True

    def open_position(
        self,
        token_id: str,
        entry_price: float,
        direction: Direction,
        size: float,
        strategy_name: str,
    ) -> Optional[str]:
        """Register a new position for stop-loss monitoring.

        Args:
            token_id: Token identifier.
            entry_price: Entry price.
            direction: Trade direction.
            size: Position size.
            strategy_name: Strategy that opened the position.

        Returns:
            Position key if registered, None if blocked by price filter.
        """
        config = self.get_config(strategy_name)

        if not config.enabled:
            return None

        if not self.check_entry_price(entry_price, strategy_name):
            return None

        # Calculate initial stop price
        if direction == Direction.BUY:
            stop_price = entry_price * (1.0 - config.stop_loss_pct)
        else:
            stop_price = entry_price * (1.0 + config.stop_loss_pct)

        position_key = f"{strategy_name}:{token_id}"
        self._positions[position_key] = Position(
            token_id=token_id,
            entry_price=entry_price,
            direction=direction,
            size=size,
            strategy_name=strategy_name,
            stop_price=stop_price,
            highest_price=entry_price,
            lowest_price=entry_price,
        )

        self._logger.info(
            "position_opened",
            key=position_key,
            entry=entry_price,
            stop=stop_price,
            direction=direction.value,
        )
        return position_key

    def close_position(self, position_key: str) -> None:
        """Remove a position from monitoring.

        Args:
            position_key: Position key to remove.
        """
        if position_key in self._positions:
            del self._positions[position_key]
            self._logger.info("position_closed", key=position_key)

    def on_tick(self, tick: Tick) -> list[Signal]:
        """Process a tick and check all positions for stop triggers.

        Zero latency: processes inline with tick stream.

        Args:
            tick: Current tick data.

        Returns:
            List of stop-loss exit signals.
        """
        triggered: list[Signal] = []

        for key, position in list(self._positions.items()):
            if position.token_id != tick.token_id:
                continue

            config = self.get_config(position.strategy_name)

            # Update trailing stop
            if config.trailing_stop:
                self._update_trailing(position, tick.price, config)

            # Check if stop is hit
            if self._is_stop_triggered(position, tick.price):
                # Generate immediate exit signal
                exit_direction = (
                    Direction.SELL if position.direction == Direction.BUY else Direction.BUY
                )
                signal = Signal(
                    direction=exit_direction,
                    token_id=position.token_id,
                    price=tick.price,
                    size=position.size,
                    confidence=1.0,
                )
                triggered.append(signal)
                self._triggered_stops.append({
                    "position_key": key,
                    "entry_price": position.entry_price,
                    "stop_price": position.stop_price,
                    "trigger_price": tick.price,
                    "timestamp": tick.timestamp,
                })
                del self._positions[key]
                self._logger.warning(
                    "stop_loss_triggered",
                    key=key,
                    entry=position.entry_price,
                    stop=position.stop_price,
                    current=tick.price,
                )

        return triggered

    def _update_trailing(
        self, position: Position, current_price: float, config: StopLossConfig
    ) -> None:
        """Update trailing stop for a position.

        Args:
            position: Position to update.
            current_price: Current market price.
            config: Stop-loss configuration.
        """
        if position.direction == Direction.BUY:
            if current_price > position.highest_price:
                position.highest_price = current_price
                new_stop = current_price * (1.0 - config.trailing_distance)
                if new_stop > position.stop_price:
                    position.stop_price = new_stop
        else:
            if current_price < position.lowest_price:
                position.lowest_price = current_price
                new_stop = current_price * (1.0 + config.trailing_distance)
                if new_stop < position.stop_price:
                    position.stop_price = new_stop

    def _is_stop_triggered(self, position: Position, current_price: float) -> bool:
        """Check if a stop-loss is triggered.

        Args:
            position: Position to check.
            current_price: Current market price.

        Returns:
            True if stop is triggered.
        """
        if position.direction == Direction.BUY:
            return current_price <= position.stop_price
        else:
            return current_price >= position.stop_price

    @property
    def positions(self) -> dict[str, Position]:
        """Active positions being monitored."""
        return dict(self._positions)

    @property
    def triggered_stops(self) -> list[dict[str, Any]]:
        """History of triggered stop-losses."""
        return list(self._triggered_stops)

    def get_state(self) -> dict[str, Any]:
        """Get engine state for monitoring."""
        return {
            "active_positions": len(self._positions),
            "total_triggered": len(self._triggered_stops),
            "positions": {
                k: {
                    "token_id": p.token_id,
                    "entry_price": p.entry_price,
                    "stop_price": p.stop_price,
                    "direction": p.direction.value,
                }
                for k, p in self._positions.items()
            },
        }
