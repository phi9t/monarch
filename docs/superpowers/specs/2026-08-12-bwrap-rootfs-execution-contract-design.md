# Hermetic bwrap Execution Contract

**Status:** Approved

**Date:** 2026-08-12

## Purpose

Monarch's supported Linux-local development workflow runs repository code and
toolchains inside one hermetic bubblewrap rootfs. This contract covers
dependency installation, builds, tests, checks, formatting, documentation,
examples, benchmarks, code generation, profiling, and dashboard frontend work.

The rootfs controls the compiler, loader, libc, Python, Rust, Node, CUDA toolkit,
and build tools. This prevents a host toolchain, notably one provisioned by Nix,
from producing native objects that are incompatible with the runtime loader.

The contract is workflow enforcement, not an operating-system security
boundary. A developer can deliberately bypass repository hooks with an absolute
host binary, a copied source tree, or tool-specific bypass flags. Monarch makes
the supported path unambiguous, guards the repository seams it controls, and
tests that new repository entrypoints are classified.

## Scope

The contract applies to development from a Monarch checkout on Linux. It does
not change these execution domains:

- GitHub Actions Linux jobs remain a controlled CI domain. They may use their
  existing job containers or hosted toolchains.
- macOS development and CI remain a native Darwin domain because bubblewrap is
  Linux-specific.
- An installed Monarch wheel may run outside a source checkout. The guard must
  not turn the rootfs into a runtime requirement for package consumers.
- Remote workers launched through Slurm, Kubernetes, SkyPilot, MAST, or another
  scheduler obey their remote environment contract. Local preparation and
  controller processes started from this checkout still use the rootfs.
- Meta-internal build systems remain a separately classified execution domain.

Linux architectures and GPU platforms unsupported by the rootfs fail with an
explicit message. The first implementation supports x86-64, including
actor-only work on CPU-only hosts and CUDA work on NVIDIA hosts. It does not
silently fall back to the host on ARM or ROCm. GPU-specific commands fail in
preflight when the requested devices or driver are absent.

## Execution domains

Every repository-managed entrypoint belongs to one domain.

| Domain | Examples | Rule |
| --- | --- | --- |
| Host bootstrap | `scripts/run`, `scripts/rootfs/build_rootfs.sh`, `scripts/rootfs/enter_rootfs.sh`, Docker export, bwrap preflight | May run on the Linux host only to construct or enter the sandbox |
| Rootfs development | `uv`, Python, Cargo, pytest, linters, formatters, docs, examples, benchmarks, code generation, frontend tools | Must run through `scripts/run` |
| Controlled CI | GitHub Actions Linux and Darwin workflows | May use the environment declared by the workflow |
| Installed runtime | A wheel or packaged remote worker outside a Git checkout | Not subject to the checkout-development guard |
| External orchestration | Host-side scheduler and Meta-internal provisioning scripts | Must be explicitly classified; no generic environment-variable bypass |

Editing, Git operations, and read-only inspection may run on the host. Host GPU
and Docker probes required to enter or build the rootfs are also bootstrap work.
They must not compile, import, install, or execute Monarch code on the host.

The controlled GitHub Linux predicate uses all of the following signals:

```text
GITHUB_ACTIONS=true
RUNNER_OS=Linux
GITHUB_RUN_ID is numeric
GITHUB_WORKFLOW_REF is nonempty
```

`CI=true` alone is never an exemption. Monarch's documentation build already
sets that variable locally, and many unrelated environments set it.

## Canonical command

The sole supported Linux-local gateway is:

```sh
scripts/run <command> [arguments...]
```

With no command, `scripts/run` opens an interactive shell. The following are
representative commands, not special dispatcher subcommands:

```sh
scripts/run uv sync --extra test
scripts/run uv pip install -e .
scripts/run python -c "from monarch import actor"
scripts/run pytest python/tests/ -m "not oss_skip"
scripts/run cargo nextest run
scripts/run cargo fmt --check
scripts/run cargo clippy --workspace
scripts/run make -C docs html
scripts/run npm --prefix python/monarch/monarch_dashboard/frontend ci
scripts/run npm --prefix python/monarch/monarch_dashboard/frontend run build
scripts/run python python/examples/getting_started.py
```

Outside the sandbox, `scripts/run` builds the rootfs when necessary and then
re-executes itself through `enter_rootfs.sh`. Inside the sandbox, it validates
the execution contract and executes the requested command without nesting
another bwrap instance. It preserves arguments exactly, maps the caller's
checkout-relative working directory to `/workspace/monarch`, forwards signals,
and returns the command's exit status.

