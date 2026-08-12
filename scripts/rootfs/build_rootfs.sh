#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Build a flattened rootfs directory for hermetic control-plane runs.
#
# Some hosts (notably Nix-provisioned ones) ship a default cc/clang that targets
# a different dynamic loader and glibc than the system loader rustc runs under.
# That mismatch breaks proc-macro loading and yields extension .so files with
# unresolved __isoc23_* symbols. Rather than patch the toolchain per host, this
# builds a consistent Ubuntu userland from the repo's own PyTorch-CUDA baseline
# image and exports it to a plain directory that enter_rootfs.sh runs under
# bwrap. Inside it, `uv pip install -e .` builds with no toolchain hacks.
#
# The image adds the same system build deps as the repo Dockerfile, uv, the
# pinned Rust toolchain (from rust-toolchain), and a synthetic CUDA_HOME
# assembled from pip nvidia-cu13 wheels so setup.py / torch cpp_extension accept
# a real nvcc even though the baseline is a runtime (not devel) image.
#
# Usage:
#   scripts/rootfs/build_rootfs.sh [options]
#
# Options:
#   --rebuild       Force a docker rebuild even if the image tag exists.
#   --tag TAG       Docker image tag to build/use (default: monarch-rootfs:local).
#   --dest DIR      Managed directory under scripts/rootfs/ named rootfs or
#                   rootfs-* (default: scripts/rootfs/rootfs).
#   -h, --help      Show this help and exit.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOTFS_DIR="$REPO_ROOT/scripts/rootfs"

TAG="monarch-rootfs:local"
DEST="$ROOTFS_DIR/rootfs"
REBUILD=0
BASE_IMAGE="ghcr.io/pytorch/pytorch:2.13.0-cuda13.2-cudnn9-runtime@sha256:7492928e093d67276716440161f694a0e4ea27796d599d64b23cb76cdd665e71"
UV_IMAGE="ghcr.io/astral-sh/uv:0.12.2@sha256:069a51314a7bb6031777a9273205fe1b0b19e914ef418207d1338b268df641dd"
NEXTEST_VERSION="0.9.143"
CUDA_NVCC_VERSION="13.3.73"
CUDA_CCCL_VERSION="13.3.3.4.1"
SETUPTOOLS_VERSION="81.0.0"
SETUPTOOLS_RUST_VERSION="1.12.0"
WHEEL_VERSION="0.47.0"
SEMANTIC_VERSION="2.10.0"

usage() { sed -n '9,35p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    --tag) TAG="$2"; shift 2 ;;
    --tag=*) TAG="${1#*=}"; shift ;;
    --dest) DEST="$2"; shift 2 ;;
    --dest=*) DEST="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }
usage_error() { printf 'error: %s\n' "$*" >&2; exit 2; }

ROOTFS_DIR="$(realpath -e "$ROOTFS_DIR")"
dest_parent="$(realpath -m "$(dirname -- "$DEST")")"
dest_name="$(basename -- "$DEST")"
if [[ "$dest_parent" != "$ROOTFS_DIR" || ! "$dest_name" =~ ^rootfs(-[A-Za-z0-9._-]+)?$ ]]; then
  usage_error "--dest must be a managed rootfs path under $ROOTFS_DIR named rootfs or rootfs-*"
fi
DEST="$dest_parent/$dest_name"
[[ ! -L "$DEST" ]] || usage_error "--dest must not be a symbolic link: $DEST"

command -v docker >/dev/null || die "docker not found on host"

# Read the pinned Rust channel from rust-toolchain (e.g. nightly-2026-05-22).
RUST_CHANNEL="$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$REPO_ROOT/rust-toolchain")"
[[ -n "$RUST_CHANNEL" ]] || die "could not parse channel from rust-toolchain"
log "pinned rust channel: $RUST_CHANNEL"

image_exists() { docker image inspect "$TAG" >/dev/null 2>&1; }

if image_exists && [[ "$REBUILD" -eq 0 ]]; then
  log "image $TAG already exists (use --rebuild to force)"
else
  log "building $TAG from $BASE_IMAGE"
  # Inline Dockerfile via stdin. Keep the build layer minimal: only build deps,
  # uv, the pinned Rust toolchain, and a synthetic CUDA_HOME from pip wheels.
  docker build -t "$TAG" \
    --build-arg RUST_CHANNEL="$RUST_CHANNEL" \
    --build-arg BASE_IMAGE="$BASE_IMAGE" \
    --build-arg UV_IMAGE="$UV_IMAGE" \
    --build-arg NEXTEST_VERSION="$NEXTEST_VERSION" \
    --build-arg CUDA_NVCC_VERSION="$CUDA_NVCC_VERSION" \
    --build-arg CUDA_CCCL_VERSION="$CUDA_CCCL_VERSION" \
    --build-arg SETUPTOOLS_VERSION="$SETUPTOOLS_VERSION" \
    --build-arg SETUPTOOLS_RUST_VERSION="$SETUPTOOLS_RUST_VERSION" \
    --build-arg WHEEL_VERSION="$WHEEL_VERSION" \
    --build-arg SEMANTIC_VERSION="$SEMANTIC_VERSION" \
    -f - "$ROOTFS_DIR" <<'DOCKERFILE'
