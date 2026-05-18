"""Main entry point for the Polymarket trading bot.

Supports multiple operation modes:
- live: Real trading with live market connections
- dry-run: Simulated trading with live data
- backtest: Historical data replay and strategy evaluation
- record-only: Record market data without trading
"""

import argparse
import asyncio
import signal
import sys
from typing import Optional

from polymarket_bot.config import Config
from polymarket_bot.deploy.runner import BotRunner, RunMode
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


_MODE_MAP = {
    "live": RunMode.LIVE,
    "dry-run": RunMode.DRY_RUN,
    "backtest": RunMode.BACKTEST,
    "record-only": RunMode.RECORD_ONLY,
}


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

    run_mode = _MODE_MAP[args.mode]
    logger.info("starting_bot", mode=args.mode, config=str(config))

    # Create and start the BotRunner
    runner = BotRunner(config=config, mode=run_mode)
    await runner.start()

    # For backtest mode, just start and return (no live loop)
    if run_mode == RunMode.BACKTEST:
        logger.info("backtest_mode", msg="Backtest mode started - run backtest via engine API")
        await runner.stop()
        return 0

    # For live/dry-run/record-only, run until interrupted
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows does not support add_signal_handler
            pass

    logger.info("bot_running", mode=args.mode, msg="Bot is running. Press Ctrl+C to stop.")
    await stop_event.wait()

    await runner.stop()
    logger.info("bot_stopped", mode=args.mode)
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
