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
#   scripts/rootfs/enter_rootfs.sh [--chdir CHECKOUT_REL] [-- <command> [args...]]
#
# With no command, drops into an interactive bash shell inside the rootfs. If the
# rootfs directory is missing or its stamped recipe is stale, it is rebuilt
# automatically, so a first run is a single command.
#
# Options:
#   --chdir REL     Relative checkout subdirectory to start in (must stay below
#                   the checkout). Default: the checkout root.
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

die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --chdir) checkout_rel="$2"; shift 2 ;;
    --chdir=*) checkout_rel="${1#*=}"; shift ;;
    --rootfs) ROOTFS="$2"; shift 2 ;;
    --rootfs=*) ROOTFS="${1#*=}"; shift ;;
    --) shift; break ;;
    -h|--help) sed -n '9,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

command -v bwrap >/dev/null || die "bwrap not found on host"

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
  printf '\033[1m== building rootfs at %s ==\033[0m\n' "$ROOTFS" >&2
  "$ROOTFS_DIR/build_rootfs.sh" --dest "$ROOTFS"
  [[ -x "$ROOTFS/bin/bash" ]] || die "rootfs build did not produce a usable rootfs at $ROOTFS"
fi

REPO_MNT=/workspace/monarch
RECIPE_SHA256="$(monarch_rootfs_recipe_sha256 "$REPO_ROOT")"

# Managed host-side caches (Git-ignored). Keeping them outside the rootfs export
# means the read-only root is never written and caches persist across runs.
for cache in uv cargo npm xdg; do
  mkdir -p "$ROOTFS_DIR/cache/$cache"
done
CARGO_TARGET_DIR_HOST="$REPO_ROOT/target/bwrap/$RECIPE_SHA256"
mkdir -p "$CARGO_TARGET_DIR_HOST"

CACHE_MNT="$REPO_MNT/scripts/rootfs/cache"

# Base bwrap args: read-only rootfs, fresh proc/tmp/dev, ephemeral home, repo
# mounted rw, cleared environment.
bwrap_args=(
  --ro-bind "$ROOTFS" /
  --proc /proc
  --tmpfs /tmp
  --dev /dev
  --tmpfs /home
  --dir /home/monarch
  --bind "$REPO_ROOT" "$REPO_MNT"
  --unshare-all
  --share-net
  --die-with-parent
  --clearenv
  --chdir "$REPO_MNT${checkout_rel:+/$checkout_rel}"
)

# DNS: docker export leaves /etc/resolv.conf empty, so bind the host's resolver
# config in for network access (uv/pip/npm fetch during builds).
for f in /etc/resolv.conf /etc/hosts; do
  [[ -e "$f" ]] && bwrap_args+=(--ro-bind "$f" "$f")
done

# GPU device nodes: bind every /dev/nvidia* that exists.
shopt -s nullglob
for dev in /dev/nvidia* /dev/nvidia-caps; do
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
  --setenv UV_CACHE_DIR "$CACHE_MNT/uv"
  --setenv CARGO_HOME "$CACHE_MNT/cargo"
  --setenv CARGO_TARGET_DIR "$REPO_MNT/target/bwrap/$RECIPE_SHA256"
  --setenv npm_config_cache "$CACHE_MNT/npm"
  --setenv XDG_CACHE_HOME "$CACHE_MNT/xdg"
  --setenv RUSTUP_HOME /opt/rustup
  --setenv CUDA_HOME /opt/cuda-synth
  --setenv CUDA_PATH /opt/cuda-synth
  --setenv MONARCH_IN_ROOTFS 1
  --setenv MONARCH_ROOTFS_RECIPE_SHA256 "$RECIPE_SHA256"
)
if [[ "$have_nvidia" -eq 1 ]]; then
  bwrap_args+=(--setenv LD_LIBRARY_PATH "$NVIDIA_HOST_MNT:/opt/cuda-synth/lib64")
fi

# Preserve only a documented allowlist across --clearenv: terminal, proxies, GPU
# selection, Rust logging/backtrace, and documented Monarch build flags.
for var in TERM COLORTERM \
           http_proxy https_proxy ftp_proxy no_proxy \
           HTTP_PROXY HTTPS_PROXY FTP_PROXY NO_PROXY \
           NVIDIA_VISIBLE_DEVICES RUST_LOG RUST_BACKTRACE \
           USE_TENSOR_ENGINE MONARCH_GPU_PLATFORM MONARCH_PACKAGE_NAME \
           MONARCH_VERSION ENABLE_MESSAGE_LOGGING; do
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

if [[ $# -eq 0 ]]; then
  exec bwrap "${bwrap_args[@]}" /bin/bash -l
else
  exec bwrap "${bwrap_args[@]}" "$@"
fi
