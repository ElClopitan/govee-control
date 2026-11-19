"""Tests for govee.py using unittest.mock to fake sockets."""

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import govee


class TestParseColor(unittest.TestCase):
    def test_hex_with_hash(self):
        self.assertEqual(govee.parse_color("#ff8800"), (255, 136, 0))

    def test_hex_without_hash(self):
        self.assertEqual(govee.parse_color("ff8800"), (255, 136, 0))

    def test_color_name(self):
        self.assertEqual(govee.parse_color("red"), (255, 0, 0))

    def test_color_name_case_insensitive(self):
        self.assertEqual(govee.parse_color("Blue"), (0, 0, 255))

    def test_invalid_length(self):
        with self.assertRaises(ValueError):
            govee.parse_color("ff")

    def test_invalid_hex(self):
        with self.assertRaises(ValueError):
            govee.parse_color("zzzzzz")


class TestBrightnessValidation(unittest.TestCase):
    def test_brightness_zero(self):
        with mock.patch("govee.send") as mock_send:
            with self.assertRaises(ValueError):
                govee.brightness("1.2.3.4", 0)
            mock_send.assert_not_called()

    def test_brightness_101(self):
        with mock.patch("govee.send") as mock_send:
            with self.assertRaises(ValueError):
                govee.brightness("1.2.3.4", 101)
            mock_send.assert_not_called()

    def test_brightness_valid(self):
        with mock.patch("govee.send") as mock_send:
            govee.brightness("1.2.3.4", 50)
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][1]
            self.assertEqual(msg["msg"]["cmd"], "brightness")
            self.assertEqual(msg["msg"]["data"]["value"], 50)


class TestColorValidation(unittest.TestCase):
    def test_color_negative(self):
        with mock.patch("govee.send") as mock_send:
            with self.assertRaises(ValueError):
                govee.color("1.2.3.4", -1, 0, 0)
            mock_send.assert_not_called()

    def test_color_over_255(self):
        with mock.patch("govee.send") as mock_send:
            with self.assertRaises(ValueError):
                govee.color("1.2.3.4", 0, 0, 256)
            mock_send.assert_not_called()


class TestSendBytes(unittest.TestCase):
    """Verify exact JSON bytes and port for each command."""

    def _capture_sendto(self, ip, port):
        """Return a mock socket that captures sendto calls."""
        captured = {}

        class FakeSocket:
            def sendto(self, data, addr):
                captured["data"] = data
                captured["addr"] = addr

            def close(self):
                pass

        mock_sock = FakeSocket()
        return mock_sock, captured

    @mock.patch("govee.socket.socket")
    def test_turn_on(self, mock_socket_cls):
        mock_sock, captured = self._capture_sendto("1.2.3.4", govee.CONTROL_PORT)
        mock_socket_cls.return_value = mock_sock

        govee.turn("1.2.3.4", True)

        self.assertEqual(captured["addr"], ("1.2.3.4", govee.CONTROL_PORT))
        msg = json.loads(captured["data"])
        self.assertEqual(msg["msg"]["cmd"], "turn")
        self.assertEqual(msg["msg"]["data"]["value"], 1)

    @mock.patch("govee.socket.socket")
    def test_turn_off(self, mock_socket_cls):
        mock_sock, captured = self._capture_sendto("1.2.3.4", govee.CONTROL_PORT)
        mock_socket_cls.return_value = mock_sock

        govee.turn("1.2.3.4", False)

        msg = json.loads(captured["data"])
        self.assertEqual(msg["msg"]["cmd"], "turn")
        self.assertEqual(msg["msg"]["data"]["value"], 0)

    @mock.patch("govee.socket.socket")
    def test_brightness(self, mock_socket_cls):
        mock_sock, captured = self._capture_sendto("1.2.3.4", govee.CONTROL_PORT)
        mock_socket_cls.return_value = mock_sock

        govee.brightness("1.2.3.4", 75)

        self.assertEqual(captured["addr"], ("1.2.3.4", govee.CONTROL_PORT))
        msg = json.loads(captured["data"])
        self.assertEqual(msg["msg"]["cmd"], "brightness")
        self.assertEqual(msg["msg"]["data"]["value"], 75)

    @mock.patch("govee.socket.socket")
    def test_color(self, mock_socket_cls):
        mock_sock, captured = self._capture_sendto("1.2.3.4", govee.CONTROL_PORT)
        mock_socket_cls.return_value = mock_sock

        govee.color("1.2.3.4", 255, 128, 0)

        self.assertEqual(captured["addr"], ("1.2.3.4", govee.CONTROL_PORT))
        msg = json.loads(captured["data"])
        self.assertEqual(msg["msg"]["cmd"], "colorwc")
        self.assertEqual(msg["msg"]["data"]["color"]["r"], 255)
        self.assertEqual(msg["msg"]["data"]["color"]["g"], 128)
        self.assertEqual(msg["msg"]["data"]["color"]["b"], 0)
        self.assertEqual(msg["msg"]["data"]["colorTemInKelvin"], 0)

    @mock.patch("govee.socket.socket")
    def test_color_with_kelvin(self, mock_socket_cls):
        mock_sock, captured = self._capture_sendto("1.2.3.4", govee.CONTROL_PORT)
        mock_socket_cls.return_value = mock_sock

        govee.color("1.2.3.4", 255, 255, 255, kelvin=4000)

        self.assertEqual(captured["addr"], ("1.2.3.4", govee.CONTROL_PORT))
        msg = json.loads(captured["data"])
        self.assertEqual(msg["msg"]["cmd"], "colorwc")
        self.assertEqual(msg["msg"]["data"]["colorTemInKelvin"], 4000)


