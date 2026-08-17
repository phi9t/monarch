#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Enter the hermetic rootfs under bubblewrap with a read-only root, local GPUs,
# and the repo bind-mounted, then run either an interactive shell or a command.
#
# The rootfs (built by build_rootfs.sh) provides a consistent Ubuntu userland so
# the Rust/CUDA build needs no CC/LIBCLANG_PATH host overrides. The flattened
# rootfs is mounted read-only; only the checkout, dedicated caches, an ephemeral
# home, /tmp, /proc, /dev, and requested GPU devices are writable. The
# environment is cleared, so host compiler, Python, Cargo, and linker variables
# never cross the boundary.
#
# The in-rootfs CUDA runtime (pip nvidia-cu13 wheels) is linked against the
# *host* NVIDIA driver userspace, which is read-only bound in so its version
# matches the loaded kernel module. Real /dev/nvidia* nodes are bound so tests
# run on local GPUs; on a CPU-only host, absent devices and libraries are simply
# not bound, and actor-only work remains valid.
#
# Usage:
#   scripts/rootfs/enter_rootfs.sh [--chdir CHECKOUT_REL] [--repo-readonly] [--emit-plan PATH] [-- <command> [args...]]
#
# With no command, drops into an interactive bash shell inside the rootfs. If the
# rootfs directory is missing or its stamped recipe is stale, it is rebuilt
# automatically, so a first run is a single command.
#
# Options:
#   --chdir REL     Relative checkout subdirectory to start in (must stay below
#                   the checkout). Default: the checkout root.
#   --bind-rw HOST:SANDBOX
#                   Bind an extra writable host directory into the sandbox.
#   --emit-plan PATH
#                   Write the resolved bwrap/rootfs plan before launch.
#   --repo-readonly
#                   Mount the checkout read-only.
#   --rootfs DIR    Rootfs directory to enter (default: scripts/rootfs/rootfs).
#   -h, --help      Show this help and exit.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOTFS_DIR="$REPO_ROOT/scripts/rootfs"

# shellcheck source=scripts/rootfs/contract.env
source "$ROOTFS_DIR/contract.env"
# shellcheck source=scripts/rootfs/execution_contract.sh
source "$ROOTFS_DIR/execution_contract.sh"

ROOTFS="$ROOTFS_DIR/rootfs"
checkout_rel=""
emit_plan=""
repo_projection_mode="rw"
extra_rw_binds=()
declare -A emitted_sandbox_dirs=()

die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

