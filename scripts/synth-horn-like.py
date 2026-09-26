#!/usr/bin/env python3
"""Synthesize a horn "in the style of" a reference clip you supply.

This does NOT sample, copy, or redistribute the reference audio. It only
analyzes it -- dominant chord frequencies via FFT, rough attack/sustain/
release timing -- and generates brand-new audio from oscillators tuned to
what it found. The output is original synthesized content, the same
"generated, not sampled" approach as generate-default-horn.py, just with
its tone parameters pulled from a reference instead of hand-picked.

The reference file is your own personal-use copy of whatever you want the
result to sound similar to -- this script never fetches anything, and it
never reads the reference for anything beyond these few scalar numbers.
Nothing from the reference audio itself ends up in the output waveform.

Needs ffmpeg on PATH (decodes whatever format you hand it) and numpy
(FFT). Both are dev-machine-only -- this script never runs in CI or the
image build, unlike fetch-logos.py.

    python scripts/synth-horn-like.py --reference ~/Downloads/x.mp3 --team NSH
    python scripts/synth-horn-like.py --reference-dir ~/Downloads/horns --batch

Batch mode expects files named {ABBR}.<ext> in --reference-dir and writes
one output per file found.

Writes assets/horns/{ABBR}.wav -- gitignored like every other team horn
(see .gitignore), never committed by this script or anything else.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "assets" / "horns"
SAMPLE_RATE = 22050
MAX_DURATION_S = 4.0
SILENCE_RMS_FRACTION = 0.05  # trim points: below this fraction of peak RMS


def decode_to_mono_pcm(reference: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """ffmpeg decodes any input format to mono float samples in [-1, 1]."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_wav = Path(tmp) / "ref.wav"
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(reference),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-sample_fmt",
                "s16",
                str(tmp_wav),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed on {reference}: {result.stderr.strip()}")
        with wave.open(str(tmp_wav), "rb") as wav:
            raw = wav.readframes(wav.getnframes())
    ints = np.frombuffer(raw, dtype="<i2")
    return ints.astype(np.float64) / 32768.0


def short_time_rms(samples: np.ndarray, sr: int, window_s: float = 0.02) -> tuple[np.ndarray, int]:
    win = max(1, int(sr * window_s))
    n_windows = max(1, len(samples) // win)
    trimmed = samples[: n_windows * win].reshape(n_windows, win)
    rms = np.sqrt(np.mean(trimmed**2, axis=1))
    return rms, win


def trim_silence(samples: np.ndarray, sr: int) -> tuple[int, int]:
    """Sample indices (start, end) bounding the audible part of the clip."""
    rms, win = short_time_rms(samples, sr)
    peak = rms.max() if len(rms) else 0.0
    if peak <= 0:
        return 0, len(samples)
    audible = np.where(rms >= peak * SILENCE_RMS_FRACTION)[0]
    if len(audible) == 0:
        return 0, len(samples)
    start = audible[0] * win
    end = min(len(samples), (audible[-1] + 1) * win)
    return int(start), int(end)


def find_dominant_frequencies(
    samples: np.ndarray, sr: int, n_tones: int, fmin: float, fmax: float
) -> list[float]:
    """Top spectral peaks in [fmin, fmax], read off the clip's sustained middle.

    Skips the first/last 15% of the trimmed clip -- attack transients and
    tails carry more noise/percussive energy than the horn's actual chord.
    """
    if len(samples) == 0:
        return [440.0]
    skip = int(len(samples) * 0.15)
    core = samples[skip : len(samples) - skip] if len(samples) > 2 * skip else samples
    if len(core) < 256:
        core = samples
    windowed = core * np.hanning(len(core))
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(core), d=1.0 / sr)

    band = (freqs >= fmin) & (freqs <= fmax)
    band_freqs = freqs[band]
    band_mag = spectrum[band]
    if len(band_mag) < 3:
        return [(fmin + fmax) / 2]

    # Local maxima only, so we don't pick several adjacent bins off one peak.
    is_peak = (band_mag[1:-1] > band_mag[:-2]) & (band_mag[1:-1] > band_mag[2:])
    peak_idx = np.where(is_peak)[0] + 1
    if len(peak_idx) == 0:
        peak_idx = np.array([int(np.argmax(band_mag))])

    order = peak_idx[np.argsort(band_mag[peak_idx])[::-1]]
    chosen: list[float] = []
    for idx in order:
        f = float(band_freqs[idx])
        if all(abs(f - c) > 25 for c in chosen):  # merge near-duplicate peaks
            chosen.append(f)
        if len(chosen) == n_tones:
            break
    return sorted(chosen) if chosen else [(fmin + fmax) / 2]


