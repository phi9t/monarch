# Hermetic bwrap Execution Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/run` the canonical Linux-local gateway and ensure every supported Monarch development, build, test, docs, and frontend workflow executes in a validated, provenance-stamped bubblewrap rootfs.

**Architecture:** A sourceable shell contract owns execution-domain detection and rootfs identity. A digest-keyed Docker export supplies a read-only bwrap root with explicit writable mounts, while thin Python, Cargo, Make, npm, and script guards enforce the contract at repository-controlled seams. `scripts/run` is the only local gateway; controlled GitHub Linux, native Darwin, installed-wheel, and explicitly classified remote/internal workflows remain separate domains.

**Tech Stack:** Bash, bubblewrap, Docker, Python 3.12/pytest, TOML, setuptools/setuptools-rust, Cargo/Rust, Node 20/npm, TypeScript/esbuild, Sphinx, and mdBook.

## Global Constraints

- Linux-local source-checkout execution uses `scripts/run`; host bootstrap is limited to building and entering the rootfs.
- The first rootfs implementation supports x86-64, actor-only work on CPU-only Linux hosts, and CUDA work on NVIDIA hosts; ARM and ROCm fail explicitly.
- The rootfs is derived from digest-pinned PyTorch CUDA, uv, and official Node 20 images.
- `MONARCH_IN_ROOTFS=1` or another environment marker alone never proves rootfs entry.
- `CI=true` alone never grants a controlled-CI exemption.
- The exact GitHub Linux exemption requires `GITHUB_ACTIONS=true`, `RUNNER_OS=Linux`, a positive numeric `GITHUB_RUN_ID`, and nonempty `GITHUB_WORKFLOW_REF`.
- The flattened rootfs is read-only; only the checkout, dedicated caches, an ephemeral home, `/tmp`, `/proc`, `/dev`, and requested GPU devices are writable mounts.
- Host compiler, Python, Cargo, and linker variables do not cross the bwrap boundary.
- Python uses `.venv-rootfs`, Cargo uses `target/bwrap/<recipe-digest>`, and frontend dependency installation uses `package-lock.json` with `npm ci`.
- The Buck-only `yarn.lock` remains present and untouched by this implementation.
- Repository guards provide workflow enforcement, not a tamper-resistant operating-system security boundary.
- GitHub Actions, native macOS, installed wheels, Meta-internal builds, and remote worker runtimes remain explicitly separate execution domains.
- Every implementation and verification command that executes Monarch or its development tools runs through the existing bwrap entrypoint until `scripts/run` exists, and through `scripts/run` afterward.
- Preserve the user's existing modification to `python/monarch/monarch_dashboard/frontend/yarn.lock`; never stage it.
- Before Task 1, invoke `superpowers:using-git-worktrees` and create an isolated feature worktree outside this dirty checkout; run every task and commit from that worktree.

---

## File Structure

### New files

| File | Responsibility |
| --- | --- |
| `scripts/rootfs/contract.env` | Reviewed schema, image digests, architecture, and pinned tool versions |
| `scripts/rootfs/execution_contract.sh` | Sourceable validator and narrow CLI for rootfs, GitHub Linux, Darwin, and controlled execution |
| `scripts/rootfs/activate_environment.sh` | Create and activate `.venv-rootfs` after validated entry |
| `scripts/rootfs/rustc-wrapper.sh` | Enforce controlled execution before delegating to rustc or clippy-driver |
| `scripts/run` | Sole Linux-local bwrap gateway, CWD mapper, and command executor |
| `scripts/rootfs/execution-domains.toml` | Machine-readable entrypoint and execution-domain inventory |
| `scripts/rootfs/audit_entrypoints.py` | Compare tracked entrypoints and developer commands with the inventory |
| `scripts/build_dashboard_frontend.py` | Import-safe, fail-closed npm asset builder used by setuptools and tests |
| `python/monarch/_rootfs_contract.py` | Stdlib Python adapter plus editable native-artifact provenance helpers |
| `scripts/rootfs/tests/test_execution_contract.py` | Pure contract, provenance, CI predicate, and rootfs-builder tests |
| `scripts/rootfs/tests/test_run_gateway.py` | Argument, CWD, environment, exit, namespace, and mount tests for `scripts/run` |
| `scripts/rootfs/tests/test_guarded_entrypoints.py` | Negative seam and pre-mutation guard tests |
| `scripts/rootfs/tests/test_entrypoint_inventory.py` | Complete execution-domain inventory checks |
| `python/tests/test_native_artifact_provenance.py` | Editable native manifest validation and replacement tests |
| `python/tests/test_frontend_build.py` | Deterministic frontend builder tests |

### Existing files changed by subsystem

| Subsystem | Files |
| --- | --- |
| Rootfs image and entry | `.gitignore`, `scripts/rootfs/build_rootfs.sh`, `scripts/rootfs/enter_rootfs.sh`, `scripts/rootfs/run_in_rootfs.sh`, `scripts/rootfs/sync_test_environment.sh` |
| Local verifiers | `scripts/run_local_control_plane.sh`, `scripts/run_local_8gpu_capacity.sh`, `python/tests/test_local_8gpu_capacity.py` |
| Python/Rust seams | `setup.py`, `monarch_mini/python/setup.py`, `python/monarch/__init__.py`, `python/tests/conftest.py`, `.cargo/config.toml`, `scripts/sccache-rustc-wrapper.sh`, `monarch_mini/Makefile` |
| Script seams | `scripts/common-setup.sh`, `scripts/common-setup-macos.sh`, `scripts/build_monarch_for_docs.sh`, `scripts/fetch_disabled_tests.py`, `scripts/local_8gpu_capacity.py`, `scripts/profile_compile_obligations.sh`, `monarch_mini/test_certs/generate.sh`, `hyperactor_mesh/test/hyperactor_mesh_proxy_liveness_test.sh`, `hyperactor_remote/example/remote_spawner.sh` |
| Frontend | `python/monarch/monarch_dashboard/frontend/package.json`, `setup.py` |
| Docs paths | `docs/Makefile`, `docs/source/conf.py` |
| Policy and usage docs | `AGENTS.md`, `MONARCH_INFO.md`, `README.md`, `docs/DOCUMENTATION_GUIDE.md`, `docs/source/monarch-dashboard.md`, `docs/source/admin-tui.md`, `docs/source/books/hyperactor-book/README.md`, `docs/source/books/hyperactor-mesh-book/README.md`, `python/monarch/monarch_dashboard/README.md`, both frontend READMEs, `.agents/skills/run-monarch-single-machine/SKILL.md`, `.agents/skills/run-monarch-single-machine/references/rootfs.md` |

Tasks are sequential because every guard consumes the identity and diagnostics defined in Task 1, and every real verification consumes the launcher and image defined in Tasks 2 and 3.

---

### Task 1: Shared execution-contract core

**Files:**

- Create: `scripts/rootfs/contract.env`
- Create: `scripts/rootfs/execution_contract.sh`
- Create: `scripts/rootfs/tests/test_execution_contract.py`

**Interfaces:**

- Produces: `monarch_rootfs_recipe_sha256 REPO_ROOT -> stdout digest`
- Produces: `monarch_contract_files_match EXPECTED ACTUAL -> status`
- Produces: `monarch_checkout_matches EXPECTED ACTUAL -> status`
- Produces: `monarch_uid_map_is_controlled FILE -> status`
- Produces: `monarch_rootfs_contract_current ROOTFS REPO_ROOT -> status`
- Produces: `monarch_in_valid_rootfs REPO_ROOT TOOLS -> status`
- Produces: `monarch_require_rootfs REPO_ROOT TOOLS -> status 0 or diagnostic/status 2`
- Produces: `monarch_is_github_linux_ci -> status`
- Produces: `monarch_require_controlled_execution REPO_ROOT TOOLS -> status 0 or diagnostic/status 2`
- Produces CLI: `execution_contract.sh recipe-sha256`, `rootfs-current ROOTFS`, `require-rootfs TOOLS`, `require-github-linux`, `require-darwin`, `require-controlled TOOLS`, and `identify-controlled`
- Diagnostic contract: `error: Monarch development commands must run inside the hermetic bwrap rootfs` followed by `run instead: scripts/run <original command>`

