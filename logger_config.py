#!/usr/bin/env python3
"""
Logging configuration for exchange documentation monitors.

Provides centralized logging setup with per-exchange log files and rotation.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


# Directory for log files
LOG_DIR = "logs"

# Maximum log file size (10MB)
MAX_LOG_SIZE = 10 * 1024 * 1024

# Number of backup files to keep
BACKUP_COUNT = 5

# Log format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    exchange_name: str, level: int = logging.INFO
) -> logging.Logger:
    """
    Set up a logger for a specific exchange with file rotation.

    Args:
        exchange_name: Name of the exchange (e.g., "binance", "okx")
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    # Create logs directory if it doesn't exist (exist_ok so monitors started
    # at the same moment don't fail when another creates it first)
    os.makedirs(LOG_DIR, exist_ok=True)

    # Create logger
    logger_name = f"monitor.{exchange_name.lower()}"
    logger = logging.getLogger(logger_name)

    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(level)

        # Create file handler with rotation
        log_file = os.path.join(LOG_DIR, f"{exchange_name.lower()}.log")
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)

        # Create formatter
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers to logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def get_logger(exchange_name: str) -> logging.Logger:
    """
    Get or create a logger for a specific exchange.

    Args:
        exchange_name: Name of the exchange

    Returns:
        Logger instance
    """
    logger_name = f"monitor.{exchange_name.lower()}"
    logger = logging.getLogger(logger_name)

    # Set up if not already configured
    if not logger.handlers:
        return setup_logger(exchange_name)

    return logger
