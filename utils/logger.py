#!/usr/bin/env python3
"""Logger utility for consistent console and file logging."""

import logging
import sys
import os
from datetime import datetime


def setup_logger(name, level=logging.INFO, log_dir=None):
    """Create a logger that writes to both console and file.

    Args:
        name: logger name
        level: logging level
        log_dir: directory for log files (default: project_root/data/)

    Returns:
        logging.Logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if log_dir is None:
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data"
        )

    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{name}_{timestamp}.log")
    fh = logging.FileHandler(log_path)
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.info("Log file: %s", log_path)
    return logger


def get_logger(name="sdn_exp"):
    """Get or create a simple console logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger
