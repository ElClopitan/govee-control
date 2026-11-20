"""Tests for the socket guard in tests/helpers.py."""

import socket
import unittest


class TestSocketGuard(unittest.TestCase):
    """Verify the socket guard raises for non-loopback addresses."""

    def test_sendto_non_loopback_raises(self):
        """sendto to a non-loopback address should raise AssertionError."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with self.assertRaises(AssertionError) as ctx:
                s.sendto(b"x", ("192.168.1.50", 4003))
            self.assertIn("real network in a test", str(ctx.exception))
        finally:
            s.close()

    def test_connect_non_loopback_raises(self):
        """connect to a non-loopback address should raise AssertionError."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(AssertionError) as ctx:
                s.connect(("192.168.1.50", 4003))
            self.assertIn("real network in a test", str(ctx.exception))
        finally:
            s.close()

    def test_sendto_loopback_allowed(self):
        """sendto to loopback should be allowed (no exception)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # This should not raise AssertionError
            s.sendto(b"x", ("127.0.0.1", 4003))
        except AssertionError:
            self.fail("loopback sendto should be allowed")
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
