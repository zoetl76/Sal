"""Tests for the main entry point."""

from polymarket_bot.main import main, parse_args


def test_parse_args_live():
    """Should parse live mode."""
    args = parse_args(["live"])
    assert args.mode == "live"


def test_parse_args_dry_run():
    """Should parse dry-run mode."""
    args = parse_args(["dry-run"])
    assert args.mode == "dry-run"


def test_parse_args_backtest():
    """Should parse backtest mode."""
    args = parse_args(["backtest"])
    assert args.mode == "backtest"


def test_parse_args_record_only():
    """Should parse record-only mode."""
    args = parse_args(["record-only"])
    assert args.mode == "record-only"


def test_parse_args_with_options():
    """Should parse options correctly."""
    args = parse_args(["live", "--log-level", "DEBUG", "--log-format", "console"])
    assert args.mode == "live"
    assert args.log_level == "DEBUG"
    assert args.log_format == "console"


def test_main_backtest_mode():
    """main() should run without error in backtest mode."""
    exit_code = main(["backtest"])
    assert exit_code == 0