The runner sets `UV_PROJECT_ENVIRONMENT` to
`/workspace/monarch/.venv-rootfs` and puts that environment first on `PATH` when
it exists. On first use, an in-rootfs helper creates that environment with
Python 3.12 and the rootfs system packages visible. The same virtual environment
is therefore used by Python, PyO3, setuptools-rust, Cargo, pytest, and
documentation builds.

Existing high-level verifiers remain convenient entrypoints. When invoked from
the host, `run_local_control_plane.sh` and `run_local_8gpu_capacity.sh` delegate
to `scripts/run`; their actual build and test work occurs only after validation
inside the rootfs. Low-level build, test, docs, and frontend seams fail closed
instead of silently re-entering, so accidental host execution is visible.

## Rootfs identity and provenance

The flattened rootfs is derived from reviewed, digest-pinned Docker images:

- the repository's PyTorch CUDA runtime image supplies Ubuntu, glibc, Python,
  CUDA runtime libraries, and PyTorch;
- an official Node 20 image supplies Node and npm for the dashboard;
- the rootfs build installs the pinned Rust toolchain, uv, cargo-nextest, build
  dependencies, CUDA development wheels, and mdBook.

The build writes `/etc/monarch-rootfs-contract`. It records a schema version,
both image digests, architecture, Python version, Rust toolchain, uv version,
nextest version, Node and npm versions, CUDA version, and a digest of the rootfs
recipe. The expected schema and recipe digest live in the checkout. Entry
rebuilds the managed rootfs when it is absent or its contract does not match.
The intermediate Docker image carries the same recipe digest as a label, so a
stale local image is rebuilt instead of merely re-exported. Changing an image
digest or tool version is a reviewed source change.

Python resolution uses `uv.lock --frozen`, project verifiers use Cargo's
`--locked` mode, and frontend installation uses `package-lock.json` with
`npm ci`. The legacy Yarn lockfile is not a local execution input. Ubuntu
package repositories remain rebuild-time nondeterminism until the project
adopts snapshot URLs; the contract promises a controlled baseline and recorded
provenance, not byte-for-byte rootfs identity.

The rootfs filesystem is mounted read-only. Explicit writable mounts are:

- the checkout at `/workspace/monarch`, because formatting, code generation,
  and ordinary editing workflows may update source files;
- `.venv-rootfs` and Git-ignored build outputs in the checkout;
- dedicated uv, Cargo, rustup, and npm caches;
- ephemeral home and temporary directories; and
- the device interfaces required for local GPUs.

When present, the host NVIDIA driver libraries are mounted read-only and
matching device nodes are exposed. They are the only host runtime components
deliberately admitted. Their absence is valid for actor-only work. Network
access is shared so locked dependencies can be downloaded; the sandbox is
filesystem-hermetic, not an offline build appliance.

## Environment contract

`enter_rootfs.sh` constructs a known environment instead of inheriting the host
shell wholesale. It defines `HOME`, `PATH`, `TMPDIR`, locale, the project path,
cache locations, `UV_PROJECT_ENVIRONMENT`, a contract-specific
`CARGO_TARGET_DIR`, and the rootfs marker. It preserves a small documented
allowlist, including terminal settings, proxy settings, and GPU visibility. It
clears or replaces host compiler and language variables such as `CC`, `CXX`,
`PYO3_PYTHON`, `PYTHONPATH`, `RUSTFLAGS`, and `RUSTC_WRAPPER`.

The shared validator accepts rootfs execution only when all of these facts
hold:

1. The internal marker says that entry occurred through Monarch's launcher.
2. `/etc/monarch-rootfs-contract` exists and matches the checkout's schema and
   recipe digest.
3. The current checkout resolves to `/workspace/monarch`.
4. `/proc/self/uid_map` describes the expected single-ID unprivileged user
   namespace rather than the host namespace.
5. Required tools resolve to paths inside the rootfs contract.

An environment variable alone is not proof of entry. There is no general
`MONARCH_ALLOW_HOST=1` escape hatch.

Persistent native artifacts are separated by the rootfs recipe digest. Cargo
uses a target directory below `target/bwrap/`, and documentation and nextest
artifact discovery honor that path. A successful editable native build records
the same digest beside its source-tree extension; source-tree import rejects an
extension with a missing or different provenance stamp and tells the developer
to rebuild through `scripts/run`. Frontend packaging always runs its frozen
installation and asset build instead of accepting a pre-existing
`frontend/build/index.html`. These rules prevent artifacts produced by a former
host toolchain or older rootfs from being reused silently.

## Enforcement seams

Repository hooks use one shared contract implementation, with thin language
adapters where necessary. They print the same diagnostic and exit with status
2 before doing useful work:

