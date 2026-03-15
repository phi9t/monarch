# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Monarch is a distributed programming framework for PyTorch based on scalable actor messaging. It provides remote actors with mesh-based broadcasting, fault tolerance through supervision trees, point-to-point RDMA transfers for GPU/CPU memory, and distributed tensors sharded across processes.

**Language Stack**: Rust (backend/actor runtime) + Python (user-facing API) with PyO3 bindings

## Build Commands

```sh
# Development setup (with tensor engine - requires CUDA + RDMA)
uv sync

# CPU-only setup (no CUDA/RDMA required)
USE_TENSOR_ENGINE=0 uv sync

# Alternative with pip
pip install -e .
USE_TENSOR_ENGINE=0 pip install -e .

# Verify installation
uv run python -c "from monarch import actor; print('Monarch installed successfully')"
```

**PyTorch CUDA version**: Default is cu128. Change via `[tool.uv.sources]` in pyproject.toml or:
```sh
uv sync --extra-index-url https://download.pytorch.org/whl/cu126
```

## Testing

```sh
# Rust tests (requires activated Python environment)
uv run cargo nextest run

# Python tests
uv run pytest python/tests/ -v -m "not oss_skip"

# Run single Python test
uv run pytest python/tests/test_file.py::test_name -v

# Run single Rust test
uv run cargo nextest run test_name
```

**Note**: Rust binaries link against Python via PyO3. Without an active Python environment, you'll get linking errors.

## Linting/Formatting

```sh
# Python (flake8, max-line-length: 256)
flake8 python/

# Rust formatting
cargo fmt

# Rust clippy
cargo clippy
```

**Rust format config** (rustfmt.toml): Edition 2024, `imports_granularity = "Item"`, `group_imports = "StdExternalCrate"`

## Architecture

### Core Components

**Hyperactor** (`hyperactor/`): Core Rust actor framework providing high-performance scalable messaging. This is the foundational runtime for all actor operations.

**Monarch Extension** (`monarch_extension/`): PyO3-based Python bindings that expose Rust functionality to Python.

**Python API** (`python/monarch/`):
- `actor/` - Public actor API (`Actor`, `@endpoint`, `this_host`, `ProcMesh`)
- `_src/actor/` - Internal actor implementation details
- `common/` - Shared utilities (tensors, device mesh, streams, selections)
- `controller/` - Control plane functionality
- `simulator/` - Testing/simulation infrastructure
- `worker/` - Worker process infrastructure

### Rust Workspace

Key crates:
- `hyperactor`, `hyperactor_mesh` - Core actor framework
- `hyperactor_macros`, `hyperactor_mesh_macros` - Procedural macros
- `monarch_hyperactor` - Main Python bindings wrapper
- `monarch_rdma` - RDMA communication
- `monarch_tensor_worker` - Tensor operations
- `torch-sys2`, `torch-sys-cuda` - PyTorch C++ bindings
- `wirevalue`, `ndslice`, `typeuri` - Supporting data structures

### Key Patterns

**Actor Model**: Actors inherit from `Actor` base class and use `@endpoint` decorator for message handlers. Actors are organized into "meshes" (collections) supporting broadcast messaging.

```python
from monarch.actor import Actor, endpoint, this_host

class Trainer(Actor):
    @endpoint
    def train(self, step: int): ...

procs = this_host().spawn_procs({"gpus": 8})
trainers = procs.spawn("trainers", Trainer)
trainers.train.call(step=0).get()
```

**Lazy Loading**: The top-level `monarch/__init__.py` uses `__getattr__` with `_public_api` dict for on-demand module imports, avoiding unnecessary PyTorch/CUDA loading.

**Mesh Abstractions**:
- `HostMesh` - Host-level mesh with `this_host()` and `this_proc()`
- `ProcMesh` - Process-level mesh from `spawn_procs()`
- `ActorMesh` - Actor-level mesh from `spawn()`

## Build Variants

- **Full build** (default): CUDA + RDMA support for distributed tensors
- **CPU-only** (`USE_TENSOR_ENGINE=0`): Actors only, no tensor engine

## Required Toolchain

- **Rust**: `nightly-2025-12-05` - pinned in `rust-toolchain`
- **Python**: ≥3.10
- **System deps** (full build): clang, libunwind, CUDA toolkit, RDMA libraries (libibverbs, rdma-core)

### Build Environment Gotchas

**Spack toolchain conflict**: Spack installs a `cargo`/`rustc` 1.92.0 stable that shadows the nightly in `$PATH`. Always use `uv run cargo ...` or invoke nightly directly:
```sh
PROTOC=/mnt/data_infra/workspace/monarch/target/protoc/bin/protoc \
  RUSTC=~/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin/rustc \
  ~/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin/cargo <cmd>
```

**protoc**: `tracing-perfetto-sdk-schema` requires protobuf compiler. It is pre-built at `target/protoc/bin/protoc` after the first `uv sync`. Set `PROTOC` before any cargo invocation outside of `uv run`.

**`uv` lock contention**: If another `uv run` process is active, `uv run cargo` will block. Fall back to the direct nightly invocation above.

**`Proc` mutability**: `Proc` must be declared `let mut proc` if `destroy_and_wait` is called.

## Test Markers

- `@pytest.mark.oss_skip` - Exclude from OSS CI (internal Meta tests)
- Default timeout: 5 minutes per test

## Entry Points

- `monarch` - Main CLI (`monarch.tools.cli:main`)
- `monarch_bootstrap` - Worker bootstrap (`monarch._src.actor.bootstrap_main:invoke_main`)
- `worker` - Worker launcher (`monarch.tools.worker:main`)

## Building Documentation

```sh
cd docs
pip install -r requirements.txt
make html
# Output: docs/build/html/
```

## Verification

Done-conditions per task type:

| Task | Done when |
|------|-----------|
| Rust change | `uv run cargo clippy` clean + `uv run cargo nextest run` passes |
| Python change | `uv run flake8 python/` clean + `uv run pytest python/tests/ -v -m "not oss_skip"` passes |
| New `[[bin]]` example | `uv run cargo build --bin <name>` succeeds + `uv run cargo run --bin <name>` exits 0 |
| Formatting | `cargo fmt --check` and `flake8 python/` both clean |

Never declare a task done without running the relevant verification command.

## Compact Instructions

Use `/compact` after: >15 turns on a single task, switching task domains, or when context pressure is evident. Before compacting, confirm current work is at a stable checkpoint (no half-edited files).
