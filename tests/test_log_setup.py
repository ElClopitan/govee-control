"""Tests for log_setup module."""

import logging
import sys
import tempfile
import unittest
from pathlib import Path


class TestSetupLogging(unittest.TestCase):
    """Test setup_logging function."""

    def setUp(self):
        """Save original logging state."""
        self.original_root_handlers = logging.root.handlers[:]
        self.original_root_level = logging.root.level
        self.original_excepthook = sys.excepthook

    def tearDown(self):
        """Restore original logging state."""
        # Close and remove all handlers
        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)
        # Restore original handlers
        logging.root.handlers = self.original_root_handlers
        logging.root.setLevel(self.original_root_level)
        sys.excepthook = self.original_excepthook

    def test_log_file_root_logger(self):
        """After setup_logging with log_file, other module loggers write to file."""
        import log_setup

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            log_setup.setup_logging(str(log_path), logging.INFO)

            # Log from a different module's logger
            other_logger = logging.getLogger("other_module")
            other_logger.warning("hello")

            # Flush and check file
            for handler in logging.root.handlers[:]:
                if hasattr(handler, "flush"):
                    handler.flush()

            content = log_path.read_text(encoding="utf-8")
            self.assertIn("hello", content)
            self.assertIn("WARNING", content)

    def test_excepthook_logs_to_file(self):
        """Uncaught exceptions are logged to the file."""
        import log_setup
        import traceback

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            log_setup.setup_logging(str(log_path), logging.INFO)

            # Create a traceback from a caught exception
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                tb = sys.exc_info()[2]

            # Call the excepthook
            sys.excepthook(RuntimeError, RuntimeError("boom"), tb)

            # Flush and check file
            for handler in logging.root.handlers[:]:
                if hasattr(handler, "flush"):
                    handler.flush()

            content = log_path.read_text(encoding="utf-8")
            self.assertIn("boom", content)
            self.assertIn("Traceback", content)
            self.assertIn("uncaught exception", content)

    def test_no_log_file_uses_basicconfig(self):
        """Without log_file, basicConfig is used."""
        import log_setup

        log_setup.setup_logging(None, logging.INFO)

        # Should have a StreamHandler
        has_stream = any(
            isinstance(h, logging.StreamHandler) for h in logging.root.handlers
        )
        self.assertTrue(has_stream)

    def test_utf8_encoding(self):
        """Log file uses UTF-8 encoding (for °C etc.)."""
        import log_setup

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            log_setup.setup_logging(str(log_path), logging.INFO)

            logger = logging.getLogger("test_utf8")
            logger.info("Temperature: 20°C")

            for handler in logging.root.handlers[:]:
                if hasattr(handler, "flush"):
                    handler.flush()

            content = log_path.read_text(encoding="utf-8")
            self.assertIn("20°C", content)


if __name__ == "__main__":
    unittest.main()