class TestGetInterfaceIPs(unittest.TestCase):
    @mock.patch("govee.socket.gethostname", return_value="testhost")
    @mock.patch("govee.socket.getaddrinfo")
    def test_filters_loopback_and_linklocal(self, mock_getaddrinfo, mock_gethostname):
        """get_interface_ips filters 127.x and 169.254.x addresses."""
        # Mock getaddrinfo to return multiple addresses
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.1.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0)),
        ]

        ips = govee.get_interface_ips()
        self.assertEqual(ips, ["10.0.0.5", "192.168.1.10"])

    @mock.patch("govee.socket.gethostname", return_value="testhost")
    @mock.patch("govee.socket.getaddrinfo")
    def test_deduplicates(self, mock_getaddrinfo, mock_gethostname):
        """get_interface_ips deduplicates identical addresses."""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0)),
        ]

        ips = govee.get_interface_ips()
        self.assertEqual(ips, ["10.0.0.5", "192.168.1.10"])


class TestScan(unittest.TestCase):
    @mock.patch("govee.socket.socket")
    def test_scan_no_devices(self, mock_socket_cls):
        """Scan with no replies returns empty list."""
        mock_sock = mock.MagicMock()
        mock_sock.recvfrom.side_effect = socket.timeout()
        mock_socket_cls.return_value = mock_sock

        devices = govee.scan(timeout=0.1)
        self.assertEqual(devices, [])

    @mock.patch("govee.get_interface_ips", return_value=["192.168.1.10"])
    @mock.patch("govee.socket.socket")
    def test_scan_finds_device(self, mock_socket_cls, mock_get_ips):
        """Scan receives a device reply."""
        mock_sock = mock.MagicMock()
        reply = json.dumps({
            "msg": {
                "cmd": "scan",
                "data": {"ip": "192.168.1.100", "device": "test", "sku": "H610A"},
            }
        }).encode("utf-8")
        mock_sock.recvfrom.side_effect = [
            (reply, ("192.168.1.100", 4002)),
            socket.timeout(),
        ]
        mock_socket_cls.return_value = mock_sock

        devices = govee.scan(timeout=0.1)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["ip"], "192.168.1.100")
        self.assertEqual(devices[0]["sku"], "H610A")

        # Verify discovery message was sent to multicast
        mock_sock.sendto.assert_called_once()
        data, addr = mock_sock.sendto.call_args[0]
        self.assertEqual(addr, (govee.MULTICAST_ADDR, govee.DISCOVERY_PORT))
        msg = json.loads(data)
        self.assertEqual(msg["msg"]["cmd"], "scan")

    @mock.patch("govee.get_interface_ips", return_value=["192.168.1.10", "10.0.0.5"])
    @mock.patch("govee.socket.socket")
    def test_scan_sends_on_all_interfaces(self, mock_socket_cls, mock_get_ips):
        """Scan without iface_ip sends on all interfaces."""
        mock_sock = mock.MagicMock()
        mock_sock.recvfrom.side_effect = socket.timeout()
        mock_socket_cls.return_value = mock_sock

        govee.scan(timeout=0.1)

        # Should have created 3 sockets: 2 for sending + 1 for receiving
        self.assertEqual(mock_socket_cls.call_count, 3)
        # Should have sent on both interfaces
        self.assertEqual(mock_sock.sendto.call_count, 2)

    @mock.patch("govee.socket.socket")
    def test_scan_deduplicates_replies(self, mock_socket_cls):
        """Duplicate scan replies from same device are deduped."""
        mock_sock = mock.MagicMock()
        reply = json.dumps({
            "msg": {
                "cmd": "scan",
                "data": {"ip": "192.168.1.100", "device": "test", "sku": "H610A"},
            }
        }).encode("utf-8")
        # Same device replies twice (e.g., from two interfaces)
        mock_sock.recvfrom.side_effect = [
            (reply, ("192.168.1.100", 4002)),
            (reply, ("192.168.1.100", 4002)),
            socket.timeout(),
        ]
        mock_socket_cls.return_value = mock_sock

        devices = govee.scan(timeout=0.1)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["ip"], "192.168.1.100")


