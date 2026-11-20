#!/usr/bin/env python
"""
Audio probe: capture PC audio via WASAPI loopback and report RMS levels.

Usage:
    python tools/audio_probe.py [--seconds N] [--json]
    python tools/audio_probe.py --selftest

Options:
    --seconds N   Record for N seconds (default: 3)
    --json        Output summary as JSON
    --selftest    Play a test tone and verify it's captured
"""

import argparse
import json
import math
import struct
import sys
import tempfile
import wave

# Optional imports for music mode
try:
    import soundcard as sc
    import numpy as np
except ImportError as e:
    print(f"Error: music mode dependencies not installed. Run: pip install soundcard numpy", file=sys.stderr)
    print(f"  ({e})", file=sys.stderr)
    sys.exit(1)


def get_default_speaker():
    """Get the default speaker device."""
    try:
        speaker = sc.default_speaker()
        return speaker
    except Exception as e:
        print(f"Error getting default speaker: {e}", file=sys.stderr)
        sys.exit(1)


def get_loopback_microphone(speaker):
    """Get a loopback microphone for the given speaker."""
    try:
        mic = sc.get_microphone(speaker.name, include_loopback=True)
        return mic
    except Exception as e:
        print(f"Error getting loopback microphone: {e}", file=sys.stderr)
        sys.exit(1)


def record_audio(seconds=3, sample_rate=48000, block_size=1024):
    """
    Record audio from the default speaker's loopback.

    Returns:
        tuple: (device_name, blocks_data) where blocks_data is a list of
               (timestamp, rms) tuples
    """
    speaker = get_default_speaker()
    mic = get_loopback_microphone(speaker)

    device_name = speaker.name
    blocks = []

    total_frames = int(seconds * sample_rate)
    frames_recorded = 0

    try:
        with mic.recorder(samplerate=sample_rate, channels=1) as recorder:
            while frames_recorded < total_frames:
                frames_to_read = min(block_size, total_frames - frames_recorded)
                data = recorder.record(frames_to_read)

                # Calculate RMS for this block
                if len(data) > 0:
                    # data shape: (frames, channels)
                    samples = data[:, 0]  # First channel
                    rms = float(np.sqrt(np.mean(samples ** 2)))
                    timestamp = frames_recorded / sample_rate
                    blocks.append((timestamp, rms))

                frames_recorded += frames_to_read
    except Exception as e:
        print(f"Error recording audio: {e}", file=sys.stderr)
        sys.exit(1)

    return device_name, blocks


def print_rms_blocks(device_name, blocks):
    """Print RMS levels for each block."""
    print(f"Device: {device_name}")
    print(f"Blocks: {len(blocks)}")

    for timestamp, rms in blocks:
        print(f"  {timestamp:.2f}s: {rms:.4f}")


def print_json_summary(device_name, blocks):
    """Print JSON summary of recording."""
    if not blocks:
        rms_max = 0.0
        rms_mean = 0.0
    else:
        rms_values = [rms for _, rms in blocks]
        rms_max = max(rms_values)
        rms_mean = sum(rms_values) / len(rms_values)

    summary = {
        "device": device_name,
        "blocks": len(blocks),
        "rms_max": rms_max,
        "rms_mean": rms_mean
    }

    print(json.dumps(summary))


def generate_test_tone(filename, frequency=440.0, duration=1.0, sample_rate=44100):
    """Generate a sine wave test tone WAV file."""
    frames = int(duration * sample_rate)

    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        for i in range(frames):
            t = i / sample_rate
            sample = int(32767 * 0.5 * math.sin(2 * math.pi * frequency * t))
            wav_file.writeframes(struct.pack('<h', sample))


def selftest():
    """
    Self-test: play a test tone and verify it's captured.

    Returns:
        bool: True if test passed (rms_max > 0.01), False otherwise
    """
    import winsound
    import struct

    print("Running audio self-test...")

    # Generate test tone
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        tone_file = f.name

    try:
        generate_test_tone(tone_file)
        print(f"Generated test tone: {tone_file}")

        # Play the tone and record simultaneously
        import threading
        import time

        result = {"rms_max": 0.0}

        def record_during_play():
            try:
                device_name, blocks = record_audio(seconds=1.5)
                if blocks:
                    rms_values = [rms for _, rms in blocks]
                    result["rms_max"] = max(rms_values)
            except Exception as e:
                print(f"Recording error: {e}", file=sys.stderr)

        # Start recording
        recorder_thread = threading.Thread(target=record_during_play)
        recorder_thread.start()

        # Play the tone after a brief delay to ensure recording has started
        time.sleep(0.2)
        winsound.PlaySound(tone_file, winsound.SND_FILENAME | winsound.SND_ASYNC)

        # Wait for recording to finish
        recorder_thread.join(timeout=3.0)

        print(f"Max RMS detected: {result['rms_max']:.4f}")

        if result["rms_max"] > 0.01:
            print("PASS: Test tone detected")
            return True
        else:
            print("FAIL: Test tone not detected (rms_max <= 0.01)")
            return False

    finally:
        # Clean up temp file
        try:
            import os
            os.unlink(tone_file)
        except:
            pass


def main():
    parser = argparse.ArgumentParser(description="Capture PC audio via WASAPI loopback")
    parser.add_argument("--seconds", type=float, default=3.0,
                        help="Recording duration in seconds (default: 3)")
    parser.add_argument("--json", action="store_true",
                        help="Output summary as JSON")
    parser.add_argument("--selftest", action="store_true",
                        help="Run self-test with test tone")

    args = parser.parse_args()

    if args.selftest:
        success = selftest()
        sys.exit(0 if success else 1)
    else:
        device_name, blocks = record_audio(seconds=args.seconds)

        if args.json:
            print_json_summary(device_name, blocks)
        else:
            print_rms_blocks(device_name, blocks)

        sys.exit(0)


if __name__ == "__main__":
    main()
