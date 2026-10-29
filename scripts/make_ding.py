#!/usr/bin/env python3
"""Synthesize the "ding" played when a followed (non-favourite) team scores.

A struck-bell tone: a sine fundamental plus inharmonic partials (the ratios of
a small bell), each with a fast attack and its own exponential decay, higher
partials dying sooner. Pure stdlib (wave + math), deterministic, same format
as the shipped goal horn (mono, 16-bit, 22050 Hz) so aplay needs nothing
special.

    python scripts/make_ding.py

Writes assets/horns/_ding.wav, committed alongside this script.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "horns" / "_ding.wav"
SAMPLE_RATE = 22050
AMPLITUDE = 0.6  # headroom below full scale so the sum never clips
SECONDS = 0.9
ATTACK_S = 0.004
RELEASE_S = 0.05
FUNDAMENTAL_HZ = 988.0  # B5

#: (frequency ratio, relative level, decay time constant in seconds)
PARTIALS: tuple[tuple[float, float, float], ...] = (
    (1.0, 1.0, 0.30),
    (2.76, 0.45, 0.16),
    (5.40, 0.22, 0.08),
)


def generate() -> bytes:
    n = int(SAMPLE_RATE * SECONDS)
    attack = int(SAMPLE_RATE * ATTACK_S)
    release = int(SAMPLE_RATE * RELEASE_S)
    samples: list[float] = []
    for i in range(n):
        t = i / SAMPLE_RATE
        value = sum(
            level * math.exp(-t / tau) * math.sin(2 * math.pi * FUNDAMENTAL_HZ * ratio * t)
            for ratio, level, tau in PARTIALS
        )
        if i < attack:
            value *= i / attack
        elif i >= n - release:
            value *= (n - i) / release
        samples.append(value)
    peak = max(abs(s) for s in samples) or 1.0
    scale = AMPLITUDE * 32767 / peak
    return b"".join(struct.pack("<h", int(s * scale)) for s in samples)


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
