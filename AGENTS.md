# AGENTS.md

Guidance for agents and developers working in the Monarch repository. For deeper
build/architecture detail see `MONARCH_INFO.md`; for using the Python API see
`docs/DOCS_INDEX.md`.

## Constitution

Read and follow `CONSTITUTION.md` at the repository root before acting. It sets
the default operating principles for coding agents; direct user instructions and
the more specific guidance in this file override it. The copy is pinned to a
reviewed release tag (`v2026.08.11`) — update it through normal pull-request
review, not by fetching a newer version at startup.

## Project Overview

Monarch (`torchmonarch`) is a distributed programming framework for PyTorch
built on scalable actor messaging. It provides:

- Remote actors with scalable messaging, grouped into collections called
  **meshes** that receive broadcast messages.
- Fault tolerance through **supervision trees**: actors/processes form a tree and
  failures propagate upward; the root actor supervises all others.
- Point-to-point **RDMA** transfers over libibverbs (any GPU or CPU memory).
- **Distributed tensors** sharded across processes.

Architecture is a Rust core with a thin Python API:

- **Rust core** — actor system, messaging, RDMA, tensor ops. A Cargo workspace of
  ~40 crates. Key ones: `hyperactor` (core actor impl), `hyperactor_mesh` (mesh
  management), `monarch_extension` (PyO3 bindings), `monarch_rdma`,
  `monarch_tensor_worker`, `torch-sys2`/`torch-sys-cuda` (libtorch bindings),
  `ndslice`, `serde_multipart`. `monarch_mini` is a self-contained mini
  implementation.
- **Python API** — `python/monarch/`, exposing actors, proc meshes, RDMA, and
  distributed tensors. Entry example: `from monarch.actor import Actor, endpoint,
  this_host`.
- **Tensor Engine** — optional GPU/RDMA layer. Actors work without it (and without
  torch); set `USE_TENSOR_ENGINE=0` for a lighter, CPU/actor-only build.

This is a mirror of an internal Meta fbsource monorepo. GitHub PRs are imported
internally, not merged directly (see `CONTRIBUTING.md`). Treat `monarch` as a
monorepo: when refactoring, update all in-repo usages and do not preserve
backward compatibility for internal implementation crates.

## Agent Skills

Shared agent skills for this repository live under `.agents/skills/` in the
repo root. Prefer repo-local skills there over user-level `~/.agents` or
tool-specific directories so all coding agents working in this checkout see the
same Monarch-specific workflows. The `run-monarch-single-machine` skill is the
canonical guide for running Monarch on one host through the hermetic bwrap
rootfs and for building or maintaining that rootfs.

For broad, multi-area codebase exploration or distributed-training design work,
use the `.agents/skills/subagent-exploration` skill to split read-heavy
investigation and disjoint implementation slices across focused subagents while
keeping synthesis in the main thread.

## Build & Commands

Every Linux-local Monarch command runs through `scripts/run`, the sole gateway
into the hermetic bwrap rootfs. `scripts/run <command> [args...]` re-execs inside
the sandbox, maps the caller's directory to the matching checkout-relative
directory, activates the rootfs virtual environment, and preserves the command's
arguments and exit status; `scripts/run` with no arguments opens an interactive
rootfs shell. The rootfs carries a validated PyTorch-CUDA baseline (Ubuntu glibc
2.39, system gcc/clang, Python 3.12, torch 2.13.0+cu132) and pinned Rust, so
`uv`, `cargo`, `pytest`, `make`, `npm`, and checkout Python all build with no
toolchain hacks. `enter_rootfs.sh` auto-builds the rootfs on first use, so
`scripts/run` is a single command from a clean checkout.

Monarch uses `uv` for Python and `setuptools-rust` to build the Rust extension.
PyO3 links against Python, so the rootfs venv must be active for `cargo`
commands; `scripts/run` activates it (running `cargo` outside the gateway on a
bare host yields `could not find native static library python3.12`).

```sh
# Development install (GPU/tensor engine auto-detected)
scripts/run uv sync

# CPU-only / actors-only (no torch, CUDA, or RDMA needed)
scripts/run env USE_TENSOR_ENGINE=0 uv sync

# Rebuild after Rust changes
scripts/run uv pip install -e .

# Build a wheel (reuses cached rust builds)
scripts/run uv build --wheel --no-build-isolation

# Verify
scripts/run uv run python -c "from monarch import actor; print('ok')"
```

