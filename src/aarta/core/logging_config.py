"""Logging configuration for AARTA."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Final


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s UTC [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        formatter.converter = lambda *args: logging.gmtime()  # type: ignore[attr-defined]
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# Default application logger
DEFAULT_LOGGER: Final[logging.Logger] = get_logger("aarta")


def setup_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    """Set up global logging configuration.

    Args:
        level: Logging level (default: INFO).
        log_file: Optional path to log file for file-based logging.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter(
        "%(asctime)s UTC [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter.converter = lambda *args: logging.gmtime()  # type: ignore[attr-defined]
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Optional file handler
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(console_formatter)
        root_logger.addHandler(file_handler)
