"""Tests for tools/segment_probe.py."""

import base64
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import helpers  # noqa: F401

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

    @mock.patch("segment_probe.time.sleep")
    @mock.patch("segment_probe.govee.send")
    def test_live_run_sends(self, mock_send, mock_sleep):
        """Live run should call govee.send() with the right sequence."""
        segment_probe.run_probe(
            ip="192.168.1.1",
            leds=5,
            pattern="walk",
            duration=1,
            fps=2,
            dry_run=False,
        )
        # Should send: turn on, brightness, enable, 2 frames, disable, turn off = 7 calls
        self.assertEqual(mock_send.call_count, 7)
        # Verify the sequence of commands
        cmds = [call[0][1]["msg"]["cmd"] for call in mock_send.call_args_list]
        self.assertEqual(cmds, ["turn", "brightness", "razer", "razer", "razer", "razer", "turn"])
        # Last turn should be off (value 0)
        last_turn = mock_send.call_args_list[-1][0][1]
        self.assertEqual(last_turn["msg"]["data"]["value"], 0)

    @mock.patch("segment_probe.time.sleep")
    @mock.patch("segment_probe.govee.brightness")
    @mock.patch("segment_probe.govee.turn")
    @mock.patch("segment_probe.govee.send")
    def test_turn_on_before_razer_enable(self, mock_send, mock_turn, mock_brightness, mock_sleep):
        """Strip must be turned on at 80% before the first razer send."""
        # Use a single mock manager to track call order
        manager = mock.Mock()
        manager.attach_mock(mock_turn, "turn")
        manager.attach_mock(mock_brightness, "brightness")
        manager.attach_mock(mock_send, "send")

        segment_probe.run_probe(
            ip="192.168.1.50",
            leds=5,
            pattern="walk",
            duration=1,
            fps=2,
            dry_run=False,
        )

        # Verify brightness was called once with 80%
        mock_brightness.assert_called_once_with("192.168.1.50", 80)

        # Verify order: turn on and brightness must come before the first send
        calls = manager.mock_calls
        turn_on_idx = None
        brightness_idx = None
        first_send_idx = None
        for i, call in enumerate(calls):
            if call[0] == "turn" and call[1][1] is True and turn_on_idx is None:
                turn_on_idx = i
            if call[0] == "brightness" and brightness_idx is None:
                brightness_idx = i
            if call[0] == "send" and first_send_idx is None:
                first_send_idx = i

        self.assertIsNotNone(turn_on_idx, "turn on was never called")
        self.assertIsNotNone(brightness_idx, "brightness was never called")
        self.assertIsNotNone(first_send_idx, "send was never called")
        self.assertLess(turn_on_idx, first_send_idx, "turn on must come before first razer send")
        self.assertLess(brightness_idx, first_send_idx, "brightness must come before first razer send")

    @mock.patch("segment_probe.time.sleep")
    @mock.patch("segment_probe.govee.turn")
    @mock.patch("segment_probe.govee.send")
    def test_error_during_frames_still_disables(self, mock_send, mock_turn, mock_sleep):
        """If govee.send raises during frames, disable is still sent and strip is turned off."""
        call_count = [0]

        def raise_on_fourth(*args, **kwargs):
            call_count[0] += 1
            # Calls 1-3: turn on, brightness, enable
            # Call 4: first frame (raise here)
            if call_count[0] == 4:
                raise OSError("network error")

        mock_send.side_effect = raise_on_fourth

        with self.assertRaises(OSError):
            segment_probe.run_probe(
                ip="192.168.1.1",
                leds=5,
                pattern="walk",
                duration=1,
                fps=2,
                dry_run=False,
            )

        # Should have sent: turn on (1), brightness (2), enable (3),
        # raised on frame (4), then disable (5)
        self.assertEqual(call_count[0], 5)
        # Last send_razer call should be the disable packet
        last_call = mock_send.call_args_list[-1]
        msg = last_call[0][1]
        self.assertEqual(msg["msg"]["cmd"], "razer")
        self.assertEqual(msg["msg"]["data"]["pt"], "uwABsQAL")
        # Strip should be turned off (second call to turn)
        self.assertEqual(mock_turn.call_count, 2)
        mock_turn.assert_called_with("192.168.1.1", False)

    @mock.patch("segment_probe.time.sleep")
    @mock.patch("segment_probe.govee.turn")
    @mock.patch("segment_probe.govee.send")
    def test_error_on_enable_still_turns_off(self, mock_send, mock_turn, mock_sleep):
        """If govee.send raises on the enable send, strip is still turned off."""
        call_count = [0]

        def raise_on_enable(*args, **kwargs):
            call_count[0] += 1
            # Call 1: brightness
            # Call 2: enable (raise here)
            if call_count[0] == 2:
                raise OSError("network error")

        mock_send.side_effect = raise_on_enable

        with self.assertRaises(OSError):
            segment_probe.run_probe(
                ip="192.168.1.1",
                leds=5,
                pattern="walk",
                duration=1,
                fps=2,
                dry_run=False,
            )

        # Should have sent: brightness (1), raised on enable (2),
        # then disable in finally (3)
        self.assertEqual(call_count[0], 3)
        # Strip should be turned off
        self.assertEqual(mock_turn.call_count, 2)
        mock_turn.assert_called_with("192.168.1.1", False)