ARG BASE_IMAGE
ARG UV_IMAGE
FROM ${UV_IMAGE} AS uv

FROM ${BASE_IMAGE}
ARG RUST_CHANNEL
ARG NEXTEST_VERSION
ARG CUDA_NVCC_VERSION
ARG CUDA_CCCL_VERSION
ARG SETUPTOOLS_VERSION
ARG SETUPTOOLS_RUST_VERSION
ARG WHEEL_VERSION
ARG SEMANTIC_VERSION
SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# System build deps: superset of the repo Dockerfile list, plus the compilers
# and clang/llvm bindgen needs, matched to this image's glibc.
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        build-essential g++ clang libclang-dev llvm-dev \
        liblzma-dev libunwind-dev libibverbs-dev librdmacm-dev \
        protobuf-compiler pkg-config git curl ca-certificates rsync && \
    rm -rf /var/lib/apt/lists/*

# uv: copy pinned standalone binaries from the official image.
COPY --from=uv /uv /uvx /usr/local/bin/

# Pinned Rust toolchain via rustup, reading the repo's rust-toolchain channel.
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo
ENV PATH=/opt/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
        sh -s -- -y --no-modify-path --profile minimal \
            --default-toolchain "${RUST_CHANNEL}" \
            --component rustfmt --component clippy && \
    rustc --version && cargo --version

# cargo-nextest: the Rust control-plane suite runs under nextest for process
# isolation. Install the prebuilt binary into CARGO_HOME/bin (fast + hermetic).
RUN curl -LsSf "https://get.nexte.st/${NEXTEST_VERSION}/linux" | \
        tar -C /opt/cargo/bin -xzf - && \
    cargo nextest --version

# CUDA nvcc and Python build tools: the runtime baseline ships CUDA headers +
# libs under nvidia/cu13/{include,lib} but no compiler. The canonical
# nvidia-cuda-nvcc wheel adds nvidia/cu13/bin/nvcc (+ crt/nvvm) into the same
# tree, so CUDA_HOME can point straight at nvidia/cu13. setup.py get_cuda_home() and torch
# cpp_extension expect bin/nvcc, include/, and lib64/, so symlink lib64 -> lib.
RUN pip install --break-system-packages --no-cache-dir \
        "nvidia-cuda-nvcc==${CUDA_NVCC_VERSION}" \
        "nvidia-cuda-cccl==${CUDA_CCCL_VERSION}" \
        "setuptools==${SETUPTOOLS_VERSION}" \
        "setuptools-rust==${SETUPTOOLS_RUST_VERSION}" \
        "wheel==${WHEEL_VERSION}" \
        "semantic-version==${SEMANTIC_VERSION}"
RUN set -euo pipefail; \
    site="$(python -c 'import site;print(site.getsitepackages()[0])')"; \
    cu="$site/nvidia/cu13"; \
    test -x "$cu/bin/nvcc" || { echo "nvcc missing at $cu/bin/nvcc" >&2; exit 1; }; \
    test -f "$cu/include/cuda_runtime.h" || { echo "cuda headers missing" >&2; exit 1; }; \
    ln -sfn lib "$cu/lib64"; \
    ln -sfn "$cu" /opt/cuda-synth; \
    /opt/cuda-synth/bin/nvcc --version
ENV CUDA_HOME=/opt/cuda-synth CUDA_PATH=/opt/cuda-synth
ENV PATH=/opt/cuda-synth/bin:$PATH
DOCKERFILE
fi

# Export the image filesystem to a flattened directory. Export to a temp dir and
# swap into place so an interrupted run never leaves a half-populated rootfs.
log "exporting $TAG to $DEST"
mkdir -p "$ROOTFS_DIR"
STAGE="$(mktemp -d "$ROOTFS_DIR/.rootfs.stage.XXXXXX")"
[[ -d "$STAGE" && ! -L "$STAGE" && "$(dirname -- "$STAGE")" == "$ROOTFS_DIR" ]] || \
  die "mktemp produced an invalid stage directory: $STAGE"
cid="$(docker create "$TAG")"
[[ "$cid" =~ ^[0-9a-f]+$ ]] || die "docker create returned an invalid container id"
cleanup() {
  docker rm -f -- "${cid:?}" >/dev/null 2>&1 || true
  if [[ -d "${STAGE:-}" && ! -L "$STAGE" && \
        "$(dirname -- "$STAGE")" == "$ROOTFS_DIR" && \
        "$(basename -- "$STAGE")" == .rootfs.stage.* ]]; then
    rm -rf -- "${STAGE:?}"
  fi
}
trap cleanup EXIT
docker export "$cid" | tar -C "$STAGE" -xf -
[[ -x "$STAGE/bin/bash" ]] || die "export produced an unusable rootfs (no bin/bash)"
[[ "$(dirname -- "$DEST")" == "$ROOTFS_DIR" && ! -L "$DEST" ]] || \
  die "refusing to replace invalid rootfs destination: $DEST"
if [[ -e "$DEST" ]]; then
  [[ -d "$DEST" ]] || die "rootfs destination is not a directory: $DEST"
  rm -rf -- "${DEST:?}"
fi
mv "$STAGE" "$DEST"

log "rootfs ready: $DEST"
