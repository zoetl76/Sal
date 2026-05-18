"""
Notification Module
===================
Sends alerts via Telegram for important bot events.
"""

import asyncio
from typing import Optional
from loguru import logger

from config import Config


class Notifier:
    """Sends notifications to Telegram."""

    def __init__(self, config: Config):
        self.config = config
        self.enabled = config.bot.telegram_enabled
        self.bot = None

        if self.enabled:
            try:
                from telegram import Bot
                self.bot = Bot(token=config.bot.telegram_bot_token)
                logger.info("Telegram notifications enabled")
            except Exception as e:
                logger.warning(f"Telegram init failed: {e}. Notifications disabled.")
                self.enabled = False

    def send(self, message: str, parse_mode: str = "HTML"):
        """Send a message synchronously."""
        if not self.enabled:
            return

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._async_send(message, parse_mode))
            else:
                loop.run_until_complete(self._async_send(message, parse_mode))
        except RuntimeError:
            # Create a new loop if none exists
            asyncio.run(self._async_send(message, parse_mode))

    async def _async_send(self, message: str, parse_mode: str):
        """Async message sender."""
        try:
            await self.bot.send_message(
                chat_id=self.config.bot.telegram_chat_id,
                text=message,
                parse_mode=parse_mode,
            )
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")

    def notify_trade(self, side: str, size: float, price: float, market: str):
        """Notify about a trade execution."""
        msg = (
            f"🔔 <b>Trade Executed</b>\n"
            f"{'🟢' if side == 'BUY' else '🔴'} {side} {size:.1f}@{price:.3f}\n"
            f"📈 {market[:60]}"
        )
        self.send(msg)

    def notify_stop_loss(self, token_id: str, loss_pct: float):
        """Notify about a stop loss trigger."""
        msg = f"⚠️ <b>Stop Loss Triggered</b>\n🔻 Loss: {loss_pct*100:.1f}%\nToken: {token_id[:32]}..."
        self.send(msg)

    def notify_take_profit(self, token_id: str, profit_pct: float):
        """Notify about a take profit trigger."""
        msg = f"✅ <b>Take Profit</b>\n📈 Profit: {profit_pct*100:.1f}%\nToken: {token_id[:32]}..."
        self.send(msg)

    def notify_daily_summary(self, summary: dict):
        """Send daily portfolio summary."""
        msg = (
            f"📊 <b>Daily Summary</b>\n"
            f"Positions: {summary.get('open_positions', 0)}\n"
            f"Exposure: ${summary.get('total_exposure', 0):.2f}/{summary.get('max_exposure', 0):.2f}\n"
            f"Unrealized PnL: ${summary.get('unrealized_pnl', 0):.2f}\n"
            f"Realized PnL: ${summary.get('realized_pnl_today', 0):.2f}\n"
            f"Trades: {summary.get('trades_today', 0)}"
        )
        self.send(msg)

    def notify_error(self, error: str):
        """Notify about a critical error."""
        msg = f"🚨 <b>Bot Error</b>\n{error[:200]}"
        self.send(msg)

    def notify_startup(self):
        """Notify that the bot has started."""
        msg = (
            f"🤖 <b>Polymarket Bot Started</b>\n"
            f"Strategy: {self.config.strategy.strategy}\n"
            f"Paper: {'Yes' if self.config.bot.paper_trading else 'No'}\n"
            f"Max Exposure: ${self.config.risk.max_total_exposure:.0f}"
        )
        self.send(msg)