```text
error: Monarch development commands must run inside the hermetic bwrap rootfs
run instead: scripts/run <original command>
```

The first implementation guards these seams:

- source-tree Python imports, while leaving installed-wheel imports alone;
- top-level and `monarch_mini` Python build backends before dependency, CUDA,
  or frontend probing;
- the root pytest configuration before collection-time hardware detection;
- a Cargo compiler wrapper configured by the workspace, chained correctly with
  clippy and optional sccache;
- repository build, test, profiling, code-generation, and example scripts;
- the docs Makefile and docs build helper, including overridden
  `SPHINXBUILD`;
- dashboard npm lifecycle commands and the setuptools frontend builder; and
- the control-plane and capacity verifiers.

Cargo commands that reuse a cached binary, `cargo fmt`, dependency-only uv and
pip operations, direct absolute binaries, `pytest --noconftest`, and copied
scripts have no reliable repository pre-execution hook. They remain unsupported
outside `scripts/run`. The command gateway, documentation, seam guards, and
entrypoint audit jointly enforce normal development; only workstation policy
could make this a tamper-resistant rule for arbitrary host processes.

An execution inventory classifies repository-owned executable scripts,
Makefiles, Python build backends, package lifecycle commands, and documented
developer commands. A contract test fails when a new entrypoint lacks a domain
or when documentation reintroduces an unwrapped Linux-local command.

## Error handling

Bootstrap failures distinguish these cases and give a direct remedy:

- missing `bwrap` or Docker;
- unsupported architecture or GPU platform;
- an absent, stale, or malformed rootfs contract;
- missing host driver libraries or requested GPU devices; and
- a missing required rootfs tool.

An absent or stale managed rootfs is rebuilt automatically. A malformed active
sandbox never falls back to host execution. The launcher uses `exec` at both
boundaries so signals and exit codes are not hidden by wrapper processes.

Frontend packaging must fail when Node, npm, installation, or asset generation
fails. It must not warn and ship stale assets. The existing no-op frontend test
command must report that no test runner is configured with a nonzero exit code;
it must not claim a successful test run.

## Verification

Implementation follows red-green-refactor. All test harnesses are launched with
`scripts/run`; host-state cases use injected validator probes or exercise the
host half of the launcher before the test process enters bwrap.

The focused contract suite verifies:

- valid rootfs detection and rejection of a missing marker, forged marker,
  wrong contract, wrong checkout mount, or broad UID mapping;
- exact GitHub Linux and Darwin exemptions, including rejection of `CI=true`;
- argument, working-directory, signal, and exit-status preservation;
- no nested bwrap entry;
- read-only rootfs paths and writable checkout, cache, home, and temporary
  paths;
- expected Python, Rust, uv, nextest, Node, npm, CUDA, and mdBook identities;
- rejection of native artifacts stamped by a different rootfs recipe;
- fail-closed behavior at Python build/import/test, Cargo compile, docs,
  frontend, and shell-script seams;
- frontend assets are freshly built and included in package output;
- every repository-managed entrypoint has an execution-domain classification;
  and
- developer documentation uses `scripts/run` for Linux-local execution.

Acceptance then runs representative real workflows in the rootfs:

```sh
scripts/run uv sync --frozen --extra test
scripts/run uv pip install -e .
scripts/run python -c "from monarch import actor; print('ok')"
scripts/run pytest python/tests/ -m "not oss_skip"
scripts/run cargo nextest run
scripts/run cargo fmt --check
scripts/run cargo clippy --workspace
scripts/run npm --prefix python/monarch/monarch_dashboard/frontend ci
scripts/run npm --prefix python/monarch/monarch_dashboard/frontend run build
scripts/run uv sync --frozen --inexact --group docs --extra kubernetes
scripts/run make -C docs html
```

The local control-plane verifier remains the integration test for actor and
coordination behavior. On an eight-GPU host, the existing capacity verifier
remains the final tensor-engine acceptance ladder and retains its current
failure-classification contract.

## Documentation and ownership

`AGENTS.md`, `MONARCH_INFO.md`, the documentation guide, dashboard instructions,
and the repo-local `run-monarch-single-machine` skill use the canonical command
and explain the domain exemptions. Direct Linux-local `uv`, Cargo, pytest,
Make, and npm examples are replaced with `scripts/run` forms.

Ownership remains split deliberately:

- scripts own executable behavior;
- this design and `AGENTS.md` own repository policy;
- the rootfs contract file owns environment provenance;
- the execution inventory owns entrypoint classification; and
- `.agents/skills/run-monarch-single-machine` owns the agent procedure.

Future local verifiers must enter through `scripts/run`, document their
acceptance ladder, and emit machine-readable artifacts for every suite result
that affects acceptance.
