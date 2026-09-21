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
| Display | 2 × 64×32 P2 HUB75 panels, daisy-chained → **128×32** |
| Adapter | Adafruit RGB Matrix Bonnet or HAT |
| Power | 5 V supply rated for the panels (≈4 A for two P2 panels at full white) |

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

# Run the board in the emulator
nhl-scoreboard --backend RGBMatrixEmulator
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
hardware_mapping = "adafruit-hat"
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
