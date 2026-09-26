"""The HUB75 driver needs the onboard audio path fully disabled (see
CLAUDE.md's hardware facts), verified live on real hardware: a board that
booted fine but never displayed anything, because dtparam=audio=off alone
was not enough (#see PR that added this test).

Two things this test pins down so a future edit can't silently regress them:

1. image/layer/nhl-scoreboard.yaml must strip the base image's own
   'dtparam=audio=on' line, not just append an 'off' override after it --
   leaving both in config.txt caused the firmware to emit conflicting
   snd_bcm2835.enable_headphones=/enable_hdmi= pairs on the kernel cmdline,
   independently defaulting each flag to its own last-seen value rather than
   collapsing cleanly to 'off'.
2. It must also blacklist the snd_bcm2835 kernel module outright --
   rpi-rgb-led-matrix's own startup check is "is the module loaded", not
   whether its outputs are enabled, so a clean enable_headphones=0/
   enable_hdmi=0 cmdline was verified to still leave the module loaded and
   the driver refusing to start.

Deliberately regex-based against the raw file, matching this repo's existing
convention (tests/test_image_deps.py) for reading the hand-written shell
inside this YAML rather than parsing it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_LAYER = REPO_ROOT / "image" / "layer" / "nhl-scoreboard.yaml"


def _layer_text() -> str:
    return IMAGE_LAYER.read_text()


def test_strips_the_base_images_audio_on_line():
    text = _layer_text()
    assert "sed -i '/^dtparam=audio=on$/d'" in text, (
        "the firmware-configuration hook must strip the base image's own "
        "'dtparam=audio=on' line, not just append 'dtparam=audio=off' after "
        "it -- leaving both present produced conflicting "
        "snd_bcm2835.enable_headphones=/enable_hdmi= cmdline flags on real "
        "hardware, with the onboard audio path still effectively enabled"
    )


def test_blacklists_the_onboard_audio_module():
    text = _layer_text()
    assert "/etc/modprobe.d" in text
    assert "blacklist snd_bcm2835" in text, (
        "dtparam=audio=off alone does not stop the snd_bcm2835 kernel module "
        "from loading -- verified live, the module was still present in "
        "lsmod with a clean cmdline. rpi-rgb-led-matrix refuses to start "
        "whenever the module is loaded at all, so it must be blacklisted, "
        "not just have its outputs disabled"
    )
