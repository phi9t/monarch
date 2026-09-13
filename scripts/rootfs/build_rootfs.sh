#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Build a flattened, provenance-stamped rootfs directory for hermetic local runs.
#
# Some hosts (notably Nix-provisioned ones) ship a default cc/clang that targets
# a different dynamic loader and glibc than the system loader rustc runs under.
# That mismatch breaks proc-macro loading and yields extension .so files with
# unresolved __isoc23_* symbols. Rather than patch the toolchain per host, this
# builds a consistent Ubuntu userland from the repo's own PyTorch-CUDA baseline
# image and exports it to a plain directory that enter_rootfs.sh runs under
# bwrap. Inside it, `uv pip install -e .` builds with no toolchain hacks.
#
# The image adds the same system build deps as the repo Dockerfile, uv, Node 20
# and npm, the pinned Rust toolchain (from rust-toolchain), pinned mdBook, and a
# synthetic CUDA_HOME assembled from pip nvidia-cu13 wheels so setup.py / torch
# cpp_extension accept a real nvcc even though the baseline is a runtime image.
#
# All image digests and tool pins come from contract.env. The recipe digest
# (contract.env + this builder + rust-toolchain) labels the image and is written
# into /etc/monarch-rootfs-contract so entry can detect a stale rootfs.
#
# Usage:
#   scripts/rootfs/build_rootfs.sh [options]
#
# Options:
#   --rebuild       Force a docker rebuild even if the image tag exists.
#   --tag TAG       Docker image tag to build/use (default: derived from recipe).
#   --dest DIR      Absolute rootfs export directory named rootfs or rootfs-*.
#                   Defaults to scripts/rootfs/rootfs.
#   --dry-run       Validate and print the resolved build/export plan.
#   -h, --help      Show this help and exit.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOTFS_DIR="$REPO_ROOT/scripts/rootfs"

# shellcheck source=scripts/rootfs/contract.env
source "$ROOTFS_DIR/contract.env"
# shellcheck source=scripts/rootfs/execution_contract.sh
source "$ROOTFS_DIR/execution_contract.sh"

TAG=""
DEST="$ROOTFS_DIR/rootfs"
REBUILD=0
DRY_RUN=0