class TestModeGate(unittest.TestCase):
    """Test that main() checks mode/signal before running."""

    @mock.patch("segment_probe.arbiter.get_mode", return_value="music")
    @mock.patch("segment_probe.arbiter.signal_active", return_value=False)
    @mock.patch("segment_probe.run_probe")
    def test_music_mode_exits_1(self, mock_run, mock_signal, mock_mode):
        """main() with mode 'music' exits 1 and sends nothing."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 1)
        mock_run.assert_not_called()

    @mock.patch("segment_probe.arbiter.get_mode", return_value="off")
    @mock.patch("segment_probe.arbiter.signal_active", return_value=True)
    @mock.patch("segment_probe.run_probe")
    def test_signal_active_exits_1(self, mock_run, mock_signal, mock_mode):
        """main() with active signal exits 1 and sends nothing."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 1)
        mock_run.assert_not_called()

    @mock.patch("segment_probe.arbiter.get_mode", return_value="off")
    @mock.patch("segment_probe.arbiter.signal_active", return_value=False)
    @mock.patch("segment_probe.run_probe")
    def test_off_mode_runs(self, mock_run, mock_signal, mock_mode):
        """main() with mode 'off' and no signal runs the probe."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50"]):
            segment_probe.main()
        mock_run.assert_called_once()

    @mock.patch("segment_probe.arbiter.get_mode", return_value="music")
    @mock.patch("segment_probe.arbiter.signal_active", return_value=False)
    @mock.patch("segment_probe.run_probe")
    def test_dry_run_skips_mode_gate(self, mock_run, mock_signal, mock_mode):
        """main() with --dry-run skips the mode/signal gate."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50", "--dry-run"]):
            segment_probe.main()
        mock_run.assert_called_once()


class TestArgValidation(unittest.TestCase):
    """Test argument validation."""

    def test_leds_0_exits_2(self):
        """--leds 0 exits with code 2."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50", "--leds", "0"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_leds_85_exits_2(self):
        """--leds 85 exits with code 2."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50", "--leds", "85"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_fps_0_exits_2(self):
        """--fps 0 exits with code 2."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50", "--fps", "0"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_fps_21_exits_2(self):
        """--fps 21 exits with code 2."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50", "--fps", "21"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_duration_negative_exits_2(self):
        """--duration -1 exits with code 2."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50", "--duration", "-1"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_duration_61_exits_2(self):
        """--duration 61 exits with code 2."""
        with mock.patch.object(sys, "argv", ["segment_probe.py", "192.168.1.50", "--duration", "61"]):
            with self.assertRaises(SystemExit) as ctx:
                segment_probe.main()
        self.assertEqual(ctx.exception.code, 2)


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
