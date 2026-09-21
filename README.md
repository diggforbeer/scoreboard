# scoreboard

An NHL scoreboard for a HUB75 LED matrix, delivered as a ready-to-flash
Raspberry Pi image.

Flash the image with the official [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
("Use custom"), drop your Wi-Fi details and favourite team into a text file on
the boot partition, and the board comes up showing live scores.

## Hardware

| Part | Target |
|------|--------|
| Computer | Raspberry Pi 4 (Pi 3B+ also supported) |
| Display | 2 × 64×32 **P2.5** HUB75 panels, daisy-chained → **128×32** (320 × 80 mm) |
| Adapter | Seengreat-style RGB Matrix Adapter Board (also sold as XICOOLEE, WatangTech) |
| Power | One 5 V supply into the adapter's DC barrel jack; it feeds the panels and back-powers the Pi |

The adapter board's pinout is the driver's `regular` mapping, with output-enable
on GPIO 18. That is the hardware-PWM pin, so you get flicker-free refresh with
no modification — the Adafruit Bonnet needs a solder bridge for the same result.
An Adafruit board still works: set `hardware_mapping = "adafruit-hat"`.

**Power notes.** The board accepts USB-C (5 V / 4 A) or a 5.5 × 2.1 mm barrel
jack (5 V / 8 A) and passes 5 V to the Pi through the GPIO header. Two 64×32
panels can each draw ~2 A at full white, plus ~1 A for the Pi, so use the barrel
jack with a supply rated 6 A or better. At the default `brightness = 60` and
mostly-dark scoreboard content the real draw is far lower, but headroom is what
keeps the supply from browning out on a bright frame. **Do not also connect a
USB-C supply to the Pi** — two supplies feeding the same 5 V rail is a good way
to damage one of them.

Panel geometry is configuration-driven, so a single 64×32 or a 128×64 stack
works too — see `[panel]` in the config file.

## Status

Early development. Working today:

- [x] NHL API client against `api-web.nhle.com` (live scores, period, clock)
- [x] 128×32 renderer with per-team accent colours
- [x] Hardware / emulator / headless display backends
- [x] rpi-image-gen image definition ([image/](image/))
- [x] CI pipelines — lint/test, plus an image build on native arm64 runners
- [x] Wi-Fi and settings applied from the boot partition on every boot
- [ ] Verified on real hardware
- [ ] Team logos

## Development

No LED panel required — the app falls back to
[RGBMatrixEmulator](https://github.com/ty-porter/RGBMatrixEmulator), which
renders to a browser window.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Print today's scores; needs no display at all
nhl-scoreboard --dump

# Run the board in the emulator, then open http://localhost:8888
cp image/files/boot/scoreboard.toml scoreboard.local.toml   # edit favourite_team etc.
nhl-scoreboard --backend RGBMatrixEmulator -c scoreboard.local.toml

# Print frames as ASCII art - fastest way to iterate on layout
python scripts/preview.py --team TOR
python scripts/preview.py --fixture      # offline, uses the test fixture

# Rendering tests: every scene is snapshot-compared against tests/snapshots/
pytest -s tests/test_render.py           # -s prints each frame
pytest --update-snapshots                # after an intentional layout change
```

## Configuration

The running image reads `/boot/firmware/scoreboard.toml`. Because the boot
partition is FAT32, you can edit it from any computer after flashing the card.

```toml
[scoreboard]
favourite_team = "TOR"      # pinned to the front of the rotation
timezone = "America/Toronto"
rotate_seconds = 8
poll_seconds = 60
live_poll_seconds = 15

[panel]
rows = 32
cols = 64
chain_length = 2            # two panels daisy-chained = 128x32
pitch_mm = 2.5              # informational; 128x32 at P2.5 is 320x80 mm
hardware_mapping = "regular"  # "adafruit-hat" for an Adafruit Bonnet/HAT
gpio_slowdown = 4           # 4 suits a Pi 4; try 2 on a Pi 3
brightness = 60
```

## Layout

```
┌──────────────────────────────────────┐
│  TOR      3   │   MTL             2  │
│──────────────────────────────────────│
│              2ND 12:34               │
└──────────────────────────────────────┘
```

## Licence

MIT — see [LICENSE](LICENSE). Bundled BDF fonts come from
[rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) and derive
from the public-domain X11 "misc-fixed" fonts; see [fonts/README.md](fonts/README.md).

Not affiliated with or endorsed by the National Hockey League.