class TestStatus(unittest.TestCase):
    """Tests for govee.status() — IP filtering, JSON errors, timeout."""

    def _make_sock(self, recvfrom_side_effect):
        """Create a mock socket with the given recvfrom behavior."""
        mock_sock = mock.MagicMock()
        mock_sock.recvfrom.side_effect = recvfrom_side_effect
        return mock_sock

    @mock.patch("govee.socket.socket")
    @mock.patch("govee.send")
    def test_status_sends_correct_request(self, mock_send, mock_socket_cls):
        """status() sends the devStatus request to the given IP."""
        mock_sock = self._make_sock([socket.timeout()])
        mock_socket_cls.return_value = mock_sock

        govee.status("10.0.0.5", timeout=0.1)

        mock_send.assert_called_once_with(
            "10.0.0.5",
            {"msg": {"cmd": "devStatus", "data": {}}},
        )

    @mock.patch("govee.socket.socket")
    @mock.patch("govee.send")
    def test_status_filters_by_ip(self, mock_send, mock_socket_cls):
        """status() skips replies from other IPs and returns the correct one."""
        reply_wrong_ip = json.dumps({
            "msg": {"cmd": "devStatus", "data": {"ip": "10.0.0.9", "state": "wrong"}}
        }).encode("utf-8")
        reply_right_ip = json.dumps({
            "msg": {"cmd": "devStatus", "data": {"ip": "10.0.0.5", "state": "right"}}
        }).encode("utf-8")

        mock_sock = self._make_sock([
            (reply_wrong_ip, ("10.0.0.9", 4002)),
            (reply_right_ip, ("10.0.0.5", 4002)),
        ])
        mock_socket_cls.return_value = mock_sock

        result = govee.status("10.0.0.5", timeout=0.5)

        self.assertIsNotNone(result)
        self.assertEqual(result["msg"]["data"]["ip"], "10.0.0.5")
        self.assertEqual(result["msg"]["data"]["state"], "right")

    @mock.patch("govee.socket.socket")
    @mock.patch("govee.send")
    def test_status_skips_non_json(self, mock_send, mock_socket_cls):
        """status() skips non-JSON packets and returns the valid reply."""
        valid_reply = json.dumps({
            "msg": {"cmd": "devStatus", "data": {"ip": "10.0.0.5", "state": "ok"}}
        }).encode("utf-8")

        mock_sock = self._make_sock([
            (b"not json", ("10.0.0.5", 4002)),
            (valid_reply, ("10.0.0.5", 4002)),
        ])
        mock_socket_cls.return_value = mock_sock

        result = govee.status("10.0.0.5", timeout=0.5)

        self.assertIsNotNone(result)
        self.assertEqual(result["msg"]["data"]["state"], "ok")

    @mock.patch("govee.socket.socket")
    @mock.patch("govee.send")
    def test_status_timeout_returns_none(self, mock_send, mock_socket_cls):
        """status() returns None when recvfrom times out."""
        mock_sock = self._make_sock([socket.timeout()])
        mock_socket_cls.return_value = mock_sock

        result = govee.status("10.0.0.5", timeout=0.1)

        self.assertIsNone(result)


class TestCLI(unittest.TestCase):
    def test_help(self):
        """--help exits 0."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "govee.py", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Govee LAN light controller", result.stdout)

    def test_cli_on_multiple_ips(self):
        """CLI sends to both IPs from config."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(
                {
                    "iface_ip": "",
                    "devices": [
                        {"name": "left", "ip": "192.168.1.50"},
                        {"name": "right", "ip": "192.168.1.51"},
                    ],
                },
                f,
            )
            config_path = f.name

        try:
            with mock.patch("govee.send") as mock_send:
                sys.argv = ["govee.py", "on", "--config", config_path]
                govee.main()

                self.assertEqual(mock_send.call_count, 2)
                ips = [call[0][0] for call in mock_send.call_args_list]
                self.assertIn("192.168.1.50", ips)
                self.assertIn("192.168.1.51", ips)
        finally:
            Path(config_path).unlink()

    def test_cli_brightness_non_integer(self):
        """brightness with non-integer value exits 2 with clean error."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "govee.py", "brightness", "abc", "--ip", "10.0.0.5"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("brightness must be an integer 1-100", result.stderr)

    def test_cli_brightness_zero(self):
        """brightness 0 exits 2 with clean error."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "govee.py", "brightness", "0", "--ip", "10.0.0.5"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("brightness must be an integer 1-100", result.stderr)

    def test_cli_brightness_over_100(self):
        """brightness 101 exits 2 with clean error."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "govee.py", "brightness", "101", "--ip", "10.0.0.5"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("brightness must be an integer 1-100", result.stderr)

    def test_cli_color_invalid(self):
        """color with invalid hex exits 2 with clean error."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "govee.py", "color", "zzzzzz", "--ip", "10.0.0.5"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("invalid colour", result.stderr)

    def test_cli_invalid_json_config(self):
        """on with invalid JSON config exits 1 with clean error."""
        import subprocess
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("{")
            config_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, "govee.py", "on", "--config", config_path],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent.parent),
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid JSON", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        finally:
            Path(config_path).unlink()


if __name__ == "__main__":
    unittest.main()
