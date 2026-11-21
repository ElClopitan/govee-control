#!/usr/bin/env python
"""
Benchmark for screen_color.py.

Captures the screen and computes dominant colour 20 times,
reporting mean ms per call and process CPU seconds used.

Usage:
    python tools/screen_bench.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import screen_color


def main():
    iterations = 20

    print(f"screen_color benchmark ({iterations} iterations)")
    print("=" * 50)

    # Warmup
    try:
        pixels, w, h = screen_color.grab_small()
        r, g, b = screen_color.dominant_color(pixels, w, h)
        print(f"Warmup: {w}x{h} -> ({r}, {g}, {b})")
    except ImportError as e:
        print(f"mss not installed: {e}")
        print("Skipping benchmark (install with: pip install mss)")
        return 1
    except Exception as e:
        print(f"Error during warmup: {e}")
        return 1

    # Benchmark
    wall_start = time.time()
    cpu_start = time.process_time()

    for i in range(iterations):
        pixels, w, h = screen_color.grab_small()
        r, g, b = screen_color.dominant_color(pixels, w, h)

    wall_end = time.time()
    cpu_end = time.process_time()

    wall_total = wall_end - wall_start
    cpu_total = cpu_end - cpu_start
    wall_per_call = (wall_total / iterations) * 1000  # ms
    cpu_per_call = (cpu_total / iterations) * 1000  # ms

    print(f"\nResults:")
    print(f"  Wall time per call: {wall_per_call:.1f} ms")
    print(f"  CPU time per call:  {cpu_per_call:.1f} ms")
    print(f"  Total wall time:    {wall_total:.2f} s")
    print(f"  Total CPU time:     {cpu_total:.2f} s")

    if wall_per_call < 15:
        print(f"\nTarget met: {wall_per_call:.1f} ms < 15 ms")
    else:
        print(f"\nTarget missed: {wall_per_call:.1f} ms >= 15 ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
