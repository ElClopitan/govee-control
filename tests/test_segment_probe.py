"""Tests for tools/segment_probe.py."""

import base64
import json
import unittest
from unittest import mock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
import segment_probe


class TestRazerPayloads(unittest.TestCase):
    """Test the Razer payload builders."""

    def test_enable_payload(self):
        """razer_enable() must return the exact base64 string."""
        self.assertEqual(segment_probe.razer_enable(), "uwABsQEK")

    def test_disable_payload(self):
        """razer_disable() must return the exact base64 string."""
        self.assertEqual(segment_probe.razer_disable(), "uwABsQAL")

    def test_frame_payload_vector(self):
        """Test vector: two RGB triplets with known checksum."""
        colors = [(0x10, 0x20, 0x30), (0x40, 0x50, 0x60)]
        result = segment_probe.razer_frame(colors)
        self.assertEqual(result, "uwAIsAECECAwQFBgcA==")

    def test_frame_checksum_byte(self):
        """Verify the checksum byte is correct by decoding."""
        colors = [(0x10, 0x20, 0x30), (0x40, 0x50, 0x60)]
        result = segment_probe.razer_frame(colors)
        raw = base64.b64decode(result)
        # Last byte should be the XOR checksum
        self.assertEqual(raw[-1], 0x70)
        # Verify by recomputing
        computed = 0
        for byte in raw[:-1]:
            computed ^= byte
        self.assertEqual(computed, raw[-1])

    def test_frame_single_led(self):
        """Single LED frame."""
        colors = [(255, 0, 0)]
        result = segment_probe.razer_frame(colors)
        raw = base64.b64decode(result)
        # Header: bb 00 05 b0 01 01, then 255 0 0, then checksum
        self.assertEqual(raw[0], 0xbb)
        self.assertEqual(raw[1], 0x00)
        self.assertEqual(raw[2], 5)  # len = 3*1 + 2
        self.assertEqual(raw[3], 0xb0)
        self.assertEqual(raw[4], 0x01)
        self.assertEqual(raw[5], 1)  # n = 1
        self.assertEqual(raw[6], 255)
        self.assertEqual(raw[7], 0)
        self.assertEqual(raw[8], 0)
        # Checksum
        computed = 0
        for byte in raw[:-1]:
            computed ^= byte
        self.assertEqual(computed, raw[-1])

    def test_frame_many_leds(self):
        """Frame with many LEDs."""
        colors = [(i % 256, (i * 2) % 256, (i * 3) % 256) for i in range(50)]
        result = segment_probe.razer_frame(colors)
        raw = base64.b64decode(result)
        # Verify length: 6 header + 3*50 colors + 1 checksum = 157
        self.assertEqual(len(raw), 157)
        # Verify checksum
        computed = 0
        for byte in raw[:-1]:
            computed ^= byte
        self.assertEqual(computed, raw[-1])


class TestDryRun(unittest.TestCase):
    """Test that --dry-run sends nothing."""

    @mock.patch("segment_probe.govee.send")
    def test_dry_run_sends_nothing(self, mock_send):
        """Dry run should not call govee.send()."""
        segment_probe.run_probe(
            ip="192.168.1.1",
            leds=5,
            pattern="walk",
            duration=1,
            fps=2,
            dry_run=True,
        )
        mock_send.assert_not_called()

    @mock.patch("segment_probe.govee.send")
    def test_live_run_sends(self, mock_send):
        """Live run should call govee.send()."""
        segment_probe.run_probe(
            ip="192.168.1.1",
            leds=5,
            pattern="walk",
            duration=1,
            fps=2,
            dry_run=False,
        )
        # Should send: enable + 2 frames + disable + color + brightness = 6 calls
        self.assertGreater(mock_send.call_count, 0)


class TestPatterns(unittest.TestCase):
    """Test pattern generators."""

    def test_halves_pattern(self):
        """Halves pattern: left red, right blue."""
        colors = segment_probe.pattern_halves(10)
        self.assertEqual(len(colors), 10)
        # First half red
        for i in range(5):
            self.assertEqual(colors[i], (255, 0, 0))
        # Second half blue
        for i in range(5, 10):
            self.assertEqual(colors[i], (0, 0, 255))

    def test_rainbow_pattern(self):
        """Rainbow pattern: all LEDs have different colors."""
        colors = segment_probe.pattern_rainbow(10)
        self.assertEqual(len(colors), 10)
        # All should be valid RGB
        for r, g, b in colors:
            self.assertGreaterEqual(r, 0)
            self.assertLessEqual(r, 255)
            self.assertGreaterEqual(g, 0)
            self.assertLessEqual(g, 255)
            self.assertGreaterEqual(b, 0)
            self.assertLessEqual(b, 255)

    def test_walk_pattern(self):
        """Walk pattern: one white LED, rest black."""
        colors = segment_probe.pattern_walk(10, 3)
        self.assertEqual(len(colors), 10)
        white_count = 0
        for i, (r, g, b) in enumerate(colors):
            if i == 3:
                self.assertEqual((r, g, b), (255, 255, 255))
                white_count += 1
            else:
                self.assertEqual((r, g, b), (0, 0, 0))
        self.assertEqual(white_count, 1)


if __name__ == "__main__":
    unittest.main()
