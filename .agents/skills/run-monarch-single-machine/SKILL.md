---
name: run-monarch-single-machine
description: Run Monarch on a single machine inside the hermetic bubblewrap (bwrap) rootfs, and build or maintain that rootfs. Use when the task is to build Monarch's Rust extension, run actors / proc meshes / control-plane tests, or execute any Monarch Python on one host, especially on Nix-provisioned or otherwise mismatched hosts where native cc/clang targets a different loader/glibc than the system. Also use when asked to build, rebuild, refresh, or debug the Monarch `scripts/rootfs/` bwrap sandbox.
---

# Run Monarch on a single machine (bwrap rootfs)

Monarch's Rust extension must build against a toolchain whose `cc`/`clang`
targets the same dynamic loader and glibc as the system loader `rustc` runs
under. On Nix-provisioned or otherwise mismatched hosts, that invariant is
violated and the build can fail during proc-macro loading or produce `.so`
files with unresolved `__isoc23_*` symbols.

`scripts/run` is the sole Linux-local gateway into the hermetic bwrap rootfs and
the default for every single-machine command. It re-execs into the sandbox, maps
the caller's directory to the matching checkout-relative directory, activates the
rootfs virtual environment, and preserves arguments and exit status; it
auto-builds the rootfs on first use. Run all local build, test, run, and docs
work through it.

## Choosing a branch

- **Any Linux-local command** — actor tests, a proc-mesh script, `cargo`, `uv`,
  `pytest`, docs — runs through `scripts/run <command> [args...]`. This is the
  default branch; take it unless the request names one of the domains below.
- **Control-plane or 8-GPU capacity** — run the committed verifiers, which enter
  the same rootfs (see the sections below).
- **GitHub Linux CI, native macOS, or a remote worker** — these are separate
  execution domains and never nest the local bwrap. GitHub runners already run on
  a controlled Ubuntu image; macOS has no bwrap; remote workers run under their
  own scheduler. Do not wrap their commands in `scripts/run`, and do not suggest
  host toolchain overrides to force a local build in those domains.

Do not fall back to the host toolchain unless the user explicitly asks to bypass
the sandbox.

## Repository

Run commands from the Monarch checkout root, using repo-relative paths such as
`scripts/run` and `scripts/run_local_8gpu_capacity.sh`. The rootfs mounts the
checkout at `/workspace/monarch`, so the sandbox path layout — not the host path
— is what the gateway and verifiers depend on.

## Host prerequisites

The host outside the sandbox needs:

- `bwrap` (bubblewrap) and `docker` on `PATH`.
- The local NVIDIA driver userspace (`libcuda.so*`, `libnvidia-*.so*`,
  `nvidia-smi`) and `/dev/nvidia*` device nodes for GPU work.

Check quickly:

```sh
command -v bwrap docker
nvidia-smi -L
```

Building `bwrap`/`docker`/driver availability and entering the rootfs is host
bootstrap — the only Linux-local work outside the `scripts/run` gateway.

## Run the control-plane suites

The runner re-execs itself through `scripts/run` when invoked outside the rootfs,
builds `-e .`, and runs both the Python crash-recovery and Rust nextest
control-plane suites:

```sh
scripts/run scripts/run_local_control_plane.sh
```

The rootfs is built automatically on first use if missing, so this is a single
command from a clean checkout. Useful variants:

```sh
scripts/run scripts/run_local_control_plane.sh --rust-only
scripts/run scripts/run_local_control_plane.sh --python-only
scripts/run scripts/run_local_control_plane.sh --keep-going
```

Results:

- Python JUnit: `control-plane-results/control-plane-python.xml`
- Rust JUnit: `target/nextest/ci/junit.xml`

## Verify all 8 local GPUs

For capacity checks that must prove the tensor engine runs across all eight
local GPUs, prefer the committed verifier:

```sh
scripts/run scripts/run_local_8gpu_capacity.sh
```

It re-enters through `scripts/run`, creates or reuses `.venv-rootfs`, synchronizes the frozen `uv.lock` test dependencies, applies the
hash-pinned TorchX compatibility override described below, and installs Monarch
editable without resolving project dependencies. The editable build uses the
build tools and torch pinned in the rootfs. It requires
`torch.cuda.device_count() == 8` and runs an 8-rank tensor smoke before running
the control-plane suites with all eight GPUs exposed. If the caller sets
`CUDA_VISIBLE_DEVICES`, it must name exactly eight devices and the verifier
preserves that explicit device list.

