"""Structured logging configuration for the Polymarket trading bot.

Supports both JSON and human-readable output formats.
Includes context fields: timestamp, module, level, trade_id, token_id.
"""

import logging
import sys
from typing import Optional

import structlog


def setup_logging(
    level: str = "INFO",
    log_format: str = "json",
    log_file: Optional[str] = None,
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: Output format - 'json' for machine-readable, 'console' for human-readable.
        log_file: Optional file path for log output. If None, logs go to stdout.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure shared processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str, **initial_context: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger with optional initial context.

    Args:
        name: Logger name (typically __name__).
        **initial_context: Initial context fields to bind (e.g., trade_id, token_id).

    Returns:
        A bound structured logger.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    if initial_context:
        logger = logger.bind(**initial_context)
    return logger
