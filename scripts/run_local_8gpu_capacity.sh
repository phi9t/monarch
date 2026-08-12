#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Build Monarch with the tensor engine inside the hermetic bwrap rootfs and
# verify that this host can run a local Monarch mesh across exactly eight GPUs.
#
# Usage:
#   scripts/run_local_8gpu_capacity.sh
#
# The script re-execs through scripts/rootfs/enter_rootfs.sh unless already
# inside the sandbox. It creates/reuses .venv-rootfs, synchronizes the locked
# test dependencies, installs Monarch editable using the rootfs-pinned build
# tools, runs an 8-rank tensor-engine smoke, and then runs the local
# control-plane suites with all eight GPUs exposed.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

DEFAULTED_CUDA_VISIBLE_DEVICES=0
HOST_PYTHON="$(command -v python3 || command -v python || true)"
[[ -n "$HOST_PYTHON" ]] || die "python3 or python is required to validate CUDA_VISIBLE_DEVICES"

log "environment: CUDA visibility"
cuda_visibility_output="$("$HOST_PYTHON" "$REPO_ROOT/scripts/local_8gpu_capacity.py" cuda-visible-devices)" || \
  die "invalid CUDA_VISIBLE_DEVICES"
mapfile -t cuda_visibility <<< "$cuda_visibility_output"
CUDA_VISIBLE_DEVICES="${cuda_visibility[0]}"
export CUDA_VISIBLE_DEVICES
if [[ "${cuda_visibility[1]}" == "defaulted" ]]; then
  DEFAULTED_CUDA_VISIBLE_DEVICES=1
  echo "defaulted CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
else
  echo "honoring caller CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
fi

if [[ "${MONARCH_IN_ROOTFS:-0}" != "1" ]]; then
  log "environment: rootfs entry"
  echo "entering hermetic bwrap rootfs"
  exec "$REPO_ROOT/scripts/rootfs/enter_rootfs.sh" -- scripts/run_local_8gpu_capacity.sh
fi

log "environment: rootfs"
echo "inside hermetic bwrap rootfs"
echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
command -v uv >/dev/null || die "uv not found in rootfs"
echo "uv=$(command -v uv)"
[[ -n "${CUDA_HOME:-}" ]] || die "CUDA_HOME is unset inside the rootfs"
echo "CUDA_HOME=$CUDA_HOME"

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

log "unit-level smoke: 8-gpu tensor engine"
set +e
python - <<'PY'
import sys

import torch

from monarch import fetch_shard
from monarch._rust_bindings import has_tensor_engine
from monarch.actor import this_host

if not has_tensor_engine():
    print(
        "tensor engine not built (has_tensor_engine() is False)",
        file=sys.stderr,
    )
    sys.exit(21)

count = torch.cuda.device_count()
if count != 8:
    print(
        f"expected exactly 8 visible CUDA devices, got {count}; "
        "check CUDA_VISIBLE_DEVICES",
        file=sys.stderr,
    )
    sys.exit(22)

proc_mesh = None
try:
    proc_mesh = this_host().spawn_procs(per_host={"gpus": 8})
    proc_mesh.initialized.get(timeout=120)
    with proc_mesh.activate():
        ranks = proc_mesh.rank_tensor("gpus").cuda()
        observed = [
            int(fetch_shard(ranks, gpus=i).result(timeout=120).item())
            for i in range(8)
        ]

    expected = list(range(8))
    if observed != expected:
        print(f"expected shard ranks {expected}, got {observed}", file=sys.stderr)
        sys.exit(23)

    print(f"8-gpu shard ranks: {observed}")
finally:
    if proc_mesh is not None:
        proc_mesh.stop("8-gpu capacity verifier cleanup").get(timeout=120)
PY
smoke_rc=$?
set -e
[[ "$smoke_rc" -eq 0 ]] || die "8-gpu tensor-engine smoke failed (exit $smoke_rc)"
echo "unit-level smoke outcome: PASS"

log "integration: control-plane suites over 8 GPUs"
integration_started_ns="$(date +%s%N)"
python_junit="$REPO_ROOT/control-plane-results/control-plane-python.xml"
rust_junit="$REPO_ROOT/target/nextest/ci/junit.xml"
rm -f -- "$python_junit" "$rust_junit"
control_args=(--keep-going)
if [[ "$DEFAULTED_CUDA_VISIBLE_DEVICES" -eq 1 ]]; then
  control_args=(--gpus 8 "${control_args[@]}")
fi
set +e
"$REPO_ROOT/scripts/run_local_control_plane.sh" "${control_args[@]}"
control_rc=$?
set -e

if [[ "$control_rc" -eq 0 ]]; then
  log "summary"
  echo "8-gpu tensor-engine smoke : PASS"
  echo "control-plane suites      : PASS"
  exit 0
fi

rust_status="unknown"
if [[ -f "$rust_junit" ]]; then
  rust_status="$("$VENV/bin/python" "$REPO_ROOT/scripts/local_8gpu_capacity.py" nextest-status \
    "$rust_junit" --not-before-ns "$integration_started_ns")"
fi

log "summary"
echo "8-gpu tensor-engine smoke : PASS"
echo "control-plane suites      : FAIL (exit $control_rc)"
echo "rust control-plane        : $rust_status"

if [[ "$rust_status" == "pass" && -f "$python_junit" ]]; then
  log "failure classification: Python full-run failures"
  failed_python_output="$("$VENV/bin/python" "$REPO_ROOT/scripts/local_8gpu_capacity.py" pytest-failures \
    "$python_junit" --not-before-ns "$integration_started_ns")" || \
    exit "$control_rc"
  failed_python_tests=()
  if [[ -n "$failed_python_output" ]]; then
    mapfile -t failed_python_tests <<< "$failed_python_output"
  fi

  if [[ "${#failed_python_tests[@]}" -eq 0 ]]; then
    echo "python control-plane      : failed, but no failed JUnit testcases were found"
    exit "$control_rc"
  fi

  isolation_log="$REPO_ROOT/control-plane-results/control-plane-python-isolation.txt"
  : > "$isolation_log"
  isolation_rc=0
  log "failure classification: isolated Python reruns"
  for test_id in "${failed_python_tests[@]}"; do
    echo "rerun: $test_id" | tee -a "$isolation_log"
    set +e
    LC_ALL=C python -m pytest "$test_id" -q -m "control_plane and not oss_skip" 2>&1 | tee -a "$isolation_log"
    test_rc=${PIPESTATUS[0]}
    set -e
    if [[ "$test_rc" -ne 0 ]]; then
      isolation_rc=1
      echo "isolation failed: $test_id (exit $test_rc)" | tee -a "$isolation_log"
    else
      echo "isolation passed: $test_id" | tee -a "$isolation_log"
    fi
  done

  log "summary"
  echo "8-gpu tensor-engine smoke : PASS"
  echo "rust control-plane        : PASS"
  if [[ "$isolation_rc" -eq 0 ]]; then
    echo "python control-plane      : full-run failures passed in isolation"
    echo "isolation log            : $isolation_log"
    exit 0
  fi
  echo "python control-plane      : isolation rerun failed"
  echo "isolation log            : $isolation_log"
  exit "$control_rc"
fi

exit "$control_rc"
