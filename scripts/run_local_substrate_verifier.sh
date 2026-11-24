#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Verify the shared control-plane substrate (Placement + Reallocation Policy +
# Control Store) end to end on the local host, inside the hermetic bwrap rootfs.
#
# Usage:
#   scripts/run scripts/run_local_substrate_verifier.sh [--gpus N]
#
# When run outside the rootfs this re-execs through scripts/run, which enters
# the sandbox and activates .venv-rootfs. Inside, it builds the tensor-engine
# editable install, runs the pure-Python substrate unit tests, then runs the
# mesh-level tracer bullet: place a gang, round-trip the control store, spawn
# the mesh, crash an actor, and prove the Reallocation Policy returns Replace
# instead of sys.exit(1).
#
# Fails loudly (aborts in preflight) rather than skipping if the environment is
# not as expected: an active rootfs, the tensor engine, and at least --gpus
# visible CUDA devices are all required. Ladder exit codes mirror the verifier
# script: 21 tensor-engine, 22 placement, 23 smoke, 24 reallocation.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GPUS=2

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpus)
      [[ $# -ge 2 ]] || die "--gpus requires a value"
      GPUS="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '8,24p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ "$GPUS" =~ ^[1-9][0-9]*$ ]] || die "--gpus must be a positive integer, got $GPUS"

# Route through the canonical gateway before any Python, CUDA, build, or test
# work when we are not already inside a valid rootfs.
if ! "$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs >/dev/null 2>&1; then
  log "environment: rootfs entry"
  echo "entering hermetic bwrap rootfs via scripts/run"
  exec "$REPO_ROOT/scripts/run" \
    /workspace/monarch/scripts/run_local_substrate_verifier.sh --gpus "$GPUS"
fi
"$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs python uv cargo >/dev/null

log "environment: rootfs"
echo "inside hermetic bwrap rootfs"
command -v uv >/dev/null || die "uv not found in rootfs"
echo "uv=$(command -v uv)"
[[ -n "${CUDA_HOME:-}" ]] || die "CUDA_HOME is unset inside the rootfs"
echo "CUDA_HOME=$CUDA_HOME"
echo "requested gpus=$GPUS"

VENV="$REPO_ROOT/.venv-rootfs"
if [[ ! -x "$VENV/bin/python" ]]; then
  log "environment: .venv-rootfs"
  echo "creating rootfs venv at $VENV"
  uv venv --python 3.12 --system-site-packages "$VENV"
else
  echo ".venv-rootfs=$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

log "build: editable tensor-engine install"
echo "synchronizing locked dependencies and installing monarch editable"
"$REPO_ROOT/scripts/rootfs/sync_test_environment.sh"

log "unit-level: substrate unit tests (pure python)"
python -m pytest python/tests/test_control_plane_substrate.py -q \
  || die "substrate unit tests failed"
echo "substrate unit tests: PASS"

log "integration: mesh-level substrate tracer bullet (--gpus $GPUS)"
set +e
python "$REPO_ROOT/scripts/local_substrate_verifier.py" --gpus "$GPUS"
tracer_rc=$?
set -e
[[ "$tracer_rc" -eq 0 ]] || die "substrate tracer bullet failed (exit $tracer_rc)"

log "summary"
echo "substrate unit tests      : PASS"
echo "substrate tracer bullet   : PASS"
echo "contract artifacts        : $REPO_ROOT/substrate-results/"
exit 0
