# Repository Guidelines

## Project Structure & Module Organization
- `hyperactor/`, `hyperactor_mesh/`, and related crates: core Rust actor runtime and messaging infrastructure.
- `monarch_*` crates (e.g., `monarch_hyperactor/`, `monarch_extension/`, `monarch_rdma/`): PyO3 bindings, tensor engine, and RDMA integration.
- `python/monarch/`: public Python API; internal implementation under `python/monarch/_src/`.
- `python/tests/`: Python unit tests.
- `examples/` and `docs/`: runnable demos and documentation sources.

## Build, Test, and Development Commands
Only container build and launch actions are allowed to be done on the host.
All other activitivies must be done within a container.

- `uv sync`: dev setup with tensor engine (CUDA/RDMA required).
- `USE_TENSOR_ENGINE=0 uv sync`: CPU-only setup (actors only).
- `uv run python -c "from monarch import actor; print('ok')"`: sanity check install.
- `uv run cargo nextest run`: Rust tests (requires an active Python env).
- `uv run pytest python/tests/ -v -m "not oss_skip"`: Python tests.
- `flake8 python/`: Python lint (max line length 256).
- `cargo fmt` / `cargo clippy`: Rust formatting and linting.

## Coding Style & Naming Conventions
- Rust: follow `rustfmt.toml` (edition 2024); use `snake_case` for functions/vars and `CamelCase` for types.
- Python: PEP8-ish with `snake_case`; prefer explicit types in public APIs.
- Keep APIs consistent with existing actor/mesh terminology (`Actor`, `ProcMesh`, `ActorMesh`).

## Testing Guidelines
- Rust tests run via `cargo nextest`; ensure a Python env is active for PyO3 linking.
- Python tests live in `python/tests/` and use `pytest`; name tests `test_*.py` and functions `test_*`.
- Tests marked `@pytest.mark.oss_skip` are skipped in OSS runs; avoid depending on them for coverage.

## Commit & Pull Request Guidelines
- Commit messages are short, imperative, and often include a topic or issue tag (e.g., `fix actor shutdown (#1234)`).
- PRs should include a clear description, tests for code changes, and documentation updates for API changes.
- Follow the Meta OSS flow: GitHub PRs are imported into an internal repo before appearing as merged.
- Complete the Meta CLA before contribution acceptance.

## Configuration & Tooling Notes
- Rust nightly `nightly-2025-12-05` is pinned in `rust-toolchain`; Python 3.10+ is expected.
- Default PyTorch index is `pytorch-cu128`; override via `[tool.uv.sources]` in `pyproject.toml` or `uv sync --extra-index-url ...`.
- Set `USE_TENSOR_ENGINE=0` to avoid CUDA/RDMA dependencies during development.

## Build Environment Gotchas (read before running cargo)

**All builds must run inside the container** — host is for container launch only.

**Spack toolchain conflict**: Spack's `cargo` 1.92.0 stable is earlier in `$PATH` than rustup's nightly. Always use `uv run cargo ...`. If `uv` is locked by another process, invoke nightly directly:
```sh
PROTOC=/mnt/data_infra/workspace/monarch/target/protoc/bin/protoc \
  RUSTC=~/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin/rustc \
  ~/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin/cargo <cmd>
```

**protoc**: Required by `tracing-perfetto-sdk-schema`. Pre-built at `target/protoc/bin/protoc` after first `uv sync`. Set `PROTOC` env var before any direct cargo invocation.

**Verification before closing a task**:
- Rust change: `uv run cargo clippy` + `uv run cargo nextest run`
- Python change: `uv run flake8 python/` + `uv run pytest python/tests/ -v -m "not oss_skip"`
- New binary: `uv run cargo build --bin <name>` + `uv run cargo run --bin <name>`
