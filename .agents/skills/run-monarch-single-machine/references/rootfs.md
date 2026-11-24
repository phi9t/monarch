# Monarch bwrap rootfs internals

Read this when building, rebuilding, version-bumping, or debugging the Monarch
single-machine bwrap rootfs. The source of truth lives in the Monarch repo under
`scripts/rootfs/`.

## Scripts

- `scripts/rootfs/build_rootfs.sh` builds docker image `monarch-rootfs:local`
  from the repo's PyTorch-CUDA baseline image, then exports a flattened rootfs
  into `scripts/rootfs/rootfs/`. It skips the docker build when the image tag
  already exists unless `--rebuild` is passed. The rootfs export is staged in a
  temp dir and swapped into place atomically.
- `scripts/rootfs/enter_rootfs.sh` wraps `bwrap`: rootfs bound at `/`, fresh
  `/proc`/`/tmp`/`/dev`, repo mounted rw at `/workspace/monarch`, all existing
  `/dev/nvidia*` nodes dev-bound, host NVIDIA driver libs and `nvidia-smi`
  ro-bound, host `/etc/resolv.conf` and `/etc/hosts` ro-bound for DNS,
  `--unshare-all --share-net --die-with-parent`, and `MONARCH_IN_ROOTFS=1`.
  It auto-builds the rootfs if missing.
- `scripts/rootfs/run_in_rootfs.sh` runs inside bwrap: creates/reuses
  `.venv-rootfs` with `uv venv --python 3.12 --system-site-packages`, synchronizes
  the test environment through `scripts/rootfs/sync_test_environment.sh`, then
  delegates to `scripts/run_local_control_plane.sh`.
- `scripts/rootfs/sync_test_environment.sh` synchronizes the frozen `uv.lock`,
  replaces its Linux-only `torchx-nightly==2021.10.28` selection with the
  hash-pinned `2026.7.27` wheel already present in the lock, and installs the
  project editable with dependency resolution disabled using the build tools
  pinned in the rootfs. The override is required because the vendored 2021
  TorchX release cannot import on Python 3.12.

`scripts/run` re-execs into the sandbox via `enter_rootfs.sh` and activates
`.venv-rootfs`; `scripts/run_local_control_plane.sh` re-execs itself through
`scripts/run` when invoked outside the rootfs. The `MONARCH_IN_ROOTFS=1` marker
prevents recursion. Inside the rootfs, `prepare_rust_toolchain()` should be a
no-op because the rootfs `cc`/`clang` already targets the same loader/glibc as
`rustc`.

The checked-in `uv.lock` is generated with Meta's vendored-version overrides.
Use frozen syncs inside the rootfs; plain `uv lock` cannot reproduce the file
and rewrites unrelated dependency versions.

## Image contents

Base image:

```text
ghcr.io/pytorch/pytorch:2.13.0-cuda13.2-cudnn9-runtime@sha256:7492928e093d67276716440161f694a0e4ea27796d599d64b23cb76cdd665e71
```

Verified baseline facts: Python 3.12.3, torch 2.13.0+cu132, glibc 2.39. It is
a runtime image, not a devel image, so it has no `/usr/local/cuda`; CUDA runtime
bits come from pip wheels.

The build layer installs:

```text
build-essential g++ clang libclang-dev llvm-dev liblzma-dev libunwind-dev
libibverbs-dev librdmacm-dev protobuf-compiler pkg-config git curl
ca-certificates rsync
```

The baseline and `uv` images are digest-pinned. The build also installs pinned
`uv` 0.12.2, the Rust channel from repo
`rust-toolchain` via rustup, pinned `cargo-nextest` 0.9.143, and CUDA nvcc from
the pinned `nvidia-cuda-nvcc==13.3.73` and
`nvidia-cuda-cccl==13.3.3.4.1` wheels. Editable builds use pinned
`setuptools==81.0.0`, `setuptools-rust==1.12.0`, `wheel==0.47.0`, and
`semantic-version==2.10.0` from the rootfs system site-packages.

Ubuntu build packages follow the current Noble package repositories and are not
snapshot-pinned. A rebuild can therefore incorporate newer security updates
even though the container bases and application-level build tools are pinned.

## Synthetic CUDA_HOME

`setup.py` and torch `cpp_extension` require `CUDA_HOME` with `bin/nvcc`,
`include/`, and `lib64/`. The runtime base image has CUDA headers/libs under
`site-packages/nvidia/cu13/{include,lib}` but no compiler. The rootfs builder
installs canonical `nvidia-cuda-nvcc` and `nvidia-cuda-cccl` wheels, which add
`nvidia/cu13/bin/nvcc` and compiler support into the same tree, then creates:

```text
/opt/cuda-synth -> <site-packages>/nvidia/cu13
<site-packages>/nvidia/cu13/lib64 -> lib
CUDA_HOME=/opt/cuda-synth
```

Do not use deprecated `nvidia-cuda-nvcc-cu13`, `nvidia-cuda-runtime-cu13`, or
`nvidia-cuda-cccl-cu13` stub packages.

## Rebuild and version bump procedure

After editing the inline Dockerfile in `build_rootfs.sh`, changing system deps,
or bumping the repo `rust-toolchain` channel:

```sh
scripts/rootfs/build_rootfs.sh --rebuild
rm -rf .venv-rootfs
scripts/run scripts/run_local_control_plane.sh --rust-only
```

For a fully clean rootfs export as well:

```sh
rm -rf scripts/rootfs/rootfs
scripts/rootfs/build_rootfs.sh --rebuild
rm -rf .venv-rootfs
```

For custom image tags or destinations, the destination must be a direct child
of `scripts/rootfs/` named `rootfs` or `rootfs-*`:

```sh
scripts/rootfs/build_rootfs.sh --tag monarch-rootfs:experiment --dest scripts/rootfs/rootfs-experiment
scripts/rootfs/enter_rootfs.sh --rootfs scripts/rootfs/rootfs-experiment -- nvidia-smi -L
```

## Troubleshooting

- **DNS failures in bwrap**: confirm `enter_rootfs.sh` ro-binds host
  `/etc/resolv.conf` and `/etc/hosts`.
- **`no such command: nextest`**: rebuild the rootfs; nextest should be baked
  into `/opt/cargo/bin`.
- **GPUs not visible**: confirm host `/dev/nvidia*`, host driver libs, and that
  `CUDA_VISIBLE_DEVICES` is not set to an empty string.
- **Build links against host/Nix toolchain**: ensure the command is run through
  `scripts/run` (or `enter_rootfs.sh`). Do not pass `CC`, `LIBCLANG_PATH`, or
  `BINDGEN_EXTRA_CLANG_ARGS` unless deliberately debugging.
- **Python full-suite failures that pass alone**: treat as cross-test state
  fragility in the unprivileged user namespace, not as rootfs build failure.
- **Corrupt or partial rootfs**: remove `scripts/rootfs/rootfs/` and re-run
  `scripts/rootfs/build_rootfs.sh`; export is atomic on normal builds.

## Quick verification

```sh
scripts/run nvidia-smi -L
scripts/run python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.device_count())'
scripts/run scripts/run_local_control_plane.sh --rust-only
```
