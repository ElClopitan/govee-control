#!/usr/bin/env python3
"""Govee Razer Chroma segment probe.

Sends per-segment colour frames to Govee strips via the undocumented
'razer' LAN command. The owner confirmed the Govee app lists Razer
Chroma support for the H1AB2/H1AB3 strips.

Protocol: UDP JSON to device IP:4003, same envelope as govee.py.
The 'pt' field is base64-encoded binary payload.

Payload formats:
- Enable:  bb 00 01 b1 01 0a
- Disable: bb 00 01 b1 00 0b
- Frame:   bb 00 <len> b0 01 <n> <n RGB triplets> <xor checksum>
  where <len> = 3*n + 2, checksum = XOR of all preceding bytes.
"""

import argparse
import base64
import json
import socket
import sys
import time
from pathlib import Path

# Add parent dir so we can import govee.py
sys.path.insert(0, str(Path(__file__).parent.parent))
import govee
import arbiter

CONTROL_PORT = 4003


def razer_enable():
    """Return base64 payload to enable Razer Chroma mode."""
    raw = bytes([0xbb, 0x00, 0x01, 0xb1, 0x01, 0x0a])
    return base64.b64encode(raw).decode("ascii")


def razer_disable():
    """Return base64 payload to disable Razer Chroma mode."""
    raw = bytes([0xbb, 0x00, 0x01, 0xb1, 0x00, 0x0b])
    return base64.b64encode(raw).decode("ascii")


def razer_frame(colors):
    """Build a Razer frame payload for a list of (r, g, b) tuples.

    Returns the base64-encoded payload string.
    """
    n = len(colors)
    # Header: bb 00 <len> b0 01 <n>
    # <len> = 3*n + 2 (n triplets + 1 checksum byte)
    payload = bytearray([0xbb, 0x00, 3 * n + 2, 0xb0, 0x01, n])
    for r, g, b in colors:
        payload.append(r & 0xff)
        payload.append(g & 0xff)
        payload.append(b & 0xff)
    # XOR checksum over all preceding bytes
    checksum = 0
    for byte in payload:
        checksum ^= byte
    payload.append(checksum)
    return base64.b64encode(bytes(payload)).decode("ascii")


def send_razer(ip, pt):
    """Send a Razer command to a device."""
    msg = {"msg": {"cmd": "razer", "data": {"pt": pt}}}
    govee.send(ip, msg)


def pattern_halves(n):
    """Left half red, right half blue."""
    colors = []
    for i in range(n):
        if i < n // 2:
            colors.append((255, 0, 0))
        else:
            colors.append((0, 0, 255))
    return colors


def pattern_rainbow(n):
    """Rainbow gradient across the strip."""
    colors = []
    for i in range(n):
        # Hue goes from 0 to 360 across the strip
        hue = (i / max(n - 1, 1)) * 360
        # Simple HSV to RGB (saturation=1, value=1)
        h = hue / 60.0
        sector = int(h) % 6
        f = h - int(h)
        p = 0
        q = 1 - f
        t = f
        if sector == 0:
            r, g, b = 1, t, p
        elif sector == 1:
            r, g, b = q, 1, p
        elif sector == 2:
            r, g, b = p, 1, t
        elif sector == 3:
            r, g, b = p, q, 1
        elif sector == 4:
            r, g, b = t, p, 1
        else:
            r, g, b = 1, p, q
        colors.append((int(r * 255), int(g * 255), int(b * 255)))
    return colors


def pattern_walk(n, frame_num):
    """Walking dot pattern."""
    colors = []
    for i in range(n):
        if i == frame_num % n:
            colors.append((255, 255, 255))
        else:
            colors.append((0, 0, 0))
    return colors


def run_probe(ip, leds=20, pattern="walk", duration=10, fps=10, dry_run=False):
    """Run the segment probe against a device."""
    print(f"Probing {ip} with {leds} LEDs, pattern={pattern}, {duration}s")

    # Turn the strip on so the owner can see the probe
    if not dry_run:
        govee.turn(ip, True)
        govee.brightness(ip, 80)
        print("Turned strip on at 80%")

    # Enable Razer mode
    enable_pt = razer_enable()
    if dry_run:
        print(f"ENABLE: {json.dumps({'msg': {'cmd': 'razer', 'data': {'pt': enable_pt}}})}")
    else:
        send_razer(ip, enable_pt)
        print("Sent enable")

    # Send pattern frames
    frames = duration * fps
    try:
        for frame in range(frames):
            if pattern == "halves":
                colors = pattern_halves(leds)
            elif pattern == "rainbow":
                colors = pattern_rainbow(leds)
            elif pattern == "walk":
                colors = pattern_walk(leds, frame)
            else:
                raise ValueError(f"unknown pattern: {pattern}")

            pt = razer_frame(colors)
            if dry_run:
                if frame < 3:
                    print(f"FRAME {frame}: {json.dumps({'msg': {'cmd': 'razer', 'data': {'pt': pt}}})}")
                elif frame == 3:
                    print(f"... (skipping frames 3-{frames-1})")
            else:
                send_razer(ip, pt)

            if not dry_run:
                time.sleep(1.0 / fps)

        if not dry_run:
            print(f"Sent {frames} frames")
    finally:
        # Disable Razer mode
        disable_pt = razer_disable()
        if dry_run:
            print(f"DISABLE: {json.dumps({'msg': {'cmd': 'razer', 'data': {'pt': disable_pt}}})}")
        else:
            send_razer(ip, disable_pt)
            print("Sent disable")

        # Turn off the strip (replaces the old white/80% restore)
        if not dry_run:
            govee.turn(ip, False)
            print("Sent disable; strip turned off")


def main():
    parser = argparse.ArgumentParser(
        description="Govee Razer Chroma segment probe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Pick Off in the tray first; the strip is turned off at the end.

Examples:
  python tools/segment_probe.py 192.168.1.50 --leds 20 --pattern walk
  python tools/segment_probe.py 192.168.1.50 --leds 30 --pattern rainbow --dry-run
""",
    )
    parser.add_argument("ip", help="device IP address")
    parser.add_argument("--leds", type=int, default=20, help="number of LEDs (default: 20)")
    parser.add_argument(
        "--pattern",
        choices=["halves", "rainbow", "walk"],
        default="walk",
        help="pattern to display (default: walk)",
    )
    parser.add_argument("--duration", type=int, default=10, help="duration in seconds (default: 10)")
    parser.add_argument("--fps", type=int, default=10, help="frames per second (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="print JSON instead of sending")

    args = parser.parse_args()

    # Validate arguments
    if args.leds < 1 or args.leds > 84:
        parser.error("--leds must be between 1 and 84")
    if args.fps < 1 or args.fps > 20:
        parser.error("--fps must be between 1 and 20")
    if args.duration < 0 or args.duration > 60:
        parser.error("--duration must be between 0 and 60")

    # Check mode/signal gate (skip for dry-run)
    if not args.dry_run:
        mode = arbiter.get_mode()
        if mode != "off":
            print(f"pick Off in the tray first (mode is {mode})", file=sys.stderr)
            sys.exit(1)
        if arbiter.signal_active():
            print("agent signal is active; try again later", file=sys.stderr)
            sys.exit(1)

    run_probe(
        ip=args.ip,
        leds=args.leds,
        pattern=args.pattern,
        duration=args.duration,
        fps=args.fps,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
