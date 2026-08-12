#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# In-sandbox driver for the hermetic control-plane run. This is meant to be run
# *inside* the bwrap rootfs (via enter_rootfs.sh); it builds the extension and
# then delegates to the existing suite runner.
#
# It builds `-e .` in an in-rootfs venv with the tensor engine auto-detected
# from the baked CUDA_HOME. No CC/LIBCLANG_PATH overrides are needed: the rootfs
# toolchain's cc targets the same loader as the system, so the
# prepare_rust_toolchain() heuristic in run_local_control_plane.sh is a verified
# no-op here.
#
# Usage (from inside the rootfs):
#   scripts/rootfs/run_in_rootfs.sh [args passed to run_local_control_plane.sh]

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

[[ "${MONARCH_IN_ROOTFS:-0}" == "1" ]] || \
  die "not inside the rootfs; run via scripts/rootfs/enter_rootfs.sh -- scripts/rootfs/run_in_rootfs.sh"

command -v uv >/dev/null || die "uv not found in rootfs"

# Create/reuse an in-rootfs venv. Keep it inside the repo mount so it persists
# across enters and does not pollute the read-only rootfs layer. Inherit the
# rootfs system site-packages so the pre-installed torch 2.13.0+cu132 and
# nvidia-cu13 wheels are visible at build and runtime without re-downloading.
VENV="$REPO_ROOT/.venv-rootfs"
if [[ ! -x "$VENV/bin/python" ]]; then
  log "creating rootfs venv at $VENV"
  uv venv --python 3.12 --system-site-packages "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

log "building monarch (-e .) with tensor engine (CUDA_HOME=$CUDA_HOME)"
# torch is provided by the inherited system site-packages; setup.py detects it
# and the baked CUDA_HOME at build time. Build without isolation so the extension
# links the rootfs torch (rather than a fresh download), which means the build
# backend deps must be present in the environment first. They and torch come
# from the inherited, version-pinned system site-packages. Synchronize the test
# dependencies from uv.lock, apply the rootfs compatibility override, then
# install the project separately without dependency resolution so the rootfs
# torch remains authoritative.
"$REPO_ROOT/scripts/rootfs/sync_test_environment.sh"

log "delegating to run_local_control_plane.sh"
exec "$REPO_ROOT/scripts/run_local_control_plane.sh" "$@"
