#!/usr/bin/env python3
"""Synthesize the default football scoring sounds: a touchdown fanfare and a field-goal sting.

Brass-like notes (a fundamental plus a few harmonics, a short attack, a slow release) played
as a rising triad for the touchdown and a two-note lift for the field goal. Pure stdlib
(wave + math), deterministic, same format as the shipped goal horn (mono, 16-bit, 22050 Hz).

    python scripts/make_football_sounds.py

Writes assets/horns/football/_td.wav and _fg.wav, committed alongside this script. A team's own
file (``football/NE_td.wav``) or an upload always wins over these.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "assets" / "horns" / "football"
SAMPLE_RATE = 22050
AMPLITUDE = 0.6  # headroom below full scale so the sum never clips
ATTACK_S = 0.015
RELEASE_S = 0.12
#: Relative levels of the harmonics (1x, 2x, 3x, 4x): enough edge to read as a horn.
HARMONICS: tuple[float, ...] = (1.0, 0.55, 0.35, 0.18)

#: Note frequencies in Hz.
C5, E5, G5, C6 = 523.25, 659.25, 783.99, 1046.50

#: (frequency, start seconds, length seconds)
TOUCHDOWN: tuple[tuple[float, float, float], ...] = (
    (C5, 0.00, 0.20),
    (E5, 0.20, 0.20),
    (G5, 0.40, 0.20),
    (C6, 0.60, 0.90),
)
FIELD_GOAL: tuple[tuple[float, float, float], ...] = (
    (G5, 0.00, 0.22),
    (C6, 0.22, 0.60),
)


def _note(freq: float, length: float) -> list[float]:
    n = int(SAMPLE_RATE * length)
    attack = int(SAMPLE_RATE * ATTACK_S)
    release = min(int(SAMPLE_RATE * RELEASE_S), n)
    out: list[float] = []
    for i in range(n):
        t = i / SAMPLE_RATE
        value = sum(
            level * math.sin(2 * math.pi * freq * (k + 1) * t) for k, level in enumerate(HARMONICS)
        )
        if i < attack:
            value *= i / attack
        if i >= n - release:
            value *= (n - i) / release
        out.append(value)
    return out


def generate(notes: tuple[tuple[float, float, float], ...]) -> bytes:
    total = int(SAMPLE_RATE * max(start + length for _, start, length in notes))
    samples = [0.0] * total
    for freq, start, length in notes:
        offset = int(SAMPLE_RATE * start)
        for i, value in enumerate(_note(freq, length)):
            samples[offset + i] += value
    peak = max(abs(s) for s in samples) or 1.0
    scale = AMPLITUDE * 32767 / peak
    return b"".join(struct.pack("<h", int(s * scale)) for s in samples)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, notes in (("_td.wav", TOUCHDOWN), ("_fg.wav", FIELD_GOAL)):
        out = OUT_DIR / name
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(generate(notes))
        print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
