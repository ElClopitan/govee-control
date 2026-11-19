#!/usr/bin/env python3
"""Govee LAN client + CLI.

Controls Govee lights over the documented Govee LAN API (UDP JSON).
Stdlib-only.

Protocol:
- Discovery: multicast UDP to 239.255.255.250:4001, devices reply on 4002
- Control: UDP to device IP:4003
- Status: UDP to device IP:4003, reply on 4002
"""

import argparse
import json
import socket
import struct
import sys
import time
from pathlib import Path

MULTICAST_ADDR = "239.255.255.250"
DISCOVERY_PORT = 4001
REPLY_PORT = 4002
CONTROL_PORT = 4003

COLOR_NAMES = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "pink": (255, 192, 203),
}


def parse_color(s):
    """Parse a colour string to (r, g, b).

    Accepts '#ff8800', 'ff8800', or a colour name.
    Raises ValueError on invalid input.
    """
    s = s.strip().lower()
    if s in COLOR_NAMES:
        return COLOR_NAMES[s]
    if s.startswith("#"):
        s = s[1:]
    if len(s) != 6:
        raise ValueError(f"invalid colour: {s!r}")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        raise ValueError(f"invalid colour hex: {s!r}")
    return (r, g, b)


def _make_socket(iface_ip=None):
    """Create a UDP socket, optionally bound to a specific interface."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if iface_ip:
        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_MULTICAST_IF,
            socket.inet_aton(iface_ip),
        )
    return sock


def get_interface_ips():
    """Get all non-loopback, non-link-local IPv4 interface addresses.

    Returns a list of IP address strings.
    """
    ips = set()
    try:
        hostname = socket.gethostname()
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in addrinfos:
            ip = info[4][0]
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            ips.add(ip)
    except socket.gaierror:
        pass
    return sorted(ips)


def scan(timeout=3, iface_ip=None):
    """Discover Govee devices on the LAN.

    If iface_ip is not specified, sends the scan packet on every
    non-loopback, non-link-local IPv4 interface.

    Returns a list of dicts with 'ip', 'device', 'sku' keys.
    """
    # Determine which interfaces to send on
    if iface_ip:
        interfaces = [iface_ip]
    else:
        interfaces = get_interface_ips()
        if not interfaces:
            interfaces = [""]  # fallback: let OS choose

    # Create one socket per interface for sending
    send_socks = []
    for ip in interfaces:
        sock = _make_socket(ip)
        send_socks.append(sock)

    # One socket for receiving replies
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        recv_sock.bind(("", REPLY_PORT))
        recv_sock.settimeout(timeout)

        msg = {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}
        payload = json.dumps(msg).encode("utf-8")

        # Send on all interfaces
        for sock in send_socks:
            try:
                sock.sendto(payload, (MULTICAST_ADDR, DISCOVERY_PORT))
            except OSError:
                pass  # interface may be down

        devices = []
        seen = set()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                recv_sock.settimeout(max(0.1, deadline - time.time()))
                data, addr = recv_sock.recvfrom(4096)
                try:
                    resp = json.loads(data.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if resp.get("msg", {}).get("cmd") != "scan":
                    continue
                dev = resp.get("msg", {}).get("data", {})
                ip = dev.get("ip")
                if not ip or ip in seen:
                    continue
                seen.add(ip)
                devices.append({
                    "ip": ip,
                    "device": dev.get("device", ""),
                    "sku": dev.get("sku", ""),
                })
            except socket.timeout:
                break
        return devices
    finally:
        recv_sock.close()
        for sock in send_socks:
            sock.close()


def send(ip, msg):
    """Send a control message to a device."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        payload = json.dumps(msg).encode("utf-8")
        sock.sendto(payload, (ip, CONTROL_PORT))
    finally:
        sock.close()


def turn(ip, on):
    """Turn a device on or off."""
    send(ip, {"msg": {"cmd": "turn", "data": {"value": 1 if on else 0}}})


