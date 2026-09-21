# Image build

Builds a flashable Raspberry Pi image using
[rpi-image-gen](https://github.com/raspberrypi/rpi-image-gen), Raspberry Pi's
Debian-based image builder.

## Layout

| Path | Purpose |
|------|---------|
| `config/scoreboard.yaml` | Image definition — device, partition sizes, which layers to apply |
| `layer/nhl-scoreboard.yaml` | Custom layer: installs the app, builds the HUB75 bindings, wires up services |
| `files/systemd/` | Service units and `systemd-networkd` DHCP configuration |
| `files/scripts/scoreboard-provision` | Applies boot-partition settings on every boot |
| `files/boot/scoreboard.toml` | The user-editable settings file, installed to `/boot/firmware/` |
| `files/vendor/` | Vendored `rpi-rgb-led-matrix` source (git-ignored, fetched on demand) |

## Building in CI

`.github/workflows/build-image.yml` builds on `ubuntu-24.04-arm`, which is
native arm64 and free for public repositories — no QEMU emulation. The
compressed `.img.xz` is uploaded as a workflow artifact, and attached to a
GitHub Release when a `v*` tag is pushed.

## Building locally

rpi-image-gen's supported host is Debian Bookworm/Trixie **arm64** — a Pi 4 or
later running 64-bit Raspberry Pi OS is ideal. It also cross-builds on an
amd64 Debian/Ubuntu machine with QEMU, which is unsupported but works.

```bash
# On amd64 only: foreign architecture support
sudo apt-get install -y --no-install-recommends \
    binfmt-support qemu-user-static debian-archive-keyring git

git clone https://github.com/raspberrypi/rpi-image-gen.git
cd rpi-image-gen && sudo ./install_deps.sh && cd ..

# Fetch the pinned HUB75 driver source
./scripts/fetch-vendor.sh

# Build
rpi-image-gen/rpi-image-gen build -S "$PWD/image" -c scoreboard.yaml
```

The image lands in `rpi-image-gen/work/nhl-scoreboard/nhl-scoreboard.img`.

## What the image contains

Debian Trixie arm64 (`trixie-minbase`) plus:

- The scoreboard app at `/opt/nhl-scoreboard`, run by `nhl-scoreboard.service`
- `rgbmatrix` Python bindings, compiled during the build
- `scoreboard-provision.service`, which reads `/boot/firmware/scoreboard.toml`
  on each boot and applies Wi-Fi, timezone and regulatory domain
- `systemd-networkd` DHCP for wired and wireless interfaces
- `dtparam=audio=off` in `config.txt` and `isolcpus=3` in `cmdline.txt`, both
  required for a stable, flicker-free panel refresh

## Notes and gotchas

- **Raspberry Pi Imager's "OS customisation" screen does not apply here.** That
  dialog only writes settings Raspberry Pi OS knows how to read. Configure the
  board through `scoreboard.toml` on the boot partition instead.
- The base image uses **iwd** for Wi-Fi, not NetworkManager or wpa_supplicant.
- `systemd-net-min` enables networkd but ships no `.network` files; ours supply
  the DHCP configuration, without which the board has no network at all.
- Default login is `scoreboard` / `hockey`. Change it before putting the board
  on an untrusted network.
