"""Configuration management for the Polymarket trading bot.

Loads configuration from multiple sources with the following priority (highest first):
1. Environment variables
2. .env file
3. YAML config files
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv


# Default project root (two levels up from this file)
PROJECT_ROOT = Path(__file__).parent.parent


class Config:
    """Central configuration class that merges env vars, .env, and YAML configs."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        env_file: Optional[str] = None,
    ) -> None:
        """Initialize configuration.

        Args:
            config_path: Path to a YAML config file. Defaults to config/default.yaml.
            env_file: Path to a .env file. Defaults to .env in project root.
        """
        # Load .env file
        env_path = Path(env_file) if env_file else PROJECT_ROOT / ".env"
        load_dotenv(dotenv_path=env_path, override=False)

        # Load YAML config
        yaml_path = Path(config_path) if config_path else PROJECT_ROOT / "config" / "default.yaml"
        self._yaml_config = self._load_yaml(yaml_path)

        # Build final config
        self._config = self._build_config()

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """Load a YAML configuration file."""
        if path.exists():
            with open(path, "r") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _build_config(self) -> dict[str, Any]:
        """Build merged configuration from YAML defaults and environment overrides."""
        config: dict[str, Any] = {}

        # Start with YAML defaults
        config.update(self._yaml_config)

        # Override with environment variables where applicable
        config["api"] = self._build_api_config()
        config["websocket"] = self._build_websocket_config()
        config["trading"] = self._build_trading_config()
        config["data"] = self._build_data_config()
        config["logging"] = self._build_logging_config()

        return config

    def _build_api_config(self) -> dict[str, Any]:
        """Build API configuration with env var overrides."""
        yaml_api = self._yaml_config.get("api", {})
        return {
            "polymarket_api_key": os.getenv("POLYMARKET_API_KEY", yaml_api.get("polymarket_api_key", "")),
            "polymarket_secret": os.getenv("POLYMARKET_SECRET", yaml_api.get("polymarket_secret", "")),
            "polymarket_passphrase": os.getenv("POLYMARKET_PASSPHRASE", yaml_api.get("polymarket_passphrase", "")),
            "binance_api_key": os.getenv("BINANCE_API_KEY", yaml_api.get("binance_api_key", "")),
            "binance_secret": os.getenv("BINANCE_SECRET", yaml_api.get("binance_secret", "")),
            "coinbase_api_key": os.getenv("COINBASE_API_KEY", yaml_api.get("coinbase_api_key", "")),
            "coinbase_secret": os.getenv("COINBASE_SECRET", yaml_api.get("coinbase_secret", "")),
        }

    def _build_websocket_config(self) -> dict[str, Any]:
        """Build WebSocket configuration with env var overrides."""
        yaml_ws = self._yaml_config.get("websocket", {})
        return {
            "num_connections": int(os.getenv("WS_NUM_CONNECTIONS", yaml_ws.get("num_connections", 6))),
            "respawn_rate_ms": int(os.getenv("WS_RESPAWN_RATE_MS", yaml_ws.get("respawn_rate_ms", 500))),
            "jitter_threshold_ms": int(os.getenv("WS_JITTER_THRESHOLD_MS", yaml_ws.get("jitter_threshold_ms", 50))),
            "reconnect_delay_s": float(os.getenv("WS_RECONNECT_DELAY_S", yaml_ws.get("reconnect_delay_s", 1.0))),
            "max_reconnect_delay_s": float(os.getenv("WS_MAX_RECONNECT_DELAY_S", yaml_ws.get("max_reconnect_delay_s", 60.0))),
            "ping_interval_s": float(os.getenv("WS_PING_INTERVAL_S", yaml_ws.get("ping_interval_s", 30.0))),
        }

    def _build_trading_config(self) -> dict[str, Any]:
        """Build trading configuration with env var overrides."""
        yaml_trading = self._yaml_config.get("trading", {})
        return {
            "max_price_filter": float(os.getenv("TRADING_MAX_PRICE", yaml_trading.get("max_price_filter", 0.95))),
            "min_price_filter": float(os.getenv("TRADING_MIN_PRICE", yaml_trading.get("min_price_filter", 0.05))),
            "default_stop_loss_pct": float(os.getenv("TRADING_STOP_LOSS_PCT", yaml_trading.get("default_stop_loss_pct", 0.10))),
            "max_position_size": float(os.getenv("TRADING_MAX_POSITION", yaml_trading.get("max_position_size", 100.0))),
            "max_open_positions": int(os.getenv("TRADING_MAX_OPEN_POSITIONS", yaml_trading.get("max_open_positions", 10))),
        }

    def _build_data_config(self) -> dict[str, Any]:
        """Build data storage configuration with env var overrides."""
        yaml_data = self._yaml_config.get("data", {})
        return {
            "storage_path": os.getenv("DATA_STORAGE_PATH", yaml_data.get("storage_path", "data/")),
            "db_path": os.getenv("DATA_DB_PATH", yaml_data.get("db_path", "data/market_data.db")),
            "record_raw_messages": bool(
                os.getenv("DATA_RECORD_RAW", yaml_data.get("record_raw_messages", True))
            ),
        }

    def _build_logging_config(self) -> dict[str, Any]:
        """Build logging configuration with env var overrides."""
        yaml_logging = self._yaml_config.get("logging", {})
        return {
            "level": os.getenv("LOG_LEVEL", yaml_logging.get("level", "INFO")),
            "format": os.getenv("LOG_FORMAT", yaml_logging.get("format", "json")),
            "file_path": os.getenv("LOG_FILE_PATH", yaml_logging.get("file_path", "")),
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a top-level config value."""
        return self._config.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Get a config value by key."""
        return self._config[key]

    def __contains__(self, key: str) -> bool:
        """Check if a key exists in configuration."""
        return key in self._config

    def __repr__(self) -> str:
        """Return a string representation of the config (secrets masked)."""
        safe_config = {}
        for key, value in self._config.items():
            if key == "api":
                safe_config[key] = {
                    k: "***" if v else "" for k, v in value.items()
                }
            else:
                safe_config[key] = value
        return f"Config({safe_config})"

    def __str__(self) -> str:
        """Return a human-readable string of the config."""
        return self.__repr__()