def estimate_envelope(samples: np.ndarray, sr: int) -> dict[str, float]:
    start, end = trim_silence(samples, sr)
    trimmed = samples[start:end]
    duration_s = min(len(trimmed) / sr, MAX_DURATION_S)
    if len(trimmed) == 0:
        return {"attack_s": 0.05, "sustain_s": 1.0, "release_s": 0.2}

    rms, win = short_time_rms(trimmed, sr)
    peak = rms.max() if len(rms) else 0.0
    if peak <= 0:
        return {"attack_s": 0.05, "sustain_s": max(duration_s - 0.25, 0.1), "release_s": 0.2}

    above = np.where(rms >= peak * 0.7)[0]
    attack_s = float(above[0] * win / sr) if len(above) else 0.05
    release_start_s = float(above[-1] * win / sr) if len(above) else duration_s * 0.8
    release_s = max(duration_s - release_start_s, 0.1)
    attack_s = max(min(attack_s, duration_s * 0.3), 0.02)
    sustain_s = max(duration_s - attack_s - release_s, 0.1)
    return {"attack_s": attack_s, "sustain_s": sustain_s, "release_s": release_s}


def synthesize(
    frequencies: list[float], envelope: dict[str, float], sr: int = SAMPLE_RATE
) -> bytes:
    """Sum-of-oscillators chord, soft-clipped for a brassier timbre, ADSR-shaped."""
    attack_s, sustain_s, release_s = (
        envelope["attack_s"],
        envelope["sustain_s"],
        envelope["release_s"],
    )
    total_s = attack_s + sustain_s + release_s
    n = int(sr * total_s)
    t = np.arange(n) / sr

    mix = np.zeros(n)
    for f in frequencies:
        # A touch of detune per tone gives a chorus-like beat, closer to a
        # real multi-chime horn than perfectly locked sine waves.
        detune = 1.0 + (0.002 * (frequencies.index(f) - len(frequencies) / 2))
        mix += np.sin(2 * np.pi * f * detune * t)
    mix /= len(frequencies)
    mix = np.tanh(mix * 1.8)  # soft clip: rounds sines toward a brassier waveform

    attack_n = int(sr * attack_s)
    release_n = int(sr * release_s)
    env = np.ones(n)
    env[:attack_n] = np.linspace(0, 1, attack_n, endpoint=False) if attack_n else 1.0
    if release_n:
        env[-release_n:] = np.linspace(1, 0, release_n, endpoint=True)

    out = np.clip(mix * env * 0.85, -1.0, 1.0)
    ints = (out * 32767).astype("<i2")
    return struct.pack(f"<{len(ints)}h", *ints)


def build_one(reference: Path, team: str, n_tones: int, fmin: float, fmax: float) -> Path:
    samples = decode_to_mono_pcm(reference)
    start, end = trim_silence(samples, SAMPLE_RATE)
    frequencies = find_dominant_frequencies(samples[start:end], SAMPLE_RATE, n_tones, fmin, fmax)
    envelope = estimate_envelope(samples, SAMPLE_RATE)

    out_path = OUT_DIR / f"{team.strip().upper()}.wav"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(synthesize(frequencies, envelope))

    print(
        f"{team.upper()}: tones={[round(f) for f in frequencies]}Hz "
        f"attack={envelope['attack_s']:.2f}s sustain={envelope['sustain_s']:.2f}s "
        f"release={envelope['release_s']:.2f}s -> {out_path}"
    )
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reference", type=Path, help="single reference audio file")
    parser.add_argument("--team", help="team abbreviation for --reference mode, e.g. NSH")
    parser.add_argument(
        "--reference-dir", type=Path, help="directory of {ABBR}.<ext> reference files"
    )
    parser.add_argument(
        "--batch", action="store_true", help="process every file in --reference-dir"
    )
    parser.add_argument("--tones", type=int, default=4, help="chord size (default: 4)")
    parser.add_argument("--fmin", type=float, default=150.0, help="lowest tone considered, Hz")
    parser.add_argument("--fmax", type=float, default=1200.0, help="highest tone considered, Hz")
    args = parser.parse_args()

    if args.batch:
        if not args.reference_dir:
            parser.error("--batch needs --reference-dir")
        files = sorted(p for p in args.reference_dir.iterdir() if p.is_file())
        if not files:
            print(f"No files found in {args.reference_dir}", file=sys.stderr)
            return 1
        for f in files:
            build_one(f, f.stem, args.tones, args.fmin, args.fmax)
        return 0

    if not args.reference or not args.team:
        parser.error("need --reference and --team (or --reference-dir --batch)")
    build_one(args.reference, args.team, args.tones, args.fmin, args.fmax)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
