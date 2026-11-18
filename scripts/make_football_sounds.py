#!/usr/bin/env python3
"""Synthesize the default football sounds: a touchdown fanfare and a field-goal sting (#517).

Brass-ish tones (a fundamental plus a few harmonics, a short attack, an exponential decay), no
third-party audio. Same format as the shipped horn (mono, 16-bit, 22050 Hz), deterministic.

    python scripts/make_football_sounds.py

Writes assets/horns/_football_td.wav and assets/horns/_football_fg.wav.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "assets" / "horns"
SAMPLE_RATE = 22050
AMPLITUDE = 0.7
ATTACK_S = 0.015
RELEASE_S = 0.08

#: (harmonic number, relative level): a rough trumpet spectrum.
HARMONICS: tuple[tuple[int, float], ...] = ((1, 1.0), (2, 0.6), (3, 0.45), (4, 0.25), (5, 0.12))

#: Each sound is a list of (frequency Hz, start s, length s). A touchdown is a rising
#: C-E-G arpeggio into a held high C; a field goal is a quicker two-note "ta-da".
TOUCHDOWN: tuple[tuple[float, float, float], ...] = (
    (523.25, 0.00, 0.20),  # C5
    (659.25, 0.20, 0.20),  # E5
    (783.99, 0.40, 0.20),  # G5
    (1046.50, 0.60, 1.20),  # C6, held
)
FIELD_GOAL: tuple[tuple[float, float, float], ...] = (
    (783.99, 0.00, 0.18),  # G5
    (1046.50, 0.18, 0.62),  # C6
)

SOUNDS = {"_football_td.wav": TOUCHDOWN, "_football_fg.wav": FIELD_GOAL}


def generate(notes: tuple[tuple[float, float, float], ...]) -> bytes:
    total = max(start + length for _, start, length in notes)
    n = int(SAMPLE_RATE * total)
    samples = [0.0] * n
    for freq, start, length in notes:
        first = int(SAMPLE_RATE * start)
        count = int(SAMPLE_RATE * length)
        attack = int(SAMPLE_RATE * ATTACK_S)
        release = int(SAMPLE_RATE * RELEASE_S)
        for i in range(count):
            t = i / SAMPLE_RATE
            value = sum(
                level * math.sin(2 * math.pi * freq * harmonic * t) for harmonic, level in HARMONICS
            )
            value *= math.exp(-t / (length * 1.5))
            if i < attack:
                value *= i / attack
            elif i >= count - release:
                value *= (count - i) / release
            if first + i < n:
                samples[first + i] += value
    peak = max(abs(s) for s in samples) or 1.0
    scale = AMPLITUDE * 32767 / peak
    return b"".join(struct.pack("<h", int(s * scale)) for s in samples)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, notes in SOUNDS.items():
        path = OUT_DIR / name
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(generate(notes))
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
