"""
Main Bot Module
===============
Orchestrates the trading loop:
1. Discover markets
2. Generate signals via strategy
3. Validate signals via risk manager
4. Execute trades
5. Monitor positions
6. Repeat
"""

import sys
import time
import signal as sig
import traceback
from loguru import logger

from config import Config, config
from client import PolymarketClient
from strategy import MarketAnalyzer, Signal, get_strategy
from risk_manager import RiskManager
from notifier import Notifier


class PolymarketBot:
    """
    Main trading bot that orchestrates all components.
    """

    def __init__(self, cfg: Config = None):
        self.config = cfg or config
        self.running = False

        # Setup logging
        self._setup_logging()

        # Validate config
        errors = self.config.validate()
        if errors and not self.config.bot.paper_trading:
            for err in errors:
                logger.error(f"Config error: {err}")
            raise ValueError(f"Configuration errors: {errors}")

        # Initialize components
        logger.info("=" * 60)
        logger.info("  POLYMARKET AUTOMATIC TRADING BOT")
        logger.info("=" * 60)
        logger.info(f"Strategy: {self.config.strategy.strategy}")
        logger.info(f"Paper Trading: {self.config.bot.paper_trading}")
        logger.info(f"Max Exposure: ${self.config.risk.max_total_exposure}")
        logger.info(f"Order Size: ${self.config.strategy.order_size}")
        logger.info(f"Loop Interval: {self.config.bot.loop_interval}s")
        logger.info("=" * 60)

        # Initialize client (skip if paper trading without valid key)
        if self.config.bot.paper_trading and not self.config.wallet.private_key:
            logger.warning("Paper trading mode without valid key - using mock client")
            self.client = None
        else:
            self.client = PolymarketClient(self.config)

        self.risk_manager = RiskManager(self.config)
        self.notifier = Notifier(self.config)

        if self.client:
            self.analyzer = MarketAnalyzer(self.client, self.config)
            self.strategy = get_strategy(
                self.config.strategy.strategy, self.analyzer, self.config
            )
        else:
            self.analyzer = None
            self.strategy = None

        # Register signal handlers for graceful shutdown
        sig.signal(sig.SIGINT, self._handle_shutdown)
        sig.signal(sig.SIGTERM, self._handle_shutdown)

    def _setup_logging(self):
        """Configure loguru logging."""
        logger.remove()
        logger.add(
            sys.stdout,
            level=self.config.bot.log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level:<8}</level> | "
                "<cyan>{module}</cyan>:<cyan>{function}</cyan> | "
                "<level>{message}</level>"
            ),
        )
        logger.add(
            "logs/bot_{time:YYYY-MM-DD}.log",
            rotation="1 day",
            retention="30 days",
            level="DEBUG",
        )

    def _handle_shutdown(self, signum, frame):
        """Handle graceful shutdown."""
        logger.warning("Shutdown signal received. Stopping bot...")
        self.running = False

    # =========================================================================
    # MAIN TRADING LOOP
    # =========================================================================

    def run(self):
        """Main entry point - start the trading bot."""
        self.running = True
        self.notifier.notify_startup()
        logger.info("Bot started. Entering main trading loop...")

        while self.running:
            try:
                self._trading_cycle()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}")
                logger.debug(traceback.format_exc())
                self.notifier.notify_error(str(e))

            # Wait for next cycle
            logger.debug(f"Sleeping {self.config.bot.loop_interval}s until next cycle...")
            time.sleep(self.config.bot.loop_interval)

        self._shutdown()

    def _trading_cycle(self):
        """Execute one full trading cycle."""
        logger.info("─" * 40)
        logger.info("Starting trading cycle...")

        # Step 0: Daily reset check
        self.risk_manager.check_daily_reset()

        # Step 1: Monitor existing positions
        self._monitor_positions()

        # Step 2: Discover markets
        markets = self._discover_markets()
        if not markets:
            logger.info("No suitable markets found this cycle")
            return

        # Step 3: Generate signals
        signals = self._generate_signals(markets)
        if not signals:
            logger.info("No signals generated this cycle")
            return

        # Step 4: Execute signals
        for signal in signals:
            if not self.running:
                break
            self._execute_signal(signal)

        # Log portfolio summary
        summary = self.risk_manager.get_portfolio_summary()
        logger.info(
            f"Cycle complete | Positions: {summary['open_positions']} | "
            f"Exposure: ${summary['total_exposure']:.2f} ({summary['exposure_pct']:.0f}%) | "
            f"PnL today: ${summary['realized_pnl_today']:.2f}"
        )

    # =========================================================================
    # DISCOVERY
    # =========================================================================

    def _discover_markets(self) -> list[dict]:
        """Discover and filter tradeable markets."""
        if not self.client:
            logger.debug("No client available (paper mode without key)")
            return []

        raw_markets = self.client.get_active_markets(limit=50)
        if not raw_markets:
            return []

        # Filter markets
        filtered = []
        for market in raw_markets:
            # Must have orderbook enabled
            if not market.get("enableOrderBook"):
                continue

            # Must not be closed
            if market.get("closed"):
                continue

            # Must have token IDs
            clob_ids = market.get("clobTokenIds", "[]")
            if isinstance(clob_ids, str):
                import json
                try:
                    clob_ids = json.loads(clob_ids)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not clob_ids:
                continue

            # Score the market
            score = self.analyzer.score_market(market)
            if score >= 0.4:
                market["_score"] = score
                filtered.append(market)

        # Sort by score
        filtered.sort(key=lambda m: m.get("_score", 0), reverse=True)

        logger.info(f"Markets: {len(raw_markets)} total, {len(filtered)} passed filters")
        return filtered[:20]  # Top 20 candidates

    # =========================================================================
    # SIGNAL GENERATION
    # =========================================================================

    def _generate_signals(self, markets: list[dict]) -> list[Signal]:
        """Generate trading signals using the active strategy."""
        if not self.strategy:
            return []

        signals = self.strategy.generate_signals(markets)
        logger.info(f"Signals generated: {len(signals)}")

        for s in signals:
            logger.debug(f"  {s}")

        return signals

    # =========================================================================
    # EXECUTION
    # =========================================================================

    def _execute_signal(self, signal: Signal):
        """Validate and execute a trading signal."""
        # Risk check
        approved, reason = self.risk_manager.validate_signal(signal)
        if not approved:
            logger.info(f"Signal rejected: {reason}")
            return

        # Calculate optimal size
        optimal_size = self.risk_manager.calculate_position_size(signal)
        signal.size = optimal_size

        logger.info(
            f"Executing: {signal.side} {signal.size:.1f}@{signal.price:.3f} "
            f"conf={signal.confidence:.2f} | {signal.reason}"
        )

        # Paper trading mode
        if self.config.bot.paper_trading:
            logger.info(f"[PAPER] Order would be placed: {signal}")
            self.risk_manager.open_position(signal, signal.price)
            self.notifier.notify_trade(signal.side, signal.size, signal.price, signal.question)
            return

        # Live execution
        if not self.client:
            logger.error("Cannot execute: no client")
            return

        response = self.client.place_limit_order(
            token_id=signal.token_id,
            side=signal.side,
            price=signal.price,
            size=signal.size,
            tick_size=signal.tick_size,
            neg_risk=signal.neg_risk,
        )

        if response and response.get("success"):
            self.risk_manager.open_position(signal, signal.price)
            self.notifier.notify_trade(signal.side, signal.size, signal.price, signal.question)
        else:
            error_msg = response.get("errorMsg", "Unknown error") if response else "No response"
            logger.warning(f"Order failed: {error_msg}")

    # =========================================================================
    # POSITION MONITORING
    # =========================================================================

    def _monitor_positions(self):
        """Monitor open positions for stop loss / take profit."""
        if not self.risk_manager.positions:
            return

        if not self.client:
            return

        positions_to_close = []

        for token_id, position in self.risk_manager.positions.items():
            current_price = self.client.get_midpoint(token_id)
            if current_price is None:
                continue

            # Check stop loss
            if self.risk_manager.check_stop_loss(token_id, current_price):
                positions_to_close.append((token_id, current_price, "stop_loss"))
                continue

            # Check take profit
            if self.risk_manager.check_take_profit(token_id, current_price):
                positions_to_close.append((token_id, current_price, "take_profit"))
                continue

        # Close positions that triggered exits
        for token_id, price, reason in positions_to_close:
            self._close_position(token_id, price, reason)

    def _close_position(self, token_id: str, price: float, reason: str):
        """Close a position."""
        position = self.risk_manager.positions.get(token_id)
        if not position:
            return

        # Determine sell side
        sell_side = "SELL" if position.side == "BUY" else "BUY"

        logger.info(f"Closing position ({reason}): {sell_side} {position.size}@{price:.3f}")

        if not self.config.bot.paper_trading and self.client:
            self.client.place_market_order(
                token_id=token_id,
                side=sell_side,
                amount=position.size if sell_side == "SELL" else position.size * price,
                price=price,
            )

        self.risk_manager.close_position(token_id, price)

        if reason == "stop_loss":
            self.notifier.notify_stop_loss(token_id, self.config.risk.stop_loss)
        elif reason == "take_profit":
            self.notifier.notify_take_profit(token_id, self.config.risk.take_profit)

    # =========================================================================
    # SHUTDOWN
    # =========================================================================

    def _shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down bot...")

        # Cancel all open orders on live trading
        if not self.config.bot.paper_trading and self.client:
            logger.info("Cancelling all open orders...")
            self.client.cancel_all_orders()

        # Final summary
        summary = self.risk_manager.get_portfolio_summary()
        logger.info(f"Final summary: {summary}")
        self.notifier.notify_daily_summary(summary)

        logger.info("Bot stopped. Goodbye!")


def main():
    """Entry point for the bot."""
    try:
        bot = PolymarketBot()
        bot.run()
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
