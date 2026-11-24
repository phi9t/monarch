#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Hermetic local control-plane test runner.
#
# Brings up all of Monarch's control-plane elements (host/proc/actor meshes and
# supervision) on the local host using local GPUs, then runs both the Python and
# Rust control-plane test suites. Everything is spawned on this_host() /
# local_host_mesh -- no CI variables, no remote or distributed execution.
#
# Fails loudly if the environment is not as expected rather than silently
# skipping tests: an active Python env, a working `import monarch` with the
# tensor engine, and at least one local GPU are all required.
#
# Usage:
#   scripts/run scripts/run_local_control_plane.sh [options]
#
# Options:
#   --python-only   Run only the Python control-plane suite.
#   --rust-only     Run only the Rust control-plane suite.
#   --gpus N        Restrict the run to the first N local GPUs (sets
#                   CUDA_VISIBLE_DEVICES). Honors a caller-set value otherwise.
#   --keep-going    Run both suites even if the first one fails.
#   -h, --help      Show this help and exit.
#
# This script must run inside the hermetic bwrap rootfs. Invoke it through
# scripts/run, which enters the sandbox and activates .venv-rootfs; when run
# outside the rootfs it re-execs itself through scripts/run automatically.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Route through the canonical gateway before any Python, CUDA, build, or test
# work when we are not already inside a valid rootfs. Hand the gateway the
# in-rootfs mount path so the re-exec resolves inside the sandbox regardless of
# the host checkout location.
if ! "$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs >/dev/null 2>&1; then
  exec "$REPO_ROOT/scripts/run" /workspace/monarch/scripts/run_local_control_plane.sh "$@"
fi
"$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs python uv cargo >/dev/null

PYTHON_ONLY=0
RUST_ONLY=0
KEEP_GOING=0
GPUS=""

usage() {
  sed -n '19,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-only) PYTHON_ONLY=1; shift ;;
    --rust-only) RUST_ONLY=1; shift ;;
    --keep-going) KEEP_GOING=1; shift ;;
    --gpus)
      [[ $# -ge 2 ]] || { echo "error: --gpus requires an argument" >&2; exit 2; }
      GPUS="$2"; shift 2 ;;
    --gpus=*) GPUS="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$PYTHON_ONLY" -eq 1 && "$RUST_ONLY" -eq 1 ]]; then
  echo "error: --python-only and --rust-only are mutually exclusive" >&2
  exit 2
fi

OUT="$REPO_ROOT/control-plane-results"
mkdir -p "$OUT"

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# --- Preflight: assert a hermetic local GPU environment -----------------------

log "preflight"

if [[ -z "${VIRTUAL_ENV:-}" && -z "${CONDA_PREFIX:-}" ]]; then
  die "no active Python environment (VIRTUAL_ENV/CONDA_PREFIX unset); PyO3 links against Python, so activate a venv or conda env first"
fi

# Restrict visible GPUs when asked, before probing torch so the count reflects
# what the tests will actually see.
if [[ -n "$GPUS" ]]; then
  [[ "$GPUS" =~ ^[0-9]+$ && "$GPUS" -gt 0 ]] || die "--gpus must be a positive integer, got: $GPUS"
  CUDA_VISIBLE_DEVICES="$(seq -s, 0 $((GPUS - 1)))"
  export CUDA_VISIBLE_DEVICES
  echo "restricting to $GPUS GPU(s): CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