- [ ] **Step 1: Write failing contract tests**

Add subprocess tests that source the shell library and pass explicit fact files to its pure validation helpers. Cover a valid single-ID UID map, broad host UID map, missing and forged markers, mismatched recipe digests, wrong checkout mounts, exact GitHub Linux signals, `CI=true`, Darwin, required tool paths, and status 2 diagnostics.

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "scripts/rootfs/execution_contract.sh"


def bash(script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift; {script}', "bash", str(CONTRACT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_github_linux_requires_the_complete_identity() -> None:
    complete = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_ACTIONS": "true",
        "RUNNER_OS": "Linux",
        "GITHUB_RUN_ID": "1234",
        "GITHUB_WORKFLOW_REF": "meta-pytorch/monarch/.github/workflows/test.yml@refs/pull/1/merge",
    }
    assert bash("monarch_is_github_linux_ci", env=complete).returncode == 0
    assert bash("monarch_is_github_linux_ci", env={"PATH": "/usr/bin:/bin", "CI": "true"}).returncode != 0
    assert bash("monarch_is_github_linux_ci", env={**complete, "GITHUB_RUN_ID": "0"}).returncode != 0


def test_uid_map_accepts_controlled_namespaces(tmp_path: Path) -> None:
    single = tmp_path / "single"
    single.write_text("1018 0 1\n")
    nested_userns = tmp_path / "nested"
    nested_userns.write_text("")
    broad = tmp_path / "broad"
    broad.write_text("0 0 4294967295\n")
    assert bash('monarch_uid_map_is_controlled "$1"', str(single)).returncode == 0
    assert bash('monarch_uid_map_is_controlled "$1"', str(nested_userns)).returncode == 0
    assert bash('monarch_uid_map_is_controlled "$1"', str(broad)).returncode != 0


def test_require_rootfs_uses_the_common_status_two_diagnostic() -> None:
    result = subprocess.run(
        [CONTRACT, "require-rootfs"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "MONARCH_IN_ROOTFS": "1"},
    )
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr
    assert "run instead: scripts/run" in result.stderr
```

- [ ] **Step 2: Run the tests through the current rootfs and confirm RED**

Run:

```sh
scripts/rootfs/enter_rootfs.sh -- .venv-rootfs/bin/python -m pytest scripts/rootfs/tests/test_execution_contract.py -q
```

Expected: FAIL because `contract.env`, `execution_contract.sh`, and their functions do not exist.

- [ ] **Step 3: Add reviewed contract constants**

Create a shell-data-only file with these exact pins. The Node pin is the official linux/amd64 manifest resolved from the multi-platform image index.

```sh
MONARCH_ROOTFS_SCHEMA=1
MONARCH_ROOTFS_ARCH=x86_64
MONARCH_BASE_IMAGE=ghcr.io/pytorch/pytorch:2.13.0-cuda13.2-cudnn9-runtime@sha256:7492928e093d67276716440161f694a0e4ea27796d599d64b23cb76cdd665e71
MONARCH_UV_IMAGE=ghcr.io/astral-sh/uv:0.12.2@sha256:069a51314a7bb6031777a9273205fe1b0b19e914ef418207d1338b268df641dd
MONARCH_NODE_IMAGE=node:20.19.5-bookworm-slim@sha256:d08621e478133b0492bd661ceee5d13a22b8c55297f3dbbb57f1c15d0c214942
MONARCH_PYTHON_VERSION=3.12.3
MONARCH_UV_VERSION=0.12.2
MONARCH_NEXTEST_VERSION=0.9.143
MONARCH_NODE_VERSION=20.19.5
MONARCH_NPM_VERSION=10.8.2
MONARCH_MDBOOK_VERSION=0.5.4
MONARCH_CUDA_NVCC_VERSION=13.3.73
MONARCH_CUDA_CCCL_VERSION=13.3.3.4.1
MONARCH_SETUPTOOLS_VERSION=81.0.0
MONARCH_SETUPTOOLS_RUST_VERSION=1.12.0
MONARCH_WHEEL_VERSION=0.47.0
MONARCH_SEMANTIC_VERSION=2.10.0
```

- [ ] **Step 4: Implement the sourceable validator and CLI**

Use strict Bash, derive `REPO_ROOT` from the script, and hash relative file names so worktree location does not change the recipe identity.

```bash
monarch_rootfs_recipe_sha256() {
  local repo_root="$1"
  (
    cd "$repo_root"
    sha256sum scripts/rootfs/contract.env scripts/rootfs/build_rootfs.sh rust-toolchain
  ) | sha256sum | awk '{print $1}'
}

monarch_uid_map_is_controlled() {
  awk '
    { lines++; count = $3 }
    NF != 3 { exit 1 }
    END { if (lines == 0) exit 0; exit !(lines == 1 && count == 1) }
  ' "$1"
}

monarch_is_github_linux_ci() {
  [[ "${GITHUB_ACTIONS:-}" == "true" &&
     "${RUNNER_OS:-}" == "Linux" &&
     "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ &&
     -n "${GITHUB_WORKFLOW_REF:-}" ]]
}

monarch_contract_error() {
  echo "error: Monarch development commands must run inside the hermetic bwrap rootfs" >&2
  echo "run instead: scripts/run ${MONARCH_ORIGINAL_COMMAND:-<command>}" >&2
  return 2
}
```

`monarch_in_valid_rootfs` must require the marker, `/workspace/monarch`, a matching `/etc/monarch-rootfs-contract`, a single-ID `/proc/self/uid_map`, and controlled paths for any requested tools. Map `uv`, `cargo`, `node`, `npm`, and `mdbook` to `/usr/local/bin/uv`, `/opt/cargo/bin/cargo`, `/usr/local/bin/node`, `/usr/local/bin/npm`, and `/opt/cargo/bin/mdbook`. Accept Python before activation at `/usr/bin/python` and after activation at `/workspace/monarch/.venv-rootfs/bin/python` only when `readlink -f` resolves to `/usr/bin/python3.12`. `identify-controlled` prints `rootfs <recipe-digest>`, `github-linux`, or `darwin`; it prints the common diagnostic and exits 2 otherwise.

Make the shell contract executable because npm and repository scripts invoke its CLI directly:

```sh
chmod +x scripts/rootfs/execution_contract.sh
```

- [ ] **Step 5: Run the contract tests and confirm GREEN**

Run:

```sh
scripts/rootfs/enter_rootfs.sh -- .venv-rootfs/bin/python -m pytest scripts/rootfs/tests/test_execution_contract.py -q
scripts/rootfs/enter_rootfs.sh -- bash -n scripts/rootfs/execution_contract.sh scripts/rootfs/contract.env
```

Expected: all tests pass; Bash syntax checks pass.

- [ ] **Step 6: Commit the contract core**

```sh
git add scripts/rootfs/contract.env scripts/rootfs/execution_contract.sh scripts/rootfs/tests/test_execution_contract.py
git commit -m "Define the bwrap execution contract"
```

---

### Task 2: Provenance-stamped, read-only rootfs

**Files:**

- Modify: `scripts/rootfs/build_rootfs.sh`
- Modify: `scripts/rootfs/enter_rootfs.sh`
- Modify: `.gitignore`
- Test: `scripts/rootfs/tests/test_execution_contract.py`

**Interfaces:**

- Consumes: Task 1's `contract.env`, `monarch_rootfs_recipe_sha256`, and `monarch_rootfs_contract_current`
- Produces: `/etc/monarch-rootfs-contract` with schema, recipe digest, image digests, architecture, and exact tool versions
- Produces: recipe-labeled Docker images and a stale-rootfs auto-rebuild check
- Produces: `enter_rootfs.sh --chdir CHECKOUT_REL -- COMMAND ARGS`

- [ ] **Step 1: Extend tests for image provenance and entry arguments**

Assert that the builder sources `contract.env`, labels the image with the recipe digest, emits every required contract key, includes a Node stage, installs pinned mdBook, and rejects a rootfs whose recipe differs. Assert that the entry script uses `--ro-bind` for `/`, `--clearenv`, `--chdir`, explicit cache variables, and no host compiler propagation.

```python
def test_builder_uses_every_reviewed_tool_pin() -> None:
    builder = (REPO_ROOT / "scripts/rootfs/build_rootfs.sh").read_text()
    for name in (
        "MONARCH_BASE_IMAGE",
        "MONARCH_UV_IMAGE",
        "MONARCH_NODE_IMAGE",
        "MONARCH_NEXTEST_VERSION",
        "MONARCH_MDBOOK_VERSION",
    ):
        assert name in builder
    assert "org.pytorch.monarch.rootfs-recipe" in builder
    assert "/etc/monarch-rootfs-contract" in builder


