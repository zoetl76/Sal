"""
Configuration module for the Polymarket Trading Bot.
Loads settings from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class WalletConfig:
    """Wallet and authentication configuration."""
    private_key: str = field(default_factory=lambda: os.getenv("PRIVATE_KEY", ""))
    deposit_wallet_address: str = field(default_factory=lambda: os.getenv("DEPOSIT_WALLET_ADDRESS", ""))
    signature_type: int = field(default_factory=lambda: int(os.getenv("SIGNATURE_TYPE", "3")))
    api_key: str = field(default_factory=lambda: os.getenv("CLOB_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("CLOB_API_SECRET", ""))
    api_passphrase: str = field(default_factory=lambda: os.getenv("CLOB_API_PASSPHRASE", ""))


@dataclass
class APIConfig:
    """API endpoints configuration."""
    clob_url: str = field(default_factory=lambda: os.getenv("CLOB_API_URL", "https://clob.polymarket.com"))
    gamma_url: str = field(default_factory=lambda: os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com"))
    data_url: str = field(default_factory=lambda: os.getenv("DATA_API_URL", "https://data-api.polymarket.com"))
    chain_id: int = field(default_factory=lambda: int(os.getenv("CHAIN_ID", "137")))


@dataclass
class StrategyConfig:
    """Trading strategy configuration."""
    strategy: str = field(default_factory=lambda: os.getenv("STRATEGY", "value"))
    max_active_markets: int = field(default_factory=lambda: int(os.getenv("MAX_ACTIVE_MARKETS", "5")))
    min_liquidity: float = field(default_factory=lambda: float(os.getenv("MIN_LIQUIDITY", "1000")))
    min_edge: float = field(default_factory=lambda: float(os.getenv("MIN_EDGE", "0.05")))
    order_size: float = field(default_factory=lambda: float(os.getenv("ORDER_SIZE", "10")))
    max_position_size: float = field(default_factory=lambda: float(os.getenv("MAX_POSITION_SIZE", "100")))


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_total_exposure: float = field(default_factory=lambda: float(os.getenv("MAX_TOTAL_EXPOSURE", "500")))
    stop_loss: float = field(default_factory=lambda: float(os.getenv("STOP_LOSS", "0.15")))
    take_profit: float = field(default_factory=lambda: float(os.getenv("TAKE_PROFIT", "0.30")))
    max_open_orders: int = field(default_factory=lambda: int(os.getenv("MAX_OPEN_ORDERS", "20")))
    daily_loss_limit: float = field(default_factory=lambda: float(os.getenv("DAILY_LOSS_LIMIT", "50")))


@dataclass
class BotConfig:
    """General bot settings."""
    loop_interval: int = field(default_factory=lambda: int(os.getenv("LOOP_INTERVAL", "60")))
    paper_trading: bool = field(default_factory=lambda: os.getenv("PAPER_TRADING", "true").lower() == "true")
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    telegram_enabled: bool = field(default_factory=lambda: os.getenv("TELEGRAM_ENABLED", "false").lower() == "true")
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))


@dataclass
class Config:
    """Main configuration container."""
    wallet: WalletConfig = field(default_factory=WalletConfig)
    api: APIConfig = field(default_factory=APIConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    bot: BotConfig = field(default_factory=BotConfig)

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        if not self.wallet.private_key:
            errors.append("PRIVATE_KEY is required")
        if not self.wallet.deposit_wallet_address:
            errors.append("DEPOSIT_WALLET_ADDRESS is required")
        if self.strategy.order_size <= 0:
            errors.append("ORDER_SIZE must be positive")
        if self.risk.stop_loss <= 0 or self.risk.stop_loss >= 1:
            errors.append("STOP_LOSS must be between 0 and 1")
        if self.risk.take_profit <= 0 or self.risk.take_profit >= 1:
            errors.append("TAKE_PROFIT must be between 0 and 1")
        return errors


# Global config instance
config = Config()
