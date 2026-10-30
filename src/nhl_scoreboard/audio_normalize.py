"""Loudness-normalise an uploaded horn / wah-wah / ding (#322).

Uploads used to play at whatever level they were recorded at, and the global
volume can't fix a mismatch *between* files. So each upload is decoded to
16-bit PCM once, scaled to a common RMS level and stored as a mono WAV, which
plays with ``aplay`` alone (no ``mpg123`` for uploaded sounds).

All the maths is ``array``/``math`` -- the board has no numpy/sox/ffmpeg and
Python 3.13 dropped ``audioop``. MP3s are decoded by ``mpg123 -w`` into a temp
file; nothing client-supplied reaches a path or a command line.
"""

from __future__ import annotations

import array
import io
import math
import struct
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

#: Target loudness, RMS in dBFS. Measured on the shipped default horn
#: (assets/horns/_default.wav): RMS 15820 / 32768 = -6.3 dBFS, peak -3.1 dBFS.
#: The other shipped sounds sit lower (wah-wah 8415 = -11.8, ding 3874 =
#: -18.6) but are short stings; the horn is the loudest thing the board plays
#: and the one the owner balances against, so uploads land at its level.
TARGET_RMS_DBFS = -6.3
#: Gain is capped so the loudest sample stays under this (leaves headroom for
#: DAC/resampling overshoot). A peaky recording therefore ends up quieter than
#: the target rather than clipping.
PEAK_CEILING_DBFS = -1.0
#: Below this RMS a file is treated as silent: infinite gain would only
#: amplify noise, so it is stored as it is.
SILENCE_RMS_DBFS = -60.0
#: Longer clips are rejected, not trimmed: cutting a horn mid-sound is worse
#: than asking for a shorter file. The default horn is 2.2s.
MAX_SECONDS = 10.0
#: ``mpg123 -n``: decode at most this many frames (>= 24s of any MP3), so a
#: 2 MB upload can't balloon into a huge temp file before the length check.
MP3_MAX_FRAMES = 1000
MP3_DECODE_TIMEOUT = 20

_FULL_SCALE = 32768.0
_run = subprocess.run  # a seam for tests, like GoalHornPlayer._popen


@dataclass(frozen=True)
class Normalized:
    wav: bytes
    #: Applied gain in dB; ``None`` when the file was stored unchanged.
    gain_db: float | None
    #: A sentence fit to show the owner.
    note: str


def _db(ratio: float) -> float:
    return 20 * math.log10(ratio)


def decode_mp3(raw: bytes) -> bytes:
    """MP3 bytes -> WAV bytes via ``mpg123``. Raises ValueError (fit to show)."""
    with tempfile.TemporaryDirectory(prefix="horn-") as tmp:
        src, dst = Path(tmp) / "in.mp3", Path(tmp) / "out.wav"
        src.write_bytes(raw)
        cmd = ["mpg123", "-q", "-n", str(MP3_MAX_FRAMES), "-w", str(dst), str(src)]
        try:
            proc = _run(cmd, capture_output=True, timeout=MP3_DECODE_TIMEOUT, check=False)
        except FileNotFoundError:
            raise ValueError(
                "MP3 uploads need mpg123, which isn't installed on this board "
                "(sudo apt install mpg123), or upload a WAV instead"
            ) from None
        except subprocess.TimeoutExpired:
            raise ValueError("the MP3 took too long to decode") from None
        if proc.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
            raise ValueError("could not decode the MP3 file")
        return dst.read_bytes()


def _to_int16(frames: bytes, width: int) -> array.array:
    if width == 2:
        out = array.array("h")
        out.frombytes(frames[: len(frames) // 2 * 2])
        if sys.byteorder == "big":
            out.byteswap()
        return out
    if width == 1:  # unsigned 8-bit
        return array.array("h", [(b - 128) << 8 for b in frames])
    if width == 3:
        return array.array(
            "h",
            [
                int.from_bytes(frames[i : i + 3], "little", signed=True) >> 8
                for i in range(0, len(frames) - 2, 3)
            ],
        )
    if width == 4:
        count = len(frames) // 4
        return array.array("h", [v >> 16 for v in struct.unpack(f"<{count}i", frames[: count * 4])])
    raise ValueError("unsupported WAV sample size")


def _read_wav(data: bytes) -> tuple[array.array, int]:
    """Mono 16-bit samples and the sample rate. ValueError if unreadable."""
    try:
        with wave.open(io.BytesIO(data)) as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            if wav.getnframes() <= 0:
                raise ValueError("WAV file has no audio")
            if rate <= 0 or channels <= 0:
                raise ValueError("not a valid WAV or MP3 file")
            # Cap the read: a header can claim far more than the bytes hold.
            frames = wav.readframes(min(wav.getnframes(), int(MAX_SECONDS * rate) + rate))
    except (wave.Error, EOFError):
        raise ValueError("not a valid WAV or MP3 file") from None
    samples = _to_int16(frames, width)
    if channels > 1:
        usable = len(samples) // channels * channels
        lanes = [samples[i:usable:channels] for i in range(channels)]
        samples = array.array("h", [sum(t) // channels for t in zip(*lanes, strict=True)])
    if not samples:
        raise ValueError("WAV file has no audio")
    return samples, rate


def _wav_bytes(samples: array.array, rate: int) -> bytes:
    buf = io.BytesIO()
    data = array.array("h", samples)
    if sys.byteorder == "big":
        data.byteswap()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(data.tobytes())
    return buf.getvalue()


def normalize(raw: bytes, is_mp3: bool) -> Normalized:
    """Decode, measure and rescale an upload. Raises ValueError (fit to show)."""
    wav_in = decode_mp3(raw) if is_mp3 else raw
    samples, rate = _read_wav(wav_in)
    seconds = len(samples) / rate
    if seconds > MAX_SECONDS:
        raise ValueError(f"the clip is too long ({seconds:.0f}s, max {MAX_SECONDS:.0f}s)")

    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    peak = max(max(samples), -min(samples))
    if rms / _FULL_SCALE < 10 ** (SILENCE_RMS_DBFS / 20):
        # Keep a WAV exactly as sent; an MP3 still has to be stored as WAV.
        wav = _wav_bytes(samples, rate) if is_mp3 else raw
        return Normalized(wav, None, "stored unchanged: the file is silent or nearly silent")

    want = 10 ** (TARGET_RMS_DBFS / 20) * _FULL_SCALE / rms
    ceiling = 10 ** (PEAK_CEILING_DBFS / 20) * _FULL_SCALE / peak
    gain = min(want, ceiling)
    scaled = array.array("h", [max(-32768, min(32767, round(s * gain))) for s in samples])
    gain_db = round(_db(gain), 1)
    note = f"normalized, {gain_db:+.1f} dB"
    if ceiling < want:
        note += " (limited by peak level, so it stays a little quieter than the target)"
    return Normalized(_wav_bytes(scaled, rate), gain_db, note)
