"""scripts/generate-default-horn.py: generate() pinned against the committed
assets/horns/_default.wav, so that asset silently drifting from its
generator would fail CI instead of going unnoticed."""

from __future__ import annotations

import importlib.util
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "generate-default-horn.py"
COMMITTED_WAV = REPO_ROOT / "assets" / "horns" / "_default.wav"


def load_module():
    spec = importlib.util.spec_from_file_location("generate_default_horn", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


horn = load_module()


def test_generate_is_deterministic():
    assert horn.generate() == horn.generate()


def test_generate_reproduces_the_committed_wav_frames_exactly():
    with wave.open(str(COMMITTED_WAV), "rb") as wav:
        committed_frames = wav.readframes(wav.getnframes())
    assert horn.generate() == committed_frames


def test_committed_wav_params_are_mono_16bit_22050hz():
    with wave.open(str(COMMITTED_WAV), "rb") as wav:
        params = wav.getparams()
    assert params.nchannels == 1
    assert params.sampwidth == 2
    assert params.framerate == horn.SAMPLE_RATE == 22050