Read the verifier output as a validation ladder:

1. `environment`: rootfs entry, CUDA visibility, `CUDA_HOME`, `uv`, and
   `.venv-rootfs`.
2. `build`: editable tensor-engine install.
3. `unit-level smoke`: `has_tensor_engine()`, exactly eight CUDA devices,
   `this_host().spawn_procs(per_host={"gpus": 8})`, and fetched shard ranks
   `[0, 1, 2, 3, 4, 5, 6, 7]`.
4. `integration`: Python crash-recovery control-plane tests and Rust nextest
   coordination crates over all eight GPUs.
5. `failure classification`: Rust must be green. Python full-run failures are
   treated as suite-ordering fragility only if every failed/error node ID from
   `control-plane-results/control-plane-python.xml` passes in isolation inside
   the same rootfs.

The verifier's final exit code follows the ladder's acceptance criteria, not
the raw status of each intermediate command. A nonzero Python full-suite exit
can still yield a successful verifier result only after failure classification
accepts every failed node. Contract Artifacts are
`control-plane-results/control-plane-python.xml`,
`control-plane-results/control-plane-python-isolation.txt` when classification
runs, and `target/nextest/ci/junit.xml`; treat build caches and logs as
incidental. The verifier removes the Python and Rust JUnit paths before the
integration run and accepts only reports created after that run starts.

For future Capacity Verifiers, keep behavior in scripts, repo policy in
`AGENTS.md`, and agent procedure in this skill. Reuse the Local Run Ladder unless
the verifier documents a narrower one. Failure Classification is not automatic:
the verifier must explicitly name the fragile suite, parse failed nodes from a
machine-readable artifact, and rerun them in an identical isolation environment.
The Hermetic Rootfs may be auto-built and reused.

## Run ad hoc Monarch commands

`scripts/run <command>` runs any single command inside the sandbox with the repo
mounted at `/workspace/monarch`, local GPUs bound in, the host NVIDIA driver
userspace read-only bound, and `.venv-rootfs` activated. `scripts/run` with no
arguments opens an interactive rootfs shell. It auto-builds the rootfs if missing.

```sh
scripts/run                      # interactive shell inside the rootfs
scripts/run nvidia-smi -L
scripts/run python -c 'import torch; print(torch.cuda.is_available())'
scripts/run pytest python/tests/test_actor.py -q
scripts/run cargo test -p hyperactor
```

To build the extension and run a custom single-machine script, chain the build
and run through the gateway:

```sh
scripts/run uv pip install -e .
scripts/run python your_single_machine_script.py
```

Everything runs on `this_host()` / local in-process meshes. Do not assume CI
variables or remote execution. `CUDA_VISIBLE_DEVICES` is honored from the caller;
an empty value hides all GPUs and the control-plane preflight aborts.

## Build and maintain the rootfs

Building is normally automatic, but explicit maintenance uses:

```sh
scripts/rootfs/build_rootfs.sh
scripts/rootfs/build_rootfs.sh --rebuild
```

The rootfs directory (`scripts/rootfs/rootfs/`), intermediate rootfs stage dirs,
export tarballs, and `.venv-rootfs` should stay gitignored. For image contents,
CUDA `nvcc` assembly, version bumps, and troubleshooting, read
[references/rootfs.md](references/rootfs.md).

Use `uv sync --frozen` in this workflow. The checked-in `uv.lock` carries
Meta-generated vendored-version overrides, so plain `uv lock` causes unrelated
lockfile churn and must not be used as a local setup step.

The generated lock selects `torchx-nightly==2021.10.28` on Linux, which cannot
import under the rootfs Python 3.12. `sync_test_environment.sh` replaces only
that distribution with the `2026.7.27` wheel and hash already recorded in the
same lock. Keep this exception centralized in the helper.

## Interpret results

The Rust suite should be fully green. Under the full crash-recovery Python run,
a small number of control-plane tests can fail from cross-test state in the
unprivileged user namespace (transport-init leaks, orphan-proc timing, and the
code-sync rsync daemon). Before treating such a failure as a rootfs regression,
re-run the specific test in isolation inside the same rootfs:

```sh
scripts/run python -m pytest "python/tests/<file>::<test>" -q -m "control_plane and not oss_skip"
```

If it passes alone, treat the full-run failure as pre-existing suite-ordering
fragility rather than a bwrap rootfs regression.
