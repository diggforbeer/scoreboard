#!/usr/bin/env python3
"""Synthesize the default goal siren.

We can't ship any real team's broadcast horn (copyright), so the fallback
sound is generated, not sampled -- a rising-and-falling two-tone siren, the
kind of thing an arena PA system makes. Pure stdlib: wave + math, no audio
libraries, so this runs anywhere Python does.

    python scripts/generate-default-horn.py

Writes assets/horns/_default.wav and is committed to the repo (unlike team
logos or the HUB75 driver source, this is our own content, small enough
that a fetch step at build time would be pointless).
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "horns" / "_default.wav"
SAMPLE_RATE = 22050
DURATION_S = 2.2
LOW_HZ = 420
HIGH_HZ = 880
SWEEP_HZ = 0.9  # full low->high->low cycles per second
FADE_S = 0.08
AMPLITUDE = 0.7  # headroom below full scale so the fade never clips


def generate() -> bytes:
    n = int(SAMPLE_RATE * DURATION_S)
    fade_samples = int(SAMPLE_RATE * FADE_S)
    samples = bytearray()
    phase = 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        # Triangle-wave frequency sweep between LOW_HZ and HIGH_HZ.
        cycle = (t * SWEEP_HZ) % 1.0
        triangle = 1 - abs(2 * cycle - 1)  # 0 -> 1 -> 0
        freq = LOW_HZ + (HIGH_HZ - LOW_HZ) * triangle
        phase += 2 * math.pi * freq / SAMPLE_RATE
        value = math.sin(phase)

        envelope = 1.0
        if i < fade_samples:
            envelope = i / fade_samples
        elif i > n - fade_samples:
            envelope = (n - i) / fade_samples

        sample = int(AMPLITUDE * envelope * value * 32767)
        samples += struct.pack("<h", sample)
    return bytes(samples)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(generate())
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
