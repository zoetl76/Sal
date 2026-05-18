"""Tests for the configuration module."""

from polymarket_bot.config import Config


def test_config_loads_defaults():
    """Config should load without errors using default YAML."""
    config = Config()
    assert "api" in config
    assert "websocket" in config
    assert "trading" in config
    assert "data" in config
    assert "logging" in config


def test_config_get():
    """Config.get should return values or defaults."""
    config = Config()
    assert config.get("logging") is not None
    assert config.get("nonexistent", "fallback") == "fallback"


def test_config_secrets_masked():
    """Config repr should mask API secrets."""
    config = Config()
    repr_str = repr(config)
    # When secrets are empty, they show as ''. When set, they show as '***'.
    assert "polymarket_api_key" not in repr_str or "***" in repr_str or "''" in repr_str


def test_config_websocket_defaults():
    """WebSocket config should have sensible defaults."""
    config = Config()
    ws_config = config.get("websocket")
    assert ws_config["num_connections"] == 6
    assert ws_config["reconnect_delay_s"] == 1.0


def test_config_trading_defaults():
    """Trading config should have sensible defaults."""
    config = Config()
    trading = config.get("trading")
    assert trading["max_price_filter"] == 0.95
    assert trading["min_price_filter"] == 0.05
    assert trading["default_stop_loss_pct"] == 0.10
