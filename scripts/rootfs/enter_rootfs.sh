#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Enter the hermetic rootfs under bubblewrap, with local GPUs and the repo
# bind-mounted, then run either an interactive shell or a passed command.
#
# The rootfs (built by build_rootfs.sh) provides a consistent Ubuntu userland so
# the Rust/CUDA build needs no CC/LIBCLANG_PATH host overrides. The in-rootfs
# CUDA runtime (pip nvidia-cu13 wheels) is linked against the *host* NVIDIA
# driver userspace, which we read-only bind in so its version matches the loaded
# kernel module. Real /dev/nvidia* nodes are bound so tests run on local GPUs.
#
# Usage:
#   scripts/rootfs/enter_rootfs.sh [-- <command> [args...]]
#
# With no command, drops into an interactive bash shell inside the rootfs. If the
# rootfs directory is missing, it is built automatically via build_rootfs.sh, so
# a first run is a single command. Honors CUDA_VISIBLE_DEVICES from the caller
# (empty string hides all GPUs, which the control-plane preflight treats as a
# hard failure).
#
# Options:
#   --rootfs DIR    Rootfs directory to enter (default: scripts/rootfs/rootfs).
#   -h, --help      Show this help and exit.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

ROOTFS="$REPO_ROOT/scripts/rootfs/rootfs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rootfs) ROOTFS="$2"; shift 2 ;;
    --rootfs=*) ROOTFS="${1#*=}"; shift ;;
    --) shift; break ;;
    -h|--help) sed -n '9,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

command -v bwrap >/dev/null || die "bwrap not found on host"

# Auto-build the rootfs on first use so `--rootfs` is a single command. A rootfs
# is considered ready only if it has a populated bin/ (docker export of an empty
# or interrupted build would leave a bare directory). build_rootfs.sh is
# idempotent and swaps the export into place atomically.
if [[ ! -x "$ROOTFS/bin/bash" ]]; then
  printf '\033[1m== rootfs not found at %s; building it ==\033[0m\n' "$ROOTFS" >&2
  "$REPO_ROOT/scripts/rootfs/build_rootfs.sh" --dest "$ROOTFS"
  [[ -x "$ROOTFS/bin/bash" ]] || die "rootfs build did not produce a usable rootfs at $ROOTFS"
fi

REPO_MNT=/workspace/monarch

# Base bwrap args: consistent rootfs, fresh proc/tmp/dev, repo mounted rw.
bwrap_args=(
  --bind "$ROOTFS" /
  --proc /proc
  --tmpfs /tmp
  --dev /dev
  --bind "$REPO_ROOT" "$REPO_MNT"
  --unshare-all --share-net
  --die-with-parent
  --chdir "$REPO_MNT"
)

# DNS: docker export leaves /etc/resolv.conf empty, so bind the host's resolver
# config in for network access (uv/pip fetch from PyPI during the build).
for f in /etc/resolv.conf /etc/hosts; do
  [[ -e "$f" ]] && bwrap_args+=(--ro-bind "$f" "$f")
done

# GPU device nodes: bind every /dev/nvidia* that exists (nvidiactl, nvidia0..N,
# nvidia-uvm, nvidia-uvm-tools, modeset, caps).
shopt -s nullglob
for dev in /dev/nvidia* /dev/nvidia-caps; do
  bwrap_args+=(--dev-bind "$dev" "$dev")
done

# Host NVIDIA driver userspace: read-only bind every libcuda/libnvidia-* and the
# nvidia-smi binary so the in-rootfs runtime links the matching host driver.
HOST_LIBDIR=/usr/lib/x86_64-linux-gnu
for lib in "$HOST_LIBDIR"/libcuda.so* "$HOST_LIBDIR"/libnvidia-*.so*; do
  bwrap_args+=(--ro-bind "$lib" "$lib")
done
if [[ -x /usr/bin/nvidia-smi ]]; then
  bwrap_args+=(--ro-bind /usr/bin/nvidia-smi /usr/bin/nvidia-smi)
fi
shopt -u nullglob

# Environment: rootfs toolchain paths, synthetic CUDA_HOME, marker for the
# rootfs-aware run_local_control_plane.sh re-exec guard.
bwrap_args+=(
  --setenv PATH "/opt/cuda-synth/bin:/opt/cargo/bin:/usr/local/bin:/usr/bin:/bin"
  --setenv CUDA_HOME /opt/cuda-synth
  --setenv CUDA_PATH /opt/cuda-synth
  --setenv RUSTUP_HOME /opt/rustup
  --setenv CARGO_HOME /opt/cargo
  --setenv LD_LIBRARY_PATH "$HOST_LIBDIR:/opt/cuda-synth/lib64"
  --setenv MONARCH_IN_ROOTFS 1
  --setenv HOME /root
)

# Pass through GPU selection. An explicitly empty value is meaningful (hide all
# GPUs) and is honored so the negative preflight check works.
if [[ "${CUDA_VISIBLE_DEVICES+set}" == set ]]; then
  bwrap_args+=(--setenv CUDA_VISIBLE_DEVICES "$CUDA_VISIBLE_DEVICES")
fi
bwrap_args+=(--setenv NVIDIA_VISIBLE_DEVICES "${NVIDIA_VISIBLE_DEVICES:-all}")

if [[ $# -eq 0 ]]; then
  exec bwrap "${bwrap_args[@]}" /bin/bash -l
else
  exec bwrap "${bwrap_args[@]}" "$@"
fi