The following Linux-local work is exempt from `scripts/run` because it names a
separate execution domain: **host bootstrap** (building and entering the rootfs
via `scripts/rootfs/`), **GitHub Actions** and other controlled CI, **native
macOS**, **installed wheels** (`pip install torchmonarch`), Meta-internal builds,
and **remote workers**. None nest the local bwrap.

Docs build inside the rootfs; see the [Documentation](#documentation) section.

Meta-internal tooling (not available in OSS) includes `./check`
(lint/typecheck/test), `arc f`, `arc autocargo -p monarch`, `arc pyre`, and
`buck2`. Use the `scripts/run` commands above for OSS work.

### Build Environment Variables

- `USE_TENSOR_ENGINE=0` — build actors only, no tensor engine (no torch).
- `MONARCH_GPU_PLATFORM` — `cuda`, `rocm`, or `none` (force CPU tensor engine).
  Unset auto-detects; required when both CUDA and ROCm are installed.
- `MONARCH_PACKAGE_NAME`, `MONARCH_VERSION` — override package name/version.
- `ENABLE_MESSAGE_LOGGING` — enable hyperactor message logging.

## Code Style

From `MONARCH_INFO.md` (authoritative) plus tool configs:

- **Follow surrounding code style.** Prefer short, clear names and succinct noun
  phrases. Document all public functions and classes.
- **Comments** only when the implementation is subtle; do not restate what code
  does. No decorative comments or section headers in code — use modules/structs/
  impl blocks for organization. Use Markdown (Rust) or reStructuredText (Python)
  when structure is needed.
- **Prose** (docs, comments, commit messages) follows Strunk & White; Oxford
  comma; "you" = reader, "we" = author; "that" for restrictive clauses, "which"
  for non-restrictive.
- **Rust design:** make illegal states unrepresentable (prefer enums over
  always-`Some` `Option`s). Do NOT code defensively — on violated invariants,
  `panic!`/`.unwrap()` rather than returning errors. Embrace the actor model and
  supervision tree for concurrency and fault tolerance. `use` at module scope
  (top of `mod tests` in tests), not inside functions. Avoid type aliases in
  `use`; use qualified identifiers to disambiguate.
- **Rust error and log (tracing) messages:** concise lowercase sentences, no
  trailing punctuation; use `:` for context (`operation xyz: disk i/o error`);
  prefer structured logging.
- **Rust formatting** (`rustfmt.toml`): edition 2024, `imports_granularity=Item`,
  `group_imports=StdExternalCrate`, `merge_derives=false`,
  `use_field_init_shorthand=true`, `format_code_in_doc_comments=true`. Run
  `scripts/run cargo fmt`.
- **Rust lint:** `scripts/run cargo clippy`. `clippy.toml` sets
  `too-many-lines-threshold=200` and disallows `await`-holding `tracing` span
  guards. `.cargo/config.toml` mirrors the internal allowed-lint set — keep both
  in sync.
- **Python formatting:** ufmt/ruff (`ruff-api`), target `py310`. Linting via
  flake8 (`.flake8`, `max-line-length=256`). Run `scripts/run flake8 python/`.
- **Toolchain:** Rust pinned to `nightly-2026-05-22` (`rust-toolchain`); Python
  3.10–3.13 (repo pins 3.12 for wheels/docker; `.python-version` is 3.12).
- Never commit code that fails the type checkers (rustc / pyre / pyright).
- For large changes, include a "walkthrough" in the commit message.

## Testing

Both Rust and Python tests exist. Rust tests use `cargo-nextest` for process
isolation; Python uses `pytest`.

```sh
# Python — install test deps then run (skip Meta-only tests)
scripts/run uv sync --extra test
scripts/run uv run pytest python/tests/ -v -m "not oss_skip"
scripts/run uv run pytest python/tests/ -v -m "not oss_skip" -n auto   # parallel

# Rust — the gateway activates the Python env for PyO3 linking
scripts/run uv sync
scripts/run uv run cargo nextest run          # install: scripts/run cargo install cargo-nextest --locked
```

### Local control-plane test run

`scripts/run_local_control_plane.sh` is a hermetic entrypoint that brings up the
control plane (host/proc/actor meshes and supervision) on the local host using
local GPUs and runs both suites: the Python tests marked
`@pytest.mark.control_plane` (under `--crash-recovery`) and the Rust coordination
crates (`hyperactor`, `hyperactor_mesh`, `hyperactor_cast`, `hyperactor_config`,
`ndslice`) via nextest. Everything runs on `this_host()` / local in-process
meshes — no CI variables and no remote or distributed execution. It requires an
active Python env (PyO3 linking), a tensor-engine build, and at least one local
GPU, and aborts in preflight rather than skipping if any is missing. Flags:
`--python-only`, `--rust-only`, `--gpus N`, `--keep-going`. Results land in
`control-plane-results/`.

For all-local-GPU tensor-engine capacity, use
`scripts/run_local_8gpu_capacity.sh`. It reuses the same bwrap rootfs, builds
the tensor-engine editable install in `.venv-rootfs`, requires exactly eight
visible CUDA devices, runs an 8-rank distributed tensor smoke that fetches one
rank shard per GPU, and then runs the local control-plane suites with all eight
GPUs exposed.

The 8-GPU verifier's acceptance ladder is explicit:

- **Environment:** enter the rootfs, set default `CUDA_VISIBLE_DEVICES` to
  `0,1,2,3,4,5,6,7` when unset or empty, reject explicit lists that do not have
  exactly eight non-empty entries, require `CUDA_HOME`, `uv`, and `.venv-rootfs`.
- **Build:** install Monarch editable with test dependencies and the tensor
  engine enabled. Synchronize the frozen `uv.lock` test dependencies, then
  replace its Linux-only `torchx-nightly==2021.10.28` selection with the
  hash-pinned `2026.7.27` wheel already recorded in that lock, and install the
  project editable without resolving project dependencies so the
  rootfs-provided torch and pinned build tools remain authoritative.
- **Unit-level smoke:** require `has_tensor_engine()`, require
  `torch.cuda.device_count() == 8`, spawn
  `this_host().spawn_procs(per_host={"gpus": 8})`, fetch shards `gpus=0..7`, and require ranks
  `[0, 1, 2, 3, 4, 5, 6, 7]`.
- **Integration:** run the local control-plane Python crash-recovery suite and
  Rust nextest coordination crates over the eight visible GPUs.
- **Failure classification:** Rust nextest must be green. Python full-run
  failures are acceptable only when every failed/error pytest node ID from
  `control-plane-results/control-plane-python.xml` passes when rerun in
  isolation inside the same rootfs. Otherwise, the verifier fails.

The verifier exits zero only when the ladder's acceptance criteria pass, even
when an intermediate Python full-suite command exits nonzero and is later
classified as Suite-Ordering Fragility. Its Contract Artifacts are
`control-plane-results/control-plane-python.xml`,
`control-plane-results/control-plane-python-isolation.txt` when classification
runs, and `target/nextest/ci/junit.xml`. The verifier removes the primary JUnit
paths before integration and accepts only reports created after that run starts.
Build caches, virtualenv contents, and logs are incidental artifacts.

Local Run ownership is split deliberately: scripts own executable behavior,
`AGENTS.md` owns repo-level policy, and repo-local skills under `.agents/skills/`
own agent procedure. Future Capacity Verifiers should follow the same Local Run
Ladder and emit machine-readable Contract Artifacts for any suite result that
affects acceptance. Failure Classification is opt-in per verifier; the verifier
must document the fragile suite, failed-node extraction, and identical isolation
environment. The Hermetic Rootfs may be auto-built and reused rather than
rebuilt on every run.

**Hermetic rootfs (bubblewrap).** On hosts whose default `cc`/`clang` targets a
different loader/glibc than the system loader (notably Nix-provisioned ones),
the native build breaks proc-macro loading and yields `.so`s with unresolved
`__isoc23_*` symbols. `scripts/run_local_control_plane.sh --rootfs` sidesteps
this by re-execing inside a bubblewrap sandbox built from the repo's own
PyTorch-CUDA baseline (consistent Ubuntu glibc 2.39, system gcc/clang, Python
3.12 + torch 2.13.0+cu132), where `uv pip install -e .` builds with no toolchain
hacks. Three scripts under `scripts/rootfs/`: `build_rootfs.sh` (docker-build the
baseline + build deps + pinned Rust + a synthetic `CUDA_HOME` from pip
`nvidia-cu13` wheels, then export to a flattened rootfs dir), `enter_rootfs.sh`
(`bwrap` in with local GPUs + host NVIDIA driver bind + repo mount), and
`run_in_rootfs.sh` (build then delegate to the suite runner). Requires `bwrap`,
`docker`, and the local NVIDIA driver userspace on the host. `enter_rootfs.sh`
auto-builds the rootfs on first use, so `--rootfs` is a single command from a
clean checkout. Inside the rootfs the `prepare_rust_toolchain()` heuristic is a
verified no-op. The sandbox uses an unprivileged user namespace
(`--unshare-all`), so a handful of control-plane Python tests can fail under the
full crash-recovery run from cross-test state (e.g. transport-init leaks,
orphan-proc timing, and the code-sync rsync daemon); each passes when run in
isolation inside the same rootfs, so treat them as pre-existing suite-ordering
fragility rather than a rootfs regression.

- Python tests live in `python/tests/` (`_monarch/` for the main API, `_src/` for
  internals). Rust tests are co-located with source in each crate.
- Marker `@pytest.mark.oss_skip` marks tests to skip in OSS CI; `control_plane`
  selects the host/proc/actor mesh + supervision suite and `gpu` marks tests
  needing a local GPU. `asyncio_mode` is
  `auto`; default pytest timeout is 5 minutes (`pyproject.toml`).
- **Disabling flaky CI tests:** open a GitHub issue titled `DISABLED <test-name>`;
  `scripts/fetch_disabled_tests.py` fetches these each CI run and skips them
  (Rust name = `<binary> <module::path::test_fn>`, Python = test function name).
  Override locally by pre-creating `disabled_tests.txt` and
  `.config/nextest-filter.txt` (e.g. `all()`) — the script won't overwrite them.
- CI workflows are in `.github/workflows/` (CPU/GPU × Python/Rust, macOS, docs,
  wheels, docker).

## Documentation

Documentation builds from rootfs-controlled tools; run each format through
`scripts/run`. The docs `Makefile` guards its own targets, so `make -C docs html`
aborts outside the rootfs.

```sh
scripts/run uv sync --frozen --inexact --group docs --extra kubernetes --no-dev --no-install-project
scripts/run bash scripts/build_monarch_for_docs.sh
scripts/run cargo doc --locked --workspace --no-deps
scripts/run mdbook build docs/source/books/hyperactor-book
scripts/run mdbook build docs/source/books/hyperactor-mesh-book
scripts/run make -C docs html
```

`make -C docs html` runs the Sphinx Gallery pass and copies the Cargo docs from
`$CARGO_TARGET_DIR/doc`, but it does not itself run `cargo doc` or the mdBook
builds; run those first. See `docs/DOCUMENTATION_GUIDE.md` for the full workflow.

## Security

- Security practices follow PyTorch Distributed; see
  `github.com/pytorch/pytorch/blob/main/SECURITY.md` (`SECURITY.md`). Report
  security issues through that process, not public GitHub issues; Meta runs a
  bug bounty program.
- `clippy.toml` disallows `rsa::pkcs1v15::*` types (CVE-2023-49092). Do not
  reintroduce them.
- Monarch actor messaging and RDMA operate on trusted networks/hosts; treat
  cross-process messaging as unauthenticated transport unless secured externally.

## Configuration

- `pyproject.toml` — package metadata, dependencies, `uv` sources/indices,
  pytest, ruff/ufmt. Torch comes from a PyTorch index (default `pytorch-cu132` =
  CUDA 13.2); switch via `[tool.uv.sources]` or
  `uv sync --extra-index-url https://download.pytorch.org/whl/cu130`. Torch is
  required at **build time** (setup.py detects paths + C++11 ABI; C++ extensions
  link libtorch).
- `setup.py` — build config; detects PyTorch install, CUDA (`CUDA_HOME`/`nvcc`),
  and the `USE_TENSOR_ENGINE` flag. Rust features: `tensor_engine` (CUDA/RDMA/
  distributed tensors) and always-on `extension-module`.
- `Cargo.toml` — workspace of member crates; patches Arrow crates to a pinned
  `arrow-rs` rev to match internal PyO3 0.27.
- `.cargo/config.toml` — rustflags (`--cfg tracing_unstable`, allowed clippy
  lints); enables `bindeps` unstable for `monarch_mini/rust`.
- `rust-toolchain`, `.python-version`, `.flake8`, `rustfmt.toml`, `clippy.toml`,
  `docs/source/conf.py` — toolchain/style/docs config.

## Common Pitfalls

- Rust build fails with a Python linking error → run through `scripts/run`, which
  activates the rootfs Python env; a bare-host `cargo` cannot find libpython.
- `uv lock` rewrites many unrelated packages → the checked-in lockfile is
  generated with Meta's vendored-version overrides. Use `scripts/run uv sync
  --frozen` for OSS local runs; do not regenerate `uv.lock` with plain `uv lock`
  unless you intend to replace that policy.
- Import errors for RDMA/distributed tensors → rebuild with tensor engine enabled
  (`USE_TENSOR_ENGINE=1`, default).
- Ensure your CUDA install matches the PyTorch index (cu132 = CUDA 13.2); C++11
  ABI mismatches against installed PyTorch cause runtime errors.
