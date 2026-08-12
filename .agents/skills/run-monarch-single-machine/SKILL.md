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

For this skill, always run single-machine Monarch work through the bwrap rootfs:
use `scripts/run_local_control_plane.sh --rootfs` for the control-plane suites
and `scripts/rootfs/enter_rootfs.sh -- <command>` for ad hoc Python, cargo, or
diagnostic commands. Do not fall back to the host toolchain unless the user
explicitly asks to bypass the sandbox.

## Repository

This skill is written for the Monarch checkout at:

```sh
/data02/home/philip.yang/workspace/monarch
```

Run commands from that repo root unless the user gives a different checkout.

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

## Run the control-plane suites

The single entrypoint re-execs itself into the sandbox, builds `-e .`, and runs
both the Python crash-recovery and Rust nextest control-plane suites:

```sh
scripts/run_local_control_plane.sh --rootfs
```

The rootfs is built automatically on first use if missing, so this is a single
command from a clean checkout. Useful variants:

```sh
scripts/run_local_control_plane.sh --rootfs --rust-only
scripts/run_local_control_plane.sh --rootfs --python-only
scripts/run_local_control_plane.sh --rootfs --keep-going
```

Results:

- Python JUnit: `control-plane-results/control-plane-python.xml`
- Rust JUnit: `target/nextest/ci/junit.xml`

## Verify all 8 local GPUs

For capacity checks that must prove the tensor engine runs across all eight
local GPUs, prefer the committed verifier:

```sh
scripts/run_local_8gpu_capacity.sh
```

It always re-enters through `scripts/rootfs/enter_rootfs.sh`, creates or reuses
`.venv-rootfs`, synchronizes the frozen `uv.lock` test dependencies, applies the
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

`enter_rootfs.sh` enters the sandbox with the repo mounted at
`/workspace/monarch`, local GPUs bound in, and the host NVIDIA driver userspace
read-only bound into the rootfs. It auto-builds the rootfs if missing.

```sh
scripts/rootfs/enter_rootfs.sh
scripts/rootfs/enter_rootfs.sh -- nvidia-smi -L
scripts/rootfs/enter_rootfs.sh -- python -c 'import torch; print(torch.cuda.is_available())'
```

To build the extension and run custom single-machine Python, reuse the
in-sandbox venv at `.venv-rootfs`:

```sh
scripts/rootfs/enter_rootfs.sh -- bash -lc '
  cd /workspace/monarch
  [ -x .venv-rootfs/bin/python ] || uv venv --python 3.12 --system-site-packages .venv-rootfs
  source .venv-rootfs/bin/activate
  scripts/rootfs/sync_test_environment.sh
  python your_single_machine_script.py
'
```

Everything should run on `this_host()` / local in-process meshes. Do not assume
CI variables or remote execution. `CUDA_VISIBLE_DEVICES` is honored from the
caller; an empty value hides all GPUs and the control-plane preflight should
abort.

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
scripts/rootfs/enter_rootfs.sh -- bash -lc '
  cd /workspace/monarch && source .venv-rootfs/bin/activate
  python -m pytest "python/tests/<file>::<test>" -q -m "control_plane and not oss_skip"
'
```

If it passes alone, treat the full-run failure as pre-existing suite-ordering
fragility rather than a bwrap rootfs regression.