def test_entry_uses_read_only_root_and_clear_environment() -> None:
    entry = (REPO_ROOT / "scripts/rootfs/enter_rootfs.sh").read_text()
    assert '--ro-bind "$ROOTFS" /' in entry
    assert "--clearenv" in entry
    assert "--chdir" in entry
    assert '--setenv CARGO_TARGET_DIR' in entry
    assert '--setenv UV_CACHE_DIR' in entry
    assert '--setenv npm_config_cache' in entry
    assert '--setenv CC' not in entry
    assert '--setenv PYTHONPATH' not in entry
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```sh
scripts/rootfs/enter_rootfs.sh -- .venv-rootfs/bin/python -m pytest scripts/rootfs/tests/test_execution_contract.py -q
```

Expected: the new provenance and read-only-entry assertions fail.

- [ ] **Step 3: Refactor the rootfs builder around the reviewed contract**

Source `contract.env`, reject non-`x86_64`, compute the recipe digest, default the tag to `monarch-rootfs:<first-16-digest-characters>`, and inspect the image label before reuse.

Add these Docker stages and checks:

```dockerfile
ARG UV_IMAGE
ARG NODE_IMAGE
FROM ${UV_IMAGE} AS uv
FROM ${NODE_IMAGE} AS node

ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
```

Install `mdbook` with `cargo install --locked --version "${MDBOOK_VERSION}" mdbook`. Check exact `python`, `uv`, nextest, Node, npm, mdBook, and nvcc versions during the image build. Write the contract with `printf '%s\n'` from Docker build arguments, and label the image `org.pytorch.monarch.rootfs-recipe=${ROOTFS_RECIPE_SHA256}`. Keep the existing destination validation and atomic export.

- [ ] **Step 4: Make rootfs entry fail closed and filesystem-hermetic**

Parse `--chdir`, validate it is relative and stays below the checkout, rebuild when `monarch_rootfs_contract_current` fails, and construct bwrap with:

```bash
bwrap_args=(
  --ro-bind "$ROOTFS" /
  --proc /proc
  --tmpfs /tmp
  --dev /dev
  --tmpfs /home
  --dir /home/monarch
  --bind "$REPO_ROOT" /workspace/monarch
  --unshare-all
  --share-net
  --die-with-parent
  --clearenv
  --chdir "/workspace/monarch${checkout_rel:+/$checkout_rel}"
)
```

Create Git-ignored `scripts/rootfs/cache/{uv,cargo,npm,xdg}` on the host and set:

```text
HOME=/home/monarch
PATH=/opt/cuda-synth/bin:/opt/cargo/bin:/usr/local/bin:/usr/bin:/bin
UV_PROJECT_ENVIRONMENT=/workspace/monarch/.venv-rootfs
UV_CACHE_DIR=/workspace/monarch/scripts/rootfs/cache/uv
CARGO_HOME=/workspace/monarch/scripts/rootfs/cache/cargo
CARGO_TARGET_DIR=/workspace/monarch/target/bwrap/<recipe-digest>
npm_config_cache=/workspace/monarch/scripts/rootfs/cache/npm
XDG_CACHE_HOME=/workspace/monarch/scripts/rootfs/cache/xdg
RUSTUP_HOME=/opt/rustup
CUDA_HOME=/opt/cuda-synth
CUDA_PATH=/opt/cuda-synth
MONARCH_IN_ROOTFS=1
MONARCH_ROOTFS_RECIPE_SHA256=<recipe-digest>
```

Preserve only terminal variables, upper- and lower-case proxy variables, `CUDA_VISIBLE_DEVICES`, `NVIDIA_VISIBLE_DEVICES`, `RUST_LOG`, `RUST_BACKTRACE`, and the documented Monarch build flags. Bind host NVIDIA libraries and devices only when they exist, so actor-only work remains valid on a CPU-only host.

- [ ] **Step 5: Ignore managed caches**

Add these entries without changing existing ignore rules:

```gitignore
scripts/rootfs/cache/
scripts/rootfs/cache/**
```

- [ ] **Step 6: Rebuild and inspect the actual rootfs**

Run the host-bootstrap builder:

```sh
scripts/rootfs/build_rootfs.sh --rebuild
```

Then execute checks through bwrap:

```sh
scripts/rootfs/enter_rootfs.sh -- sh -c '
  test "$(node --version)" = v20.19.5
  test "$(npm --version)" = 10.8.2
  test "$(mdbook --version)" = "mdbook v0.5.4"
  test "$(uv --version | awk "{print \$2}")" = 0.12.2
  python - <<"PY"
import os
assert os.statvfs("/").f_flag & os.ST_RDONLY
assert not (os.statvfs("/workspace/monarch").f_flag & os.ST_RDONLY)
PY
'
```

Expected: all exact versions match; `/` is read-only; the checkout is writable.

- [ ] **Step 7: Run focused tests and commit**

```sh
scripts/rootfs/enter_rootfs.sh -- .venv-rootfs/bin/python -m pytest scripts/rootfs/tests/test_execution_contract.py -q
scripts/rootfs/enter_rootfs.sh -- bash -n scripts/rootfs/build_rootfs.sh scripts/rootfs/enter_rootfs.sh
git add .gitignore scripts/rootfs/build_rootfs.sh scripts/rootfs/enter_rootfs.sh scripts/rootfs/tests/test_execution_contract.py
git commit -m "Stamp and isolate the Monarch rootfs"
```

---

### Task 3: Canonical `scripts/run` gateway and local verifier routing

**Files:**

- Create: `scripts/rootfs/activate_environment.sh`
- Create: `scripts/run`
- Create: `scripts/rootfs/tests/test_run_gateway.py`
- Modify: `scripts/rootfs/run_in_rootfs.sh`
- Modify: `scripts/rootfs/sync_test_environment.sh`
- Modify: `scripts/run_local_control_plane.sh`
- Modify: `scripts/run_local_8gpu_capacity.sh`
- Modify: `python/tests/test_local_8gpu_capacity.py`

**Interfaces:**

- Consumes: Task 1 validator and Task 2 `enter_rootfs.sh --chdir`
- Produces: `scripts/run [--] COMMAND ARGS`; no command opens `/bin/bash -l`
- Produces: active `/workspace/monarch/.venv-rootfs` with `VIRTUAL_ENV` and `PATH` set
- Produces: control-plane and 8-GPU scripts that delegate before Python, CUDA, build, or test work

- [ ] **Step 1: Write failing gateway and delegation tests**

Test exact argument and status preservation, a checkout subdirectory CWD, no nested user namespace, venv activation, stripped host compiler variables, and both verifier scripts delegating before their first Python invocation.

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN = REPO_ROOT / "scripts/run"


