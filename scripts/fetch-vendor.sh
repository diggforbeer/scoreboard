#!/usr/bin/env bash
# Fetch the HUB75 driver source used by the image build.
#
# Downloading on the build host rather than inside the image chroot keeps the
# chroot offline-safe and makes the build reproducible for a given pin.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${REPO_ROOT}/image/files/vendor"
MATRIX_DIR="${VENDOR_DIR}/rpi-rgb-led-matrix"

# Pin to a commit so image builds are repeatable. Update deliberately.
MATRIX_REPO="https://github.com/hzeller/rpi-rgb-led-matrix.git"
MATRIX_REF="${MATRIX_REF:-51d3231}"

mkdir -p "${VENDOR_DIR}"

if [ -d "${MATRIX_DIR}/.git" ]; then
    echo "==> Updating ${MATRIX_DIR}"
    git -C "${MATRIX_DIR}" fetch --quiet origin
else
    echo "==> Cloning rpi-rgb-led-matrix"
    rm -rf "${MATRIX_DIR}"
    git clone --quiet "${MATRIX_REPO}" "${MATRIX_DIR}"
fi

git -C "${MATRIX_DIR}" checkout --quiet "${MATRIX_REF}"
echo "==> rpi-rgb-led-matrix at $(git -C "${MATRIX_DIR}" rev-parse --short HEAD)"