parse_rw_bind() {
  local spec="$1"
  local host_path="${spec%%:*}"
  local sandbox_path="${spec#*:}"
  [[ "$spec" == *:* && -n "$host_path" && -n "$sandbox_path" ]] || die "--bind-rw must be HOST:SANDBOX"
  [[ "$host_path" == /* ]] || die "--bind-rw host path must be absolute: $host_path"
  [[ "$sandbox_path" == /* ]] || die "--bind-rw sandbox path must be absolute: $sandbox_path"
  extra_rw_binds+=("$host_path:$sandbox_path")
}

append_sandbox_dirs() {
  local target="$1"
  local current=""
  IFS='/' read -r -a parts <<< "${target#/}"
  for i in "${!parts[@]}"; do
    part="${parts[$i]}"
    [[ -n "$part" ]] || continue
    current="$current/$part"
    if [[ "${emitted_sandbox_dirs[$current]+set}" == set ]]; then
      continue
    fi
    emitted_sandbox_dirs[$current]=1
    if [[ "$i" -eq 0 ]]; then
      bwrap_args+=(--tmpfs "$current")
    else
      bwrap_args+=(--dir "$current")
    fi
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --chdir) checkout_rel="$2"; shift 2 ;;
    --chdir=*) checkout_rel="${1#*=}"; shift ;;
    --bind-rw) parse_rw_bind "$2"; shift 2 ;;
    --bind-rw=*) parse_rw_bind "${1#*=}"; shift ;;
    --emit-plan) emit_plan="$2"; shift 2 ;;
    --emit-plan=*) emit_plan="${1#*=}"; shift ;;
    --repo-readonly) repo_projection_mode="ro"; shift ;;
    --rootfs) ROOTFS="$2"; shift 2 ;;
    --rootfs=*) ROOTFS="${1#*=}"; shift ;;
    --) shift; break ;;
    -h|--help) sed -n '9,41p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Validate --chdir: must be relative and stay below the checkout. Reject
# absolute paths, .. traversal, and leading slashes.
if [[ -n "$checkout_rel" ]]; then
  [[ "$checkout_rel" != /* ]] || die "--chdir must be a relative path: $checkout_rel"
  case "/$checkout_rel/" in
    */../*) die "--chdir must stay below the checkout: $checkout_rel" ;;
  esac
  checkout_rel="${checkout_rel#./}"
  checkout_rel="${checkout_rel%/}"
fi

if [[ "$ROOTFS" != /* ]]; then
  ROOTFS="$PWD/$ROOTFS"
fi

if [[ "${MONARCH_ROOTFS_EMIT_PLAN_ONLY:-}" != "1" ]]; then
  command -v bwrap >/dev/null || die "bwrap not found on host"
fi

host_arch="$(uname -m)"
[[ "$host_arch" == "$MONARCH_ROOTFS_ARCH" ]] || \
  die "unsupported architecture $host_arch: this rootfs supports $MONARCH_ROOTFS_ARCH only"

# Auto-build the rootfs on first use, and rebuild it when its stamped recipe is
# stale. A rootfs is usable only if it has a populated bin/ (a docker export of
# an empty or interrupted build would leave a bare directory).
needs_build=0
if [[ ! -x "$ROOTFS/bin/bash" ]]; then
  needs_build=1
elif ! monarch_rootfs_contract_current "$ROOTFS" "$REPO_ROOT"; then
  printf '\033[1m== rootfs at %s is stale; rebuilding ==\033[0m\n' "$ROOTFS" >&2
  needs_build=1
fi
if [[ "$needs_build" -eq 1 ]]; then
  if [[ "${MONARCH_ROOTFS_EMIT_PLAN_ONLY:-}" == "1" ]]; then
    printf '\033[1m== emit-only: rootfs at %s is not built ==\033[0m\n' "$ROOTFS" >&2
  else
    printf '\033[1m== building rootfs at %s ==\033[0m\n' "$ROOTFS" >&2
    "$ROOTFS_DIR/build_rootfs.sh" --dest "$ROOTFS"
    [[ -x "$ROOTFS/bin/bash" ]] || die "rootfs build did not produce a usable rootfs at $ROOTFS"
  fi
fi
if [[ "${MONARCH_ROOTFS_EMIT_PLAN_ONLY:-}" != "1" ]]; then
  verifier_args=(--rootfs "$ROOTFS")
  if [[ -n "${MONARCH_ROOTFS_CACHE_ROOT:-}" ]]; then
    verifier_args+=(--cache-root "$MONARCH_ROOTFS_CACHE_ROOT")
  fi
  python3 "$ROOTFS_DIR/verify_rootfs.py" "${verifier_args[@]}" --skip-command-checks >/dev/null || \
    die "rootfs verification failed for $ROOTFS"
fi

REPO_MNT=/workspace/monarch
RECIPE_SHA256="$(monarch_rootfs_recipe_sha256 "$REPO_ROOT")"

# Managed host-side caches. Keeping them outside the rootfs export means the
# read-only root is never written and caches persist across runs. By default
# they live under scripts/rootfs/cache and target/bwrap. Set
# MONARCH_ROOTFS_CACHE_ROOT to an absolute host path to relocate heavy mutable
# state without changing sandbox paths.
if [[ -n "${MONARCH_ROOTFS_CACHE_ROOT:-}" ]]; then
  [[ "$MONARCH_ROOTFS_CACHE_ROOT" == /* ]] || die "MONARCH_ROOTFS_CACHE_ROOT must be absolute: $MONARCH_ROOTFS_CACHE_ROOT"
  CACHE_HOST_ROOT="$MONARCH_ROOTFS_CACHE_ROOT"
else
  CACHE_HOST_ROOT="$ROOTFS_DIR/cache"
fi
CARGO_TARGET_DIR_HOST="$CACHE_HOST_ROOT/target/bwrap/$RECIPE_SHA256"
for cache in uv cargo npm xdg; do
  mkdir -p "$CACHE_HOST_ROOT/$cache"
done
mkdir -p "$CARGO_TARGET_DIR_HOST"

CACHE_MNT="$REPO_MNT/scripts/rootfs/cache"
CARGO_TARGET_DIR_MNT="$REPO_MNT/target/bwrap/$RECIPE_SHA256"

# Base bwrap args: read-only rootfs, fresh proc/tmp/dev, ephemeral home, repo
# mounted rw, cleared environment.
bwrap_args=(
  --ro-bind "$ROOTFS" /
  --proc /proc
  --tmpfs /tmp
  --dev /dev
  --tmpfs /home
  --dir /home/monarch
  --unshare-all
  --share-net
  --die-with-parent
  --clearenv
  --chdir "$REPO_MNT${checkout_rel:+/$checkout_rel}"
)
if [[ "$repo_projection_mode" == "ro" ]]; then
  bwrap_args+=(--ro-bind "$REPO_ROOT" "$REPO_MNT")
else
  bwrap_args+=(--bind "$REPO_ROOT" "$REPO_MNT")
fi
mkdir -p "$REPO_ROOT/scripts/rootfs/cache"
bwrap_args+=(--bind "$CACHE_HOST_ROOT" "$CACHE_MNT")
mkdir -p "$REPO_ROOT/target/bwrap/$RECIPE_SHA256"
bwrap_args+=(--bind "$CARGO_TARGET_DIR_HOST" "$CARGO_TARGET_DIR_MNT")
for bind_spec in "${extra_rw_binds[@]}"; do
  host_path="${bind_spec%%:*}"
  sandbox_path="${bind_spec#*:}"
  mkdir -p "$host_path"
  sandbox_top="${sandbox_path#/}"
  sandbox_top="${sandbox_top%%/*}"
  [[ -n "$sandbox_top" ]] || die "--bind-rw sandbox path must not be root"
  mkdir -p "$ROOTFS/$sandbox_top"
  append_sandbox_dirs "$sandbox_path"
  bwrap_args+=(--bind "$host_path" "$sandbox_path")
done

# DNS: docker export leaves /etc/resolv.conf empty, so bind the host's resolver
# config in for network access (uv/pip/npm fetch during builds).
for f in /etc/resolv.conf /etc/hosts; do
  [[ -e "$f" ]] && bwrap_args+=(--ro-bind "$f" "$f")
done

# GPU device nodes: bind every /dev/nvidia* that exists.
shopt -s nullglob
declare -A seen_nvidia_devices=()
for dev in /dev/nvidia* /dev/nvidia-caps; do
  if [[ "${seen_nvidia_devices[$dev]+set}" == set ]]; then
    continue
  fi
  seen_nvidia_devices[$dev]=1
  bwrap_args+=(--dev-bind "$dev" "$dev")
done

# Host NVIDIA driver userspace: the read-only root has no target paths for these
# host libraries, so inject them into a writable tmpfs at /run/nvidia-host and
# expose that directory through LD_LIBRARY_PATH. bwrap can create files inside a
# tmpfs even though the root is read-only.
HOST_LIBDIR=/usr/lib/x86_64-linux-gnu
NVIDIA_HOST_MNT=/run/nvidia-host
have_nvidia=0
nvidia_binds=()
for lib in "$HOST_LIBDIR"/libcuda.so* "$HOST_LIBDIR"/libnvidia-*.so*; do
  nvidia_binds+=(--ro-bind "$lib" "$NVIDIA_HOST_MNT/$(basename -- "$lib")")
  have_nvidia=1
done
if [[ "$have_nvidia" -eq 1 ]]; then
  bwrap_args+=(--tmpfs "$NVIDIA_HOST_MNT" "${nvidia_binds[@]}")
fi
if [[ -x /usr/bin/nvidia-smi ]]; then
  bwrap_args+=(--ro-bind /usr/bin/nvidia-smi "$NVIDIA_HOST_MNT/nvidia-smi")
fi
shopt -u nullglob

# Environment: cleared, then set explicitly. Rootfs toolchain paths, dedicated
# cache directories, digest-scoped Cargo target, synthetic CUDA_HOME, and the
# provenance marker. Host compiler/Python/linker variables are never set.
bwrap_args+=(
  --setenv HOME /home/monarch
  --setenv PATH "/opt/cuda-synth/bin:/opt/cargo/bin:/usr/local/bin:/usr/bin:/bin:$NVIDIA_HOST_MNT"
  --setenv UV_PROJECT_ENVIRONMENT "$REPO_MNT/.venv-rootfs"
  --setenv UV_CACHE_DIR "${UV_CACHE_DIR:-$CACHE_MNT/uv}"
  --setenv CARGO_HOME "$CACHE_MNT/cargo"
  --setenv CARGO_TARGET_DIR "$CARGO_TARGET_DIR_MNT"
  --setenv npm_config_cache "$CACHE_MNT/npm"
  --setenv XDG_CACHE_HOME "${XDG_CACHE_HOME:-$CACHE_MNT/xdg}"
  --setenv RUSTUP_HOME /opt/rustup
  --setenv CUDA_HOME /opt/cuda-synth
  --setenv CUDA_PATH /opt/cuda-synth
  --setenv MONARCH_IN_ROOTFS 1
  --setenv MONARCH_ROOTFS_RECIPE_SHA256 "$RECIPE_SHA256"
)
if [[ "$have_nvidia" -eq 1 ]]; then
  bwrap_args+=(--setenv LD_LIBRARY_PATH "$NVIDIA_HOST_MNT:/opt/cuda-synth/lib64")
  bwrap_args+=(--setenv LIBRARY_PATH "$NVIDIA_HOST_MNT:/opt/cuda-synth/lib64")
fi

# Preserve only a documented allowlist across --clearenv: terminal, proxies, GPU
# selection, Rust logging/backtrace, and documented Monarch build flags.
for var in TERM COLORTERM \
           http_proxy https_proxy ftp_proxy no_proxy \
           HTTP_PROXY HTTPS_PROXY FTP_PROXY NO_PROXY \
           NVIDIA_VISIBLE_DEVICES RUST_LOG RUST_BACKTRACE \
           TORCHINDUCTOR_CACHE_DIR TRITON_CACHE_DIR SGLANG_CACHE_DIR TRANSFORMERS_CACHE USER LOGNAME \
           USE_TENSOR_ENGINE MONARCH_GPU_PLATFORM MONARCH_PACKAGE_NAME \
           MONARCH_VERSION ENABLE_MESSAGE_LOGGING \
           GLM52_MODEL GLM52_CHAT_BASE_URL GLM52_RESPONSES_BASE_URL \
           GLM52_RESPONSES_ADAPTER_HOST GLM52_RESPONSES_ADAPTER_PORT \
           GLM52_API_KEY_ENV GLM52_ADAPTER_TIMEOUT_SECONDS \
           GLM_API_KEY HF_HOME; do
  if [[ "${!var+set}" == set ]]; then
    bwrap_args+=(--setenv "$var" "${!var}")
  fi
done

# Pass through GPU selection. An explicitly empty value is meaningful (hide all
# GPUs) and is honored so the negative preflight check works.
if [[ "${CUDA_VISIBLE_DEVICES+set}" == set ]]; then
  bwrap_args+=(--setenv CUDA_VISIBLE_DEVICES "$CUDA_VISIBLE_DEVICES")
fi
if [[ "${NVIDIA_VISIBLE_DEVICES+set}" != set ]]; then
  bwrap_args+=(--setenv NVIDIA_VISIBLE_DEVICES all)
fi

write_emit_plan() {
  local plan_path="$1"
  shift
  local bwrap_arg_count="$1"
  shift
  mkdir -p "$(dirname -- "$plan_path")"
  python3 - "$plan_path" "$ROOTFS_DIR" "$ROOTFS" "$RECIPE_SHA256" "$CACHE_HOST_ROOT" "$REPO_MNT${checkout_rel:+/$checkout_rel}" "$REPO_ROOT" "$repo_projection_mode" "$bwrap_arg_count" "$@" <<'PY'
import sys
from pathlib import Path

import yaml


plan_path = Path(sys.argv[1])
rootfs_dir = Path(sys.argv[2])
rootfs = Path(sys.argv[3])
recipe_sha256 = sys.argv[4]
cache_root = Path(sys.argv[5])
cwd = sys.argv[6]
repo_root = Path(sys.argv[7])
repo_projection_mode = sys.argv[8]
bwrap_arg_count = int(sys.argv[9])
argv = sys.argv[10:]
bwrap_args = argv[:bwrap_arg_count]
inner_argv = argv[bwrap_arg_count:]

sys.path.insert(0, str(rootfs_dir))
from rootfs_sandbox_config import (  # noqa: E402
    SandboxConfigError,
    Mount,
    bwrap_argv_from_plan,
    materialize_sandbox_plan,
    parse_bwrap_argv,
    validate_bwrap_argv_matches_plan,
)

mounts = []
env = {}
network = "private"
gpu = "none"
i = 0
while i < len(bwrap_args):
    arg = bwrap_args[i]
    if arg in {"--bind", "--ro-bind", "--dev-bind"}:
        host_path = bwrap_args[i + 1]
        sandbox_path = bwrap_args[i + 2]
        mode = "ro" if arg == "--ro-bind" else "rw"
        mounts.append(
            {"host_path": host_path, "sandbox_path": sandbox_path, "mode": mode}
        )
        if arg == "--dev-bind" and sandbox_path.startswith("/dev/nvidia"):
            gpu = "dev-bind-nvidia-when-present"
        i += 3
    elif arg == "--setenv":
        env[bwrap_args[i + 1]] = bwrap_args[i + 2]
        i += 3
    elif arg == "--chdir":
        cwd = bwrap_args[i + 1]
        i += 2
    elif arg == "--share-net":
        network = "share-net"
        i += 1
    elif arg in {"--proc", "--tmpfs", "--dev", "--dir"}:
        i += 2
    else:
        i += 1

if gpu == "none":
    gpu = "dev-bind-nvidia-when-present"

actual_mounts, actual_env, actual_cwd = parse_bwrap_argv(["bwrap", *bwrap_args, *inner_argv])
schema_mount_keys = {
    "/",
    "/workspace/monarch",
    "/workspace/monarch/scripts/rootfs/cache",
    f"/workspace/monarch/target/bwrap/{recipe_sha256}",
}
purpose_by_path = {
    "/etc/resolv.conf": "dns",
    "/etc/hosts": "hosts",
    "/run/nvidia-host": "nvidia-host",
}
extra_mounts = []
for mount in actual_mounts:
    if mount.sandbox_path in schema_mount_keys:
        continue
    if mount.sandbox_path.startswith("/dev/nvidia"):
        purpose = "dev-nvidia"
    elif mount.sandbox_path.startswith("/run/nvidia-host"):
        purpose = "nvidia-host"
    else:
        purpose = purpose_by_path.get(mount.sandbox_path, "extra")
    extra_mounts.append(
        Mount(
            host_path=mount.host_path,
            sandbox_path=mount.sandbox_path,
            mode=mount.mode,
            purpose=purpose,
        )
    )

schema_plan = materialize_sandbox_plan(
    rootfs=rootfs,
    repo_root=repo_root,
    recipe_sha256=recipe_sha256,
    cache_root=cache_root,
    cwd=cwd,
    repo_projection_mode=repo_projection_mode,
    inner_argv=inner_argv,
    extra_mounts=extra_mounts,
    extra_env=env,
)
try:
    validate_bwrap_argv_matches_plan(schema_plan, ["bwrap", *bwrap_args, *inner_argv])
    validate_bwrap_argv_matches_plan(schema_plan, bwrap_argv_from_plan(schema_plan))
except SandboxConfigError as exc:
    raise SystemExit(f"schema validation failed: {exc}") from exc

materialized = schema_plan.to_dict()
materialized["mounts"] = [
    {
        "host_path": str(mount.host_path),
        "sandbox_path": mount.sandbox_path,
        "mode": mount.mode,
        "purpose": mount.purpose,
    }
    for mount in schema_plan.mounts
]
materialized["env"] = dict(sorted(actual_env.items()))
materialized["cwd"] = actual_cwd

legacy_plan = {
    "schema_version": 1,
    "outer_argv": ["bwrap", *bwrap_args, *inner_argv],
    "inner_argv": inner_argv,
    "env_allowlist": [],
    "network": network,
    "gpu": gpu,
}
plan = {
    **materialized,
    **legacy_plan,
    "rootfs": str(rootfs),
    "rootfs_export": materialized["rootfs"],
    "host_layout": materialized["host_layout"],
    "sandbox_layout": materialized["sandbox_layout"],
    "mounts": materialized["mounts"],
    "env": materialized["env"],
    "env_allowlist": [],
    "network": network,
    "gpu": gpu,
    "repo_projection_mode": repo_projection_mode,
    "schema_translated_argv": bwrap_argv_from_plan(schema_plan),
}
plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))
PY
}

if [[ $# -eq 0 ]]; then
  inner_argv=(/bin/bash -l)
else
  inner_argv=("$@")
fi

if [[ -n "$emit_plan" ]]; then
  write_emit_plan "$emit_plan" "${#bwrap_args[@]}" "${bwrap_args[@]}" "${inner_argv[@]}"
  if [[ "${MONARCH_ROOTFS_EMIT_PLAN_ONLY:-}" == "1" ]]; then
    exit 0
  fi
fi

exec bwrap "${bwrap_args[@]}" "${inner_argv[@]}"
