#!/usr/bin/env python3
"""Synthesize the "wah wah" sad-trombone sting played when the opponent scores.

Sampled sad-trombone clips are widely copied and their licensing is murky, so
this one is generated: three short descending notes, then a longer fourth that
slides down under a slow vibrato ("wah, wah, wah, waaah"). Each note is a
sawtooth through a one-pole low-pass whose cutoff sweeps open and closed -- the
muted-trumpet "wah". Pure stdlib (wave + math), deterministic, same format as
the shipped goal horn (mono, 16-bit, 22050 Hz) so aplay needs nothing special.

    python scripts/make_wah_wah.py

Writes assets/horns/_wah_wah.wav, committed alongside this script.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "horns" / "_wah_wah.wav"
SAMPLE_RATE = 22050
AMPLITUDE = 0.6  # headroom below full scale so the envelope never clips
ATTACK_S = 0.02
RELEASE_S = 0.05
GAP_S = 0.06

#: (start Hz, end Hz, seconds, vibrato depth in Hz). Three short steps down a
#: minor-ish ladder, then the long slide.
NOTES: tuple[tuple[float, float, float, float], ...] = (
    (311.0, 303.0, 0.38, 0.0),
    (293.0, 285.0, 0.38, 0.0),
    (277.0, 269.0, 0.38, 0.0),
    (261.0, 196.0, 1.05, 5.0),
)
VIBRATO_HZ = 5.5
WAH_HZ = 3.0  # filter sweeps per second within a note
CUTOFF_LOW = 500.0
CUTOFF_HIGH = 2400.0


def _note(start: float, end: float, seconds: float, vibrato: float) -> list[float]:
    n = int(SAMPLE_RATE * seconds)
    attack = int(SAMPLE_RATE * ATTACK_S)
    release = int(SAMPLE_RATE * RELEASE_S)
    out: list[float] = []
    phase = 0.0
    low = 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = start + (end - start) * (i / n)
        if vibrato:
            # Vibrato fades in so the slide starts clean and wobbles later.
            freq += vibrato * min(1.0, t / 0.3) * math.sin(2 * math.pi * VIBRATO_HZ * t)
        phase = (phase + freq / SAMPLE_RATE) % 1.0
        saw = 2.0 * phase - 1.0
        # Open the filter on the "wa", close it on the "ah".
        sweep = 0.5 - 0.5 * math.cos(2 * math.pi * WAH_HZ * t / (seconds / 0.38 if vibrato else 1))
        cutoff = CUTOFF_LOW + (CUTOFF_HIGH - CUTOFF_LOW) * sweep
        alpha = 1 - math.exp(-2 * math.pi * cutoff / SAMPLE_RATE)
        low += alpha * (saw - low)
        env = 1.0
        if i < attack:
            env = i / attack
        elif i >= n - release:
            env = (n - i) / release
        # A late decay on the last note gives the trailing "waaah" its fall-off.
        if vibrato:
            env *= 1.0 - 0.5 * (i / n)
        out.append(low * env)
    return out


def generate() -> bytes:
    samples: list[float] = []
    for start, end, seconds, vibrato in NOTES:
        samples += _note(start, end, seconds, vibrato)
        samples += [0.0] * int(SAMPLE_RATE * GAP_S)
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
