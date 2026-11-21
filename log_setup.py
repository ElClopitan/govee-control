"""Logging setup for Govee sync scripts.

Provides setup_logging() which configures root-level logging with optional
file output and uncaught exception handling.
"""

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler


def setup_logging(log_file=None, level=logging.INFO):
    """Configure logging for a sync script.

    Args:
        log_file: If set, attach a RotatingFileHandler to the root logger
            with UTF-8 encoding. If None, use basicConfig for console output.
        level: Log level (default INFO).

    When log_file is set, also installs a sys.excepthook that logs uncaught
    exceptions to the file (useful under pythonw where stderr is None).
    """
    root = logging.getLogger()
    root.setLevel(level)

    if log_file:
        handler = RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        root.addHandler(handler)

        # Install excepthook to log uncaught exceptions to the file
        _install_excepthook()
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(message)s",
        )


def _install_excepthook():
    """Install a sys.excepthook that logs uncaught exceptions."""
    original_hook = sys.excepthook

    def logging_hook(exc_type, exc_value, exc_tb):
        if exc_type is KeyboardInterrupt:
            # Let KeyboardInterrupt go to the default hook
            original_hook(exc_type, exc_value, exc_tb)
            return

        logger = logging.getLogger("uncaught")
        logger.critical("uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

        # Also show traceback on console if stderr is available
        if sys.stderr is not None:
            original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = logging_hook
