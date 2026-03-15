# Monarch testing mechanism

## Rust tests (on host, CPU-only)

Use when you want to run Rust tests without the full dev container or GPU stack.

**Requirements**

- Rust nightly (from `rust-toolchain`: `nightly-2025-12-05`)
- `protoc` — use the repo copy at `.tools/protoc/bin/protoc`, or install system protobuf-compiler / download from [Protocol Buffers releases](https://github.com/protocolbuffers/protobuf/releases)

**Command**

```bash
cd /mnt/data_infra/workspace/monarch
PATH="$HOME/.cargo/bin:$PATH" \
PROTOC="$(pwd)/.tools/protoc/bin/protoc" \
USE_TENSOR_ENGINE=0 MONARCH_BUILD_MESH_ONLY=1 RUSTFLAGS="--cfg tracing_unstable" \
cargo test --workspace \
  --exclude nccl-sys --exclude torch-sys2 --exclude torch-sys-cuda --exclude rdmaxcel-sys \
  --exclude monarch_rdma --exclude monarch_tensor_worker --exclude monarch_extension \
  --exclude monarch_cpp_static_libs --exclude monarch_messages \
  --no-fail-fast
```

**Excluded crates (need CUDA/NCCL/torch/rdma)**  
`nccl-sys`, `torch-sys2`, `torch-sys-cuda`, `rdmaxcel-sys`, `monarch_rdma`, `monarch_tensor_worker`, `monarch_extension`, `monarch_cpp_static_libs`, `monarch_messages`.

---

## Python tests

- **In dev container:** After `python setup.py develop`, run:
  ```bash
  pytest python/tests/ -v -m "not oss_skip"
  ```
- **Dependencies:** See `python/tests/requirements.txt`.

---

## Container-based full test

**GPU dev (root)**

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec dev monarch-test
```

**CPU dev (dev/)**

```bash
cd dev && docker compose up -d
docker compose exec monarch-dev bash -c '
  source /opt/conda/etc/profile.d/conda.sh && conda activate monarch
  cd /workspace && python setup.py develop
  cargo nextest run --workspace
  pytest python/tests/ -v -m "not oss_skip"
'
```

Or use the helper script (builds image, starts container, runs tests):

```bash
./dev/launch-and-test.sh
```

---

## One-off protoc setup (host)

If `.tools/protoc/bin/protoc` is missing:

```bash
mkdir -p .tools
docker run --rm -v "$(pwd)/.tools:/out" ubuntu:22.04 bash -c \
  "apt-get update -qq && apt-get install -y -qq protobuf-compiler && cp /usr/bin/protoc /out/protoc"
# Binary will be at .tools/protoc (or .tools/protoc/bin/protoc if you used a release zip)
```

Then set `PROTOC="$(pwd)/.tools/protoc/bin/protoc"` (or `.tools/protoc`) when running `cargo test` above.
