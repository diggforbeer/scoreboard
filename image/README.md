# Image build

Builds a flashable Raspberry Pi image using
[rpi-image-gen](https://github.com/raspberrypi/rpi-image-gen), Raspberry Pi's
Debian-based image builder.

## Layout

| Path | Purpose |
|------|---------|
| `config/scoreboard.yaml` | Image definition — device, partition sizes, which layers to apply |
| `layer/nhl-scoreboard.yaml` | Custom layer: installs the app, builds the HUB75 bindings, wires up services |
| `files/systemd/` | Service units for the scoreboard and its provisioner |
| `files/scripts/scoreboard-provision` | Applies boot-partition settings on every boot |
| `files/scripts/nhl-scoreboard-grow-rootfs` | Grows the root filesystem to fill the SD card on first boot |
| `files/boot/scoreboard.toml` | The user-editable settings file, installed to `/boot/firmware/` |
| `files/vendor/` | Vendored `rpi-rgb-led-matrix` source (git-ignored, fetched on demand) |
| `../assets/logos/` | Team logos rasterised by `scripts/fetch-logos.py` (git-ignored, fetched on demand) |
| `../assets/logos/overrides/` | Hand-picked replacements for crests that don't downscale legibly (#12) — committed, checked before the fetched ones |
| `../assets/horns/` | The default goal siren, synthesized by `scripts/generate-default-horn.py` and committed (no third-party content, so nothing to fetch) |

## Building in CI

`.github/workflows/build-image.yml` builds on `ubuntu-24.04-arm`, which is
native arm64 and free for public repositories — no QEMU emulation. The
compressed `.img.xz` is uploaded as a workflow artifact, and attached to a
GitHub Release when a `v*` tag is pushed.

**A pull request that touches `image/`, `src/`, `fonts/`, `assets/`,
`scripts/fetch-vendor.sh` or this workflow file must build successfully
before it can merge** — `nhl-scoreboard.img` is a required status check
on `main`. A PR that doesn't touch those paths skips the build entirely
(fast, reports as passing) rather than paying for an irrelevant build.
Compression and the
artifact upload are also skipped on a PR run — the point there is only to
prove the build succeeds, not to produce a downloadable image — so a
relevant PR's build finishes in ~3 minutes rather than the full ~12 a
release build (which does compress and upload) takes. This whole gate
exists because #21 once merged clean — every *required* check passed —
and broke the real image build anyway: `Build image` only ran *after*
merge back then, so nothing had actually gated it. See `CLAUDE.md`'s
"Image build facts" for the incident.

## Releases

`.github/workflows/release.yml` tags and creates a GitHub Release for
**every merge to `main`**, automatically — no manual tagging step.
Versioning is CalVer: `v2026.09.22`, with a `.1`/`.2`/… suffix for a
second release the same day. `pyproject.toml`'s own `version` is a
separate, static package version, deliberately *not* kept in sync — see
the comment at the top of `release.yml` for why (short version: it would
need a commit to the protected `main` branch, which tags don't).

Pushing that tag itself won't trigger `build-image.yml`'s `tags: ["v*"]`
push trigger — GitHub doesn't cascade workflow runs from events the
built-in `GITHUB_TOKEN` caused, to prevent recursive triggering — so
`release.yml` explicitly calls `build-image.yml` via `workflow_dispatch`
(the documented exception that always fires) once the tag and release
exist, which is what actually attaches the compressed image to the new
release. A human pushing a `v*` tag by hand still fires the normal push
trigger, kept as a fallback.

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

# Fetch the pinned HUB75 driver source, and rasterise the team logos
./scripts/fetch-vendor.sh
python3 scripts/fetch-logos.py        # needs libcairo2, cairosvg, pillow

# Build
rpi-image-gen/rpi-image-gen build -S "$PWD/image" -c scoreboard.yaml
```

The image lands in `rpi-image-gen/work/nhl-scoreboard/nhl-scoreboard.img`.

## What the image contains

Debian Trixie arm64 (`trixie-minbase`) plus:

- The scoreboard app at `/opt/nhl-scoreboard`, run by `nhl-scoreboard.service`
- Team logos at `/usr/share/nhl-scoreboard/logos/32/{dark,light}/`
- The default goal siren at `/usr/share/nhl-scoreboard/horns/_default.wav`,
  and `alsa-utils` for `aplay`
- `rgbmatrix` Python bindings, compiled during the build, then the compiler
  toolchain that built them (`build-essential`, `cmake`, `ninja-build`,
  `cython3`, `python3-dev`, `python3-pip`) purged in the same layer -- the
  running image never needs a compiler, only the `.so` it already built
- `scoreboard-provision.service`, which reads `/boot/firmware/scoreboard.toml`
  on each boot and applies Wi-Fi, timezone and regulatory domain
- `dtparam=audio=off` in `config.txt` and `isolcpus=3` in `cmdline.txt`, both
  required for a stable, flicker-free panel refresh
- `nhl-scoreboard-grow-rootfs.service`, which grows the root filesystem to
  fill the SD card on first boot (see below)

## Notes and gotchas

- **Raspberry Pi Imager's "OS customisation" screen does not apply here.** That
  dialog only writes settings Raspberry Pi OS knows how to read. Configure the
  board through `scoreboard.toml` on the boot partition instead.
- The base image uses **iwd** for Wi-Fi, not NetworkManager or wpa_supplicant.
- DHCP is already handled: the base layers generate `01-eth0.network` and
  `02-wlan0.network`. Adding higher-numbered files of our own would be inert,
  since networkd applies only the first matching `.network`.
- The HUB75 bindings need `python3-pil` at build time: their Pillow shim
  includes `Imaging.h`, which Pillow's wheels do not ship but Debian's
  `python3-pil` installs into `/usr/include/python3.x/`.
- The bindings are built through upstream's CMake/scikit-build-core path
  from the repository root. The older `lib/Makefile` route defaults
  `CPU_ARCH_FLAGS` to `-march=native`, which on a CI runner targets the
  runner's CPU and can emit instructions a Pi 4 cannot execute.
- Default login is `scoreboard` / `Scoreboard1!`. The `device-user-credentials`
  layer enforces a complexity rule (upper, lower, digit, symbol, 8+ chars), so
  any replacement must satisfy it. Change this before putting the board on an
  untrusted network — the base image also runs an SSH server.
- `user1sudo` accepts only `none`, `passwd` or `nopasswd`, and listing `sudo`
  in `user1groups` is rejected as a conflict with it.
- **Root filesystem growth is untested on real hardware** (tracked in #4).
  The image ships a small, fixed-size root partition; `nhl-scoreboard-grow-
  rootfs.service` grows it to fill the SD card on first boot, using the same
  two-phase technique (grow the partition table, reboot, then `resize2fs`)
  `raspi-config`'s `do_expand_rootfs` has used for years. `tests/test_grow_
  rootfs.py` runs the real script against a faked toolchain (every command
  it touches -- `findmnt`, `lsblk`, `parted`, `sfdisk`, `resize2fs`,
  `systemctl` -- is a recording fake) and verifies its logic and safety
  checks, but that cannot substitute for seeing it actually grow a real
  partition on a real SD card.
