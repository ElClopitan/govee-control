"""Tests for screen_color.py."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import helpers  # noqa: F401

sys.path.insert(0, str(Path(__file__).parent.parent))
import screen_color


class TestDominantColor(unittest.TestCase):
    """Test the dominant_color function."""

    def test_all_red(self):
        """All-red image should return red-ish."""
        pixels = [(255, 0, 0)] * 100
        r, g, b = screen_color.dominant_color(pixels, 10, 10)
        self.assertGreater(r, 200)
        self.assertLess(g, 50)
        self.assertLess(b, 50)

    def test_mostly_black_with_blue_area(self):
        """Mostly black with a 10% blue area should return blue."""
        pixels = []
        # 90% black
        for _ in range(90):
            pixels.append((10, 10, 10))
        # 10% blue
        for _ in range(10):
            pixels.append((0, 0, 255))
        r, g, b = screen_color.dominant_color(pixels, 10, 10)
        self.assertGreater(b, 200)
        self.assertLess(r, 50)
        self.assertLess(g, 50)

    def test_grey_only(self):
        """Grey-only image should return grey mean."""
        pixels = [(128, 128, 128)] * 100
        r, g, b = screen_color.dominant_color(pixels, 10, 10)
        self.assertAlmostEqual(r, 128, delta=5)
        self.assertAlmostEqual(g, 128, delta=5)
        self.assertAlmostEqual(b, 128, delta=5)

    def test_empty_list(self):
        """Empty list should return (0, 0, 0) without raising."""
        r, g, b = screen_color.dominant_color([], 0, 0)
        self.assertEqual((r, g, b), (0, 0, 0))

    def test_near_black_filtered(self):
        """Near-black pixels should be filtered out."""
        pixels = []
        # Near-black (should be filtered)
        for _ in range(90):
            pixels.append((20, 20, 20))
        # Bright green (should dominate)
        for _ in range(10):
            pixels.append((0, 255, 0))
        r, g, b = screen_color.dominant_color(pixels, 10, 10)
        self.assertGreater(g, 200)
        self.assertLess(r, 50)
        self.assertLess(b, 50)

    def test_near_grey_filtered(self):
        """Near-grey (low saturation) pixels should be filtered."""
        pixels = []
        # Near-grey (should be filtered)
        for _ in range(90):
            pixels.append((100, 105, 102))
        # Bright red (should dominate)
        for _ in range(10):
            pixels.append((255, 0, 0))
        r, g, b = screen_color.dominant_color(pixels, 10, 10)
        self.assertGreater(r, 200)
        self.assertLess(g, 50)
        self.assertLess(b, 50)

    def test_few_survivors_fallback(self):
        """If fewer than 5% survive filtering, use all pixels."""
        pixels = []
        # All near-black (will be filtered)
        for _ in range(99):
            pixels.append((10, 10, 10))
        # One bright pixel
        pixels.append((255, 0, 0))
        # Only 1% survives, so fallback to mean of all
        r, g, b = screen_color.dominant_color(pixels, 10, 10)
        # Mean of all pixels should be low
        self.assertLess(r, 50)


class TestGrabSmall(unittest.TestCase):
    """Test the grab_small function with mocked mss."""

    def test_grab_small_returns_correct_size(self):
        """grab_small should return 64x36 pixels."""
        # Create a fake mss module
        fake_img = mock.Mock()
        fake_img.width = 1920
        fake_img.height = 1080
        # BGRA buffer: 1920*1080*4 bytes, all red (B=0, G=0, R=255, A=255)
        fake_img.bgra = bytes([0, 0, 255, 255]) * (1920 * 1080)

        fake_sct = mock.Mock()
        fake_sct.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080}
        ]
        fake_sct.grab.return_value = fake_img

        fake_mss = mock.MagicMock()
        fake_mss.mss.return_value.__enter__.return_value = fake_sct
        fake_mss.mss.return_value.__exit__.return_value = None

        with mock.patch.dict("sys.modules", {"mss": fake_mss}):
            pixels, w, h = screen_color.grab_small()

        self.assertEqual(w, 64)
        self.assertEqual(h, 36)
        self.assertEqual(len(pixels), 64 * 36)

    def test_grab_small_channel_order(self):
        """grab_small should return RGB order (not BGRA)."""
        # Create a fake image with a known pattern
        # Top-left pixel: B=10, G=20, R=30, A=255
        fake_img = mock.Mock()
        fake_img.width = 1920
        fake_img.height = 1080
        buf = bytearray([0, 0, 0, 255]) * (1920 * 1080)
        # Set top-left pixel to B=10, G=20, R=30
        buf[0] = 10  # B
        buf[1] = 20  # G
        buf[2] = 30  # R
        fake_img.bgra = bytes(buf)

        fake_sct = mock.Mock()
        fake_sct.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080}
        ]
        fake_sct.grab.return_value = fake_img

        fake_mss = mock.MagicMock()
        fake_mss.mss.return_value.__enter__.return_value = fake_sct
        fake_mss.mss.return_value.__exit__.return_value = None

        with mock.patch.dict("sys.modules", {"mss": fake_mss}):
            pixels, w, h = screen_color.grab_small()

        # First pixel should be (R=30, G=20, B=10)
        self.assertEqual(pixels[0], (30, 20, 10))


if __name__ == "__main__":
    unittest.main()
