"""Main entry point for the Polymarket trading bot.

Supports multiple operation modes:
- live: Real trading with live market connections
- dry-run: Simulated trading with live data
- backtest: Historical data replay and strategy evaluation
- record-only: Record market data without trading
"""

import argparse
import asyncio
import sys
from typing import Optional

from polymarket_bot.config import Config
from polymarket_bot.logging_setup import get_logger, setup_logging


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        prog="polymarket-bot",
        description="Polymarket async trading bot - automated market making and signal trading",
    )

    parser.add_argument(
        "mode",
        choices=["live", "dry-run", "backtest", "record-only"],
        help="Operation mode: live (real trading), dry-run (simulated), backtest (historical), record-only (data collection)",
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML configuration file (default: config/default.yaml)",
    )

    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Path to .env file (default: .env in project root)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Override logging level from config",
    )

    parser.add_argument(
        "--log-format",
        choices=["json", "console"],
        default=None,
        help="Log output format (default: json)",
    )

    parser.add_argument(
        "--market-id",
        type=str,
        default=None,
        help="Specific market/condition ID to trade (optional)",
    )

    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    """Run the bot in the specified mode.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    # Load configuration
    config = Config(config_path=args.config, env_file=args.env_file)

    # Setup logging
    log_level = args.log_level or config.get("logging", {}).get("level", "INFO")
    log_format = args.log_format or config.get("logging", {}).get("format", "json")
    log_file = config.get("logging", {}).get("file_path", "") or None

    setup_logging(level=log_level, log_format=log_format, log_file=log_file)
    logger = get_logger(__name__)

    logger.info("starting_bot", mode=args.mode, config=str(config))

    if args.mode == "live":
        logger.info("live_mode", msg="Live trading mode - not yet implemented")
    elif args.mode == "dry-run":
        logger.info("dry_run_mode", msg="Dry-run mode - not yet implemented")
    elif args.mode == "backtest":
        logger.info("backtest_mode", msg="Backtest mode - not yet implemented")
    elif args.mode == "record-only":
        logger.info("record_only_mode", msg="Record-only mode - not yet implemented")

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].

    Returns:
        Exit code.
    """
    args = parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