usage() { sed -n '9,41p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
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

# Architecture gate: the first rootfs implementation is x86_64 only.
host_arch="$(uname -m)"
[[ "$host_arch" == "$MONARCH_ROOTFS_ARCH" ]] || \
  die "unsupported architecture $host_arch: this rootfs supports $MONARCH_ROOTFS_ARCH only"

ROOTFS_RECIPE_SHA256="$(monarch_rootfs_recipe_sha256 "$REPO_ROOT")"
[[ -n "$ROOTFS_RECIPE_SHA256" ]] || die "could not compute rootfs recipe digest"
[[ -n "$TAG" ]] || TAG="monarch-rootfs:${ROOTFS_RECIPE_SHA256:0:16}"

ROOTFS_DIR="$(realpath -e "$ROOTFS_DIR")"
[[ "$DEST" == /* ]] || usage_error "--dest must be absolute: $DEST"
dest_parent_raw="$(dirname -- "$DEST")"
[[ -d "$dest_parent_raw" ]] || usage_error "--dest parent does not exist: $dest_parent_raw"
dest_parent="$(realpath -e "$dest_parent_raw")"
dest_name="$(basename -- "$DEST")"
if [[ ! "$dest_name" =~ ^rootfs(-[A-Za-z0-9._-]+)?$ ]]; then
  usage_error "--dest must be named rootfs or rootfs-*"
fi
DEST="$dest_parent/$dest_name"
[[ ! -L "$DEST" ]] || usage_error "--dest must not be a symbolic link: $DEST"
[[ -w "$dest_parent" ]] || usage_error "--dest parent is not writable: $dest_parent"

# Read the pinned Rust channel from rust-toolchain (e.g. nightly-2026-05-22).
RUST_CHANNEL="$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$REPO_ROOT/rust-toolchain")"
[[ -n "$RUST_CHANNEL" ]] || die "could not parse channel from rust-toolchain"
log "pinned rust channel: $RUST_CHANNEL"
log "rootfs recipe: $ROOTFS_RECIPE_SHA256"
log "rootfs destination: $DEST"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'rootfs destination: %s\n' "$DEST"
  printf 'rootfs recipe: %s\n' "$ROOTFS_RECIPE_SHA256"
  printf 'docker tag: %s\n' "$TAG"
  exit 0
fi

command -v docker >/dev/null || die "docker not found on host"

# Reuse an existing image only when its recipe label matches the current recipe.
image_recipe() {
  docker image inspect --format '{{ index .Config.Labels "org.pytorch.monarch.rootfs-recipe" }}' \
    "$TAG" 2>/dev/null
}

if [[ "$REBUILD" -eq 0 && "$(image_recipe)" == "$ROOTFS_RECIPE_SHA256" ]]; then
  log "image $TAG already matches recipe (use --rebuild to force)"
else
  log "building $TAG from $MONARCH_BASE_IMAGE"
  # Inline Dockerfile via stdin. Keep the build layer minimal: only build deps,
  # uv, Node/npm, the pinned Rust toolchain, mdBook, and a synthetic CUDA_HOME.
  docker build -t "$TAG" \
    --build-arg RUST_CHANNEL="$RUST_CHANNEL" \
    --build-arg BASE_IMAGE="$MONARCH_BASE_IMAGE" \
    --build-arg UV_IMAGE="$MONARCH_UV_IMAGE" \
    --build-arg NODE_IMAGE="$MONARCH_NODE_IMAGE" \
    --build-arg NEXTEST_VERSION="$MONARCH_NEXTEST_VERSION" \
    --build-arg MDBOOK_VERSION="$MONARCH_MDBOOK_VERSION" \
    --build-arg NODE_VERSION="$MONARCH_NODE_VERSION" \
    --build-arg NPM_VERSION="$MONARCH_NPM_VERSION" \
    --build-arg CUDA_NVCC_VERSION="$MONARCH_CUDA_NVCC_VERSION" \
    --build-arg CUDA_CCCL_VERSION="$MONARCH_CUDA_CCCL_VERSION" \
    --build-arg CUDA_CRT_VERSION="$MONARCH_CUDA_CRT_VERSION" \
    --build-arg NVIDIA_NVVM_VERSION="$MONARCH_NVIDIA_NVVM_VERSION" \
    --build-arg CUDA_CUOBJDUMP_VERSION="$MONARCH_CUDA_CUOBJDUMP_VERSION" \
    --build-arg CUDA_NVDISASM_VERSION="$MONARCH_CUDA_NVDISASM_VERSION" \
    --build-arg SETUPTOOLS_VERSION="$MONARCH_SETUPTOOLS_VERSION" \
    --build-arg SETUPTOOLS_RUST_VERSION="$MONARCH_SETUPTOOLS_RUST_VERSION" \
    --build-arg WHEEL_VERSION="$MONARCH_WHEEL_VERSION" \
    --build-arg SEMANTIC_VERSION="$MONARCH_SEMANTIC_VERSION" \
    --build-arg ROOTFS_SCHEMA="$MONARCH_ROOTFS_SCHEMA" \
    --build-arg ROOTFS_ARCH="$MONARCH_ROOTFS_ARCH" \
    --build-arg PYTHON_VERSION="$MONARCH_PYTHON_VERSION" \
    --build-arg UV_VERSION="$MONARCH_UV_VERSION" \
    --build-arg ROOTFS_RECIPE_SHA256="$ROOTFS_RECIPE_SHA256" \
    --label "org.pytorch.monarch.rootfs-recipe=$ROOTFS_RECIPE_SHA256" \
    -f - "$ROOTFS_DIR" <<'DOCKERFILE'
ARG BASE_IMAGE
ARG UV_IMAGE
ARG NODE_IMAGE
FROM ${UV_IMAGE} AS uv
FROM ${NODE_IMAGE} AS node

ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG RUST_CHANNEL
ARG NEXTEST_VERSION
ARG MDBOOK_VERSION
ARG NODE_VERSION
ARG NPM_VERSION
ARG CUDA_NVCC_VERSION
ARG CUDA_CCCL_VERSION
ARG CUDA_CRT_VERSION
ARG NVIDIA_NVVM_VERSION
ARG CUDA_CUOBJDUMP_VERSION
ARG CUDA_NVDISASM_VERSION
ARG SETUPTOOLS_VERSION
ARG SETUPTOOLS_RUST_VERSION
ARG WHEEL_VERSION
ARG SEMANTIC_VERSION
ARG ROOTFS_SCHEMA
ARG ROOTFS_ARCH
ARG PYTHON_VERSION
ARG UV_VERSION
ARG ROOTFS_RECIPE_SHA256
SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# System build deps: superset of the repo Dockerfile list, plus the compilers
# and clang/llvm bindgen needs, matched to this image's glibc.
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        build-essential g++ clang libclang-dev llvm-dev \
        liblzma-dev libunwind-dev libibverbs-dev librdmacm-dev \
        protobuf-compiler pkg-config git curl ca-certificates rsync bubblewrap && \
    rm -rf /var/lib/apt/lists/*

# uv: copy pinned standalone binaries from the official image.
COPY --from=uv /uv /uvx /usr/local/bin/

# Node 20 and npm: copy the runtime and the bundled npm from the official image,
# then recreate the npm/npx launchers the slim image ships as symlinks.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

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

# mdBook: the hyperactor books build with mdbook. Install the pinned version.
RUN cargo install --locked --version "${MDBOOK_VERSION}" mdbook && \
    mdbook --version

# CUDA nvcc and Python build tools: the runtime baseline ships CUDA headers +
# libs under nvidia/cu13/{include,lib} but no compiler. The canonical
# nvidia-cuda-nvcc wheel adds nvidia/cu13/bin/nvcc (+ crt/nvvm) into the same
# tree, so CUDA_HOME can point straight at nvidia/cu13. setup.py get_cuda_home()
# and torch cpp_extension expect bin/nvcc, include/, and lib64/. Runtime JIT
# linkers also use -lcudart, so the synthetic CUDA_HOME must expose the
# unversioned linker name even though the wheel ships the versioned runtime.
RUN pip install --break-system-packages --no-cache-dir \
        "nvidia-cuda-nvcc==${CUDA_NVCC_VERSION}" \
        "nvidia-cuda-cccl==${CUDA_CCCL_VERSION}" \
        "nvidia-cuda-crt==${CUDA_CRT_VERSION}" \
        "nvidia-nvvm==${NVIDIA_NVVM_VERSION}" \
        "nvidia-cuda-cuobjdump==${CUDA_CUOBJDUMP_VERSION}" \
        "nvidia-cuda-nvdisasm==${CUDA_NVDISASM_VERSION}" \
        "setuptools==${SETUPTOOLS_VERSION}" \
        "setuptools-rust==${SETUPTOOLS_RUST_VERSION}" \
        "wheel==${WHEEL_VERSION}" \
        "semantic-version==${SEMANTIC_VERSION}"
RUN set -euo pipefail; \
    site="$(python -c 'import site;print(site.getsitepackages()[0])')"; \
    cu="$site/nvidia/cu13"; \
    test -x "$cu/bin/nvcc" || { echo "nvcc missing at $cu/bin/nvcc" >&2; exit 1; }; \
    test -x "$cu/bin/cuobjdump" || { echo "cuobjdump missing at $cu/bin/cuobjdump" >&2; exit 1; }; \
    test -x "$cu/bin/nvdisasm" || { echo "nvdisasm missing at $cu/bin/nvdisasm" >&2; exit 1; }; \
    test -f "$cu/include/cuda_runtime.h" || { echo "cuda headers missing" >&2; exit 1; }; \
    test -e "$cu/lib/libcudart.so.13" || { echo "cuda runtime missing at $cu/lib/libcudart.so.13" >&2; exit 1; }; \
    ln -sfn libcudart.so.13 "$cu/lib/libcudart.so"; \
    test -e "$cu/lib/libcudart.so" || { echo "cuda runtime linker name missing at $cu/lib/libcudart.so" >&2; exit 1; }; \
    ln -sfn lib "$cu/lib64"; \
    ln -sfn "$cu" /opt/cuda-synth; \
    cudart_minor="$(python -c 'from pathlib import Path; import re; text = Path("/opt/cuda-synth/include/cuda_runtime_api.h").read_text(); match = re.search(r"^#define\s+CUDART_VERSION\s+(\d+)", text, re.M); assert match, "missing CUDART_VERSION"; version = int(match.group(1)); print(f"{version // 1000}.{version % 1000 // 10}")')"; \
    nvcc_minor="$(/opt/cuda-synth/bin/nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\),.*/\1/p' | head -1)"; \
    test "$nvcc_minor" = "$cudart_minor" || { echo "cuda compiler/header mismatch: nvcc $nvcc_minor vs CUDART_VERSION $cudart_minor" >&2; exit 1; }; \
    /opt/cuda-synth/bin/nvcc --version
ENV CUDA_HOME=/opt/cuda-synth CUDA_PATH=/opt/cuda-synth
ENV PATH=/opt/cuda-synth/bin:$PATH

# Verify every reviewed tool pin during the build so a drifted base image fails
# closed rather than producing an unstamped rootfs.
RUN set -euo pipefail; \
    test "$(python --version 2>&1 | awk '{print $2}')" = "${PYTHON_VERSION}"; \
    test "$(uv --version | awk '{print $2}')" = "${UV_VERSION}"; \
    test "$(node --version)" = "v${NODE_VERSION}"; \
    test "$(npm --version)" = "${NPM_VERSION}"; \
    test "$(mdbook --version)" = "mdbook v${MDBOOK_VERSION}"; \
    bwrap --version; \
    cargo nextest --version | grep -q "${NEXTEST_VERSION}"; \
    /opt/cuda-synth/bin/nvcc --version | grep -q "${CUDA_NVCC_VERSION}"

# Provenance: stamp the reviewed contract into the image so entry can detect a
# stale rootfs. The recipe digest is the authoritative identity.
RUN printf '%s\n' \
        "MONARCH_ROOTFS_SCHEMA=${ROOTFS_SCHEMA}" \
        "MONARCH_ROOTFS_RECIPE_SHA256=${ROOTFS_RECIPE_SHA256}" \
        "MONARCH_ROOTFS_ARCH=${ROOTFS_ARCH}" \
        "MONARCH_PYTHON_VERSION=${PYTHON_VERSION}" \
        "MONARCH_UV_VERSION=${UV_VERSION}" \
        "MONARCH_NODE_VERSION=${NODE_VERSION}" \
        "MONARCH_NPM_VERSION=${NPM_VERSION}" \
        "MONARCH_MDBOOK_VERSION=${MDBOOK_VERSION}" \
        "MONARCH_NEXTEST_VERSION=${NEXTEST_VERSION}" \
        "MONARCH_CUDA_NVCC_VERSION=${CUDA_NVCC_VERSION}" \
        "MONARCH_CUDA_CCCL_VERSION=${CUDA_CCCL_VERSION}" \
        "MONARCH_CUDA_CRT_VERSION=${CUDA_CRT_VERSION}" \
        "MONARCH_NVIDIA_NVVM_VERSION=${NVIDIA_NVVM_VERSION}" \
        "MONARCH_CUDA_CUOBJDUMP_VERSION=${CUDA_CUOBJDUMP_VERSION}" \
        "MONARCH_CUDA_NVDISASM_VERSION=${CUDA_NVDISASM_VERSION}" \
        > /etc/monarch-rootfs-contract

# Pre-create the read-only mount points bwrap binds over. A read-only root
# cannot have mkdir applied at entry, and nested bwrap commands need top-level
# bind parents such as /cache before they can attach writable subtrees.
RUN mkdir -p /cache /workspace/monarch /run/nvidia-host

LABEL org.pytorch.monarch.rootfs-recipe=${ROOTFS_RECIPE_SHA256}
DOCKERFILE
fi

# Export the image filesystem to a flattened directory. Export to a temp dir and
# swap into place so an interrupted run never leaves a half-populated rootfs.
log "exporting $TAG to $DEST"
mkdir -p "$dest_parent"
STAGE="$(mktemp -d "$dest_parent/.rootfs.stage.XXXXXX")"
[[ -d "$STAGE" && ! -L "$STAGE" && "$(dirname -- "$STAGE")" == "$dest_parent" ]] || \
  die "mktemp produced an invalid stage directory: $STAGE"
cid="$(docker create "$TAG")"
[[ "$cid" =~ ^[0-9a-f]+$ ]] || die "docker create returned an invalid container id"
cleanup() {
  docker rm -f -- "${cid:?}" >/dev/null 2>&1 || true
  if [[ -d "${STAGE:-}" && ! -L "$STAGE" && \
        "$(dirname -- "$STAGE")" == "$dest_parent" && \
        "$(basename -- "$STAGE")" == .rootfs.stage.* ]]; then
    rm -rf -- "${STAGE:?}"
  fi
}
trap cleanup EXIT
docker export "$cid" | tar -C "$STAGE" -xf -
[[ -x "$STAGE/bin/bash" ]] || die "export produced an unusable rootfs (no bin/bash)"
[[ -r "$STAGE/etc/monarch-rootfs-contract" ]] || die "export is missing the stamped contract"
python3 "$ROOTFS_DIR/verify_rootfs.py" \
  --rootfs "$STAGE" \
  --expected-recipe "$ROOTFS_RECIPE_SHA256" \
  --skip-command-checks >/dev/null || die "export failed rootfs verification"
[[ "$(dirname -- "$DEST")" == "$dest_parent" && ! -L "$DEST" ]] || \
  die "refusing to replace invalid rootfs destination: $DEST"
if [[ -e "$DEST" ]]; then
  [[ -d "$DEST" ]] || die "rootfs destination is not a directory: $DEST"
  rm -rf -- "${DEST:?}"
fi
mv "$STAGE" "$DEST"
python3 "$ROOTFS_DIR/verify_rootfs.py" \
  --rootfs "$DEST" \
  --expected-recipe "$ROOTFS_RECIPE_SHA256" \
  --skip-command-checks >/dev/null || die "rootfs failed post-move verification"

log "rootfs ready: $DEST"
