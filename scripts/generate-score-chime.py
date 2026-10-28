#!/usr/bin/env python3
"""Synthesize the score-change ding.

A soft two-note notification chime (a major third up, bell-like decay), the
kind of "ding" an app makes for a score alert -- played when a followed team
other than the favourite scores (#308). Generated, not sampled, for the same
reason as the horn. Pure stdlib.

    python scripts/generate-score-chime.py

Writes assets/horns/_chime.wav, committed to the repo.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "horns" / "_chime.wav"
SAMPLE_RATE = 22050
NOTES = ((880.0, 0.0), (1108.7, 0.16))  # A5, then C#6 a beat later
DURATION_S = 1.0
DECAY_S = 0.22  # exponential decay constant per note
ATTACK_S = 0.004  # short ramp so the start doesn't click
AMPLITUDE = 0.55


def generate() -> bytes:
    n = int(SAMPLE_RATE * DURATION_S)
    samples = bytearray()
    for i in range(n):
        t = i / SAMPLE_RATE
        value = 0.0
        for freq, start in NOTES:
            age = t - start
            if age < 0:
                continue
            envelope = min(1.0, age / ATTACK_S) * math.exp(-age / DECAY_S)
            # Fundamental plus a quiet octave partial for the bell colour.
            tone = math.sin(2 * math.pi * freq * age) + 0.3 * math.sin(4 * math.pi * freq * age)
            value += envelope * tone
        fade = min(1.0, (n - i) / (SAMPLE_RATE * 0.05))
        samples += struct.pack("<h", int(AMPLITUDE * fade * value / 1.6 * 32767))
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
