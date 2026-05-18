"""Tests for the logging setup module."""

import logging

from polymarket_bot.logging_setup import get_logger, setup_logging


def test_setup_logging_json():
    """setup_logging with JSON format should not raise."""
    setup_logging(level="INFO", log_format="json")


def test_setup_logging_console():
    """setup_logging with console format should not raise."""
    setup_logging(level="DEBUG", log_format="console")


def test_get_logger():
    """get_logger should return a bound logger."""
    setup_logging(level="INFO", log_format="json")
    logger = get_logger(__name__)
    assert logger is not None


def test_get_logger_with_context():
    """get_logger should accept initial context fields."""
    setup_logging(level="INFO", log_format="json")
    logger = get_logger(__name__, trade_id="test-123", token_id="token-abc")
    assert logger is not None