def brightness(ip, pct):
    """Set brightness (1-100)."""
    if not 1 <= pct <= 100:
        raise ValueError(f"brightness must be 1-100, got {pct}")
    send(ip, {"msg": {"cmd": "brightness", "data": {"value": pct}}})


def color(ip, r, g, b, kelvin=0):
    """Set colour (RGB 0-255). Optional kelvin for white-temperature mode."""
    for ch, val in [("r", r), ("g", g), ("b", b)]:
        if not 0 <= val <= 255:
            raise ValueError(f"{ch} must be 0-255, got {val}")
    send(ip, {
        "msg": {
            "cmd": "colorwc",
            "data": {
                "color": {"r": r, "g": g, "b": b},
                "colorTemInKelvin": kelvin,
            },
        }
    })


def status(ip, timeout=2):
    """Query device status. Returns the parsed response dict, or None on timeout.

    Only accepts the reply from the queried IP; skips packets from other
    devices, non-JSON packets, and packets with the wrong cmd.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.bind(("", REPLY_PORT))
        send(ip, {"msg": {"cmd": "devStatus", "data": {}}})
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            sock.settimeout(max(0.05, remaining))
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                return None
            if addr[0] != ip:
                continue
            try:
                resp = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if resp.get("msg", {}).get("cmd") != "devStatus":
                continue
            return resp
    finally:
        sock.close()


def load_config(path):
    """Load config from JSON file."""
    with open(path, "r") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Govee LAN light controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python govee.py scan
  python govee.py on --ip 192.168.1.50
  python govee.py color red
  python govee.py brightness 50 --config myconfig.json
""",
    )
    parser.add_argument(
        "command",
        choices=["scan", "on", "off", "brightness", "color", "status"],
    )
    parser.add_argument("value", nargs="?", help="brightness (1-100) or colour")
    parser.add_argument(
        "--ip",
        action="append",
        default=[],
        help="target IP (repeatable); default: all devices in config",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.json"),
        help="path to config.json",
    )
    parser.add_argument(
        "--iface-ip",
        default=None,
        help="bind multicast to this interface IP",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="discovery timeout in seconds",
    )

    args = parser.parse_args()

    # Resolve target IPs
    target_ips = args.ip
    if not target_ips and args.command != "scan":
        try:
            cfg = load_config(args.config)
            target_ips = [d["ip"] for d in cfg.get("devices", [])]
            if not target_ips:
                print("No devices in config and no --ip given", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print(f"Config not found: {args.config}", file=sys.stderr)
            sys.exit(1)

    if args.command == "scan":
        iface_ip = args.iface_ip
        if not iface_ip:
            try:
                cfg = load_config(args.config)
                iface_ip = cfg.get("iface_ip")
            except FileNotFoundError:
                pass
        devices = scan(timeout=args.timeout, iface_ip=iface_ip)
        if not devices:
            print("no devices found")
        else:
            for d in devices:
                print(f"{d['ip']}  {d.get('sku', '')}  {d.get('device', '')}")
        return

    if args.command == "brightness":
        if not args.value:
            parser.error("brightness requires a value (1-100)")
        pct = int(args.value)
        for ip in target_ips:
            brightness(ip, pct)
            print(f"brightness {pct}% -> {ip}")
        return

    if args.command == "color":
        if not args.value:
            parser.error("color requires a value")
        r, g, b = parse_color(args.value)
        for ip in target_ips:
            color(ip, r, g, b)
            print(f"color #{r:02x}{g:02x}{b:02x} -> {ip}")
        return

    if args.command == "on":
        for ip in target_ips:
            turn(ip, True)
            print(f"on -> {ip}")
        return

    if args.command == "off":
        for ip in target_ips:
            turn(ip, False)
            print(f"off -> {ip}")
        return

    if args.command == "status":
        for ip in target_ips:
            resp = status(ip)
            if resp:
                print(f"{ip}: {json.dumps(resp)}")
            else:
                print(f"{ip}: no response")
        return


if __name__ == "__main__":
    main()