def test_inner_run_preserves_arguments_and_exit_status() -> None:
    result = subprocess.run(
        [RUN, "python", "-c", "import sys; print(sys.argv[1:]); raise SystemExit(37)", "a b", "$HOME"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 37
    assert "['a b', '$HOME']" in result.stdout


def test_inner_run_does_not_nest_the_user_namespace() -> None:
    before = os.readlink("/proc/self/ns/user")
    result = subprocess.run(
        [RUN, "python", "-c", "import os; print(os.readlink('/proc/self/ns/user'))"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == before


def test_inner_run_forwards_signals() -> None:
    process = subprocess.Popen(
        [RUN, "python", "-c", "import signal,time; signal.signal(signal.SIGTERM, lambda *_: raise SystemExit(42)); print('ready', flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    process.terminate()
    assert process.wait(timeout=5) == 42


def test_run_activates_the_rootfs_venv() -> None:
    result = subprocess.run(
        [RUN, "python", "-c", "import os,sys; print(os.environ['VIRTUAL_ENV']); print(sys.executable)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == [
        "/workspace/monarch/.venv-rootfs",
        "/workspace/monarch/.venv-rootfs/bin/python",
    ]
```

Extend `test_local_8gpu_capacity.py` with a source-order assertion: the shell script's `scripts/run` delegation occurs before `HOST_PYTHON`, `local_8gpu_capacity.py`, or CUDA-list parsing.

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```sh
scripts/rootfs/enter_rootfs.sh -- .venv-rootfs/bin/python -m pytest \
  scripts/rootfs/tests/test_run_gateway.py \
  python/tests/test_local_8gpu_capacity.py -q
```

Expected: FAIL because `scripts/run` and the activation helper do not exist and verifier ordering is unchanged.

- [ ] **Step 3: Implement rootfs environment activation**

`activate_environment.sh` is sourceable, calls `monarch_require_rootfs "$REPO_ROOT" python uv cargo node npm mdbook`, creates `.venv-rootfs` with `uv venv --python 3.12 --system-site-packages`, and exports:

```bash
export VIRTUAL_ENV=/workspace/monarch/.venv-rootfs
export PATH="$VIRTUAL_ENV/bin:$PATH"
unset PYTHONHOME
```

It never resolves or installs project dependencies.

- [ ] **Step 4: Implement `scripts/run`**

Outside a valid rootfs, compute a checked checkout-relative CWD and execute:

```bash
exec "$REPO_ROOT/scripts/rootfs/enter_rootfs.sh" \
  --chdir "$checkout_rel" -- /workspace/monarch/scripts/run "$@"
```

Inside, require the full contract, source `activate_environment.sh`, export `MONARCH_ORIGINAL_COMMAND` using shell-escaped arguments for later diagnostics, and `exec` the command. Strip an optional leading `--`. With no command, `exec /bin/bash -l`.

Reject `uname -m` values other than `x86_64` and reject `MONARCH_GPU_PLATFORM=rocm` with a direct unsupported-platform error before entry. Mark the new gateway and activation helper executable:

```sh
chmod +x scripts/run scripts/rootfs/activate_environment.sh
```

- [ ] **Step 5: Route compatibility and verifier entrypoints**

Make `run_in_rootfs.sh` a compatibility shim that enters through `scripts/run` and delegates to `run_local_control_plane.sh`. Make `sync_test_environment.sh` require a valid rootfs and exact `VIRTUAL_ENV=/workspace/monarch/.venv-rootfs` before its frozen uv operations.

Remove `--rootfs` from `run_local_control_plane.sh`. At the top of both local verifier scripts, before option-dependent Python/CUDA work, use:

```bash
if ! "$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs >/dev/null 2>&1; then
  exec "$REPO_ROOT/scripts/run" "$REPO_ROOT/scripts/run_local_control_plane.sh" "$@"
fi
"$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs python uv cargo
```

Use the corresponding 8-GPU script path in its file. Run environment synchronization inside the validated control-plane script, retain existing GPU and failure-classification behavior, add `--locked` to nextest, and report nextest JUnit at `$REPO_ROOT/target/nextest/ci/junit.xml` (cargo-nextest resolves its store from the workspace-root default target directory and ignores `CARGO_TARGET_DIR`).

- [ ] **Step 6: Run focused and real gateway checks**

```sh
scripts/run python -m pytest \
  scripts/rootfs/tests/test_run_gateway.py \
  python/tests/test_local_8gpu_capacity.py -q
scripts/run bash -n scripts/run scripts/rootfs/activate_environment.sh \
  scripts/rootfs/run_in_rootfs.sh scripts/rootfs/sync_test_environment.sh \
  scripts/run_local_control_plane.sh scripts/run_local_8gpu_capacity.sh
(cd docs && ../../scripts/run python -c 'import os; print(os.getcwd())')
```

Expected: tests pass; Bash syntax passes; the last command prints `/workspace/monarch/docs`.

Exercise the outer bwrap boundary from the host bootstrap shell as well:

```sh
ready="target/bwrap-signal-ready-${RANDOM}-$$"
[[ "$ready" == target/bwrap-signal-ready-* && ! -e "$ready" ]]
scripts/run sh -c 'trap "exit 42" TERM; touch "$1"; while :; do sleep 1; done' sh "$ready" &
runner_pid=$!
for _ in $(seq 1 100); do
  [[ -f "$ready" ]] && break
  kill -0 "$runner_pid" 2>/dev/null || { wait "$runner_pid"; exit 1; }
  sleep 0.1
done
[[ -f "$ready" ]]
kill -TERM "$runner_pid"
set +e
wait "$runner_pid"
signal_status=$?
set -e
[[ "$ready" == target/bwrap-signal-ready-* && -f "$ready" ]]
rm -f -- "$ready"
test "$signal_status" -eq 42
```

Expected: the inner command receives SIGTERM and returns its trapped status 42 through bwrap and `scripts/run`.

- [ ] **Step 7: Commit the gateway**

```sh
git add scripts/run scripts/rootfs/activate_environment.sh \
  scripts/rootfs/run_in_rootfs.sh scripts/rootfs/sync_test_environment.sh \
  scripts/rootfs/tests/test_run_gateway.py scripts/run_local_control_plane.sh \
  scripts/run_local_8gpu_capacity.sh python/tests/test_local_8gpu_capacity.py
git commit -m "Route local execution through bwrap"
```

---

### Task 4: Python, Cargo, and native-artifact enforcement

**Files:**

- Create: `python/monarch/_rootfs_contract.py`
- Create: `python/tests/test_native_artifact_provenance.py`
- Create: `scripts/rootfs/rustc-wrapper.sh`
- Create: `scripts/rootfs/tests/test_guarded_entrypoints.py`
- Modify: `python/monarch/__init__.py`
- Modify: `setup.py`
- Modify: `monarch_mini/python/setup.py`
- Modify: `python/tests/conftest.py`
- Modify: `.cargo/config.toml`
- Modify: `scripts/sccache-rustc-wrapper.sh`
- Modify: `monarch_mini/Makefile`

**Interfaces:**

- Consumes: `execution_contract.sh identify-controlled`
- Produces: `ContractIdentity(schema: int, recipe_digest: str)`
- Produces: `require_checkout(repo_root: Path, argv: Sequence[str] | None = None) -> ContractIdentity | None`
- Produces: `require_source_import(module_file: Path) -> ContractIdentity | None`
- Produces: `native_artifact_is_current(artifact: Path, package_dir: Path, identity: ContractIdentity) -> bool`
- Produces: `require_native_manifest(package_dir: Path, identity: ContractIdentity) -> None`
- Produces: `write_native_manifest(package_dir: Path, identity: ContractIdentity, artifacts: Sequence[Path]) -> None`

- [ ] **Step 1: Write failing Python and Cargo seam tests**

In `test_guarded_entrypoints.py`, remove `MONARCH_IN_ROOTFS` and `MONARCH_ROOTFS_RECIPE_SHA256` from subprocess environments and assert source import, both setup backends, nested pytest collection, and the rustc wrapper exit 2 before their delegated tool executes. Parse `.cargo/config.toml` with `tomllib` and assert `build.rustc-wrapper == "scripts/rootfs/rustc-wrapper.sh"`.

In `test_native_artifact_provenance.py`, exercise missing, malformed, wrong-recipe, missing-artifact, changed-size/mtime, valid, and atomic-replacement manifests.

```python
def test_replaced_artifact_is_not_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    identity = ContractIdentity(schema=1, recipe_digest="a" * 64)
    write_native_manifest(package, identity, [artifact])
    assert native_artifact_is_current(artifact, package, identity)
    artifact.write_bytes(b"replacement")
    assert not native_artifact_is_current(artifact, package, identity)


def test_rustc_wrapper_rejects_marker_only_entry(tmp_path: Path) -> None:
    compiler = tmp_path / "compiler"
    compiler.write_text("#!/bin/sh\necho executed > \"$1\"\n")
    compiler.chmod(0o755)
    sentinel = tmp_path / "sentinel"
    env = {**os.environ, "MONARCH_IN_ROOTFS": "1"}
    env.pop("MONARCH_ROOTFS_RECIPE_SHA256", None)
    result = subprocess.run(
        [REPO_ROOT / "scripts/rootfs/rustc-wrapper.sh", compiler, sentinel],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    assert not sentinel.exists()
```

- [ ] **Step 2: Run seam tests and confirm RED**

```sh
scripts/run python -m pytest \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  python/tests/test_native_artifact_provenance.py -q
```

Expected: FAIL because the Python adapter, manifest helpers, and Cargo wrapper do not exist.

- [ ] **Step 3: Implement the stdlib Python adapter**

Treat a path as a guarded standalone source checkout only when its computed repository root contains both `.git` and `scripts/rootfs/execution_contract.sh`. Installed wheels and fbsource paths return `None` without invoking the shell validator. Call `identify-controlled`, parse its exact output, and raise `SystemExit(2)` after forwarding its diagnostic on failure.

Use a JSON manifest at `python/monarch/.native-artifacts.json`:

```json
{
  "schema": 1,
  "recipe_digest": "<64 lowercase hex characters>",
  "artifacts": {
    "_rust_bindings.cpython-312-x86_64-linux-gnu.so": {
      "size": 123,
      "mtime_ns": 456
    }
  }
}
```

Resolve every manifest path below `package_dir`, reject symlinks and unlisted source-tree `.so` files, and write through a same-directory temporary file followed by `os.replace`. `require_source_import` requires the manifest only for a real rootfs identity; exact GitHub Linux and Darwin source builds return `None` and use their controlled-domain toolchains.

- [ ] **Step 4: Guard source import, setup backends, and pytest collection**

Call `require_source_import(__file__)` at the beginning of `python/monarch/__init__.py`, before `_rust_bindings` or Torch. Load the adapter by file path at the beginning of both setup backends, before setuptools, Torch, CUDA, npm, or Cargo probing. Load it in `python/tests/conftest.py` before plugin registration, pytest import, Monarch import, or CUDA detection.

In `monarch_mini/python/setup.py`, resolve the static library from `CARGO_TARGET_DIR` when present:

```python
target_dir = Path(os.environ.get("CARGO_TARGET_DIR", WORKSPACE_DIR / "target"))
if not target_dir.is_absolute():
    target_dir = Path(WORKSPACE_DIR, target_dir)
STATIC_LIB = target_dir / PROFILE / "libmonarch_mini.a"
```

- [ ] **Step 5: Stamp editable native outputs and reject stale cache reuse**

Subclass `setuptools_rust.build_rust` as `BuildRustWithProvenance`. After `super().run()` succeeds with `self.inplace`, collect the exact source-tree `_rust_bindings` output plus configured C/C++ extension outputs, remove known source-tree native extension files that are not outputs of the current feature set, and atomically write the manifest. Register it as `cmdclass["build_rust"]`.

Change the existing C++ mtime cache in `build_ext.build_extension` to reuse a source-tree `.so` only when both its source mtimes and `native_artifact_is_current(so_path, package_dir, contract_identity)` pass. Controlled GitHub Linux and Darwin retain their existing mtime behavior because they have no rootfs identity. Assert in a wheel test later that `.native-artifacts.json` is absent from built wheels.

- [ ] **Step 6: Add and chain Cargo guards**

Create an executable wrapper:

```bash
#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
"$repo_root/scripts/rootfs/execution_contract.sh" require-controlled
[[ $# -ge 1 ]] || { echo "error: rustc wrapper requires a compiler" >&2; exit 2; }
exec "$@"
```

Set `rustc-wrapper = "scripts/rootfs/rustc-wrapper.sh"` under `.cargo/config.toml`'s existing `[build]`. Make `sccache-rustc-wrapper.sh` call `require-github-linux` before its current fallback logic because `RUSTC_WRAPPER` overrides Cargo config. Make `monarch_mini/Makefile` invoke the shared guard before `cargo`, `cc`, run, or clean targets and honor absolute `CARGO_TARGET_DIR`.

Mark the compiler adapter executable:

```sh
chmod +x scripts/rootfs/rustc-wrapper.sh
```

- [ ] **Step 7: Run focused tests and real seams**

```sh
scripts/run python -m pytest \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  python/tests/test_native_artifact_provenance.py -q
USE_TENSOR_ENGINE=0 scripts/run uv pip install --no-build-isolation --no-deps -e .
scripts/run python -c "from monarch import actor; print('ok')"
scripts/run cargo check --locked -p hyperactor
scripts/run cargo clippy --locked -p hyperactor --all-targets -- -D warnings
```

Expected: focused tests pass; editable source import validates its manifest; Cargo invokes the wrapper and succeeds inside bwrap.

- [ ] **Step 8: Commit the Python and Cargo enforcement**

```sh
git add python/monarch/_rootfs_contract.py python/monarch/__init__.py \
  python/tests/conftest.py python/tests/test_native_artifact_provenance.py \
  setup.py monarch_mini/python/setup.py monarch_mini/Makefile \
  .cargo/config.toml scripts/rootfs/rustc-wrapper.sh \
  scripts/sccache-rustc-wrapper.sh scripts/rootfs/tests/test_guarded_entrypoints.py
git commit -m "Guard Python and Rust source execution"
```

---

### Task 5: Script seams and complete execution-domain inventory

**Files:**

- Create: `scripts/rootfs/execution-domains.toml`
- Create: `scripts/rootfs/audit_entrypoints.py`
- Create: `scripts/rootfs/tests/test_entrypoint_inventory.py`
- Modify: `scripts/rootfs/tests/test_guarded_entrypoints.py`
- Modify: `scripts/common-setup.sh`
- Modify: `scripts/common-setup-macos.sh`
- Modify: `scripts/build_monarch_for_docs.sh`
- Modify: `scripts/fetch_disabled_tests.py`
- Modify: `scripts/local_8gpu_capacity.py`
- Modify: `scripts/profile_compile_obligations.sh`
- Modify: `monarch_mini/test_certs/generate.sh`
- Modify: `hyperactor_mesh/test/hyperactor_mesh_proxy_liveness_test.sh`
- Modify: `hyperactor_remote/example/remote_spawner.sh`

**Interfaces:**

- Consumes: Task 1 guard CLI
- Produces: `python scripts/rootfs/audit_entrypoints.py --check -> status 0 or unclassified/overlapping paths`
- Produces domains: `host-bootstrap`, `rootfs-development`, `github-linux`, `darwin`, `controlled-test-fixture`, `meta-internal`, `remote-orchestration`, and `controlled-ci`

- [ ] **Step 1: Write failing inventory and pre-mutation tests**

The inventory test must discover every Git-tracked executable by mode, the two Makefiles, both setup backends, the frontend package, Python examples and benches, Cargo bin/example/bench targets from `cargo metadata --locked --no-deps`, and GitHub workflows. It must require exactly one matching inventory rule per discovery.

Extend negative seam tests so `build_monarch_for_docs.sh`, `profile_compile_obligations.sh`, `fetch_disabled_tests.py`, certificate generation, the liveness fixture, and `remote_spawner.sh` all exit 2 with the marker removed before a fake `python`, `uv`, `cargo`, `openssl`, or test binary can write a sentinel.

```python
def test_execution_inventory_is_complete() -> None:
    result = subprocess.run(
        [sys.executable, REPO_ROOT / "scripts/rootfs/audit_entrypoints.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_docs_builder_rejects_before_fake_uv_runs(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sentinel = tmp_path / "sentinel"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(f"#!/bin/sh\necho ran > {sentinel}\n")
    fake_uv.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin"}
    env.pop("MONARCH_IN_ROOTFS", None)
    result = subprocess.run(
        [REPO_ROOT / "scripts/build_monarch_for_docs.sh"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    assert not sentinel.exists()
```

- [ ] **Step 2: Run the inventory tests and confirm RED**

```sh
scripts/run python -m pytest \
  scripts/rootfs/tests/test_entrypoint_inventory.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py -q
```

Expected: FAIL because the inventory does not exist and the named seams are unguarded.

- [ ] **Step 3: Add exact execution-domain rules**

Classify host bootstrap as `scripts/run`, `scripts/rootfs/build_rootfs.sh`, `scripts/rootfs/enter_rootfs.sh`, and `scripts/rootfs/execution_contract.sh`. Classify `common-setup.sh` and `sccache-rustc-wrapper.sh` as GitHub Linux, and `common-setup-macos.sh` as Darwin. Classify rootfs development and controlled fixtures as the remaining OSS scripts that build, test, profile, generate certificates, or invoke Cargo. Classify `whittle` and the Buck-only hyperactor supervision scripts as Meta-internal. Classify remotemount and torchtitan MAST setup/driver scripts as remote orchestration. Classify `.github/workflows/*.yml` as controlled CI.

Use explicit glob rules for `python/examples/**/*.py`, `examples/**/*.py`, `python/benches/**/*.py`, `**/src/bin/**/*.rs`, `**/examples/**/*.rs`, and `**/benches/**/*.rs`; the scanner reports zero-match rules and overlapping matches.

- [ ] **Step 4: Implement the stdlib inventory scanner**

Use `tomllib`, `fnmatch`, `git ls-files --stage`, and `cargo metadata --locked --no-deps --format-version 1`. Normalize every discovered path relative to the repository, match it against TOML rules, and print one `unclassified: <path>` or `overlap: <path>: <domains>` line per error. `--check` exits 1 for any error and 0 only when every discovered entrypoint has exactly one domain.

- [ ] **Step 5: Guard local and controlled-CI script seams**

Source `execution_contract.sh` immediately after strict shell setup and before mutations. Rootfs-development and controlled fixtures call `require-controlled`; `common-setup.sh` and the sccache wrapper call `require-github-linux`; the macOS setup calls `require-darwin`. Python CLIs load `_rootfs_contract.py` by file path and guard only in their `main()` paths so unit tests can import pure helpers.

Update `profile_compile_obligations.sh` to activate `.venv-rootfs`, never `.venv`. Keep external-orchestration and Meta-internal scripts classified without adding a false local rootfs promise to their remote/Buck execution.

- [ ] **Step 6: Run the complete inventory and guard suite**

```sh
scripts/run python scripts/rootfs/audit_entrypoints.py --check
scripts/run python -m pytest \
  scripts/rootfs/tests/test_entrypoint_inventory.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py -q
scripts/run bash -n scripts/common-setup.sh scripts/common-setup-macos.sh \
  scripts/build_monarch_for_docs.sh scripts/profile_compile_obligations.sh \
  monarch_mini/test_certs/generate.sh \
  hyperactor_mesh/test/hyperactor_mesh_proxy_liveness_test.sh \
  hyperactor_remote/example/remote_spawner.sh
```

Expected: every entrypoint is classified exactly once and every guarded seam passes its focused tests.

- [ ] **Step 7: Commit the inventory and seam guards**

```sh
git add scripts/rootfs/execution-domains.toml scripts/rootfs/audit_entrypoints.py \
  scripts/rootfs/tests/test_entrypoint_inventory.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py scripts/common-setup.sh \
  scripts/common-setup-macos.sh scripts/build_monarch_for_docs.sh \
  scripts/fetch_disabled_tests.py scripts/local_8gpu_capacity.py \
  scripts/profile_compile_obligations.sh monarch_mini/test_certs/generate.sh \
  hyperactor_mesh/test/hyperactor_mesh_proxy_liveness_test.sh \
  hyperactor_remote/example/remote_spawner.sh
git commit -m "Classify and guard repository execution seams"
```

---

### Task 6: Deterministic frontend build and lifecycle guards

**Files:**

- Create: `scripts/build_dashboard_frontend.py`
- Create: `python/tests/test_frontend_build.py`
- Modify: `setup.py`
- Modify: `python/monarch/monarch_dashboard/frontend/package.json`
- Test: `scripts/rootfs/tests/test_guarded_entrypoints.py`

**Interfaces:**

- Consumes: Python `require_checkout` and shell `require-controlled`
- Produces: `build_dashboard_frontend(frontend_dir: Path, *, npm: str = "npm") -> tuple[Path, Path, Path]`
- Produces: npm scripts `rootfs-check`, `preinstall`, `prebuild`, `pretypecheck`, `pretest`, `typecheck`, `build`, and an intentionally failing `test`

- [ ] **Step 1: Write failing frontend builder and lifecycle tests**

Use a temporary frontend and fake npm executable to cover a stale build removal, symlink rejection, missing npm, `npm ci` failure, build failure, missing JS, missing CSS, CSS relocation, index copying, and successful fresh output. Assert package scripts guard install/build/typecheck/test, typecheck uses `tsc --noEmit`, and test exits nonzero with `no test runner configured`.

```python
import json

FRONTEND = REPO_ROOT / "python/monarch/monarch_dashboard/frontend"


def make_frontend(tmp_path: Path) -> Path:
    frontend = tmp_path / "frontend"
    (frontend / "public").mkdir(parents=True)
    (frontend / "public/index.html").write_text("fresh template")
    (frontend / "package.json").write_text(json.dumps({"name": "fixture"}))
    (frontend / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {}}))
    return frontend


def make_fake_npm(tmp_path: Path, *, create_js: bool, create_css: bool) -> Path:
    npm = tmp_path / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "if [ \"${1:-}\" = ci ]; then exit 0; fi\n"
        "mkdir -p build/static/js\n"
        f"{'printf js > build/static/js/main.js' if create_js else ':'}\n"
        f"{'printf css > build/static/js/main.css' if create_css else ':'}\n"
    )
    npm.chmod(0o755)
    return npm


def test_success_replaces_stale_assets(tmp_path: Path) -> None:
    frontend = make_frontend(tmp_path)
    stale = frontend / "build/index.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale")
    npm = make_fake_npm(tmp_path, create_js=True, create_css=True)
    index, javascript, css = build_dashboard_frontend(frontend, npm=str(npm))
    assert index.read_text() == (frontend / "public/index.html").read_text()
    assert javascript == frontend / "build/static/js/main.js"
    assert css == frontend / "build/static/css/main.css"
    assert "stale" not in index.read_text()


def test_frontend_test_script_fails_honestly() -> None:
    result = subprocess.run(
        ["npm", "--prefix", FRONTEND, "test"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "no test runner configured" in result.stderr
```

- [ ] **Step 2: Run the frontend tests and confirm RED**

```sh
scripts/run python -m pytest python/tests/test_frontend_build.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py -q
```

Expected: FAIL because the helper is absent, stale output is accepted, and `npm test` succeeds.

- [ ] **Step 3: Implement the fail-closed frontend helper**

Validate controlled execution before filesystem or npm probing. Resolve `frontend_dir`, reject a missing directory or symlinked `build`, resolve npm with `shutil.which`, remove only the exact build directory, and run:

```python
subprocess.run([npm_path, "ci"], cwd=frontend_dir, check=True)
subprocess.run([npm_path, "run", "build"], cwd=frontend_dir, check=True)
```

Require `build/static/js/main.js` and `build/static/js/main.css`, move CSS to `build/static/css/main.css`, copy `public/index.html` to `build/index.html`, and return those three final paths. Convert missing tools and subprocess failures to concise `RuntimeError` messages.

- [ ] **Step 4: Use the helper from setuptools**

Load the helper by file path in `setup.py`. Remove the prebuilt-index early return, `/usr/bin/npm` preference, missing-directory success, and missing-npm warning. `BuildFrontend.run()` calls the helper and propagates failure so editable and wheel builds cannot package stale assets.

- [ ] **Step 5: Add npm lifecycle enforcement and type checking**

Set these exact package scripts without changing dependencies or either lockfile:

```json
{
  "rootfs-check": "../../../../scripts/rootfs/execution_contract.sh require-controlled",
  "preinstall": "npm run rootfs-check",
  "prebuild": "npm run rootfs-check",
  "pretypecheck": "npm run rootfs-check",
  "pretest": "npm run rootfs-check",
  "typecheck": "tsc --noEmit",
  "build": "npm run typecheck && esbuild src/index.tsx --bundle --outfile=build/static/js/main.js --loader:.tsx=tsx --loader:.ts=ts --loader:.css=css --jsx=automatic --minify --target=es2020 --define:process.env.NODE_ENV=\"production\"",
  "test": "node -e \"console.error('no test runner configured'); process.exit(1)\""
}
```

The canonical gateway prevents pre-install mutation; npm lifecycle hooks provide secondary fail-closed detection. `--ignore-scripts` remains a documented deliberate bypass outside the supported workflow.

- [ ] **Step 6: Run focused and real frontend checks**

```sh
scripts/run python -m pytest python/tests/test_frontend_build.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py -q
scripts/run npm --prefix python/monarch/monarch_dashboard/frontend ci
scripts/run npm --prefix python/monarch/monarch_dashboard/frontend run typecheck
scripts/run npm --prefix python/monarch/monarch_dashboard/frontend run build
```

Run the expected-failure contract separately:

```sh
if scripts/run npm --prefix python/monarch/monarch_dashboard/frontend test; then
  echo "error: frontend test unexpectedly succeeded" >&2
  exit 1
fi
```

Expected: install, typecheck, and build pass; the test command reports no configured runner and fails.

- [ ] **Step 7: Build a wheel and verify frontend package data**

```sh
scripts/run uv build --wheel --no-build-isolation
scripts/run python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

wheel = max(Path("dist").glob("*.whl"), key=lambda path: path.stat().st_mtime_ns)
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
assert any(name.endswith("monarch_dashboard/frontend/build/index.html") for name in names)
assert any(name.endswith("monarch_dashboard/frontend/build/static/js/main.js") for name in names)
assert any(name.endswith("monarch_dashboard/frontend/build/static/css/main.css") for name in names)
assert not any(name.endswith(".native-artifacts.json") for name in names)
PY
```

Expected: the wheel contains fresh HTML, JS, and CSS and excludes the editable native manifest.

- [ ] **Step 8: Commit without staging `yarn.lock`**

```sh
git add scripts/build_dashboard_frontend.py python/tests/test_frontend_build.py \
  setup.py python/monarch/monarch_dashboard/frontend/package.json \
  scripts/rootfs/tests/test_guarded_entrypoints.py
if git diff --cached --name-only | grep -Fxq 'python/monarch/monarch_dashboard/frontend/yarn.lock'; then
  echo "error: refusing to stage the user's yarn.lock change" >&2
  exit 1
fi
git commit -m "Make dashboard assets build hermetically"
```

---

### Task 7: Docs paths, repository policy, and agent procedure

**Files:**

- Modify: `docs/Makefile`
- Modify: `docs/source/conf.py`
- Modify: `AGENTS.md`
- Modify: `MONARCH_INFO.md`
- Modify: `README.md`
- Modify: `docs/DOCUMENTATION_GUIDE.md`
- Modify: `docs/source/monarch-dashboard.md`
- Modify: `docs/source/admin-tui.md`
- Modify: `docs/source/books/hyperactor-book/README.md`
- Modify: `docs/source/books/hyperactor-mesh-book/README.md`
- Modify: `python/monarch/monarch_dashboard/README.md`
- Modify: `python/monarch/monarch_dashboard/frontend/README.md`
- Modify: `python/monarch/monarch_dashboard/frontend/README.fb`
- Modify: `.agents/skills/run-monarch-single-machine/SKILL.md`
- Modify: `.agents/skills/run-monarch-single-machine/references/rootfs.md`
- Test: `scripts/rootfs/tests/test_guarded_entrypoints.py`
- Test: `scripts/rootfs/tests/test_entrypoint_inventory.py`

**Interfaces:**

- Consumes: `scripts/run`, `CARGO_TARGET_DIR`, shared guard, and execution inventory
- Produces: guarded Sphinx Make targets and Cargo-doc discovery under the digest-specific target directory
- Produces: one canonical Linux-local command vocabulary across human and agent documentation

- [ ] **Step 1: Use the agent-document skills and write failing docs tests**

Before editing `AGENTS.md` or the repo-local skill, invoke `writing-for-agents` and `writing-skills`. Add tests that `make html`, `make linkcheck`, and `make clean` fail before running an overridden `SPHINXBUILD` or deleting a sentinel when the marker is absent. Extend the documentation audit to reject direct Linux-local `uv`, Cargo, pytest, Make, npm, and checkout-Python commands in the named development sections.

```python
def test_docs_clean_rejects_before_deleting_output(tmp_path: Path) -> None:
    output = REPO_ROOT / "docs/build/guard-sentinel"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("keep")
    env = dict(os.environ)
    env.pop("MONARCH_IN_ROOTFS", None)
    result = subprocess.run(
        ["make", "-C", REPO_ROOT / "docs", "clean"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    assert output.read_text() == "keep"
    output.unlink()
```

- [ ] **Step 2: Run docs guard and documentation audits and confirm RED**

```sh
scripts/run python -m pytest \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  scripts/rootfs/tests/test_entrypoint_inventory.py -q
```

Expected: docs Make targets are unguarded and the named files still advertise direct checkout execution.

- [ ] **Step 3: Guard Make and use the digest-specific Cargo docs path**

Set `.DEFAULT_GOAL := help`. Add a non-overridable private phony guard target whose recipe invokes `../scripts/rootfs/execution_contract.sh require-controlled`, and make `help`, `html`, `clean`, and the `%` catch-all depend on it. Remove the broken `generate-examples` target; Sphinx Gallery already owns example generation from `conf.py`.

In `docs/source/conf.py`, derive Rust docs from the environment:

```python
cargo_target_dir = Path(
    os.environ.get("CARGO_TARGET_DIR", Path(__file__).resolve().parents[2] / "target")
).resolve()
html_extra_path = [str(cargo_target_dir / "doc")]
```

Keep GitHub CI's default `target/doc` behavior when `CARGO_TARGET_DIR` is absent.

- [ ] **Step 4: Rewrite the policy and developer commands around `scripts/run`**

In `AGENTS.md`, make the bwrap contract the first build rule, list host-bootstrap/controlled-CI/Darwin/installed-runtime/remote exemptions, and replace local commands with `scripts/run`. Update `MONARCH_INFO.md`, checkout-development sections of `README.md`, and `DOCUMENTATION_GUIDE.md` consistently.

Document the truthful docs sequence:

```sh
scripts/run uv sync --frozen --inexact --group docs --extra kubernetes --no-dev --no-install-project
scripts/run bash scripts/build_monarch_for_docs.sh
scripts/run cargo doc --locked --workspace --no-deps
scripts/run mdbook build docs/source/books/hyperactor-book
scripts/run mdbook build docs/source/books/hyperactor-mesh-book
scripts/run make -C docs html
```

State that `make -C docs html` runs Sphinx Gallery but does not itself run Cargo doc or mdBook. Keep package-consumer `pip install torchmonarch`, remote scheduler commands, Git commands, and controlled CI snippets unwrapped.

- [ ] **Step 5: Correct dashboard and frontend usage docs**

Use `scripts/run python -m monarch.monarch_dashboard` or `scripts/run monarch-dashboard` for checkout execution. Remove references to absent `run.sh`, the invalid `python -m monarch_dashboard` module, and unsupported `--rebuild` and `--time-range` flags. Describe npm/package-lock as the local rootfs path and Yarn/yarn.lock as Buck-only; retain the existing lock-parity procedure without modifying `yarn.lock`.

- [ ] **Step 6: Update and pressure-test the repo-local skill**

Keep the skill procedural and point detailed rootfs facts to `references/rootfs.md`. Its normal branch must always enter with `scripts/run`; its capacity branches run control-plane or 8-GPU verification through that gateway; its CI/macOS/remote branches state why they do not nest bwrap.

Run four writing-skill pressure scenarios with fresh subagents:

1. A Nix-host actor test request must choose `scripts/run pytest python/tests/test_actor.py -q`.
2. A direct Cargo error reproduction must choose `scripts/run cargo test -p hyperactor` and preserve arguments.
3. A missing rootfs must let `scripts/run` auto-build it rather than suggesting host toolchain overrides.
4. A GitHub Linux job or remote worker request must recognize its separate controlled domain and avoid nesting local bwrap.

The skill passes only when every scenario selects the intended branch and names the relevant contract artifact or acceptance output.

- [ ] **Step 7: Run focused docs tests and build all documentation formats**

```sh
scripts/run python -m pytest \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  scripts/rootfs/tests/test_entrypoint_inventory.py -q
scripts/run uv sync --frozen --inexact --group docs --extra kubernetes \
  --no-dev --no-install-project
scripts/run bash scripts/build_monarch_for_docs.sh
scripts/run cargo doc --locked --workspace --no-deps \
  --exclude monarch_rdma_extension --exclude cuda_ping_pong --exclude parameter_server
scripts/run mdbook build docs/source/books/hyperactor-book
scripts/run mdbook build docs/source/books/hyperactor-mesh-book
scripts/run make -C docs clean
scripts/run make -C docs html SPHINXOPTS="-v --keep-going"
```

Expected: audits pass and all three documentation formats build from rootfs-controlled tools.

- [ ] **Step 8: Commit docs and skill changes**

```sh
git add docs/Makefile docs/source/conf.py AGENTS.md MONARCH_INFO.md README.md \
  docs/DOCUMENTATION_GUIDE.md docs/source/monarch-dashboard.md \
  docs/source/admin-tui.md docs/source/books/hyperactor-book/README.md \
  docs/source/books/hyperactor-mesh-book/README.md \
  python/monarch/monarch_dashboard/README.md \
  python/monarch/monarch_dashboard/frontend/README.md \
  python/monarch/monarch_dashboard/frontend/README.fb \
  .agents/skills/run-monarch-single-machine/SKILL.md \
  .agents/skills/run-monarch-single-machine/references/rootfs.md \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  scripts/rootfs/tests/test_entrypoint_inventory.py
git commit -m "Document bwrap-only local development"
```

---

### Task 8: Full acceptance and review

**Files:**

- Verify all changed files
- Preserve: `python/monarch/monarch_dashboard/frontend/yarn.lock`

**Interfaces:**

- Consumes: all preceding tasks
- Produces: current focused, build, test, docs, frontend, control-plane, and 8-GPU evidence

- [ ] **Step 1: Run formatting, syntax, and focused contract suites**

```sh
scripts/run cargo fmt --check
scripts/run bash -n scripts/run scripts/rootfs/*.sh scripts/*.sh \
  monarch_mini/test_certs/generate.sh \
  hyperactor_mesh/test/hyperactor_mesh_proxy_liveness_test.sh \
  hyperactor_remote/example/remote_spawner.sh
scripts/run python -m pytest \
  scripts/rootfs/tests/test_execution_contract.py \
  scripts/rootfs/tests/test_run_gateway.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  scripts/rootfs/tests/test_entrypoint_inventory.py \
  python/tests/test_native_artifact_provenance.py \
  python/tests/test_frontend_build.py \
  python/tests/test_local_8gpu_capacity.py -q
scripts/run python scripts/rootfs/audit_entrypoints.py --check
```

Expected: all commands pass.

- [ ] **Step 2: Verify actor-only Python and Rust workflows**

```sh
USE_TENSOR_ENGINE=0 scripts/run uv sync --frozen --extra test
USE_TENSOR_ENGINE=0 scripts/run uv pip install --no-build-isolation --no-deps -e .
scripts/run python -c "from monarch import actor; print('ok')"
scripts/run python -m pytest python/tests/ -v -m "not oss_skip"
scripts/run cargo clippy --locked --workspace --all-targets -- -D warnings
scripts/run cargo nextest run --locked
```

Expected: import, Python tests, clippy, and nextest pass inside the actor-only controlled environment. If an existing unrelated suite failure appears, capture the exact node or target, reproduce it on the approved base commit through `scripts/run`, and keep it separate from contract acceptance.

- [ ] **Step 3: Verify frontend, wheel, and docs workflows**

Repeat the real frontend and wheel commands from Task 6 and the complete docs commands from Task 7. Confirm exact Node/npm/mdBook versions, fresh packaged assets, absence of the editable manifest from the wheel, and Sphinx/Rust/mdBook output directories under their documented paths.

- [ ] **Step 4: Verify tensor-engine control-plane behavior**

```sh
scripts/run scripts/rootfs/sync_test_environment.sh
scripts/run scripts/run_local_control_plane.sh --keep-going
scripts/run scripts/run_local_8gpu_capacity.sh
```

Expected: the control-plane runner emits `control-plane-results/control-plane-python.xml` and `$REPO_ROOT/target/nextest/ci/junit.xml` (cargo-nextest resolves its store from the workspace-root default target directory and ignores `CARGO_TARGET_DIR`). On the eight-GPU host, the capacity verifier observes ranks `[0, 1, 2, 3, 4, 5, 6, 7]` and accepts Python full-suite failures only when every failed node passes its identical-environment isolation rerun.

- [ ] **Step 5: Confirm rootfs and host-boundary behavior**

```sh
CC=/host/cc CXX=/host/cxx PYTHONPATH=/host/python \
  scripts/run sh -c 'test -z "${CC+x}" && test -z "${CXX+x}" && test -z "${PYTHONPATH+x}"'
scripts/run python - <<'PY'
import os
from pathlib import Path

assert os.statvfs("/").f_flag & os.ST_RDONLY
assert not (os.statvfs("/workspace/monarch").f_flag & os.ST_RDONLY)
contract = Path("/etc/monarch-rootfs-contract").read_text()
assert "MONARCH_ROOTFS_RECIPE_SHA256=" in contract
assert Path(os.environ["CARGO_TARGET_DIR"]).parts[-3:-1] == ("target", "bwrap")
PY
```

Expected: host compiler/Python variables are absent, rootfs is read-only, checkout is writable, and target/provenance paths are digest-scoped.

- [ ] **Step 6: Run two-stage code review and verification-before-completion**

Invoke `superpowers:requesting-code-review` for spec compliance and code quality. Resolve every finding with a reproducing test through `scripts/run`. Then invoke `superpowers:verification-before-completion`, rerun any command whose evidence became stale after fixes, and record the final exit status and artifact path for each acceptance tier.

- [ ] **Step 7: Inspect final Git state**

```sh
git status --short
git log --oneline --decorate -10
git diff --check 79ed4a8b3..HEAD
```

Expected: the feature worktree is clean, no build artifacts are tracked, diff checks pass, and the original checkout still retains the user's unstaged `yarn.lock` modification.
