"""Main bot runner with multiple operating modes."""

import asyncio
import time
from enum import Enum
from typing import Any, Optional

import structlog

from polymarket_bot.config import Config
from polymarket_bot.data.models import Tick
from polymarket_bot.deploy.issues import IssueHandler
from polymarket_bot.deploy.monitor import Monitor
from polymarket_bot.risk.anomaly import AnomalyDetector
from polymarket_bot.risk.filters import RiskFilter
from polymarket_bot.risk.stop_loss import StopLossEngine
from polymarket_bot.strategy.base import Signal
from polymarket_bot.strategy.executor import StrategyExecutor

logger = structlog.get_logger(__name__)


class RunMode(str, Enum):
    """Bot operating modes."""

    LIVE = "live"
    DRY_RUN = "dry_run"
    RECORD_ONLY = "record_only"
    BACKTEST = "backtest"


class BotRunner:
    """Main bot runner orchestrating all trading systems.

    Modes:
        - live: Full trading with real money.
        - dry_run: Real wallet with zero balance, all systems active but no actual orders.
        - record_only: Just record data, no trading logic.
        - backtest: Run backtest from recorded data.

    Orchestrates: websocket system -> data recorder -> strategy executor ->
                  risk engine -> order execution.
    """

    def __init__(
        self,
        config: Config,
        mode: RunMode = RunMode.DRY_RUN,
    ) -> None:
        """Initialize the bot runner.

        Args:
            config: Bot configuration.
            mode: Operating mode.
        """
        self._config = config
        self._mode = mode
        self._running = False
        self._start_time: Optional[float] = None

        # Core components
        self._strategy_executor = StrategyExecutor(config)
        self._stop_loss_engine = StopLossEngine()
        self._risk_filter = RiskFilter()
        self._anomaly_detector = AnomalyDetector()
        self._monitor = Monitor(config)
        self._issue_handler = IssueHandler()

        self._tick_count: int = 0
        self._signal_count: int = 0
        self._logger = logger.bind(component="bot_runner", mode=mode.value)

    @property
    def mode(self) -> RunMode:
        """Current operating mode."""
        return self._mode

    @property
    def is_running(self) -> bool:
        """Whether the bot is currently running."""
        return self._running

    @property
    def strategy_executor(self) -> StrategyExecutor:
        """Strategy executor instance."""
        return self._strategy_executor

    @property
    def stop_loss_engine(self) -> StopLossEngine:
        """Stop-loss engine instance."""
        return self._stop_loss_engine

    @property
    def risk_filter(self) -> RiskFilter:
        """Risk filter instance."""
        return self._risk_filter

    @property
    def anomaly_detector(self) -> AnomalyDetector:
        """Anomaly detector instance."""
        return self._anomaly_detector

    @property
    def monitor(self) -> Monitor:
        """Monitor instance."""
        return self._monitor

    async def start(self) -> None:
        """Start the bot runner."""
        self._running = True
        self._start_time = time.time()
        self._logger.info(
            "bot_started",
            mode=self._mode.value,
            strategies=len(self._strategy_executor.strategies),
        )

        # Setup strategies
        self._strategy_executor.setup_all(self._config)
        self._strategy_executor.activate_all()

    async def stop(self) -> None:
        """Stop the bot runner gracefully."""
        self._running = False
        elapsed = time.time() - self._start_time if self._start_time else 0
        self._logger.info(
            "bot_stopped",
            mode=self._mode.value,
            elapsed_seconds=elapsed,
            ticks_processed=self._tick_count,
            signals_generated=self._signal_count,
        )

    async def process_tick(self, tick: Tick) -> list[Signal]:
        """Process a single tick through the full pipeline.

        Pipeline: anomaly check -> issue check -> strategy -> risk filter ->
                  stop-loss -> signal output.

        Args:
            tick: Incoming tick data.

        Returns:
            List of validated signals (empty if mode is record_only).
        """
        self._tick_count += 1

        # Monitor tick health
        self._monitor.on_tick(tick)
        self._issue_handler.on_tick(tick)

        # Record-only mode: just track data
        if self._mode == RunMode.RECORD_ONLY:
            return []

        # Anomaly detection
        anomaly = self._anomaly_detector.on_tick(tick)
        if anomaly is not None:
            self._monitor.on_anomaly(anomaly)

        # Check if paused (by anomaly detector or monitor)
        if self._anomaly_detector.is_paused or self._monitor.is_paused:
            return []

        # Check stop-losses (zero latency)
        stop_signals = self._stop_loss_engine.on_tick(tick)

        # Feed tick to strategies
        strategy_signals = self._strategy_executor.on_tick(tick)

        # Combine signals
        all_signals = stop_signals + strategy_signals

        # Track stop signal identities to bypass risk filter reliably
        stop_signal_ids = {id(s) for s in stop_signals}

        # Apply risk filters (skip for stop-loss signals)
        validated_signals: list[Signal] = []
        for signal in all_signals:
            if id(signal) in stop_signal_ids:
                # Stop-loss signals bypass risk filters
                validated_signals.append(signal)
            else:
                passed, reason = self._risk_filter.check_signal(signal)
                if passed:
                    validated_signals.append(signal)
                else:
                    self._logger.debug(
                        "signal_filtered",
                        reason=reason,
                        direction=signal.direction.value,
                        token_id=signal.token_id,
                    )

        # In dry-run mode, log signals but don't execute
        if self._mode == RunMode.DRY_RUN:
            for signal in validated_signals:
                self._logger.info(
                    "dry_run_signal",
                    direction=signal.direction.value,
                    token_id=signal.token_id,
                    price=signal.price,
                    size=signal.size,
                )

        self._signal_count += len(validated_signals)
        return validated_signals

    def get_state(self) -> dict[str, Any]:
        """Get complete bot state for monitoring."""
        return {
            "mode": self._mode.value,
            "running": self._running,
            "uptime": time.time() - self._start_time if self._start_time else 0,
            "tick_count": self._tick_count,
            "signal_count": self._signal_count,
            "strategies": self._strategy_executor.get_state(),
            "risk": self._risk_filter.get_state(),
            "stop_loss": self._stop_loss_engine.get_state(),
            "anomaly": self._anomaly_detector.get_state(),
            "monitor": self._monitor.get_state(),
            "issues": self._issue_handler.get_state(),
        }