elif [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  echo "honoring caller CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
fi

# `import monarch`, tensor engine present, and a local GPU must all hold. Use a
# distinct exit code per failure mode so the message is precise.
python - <<'PY'
import sys

try:
    import monarch  # noqa: F401
except Exception as e:  # pragma: no cover - environment guard
    print(f"import monarch failed: {e}", file=sys.stderr)
    sys.exit(11)

try:
    from monarch._rust_bindings import has_tensor_engine
except Exception as e:  # pragma: no cover - environment guard
    print(f"cannot import has_tensor_engine: {e}", file=sys.stderr)
    sys.exit(12)

if not has_tensor_engine():
    print("tensor engine not built (has_tensor_engine() is False); "
          "rebuild with USE_TENSOR_ENGINE=1 (the default)", file=sys.stderr)
    sys.exit(13)

try:
    import torch
except Exception as e:  # pragma: no cover - environment guard
    print(f"import torch failed: {e}", file=sys.stderr)
    sys.exit(14)

if not torch.cuda.is_available():
    print("torch.cuda.is_available() is False; this is a GPU-local run and "
          "requires a working local CUDA device", file=sys.stderr)
    sys.exit(15)

count = torch.cuda.device_count()
if count < 1:
    print("no local GPU visible (torch.cuda.device_count() == 0); a local GPU "
          "is required -- check CUDA_VISIBLE_DEVICES", file=sys.stderr)
    sys.exit(16)

print(f"local GPUs detected: {count}")
PY
rc=$?
if [[ "$rc" -ne 0 ]]; then
  die "preflight failed (exit $rc); environment is not a hermetic local GPU control-plane setup"
fi

export RUST_BACKTRACE=1

# LD_PRELOAD the conda libstdc++ only under conda; a plain venv already resolves
# the system libstdc++ correctly, unlike the CI helper which assumes conda.
if [[ -n "${CONDA_PREFIX:-}" ]]; then
  conda_libstdcpp="${CONDA_PREFIX}/lib/libstdc++.so.6"
  if [[ -f "$conda_libstdcpp" ]]; then
    export LD_PRELOAD="${conda_libstdcpp}${LD_PRELOAD:+:$LD_PRELOAD}"
    echo "LD_PRELOAD=$LD_PRELOAD"
  fi
fi

# Seed override files so nothing is skipped by remote CI issue state. The
# documented fetch_disabled_tests.py contract is to never overwrite files that
# already exist, so writing these here also protects a later CI-style run.
if [[ ! -f "$REPO_ROOT/disabled_tests.txt" ]]; then
  : > "$REPO_ROOT/disabled_tests.txt"
  echo "seeded empty disabled_tests.txt"
fi
mkdir -p "$REPO_ROOT/.config"
if [[ ! -f "$REPO_ROOT/.config/nextest-filter.txt" ]]; then
  echo "all()" > "$REPO_ROOT/.config/nextest-filter.txt"
  echo "seeded .config/nextest-filter.txt with all()"
fi
NEXTEST_FILTER="$(cat "$REPO_ROOT/.config/nextest-filter.txt")"

# Control-plane Python test modules (those marked @pytest.mark.control_plane).
# Collecting exactly these files keeps the run hermetic: unrelated modules whose
# imports fail to collect (e.g. optional torchx tooling) cannot derail it. The
# `-m control_plane` filter below still guards that only marked tests run.
CONTROL_PLANE_TESTS=(
  python/tests/test_proc_mesh.py
  python/tests/test_host_mesh.py
  python/tests/test_spmd_host_mesh.py
  python/tests/test_supervision_hierarchy.py
  python/tests/test_actor_error.py
  python/tests/test_actor_shape.py
  python/tests/test_python_actors.py
  python/tests/test_gil_on_control_plane.py
  python/tests/_monarch/test_actor_mesh.py
  python/tests/_monarch/test_hyperactor.py
  python/tests/_monarch/test_mailbox.py
  python/tests/_monarch/test_value_mesh.py
)

# Local mesh certs are required by the Rust host-bootstrap tests.
if [[ "$RUST_ONLY" -eq 1 || "$PYTHON_ONLY" -eq 0 ]]; then
  log "generating local mesh test certs"
  "$REPO_ROOT/monarch_mini/test_certs/generate.sh"
fi

# Some hosts (notably Nix-provisioned ones) expose a default `cc`/`clang` whose
# binaries target a different dynamic loader and glibc than the system loader
# rustc runs under. That mismatch makes rustc fail to load freshly built
# proc-macro .so files ("can't find crate for ...") and yields extension .so
# files with unresolved __isoc23_* symbols. Detect it by comparing the ELF
# interpreter the default cc bakes in against the system loader, and pin the C
# toolchain to the system gcc plus a glibc-compatible libclang. No-op on a
# consistent toolchain.
prepare_rust_toolchain() {
  local cc_bin probe cc_interp sys_interp
  cc_bin="$(command -v cc || true)"
  [[ -n "$cc_bin" ]] || return 0

  probe="$(mktemp -d)"
  printf 'int main(void){return 0;}\n' > "$probe/t.c"
  if "$cc_bin" "$probe/t.c" -o "$probe/t" >/dev/null 2>&1; then
    cc_interp="$(readelf -l "$probe/t" 2>/dev/null \
        | sed -n 's/.*Requesting program interpreter: \(.*\)\]/\1/p')"
  fi
  rm -rf "$probe"

  # Resolve the system loader the same way the kernel would.
  sys_interp="$(readlink -f /lib64/ld-linux-x86-64.so.2 2>/dev/null)"

  # If cc's interpreter matches the system loader, the toolchain is consistent.
  if [[ -z "$cc_interp" ]] || [[ "$(readlink -f "$cc_interp" 2>/dev/null)" == "$sys_interp" ]]; then
    return 0
  fi

  echo "detected C toolchain loader mismatch (cc targets $cc_interp, system is $sys_interp); pinning system gcc"
  if [[ -x /usr/bin/gcc ]]; then
    export CC=/usr/bin/gcc
    export CXX=/usr/bin/g++
    export CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=/usr/bin/gcc
    # Proc-macros are host artifacts linked with the default cc; put system gcc
    # first on PATH so `cc` resolves to it for host and target builds alike.
    PATH="/usr/bin:$PATH"
    export PATH
    echo "CC=$CC CXX=$CXX linker=/usr/bin/gcc"
  else
    echo "warning: /usr/bin/gcc not found; rust build may fail on this host" >&2
  fi

  # bindgen (nccl-sys) needs a libclang that loads under the system loader and
  # its matching builtin headers. Only set these if unset by the caller.
  if [[ -z "${LIBCLANG_PATH:-}" ]]; then
    local libclang
    libclang="$(find /usr/lib /usr/lib64 /usr/local -maxdepth 4 -name 'libclang.so*' 2>/dev/null | head -1)"
    if [[ -n "$libclang" ]]; then
      LIBCLANG_PATH="$(dirname "$libclang")"
      export LIBCLANG_PATH
      echo "LIBCLANG_PATH=$LIBCLANG_PATH"
    fi
  fi
}

# --- Run suites ---------------------------------------------------------------

python_rc=0
rust_rc=0
ran_python=0
ran_rust=0

run_python_suite() {
  ran_python=1
  log "python control-plane tests (this_host / local GPUs)"
  LC_ALL=C python -m pytest "${CONTROL_PLANE_TESTS[@]}" -v -m "control_plane and not oss_skip" \
      --ignore-glob="**/meta/**" \
      --crash-recovery --max-crashes=10 --max-leaked-procs=16 --restart-every=100 \
      --junit-xml="$OUT/control-plane-python.xml"
  python_rc=$?
}

run_rust_suite() {
  ran_rust=1
  prepare_rust_toolchain
  log "rust control-plane tests (local in-process meshes)"
  RUSTFLAGS="--cfg tracing_unstable --cfg hyperactor_verify_auto_traits ${RUSTFLAGS:-}" \
    cargo nextest run --locked --profile ci \
      -p hyperactor -p hyperactor_mesh -p hyperactor_cast \
      -p hyperactor_config -p ndslice \
      -E "$NEXTEST_FILTER"
  rust_rc=$?
}

if [[ "$RUST_ONLY" -ne 1 ]]; then
  run_python_suite
  if [[ "$python_rc" -ne 0 && "$KEEP_GOING" -ne 1 && "$PYTHON_ONLY" -ne 1 ]]; then
    log "summary"
    echo "python : FAIL (exit $python_rc)"
    echo "rust   : SKIPPED (python failed; pass --keep-going to run anyway)"
    exit 1
  fi
fi

if [[ "$PYTHON_ONLY" -ne 1 ]]; then
  run_rust_suite
fi

# --- Summary ------------------------------------------------------------------

log "summary"
overall=0
if [[ "$ran_python" -eq 1 ]]; then
  if [[ "$python_rc" -eq 0 ]]; then echo "python : PASS"; else echo "python : FAIL (exit $python_rc)"; overall=1; fi
fi
if [[ "$ran_rust" -eq 1 ]]; then
  if [[ "$rust_rc" -eq 0 ]]; then echo "rust   : PASS"; else echo "rust   : FAIL (exit $rust_rc)"; overall=1; fi
  # cargo-nextest resolves its store from the workspace-root default target
  # directory and ignores CARGO_TARGET_DIR, so its JUnit is always here.
  echo "rust junit: $REPO_ROOT/target/nextest/ci/junit.xml"
fi
echo "results: $OUT"
exit "$overall"
