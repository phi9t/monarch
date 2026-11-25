# Ginkgo Insula Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ginkgo/insula` the sole schema-backed rootfs invocation module for governed local bwrap-rootfs runs.

**Architecture:** Add Insula as a deep module under `ginkgo/insula`, with schema-first data models for local environment, invocation specs, materialized invocations, bwrap plans, and execution results. Migrate existing rootfs entrypoints into compatibility adapters over Insula, then migrate Ginkgo SGLang launch to consume Insula instead of raw rootfs argv.

**Tech Stack:** Python 3.12, frozen dataclasses, `yaml.safe_load` / `yaml.safe_dump`, JSON artifacts, `subprocess`, pytest, bash compatibility wrappers, existing `scripts/rootfs/build_rootfs.sh`, existing `scripts/rootfs/verify_rootfs.py`, existing `scripts/rootfs/rootfs_sandbox_config.py`.

**Spec:** `.scratch/ginkgo-insula/spec.md`

## Global Constraints

- No fallback. Fail fast, fail loud.
- Insula owns all governed local bwrap-rootfs invocation.
- No caller outside `ginkgo/insula`, `scripts/rootfs/build_rootfs.sh`, and test fixtures may construct raw bwrap argv.
- `scripts/run` and `scripts/rootfs/enter_rootfs.sh` become compatibility adapters over Insula.
- Ginkgo serving must not assemble raw `enter_rootfs.sh` or bwrap argv.
- Portable specs must not encode absolute host paths.
- Concrete host paths are allowed only in local environment config, materialized invocation artifacts, and resolved evidence.
- Sandbox paths are absolute because they are part of the rootfs protocol.
- Do not change rootfs contents or the Docker build recipe in this plan.
- Do not regenerate `uv.lock`.
- Existing dirty files `uv.lock` and `python/monarch/monarch_dashboard/frontend/yarn.lock` are unrelated and must not be staged or modified.
- Every task is test-first and independently reviewable.

---

## File Structure

- Create `ginkgo/insula/__init__.py`
  - Re-export stable public schema and runner interfaces.
- Create `ginkgo/insula/schema.py`
  - Own frozen dataclasses, parsing, validation, and serialization for Insula data models.
- Create `ginkgo/insula/refs.py`
  - Own logical ref parsing and resolution helpers.
- Create `ginkgo/insula/local_environment.py`
  - Own machine-local environment parsing and validation.
- Create `ginkgo/insula/rootfs_lifecycle.py`
  - Own rootfs existence, stale-recipe detection, build delegation, and verification delegation.
- Create `ginkgo/insula/materialize.py`
  - Own conversion from `InsulaInvocationSpec` to `MaterializedInsulaInvocation`.
- Create `ginkgo/insula/bwrap_plan.py`
  - Own bwrap argv construction, plan emission, and plan validation.
- Create `ginkgo/insula/executor.py`
  - Own direct execution of generated bwrap argv.
- Create `ginkgo/insula/artifacts.py`
  - Own durable artifact writing for materialized invocation, argv, env, plan, validation, stdout/stderr, and result.
- Create `ginkgo/insula/compatibility.py`
  - Own adapters for `scripts/run`, legacy `enter_rootfs.sh`, and Ginkgo SGLang invocation construction.
- Create `ginkgo/insula/cli.py`
  - Own command-line interface for Insula.
- Create tests:
  - `python/tests/test_ginkgo_insula_schema.py`
  - `python/tests/test_ginkgo_insula_materialize.py`
  - `python/tests/test_ginkgo_insula_bwrap_plan.py`
  - `python/tests/test_ginkgo_insula_compatibility.py`
  - `python/tests/test_ginkgo_insula_runtime_integration.py`
- Modify `scripts/run`
  - Convert to a thin compatibility adapter over `python -m ginkgo.insula.cli monarch-run`.
- Modify `scripts/rootfs/enter_rootfs.sh`
  - Convert to a thin compatibility adapter over `python -m ginkgo.insula.cli enter-rootfs-compat`.
- Modify `scripts/glm52_sglang_runtime.py`
  - Replace raw `launch.outer_argv` rootfs ownership with Insula invocation construction.
- Modify `ginkgo/local_run.py`
  - Include Insula artifacts in evidence manifests.
- Modify `ginkgo/docs/operator-workflow.md` and `ginkgo/README.md`
  - Document Insula as the authoritative rootfs invocation module.
- Modify project-contract tests:
  - Add guardrails against new direct bwrap/rootfs invocation construction outside Insula.

## Public Interfaces

The following interfaces are authoritative for implementation tasks.

```python
class InsulaConfigError(RuntimeError): ...
class InsulaExecutionError(RuntimeError): ...

@dataclass(frozen=True)
class InsulaLocalEnvironment:
    schema_version: int
    repo: str
    rootfs: dict[str, str]
    cache: str
    temp: str
    run: str
    results: str
    shared_memory: dict[str, str]
    gpu: dict[str, str]

@dataclass(frozen=True)
class InsulaBindSpec:
    name: str
    host: str
    sandbox: str
    mode: str
    create: bool
    required: bool

@dataclass(frozen=True)
class InsulaEnvironmentSpec:
    clear: bool
    values: dict[str, str]
    inherit_allowlist: list[str]

@dataclass(frozen=True)
class InsulaCommandSpec:
    cwd: str
    argv: list[str]

@dataclass(frozen=True)
class InsulaInvocationSpec:
    schema_version: int
    name: str
    rootfs_ref: str
    repo: InsulaBindSpec
    binds: list[InsulaBindSpec]
    environment: InsulaEnvironmentSpec
    command: InsulaCommandSpec
    artifacts: dict[str, str]
    network: str
    gpu: str
    die_with_parent: bool
    unshare_all: bool

@dataclass(frozen=True)
class MaterializedInsulaInvocation:
    schema_version: int
    invocation_id: str
    name: str
    repo_root: str
    rootfs_path: str
    rootfs_recipe_sha256: str
    cache_root: str
    command: InsulaCommandSpec
    binds: list[InsulaBindSpec]
    environment: dict[str, str]
    bwrap_argv: list[str]
    artifacts: dict[str, str]
    compatibility: dict[str, str]

@dataclass(frozen=True)
class InsulaPlan:
    schema_version: int
    invocation_id: str
    rootfs_path: str
    recipe_sha256: str
    cwd: str
    network: str
    gpu: str
    mounts: list[dict[str, str]]
    env: dict[str, str]
    command_argv: list[str]
    bwrap_argv_sha256: str

@dataclass(frozen=True)
class InsulaExecutionResult:
    schema_version: int
    invocation_id: str
    status: str
    returncode: int
    started_at: str
    completed_at: str
    stdout_path: str
    stderr_path: str
    materialized_path: str
    plan_path: str
    validation_path: str
```

Required functions:

```python
def load_local_environment(path: Path) -> InsulaLocalEnvironment: ...
def load_invocation_spec(path: Path) -> InsulaInvocationSpec: ...
def write_invocation_spec(spec: InsulaInvocationSpec, path: Path) -> None: ...
def materialize_invocation(
    *,
    spec: InsulaInvocationSpec,
    local_environment: InsulaLocalEnvironment,
    invocation_id: str,
    compatibility: dict[str, str] | None = None,
) -> MaterializedInsulaInvocation: ...
def emit_plan(invocation: MaterializedInsulaInvocation) -> InsulaPlan: ...
def validate_plan(invocation: MaterializedInsulaInvocation, plan: InsulaPlan) -> dict[str, object]: ...
def execute_invocation(invocation: MaterializedInsulaInvocation) -> InsulaExecutionResult: ...
```

---

### Task 1: Schema And Serialization

**Files:**
- Create: `ginkgo/insula/__init__.py`
- Create: `ginkgo/insula/schema.py`
- Create: `python/tests/test_ginkgo_insula_schema.py`

**Interfaces:**
- Produces: all dataclasses, `InsulaConfigError`, `load_invocation_spec`, `write_invocation_spec`, `invocation_spec_from_mapping`, `invocation_spec_to_mapping`

- [ ] **Step 1: Write the failing schema test file**

Create `python/tests/test_ginkgo_insula_schema.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import invocation_spec_from_mapping
from ginkgo.insula.schema import invocation_spec_to_mapping
from ginkgo.insula.schema import load_invocation_spec
from ginkgo.insula.schema import write_invocation_spec


VALID_INVOCATION = {
    "schema_version": 1,
    "name": "qwen3-sglang",
    "rootfs_ref": "rootfs://monarch-default",
    "repo": {
        "name": "repo",
        "host": "repo://",
        "sandbox": "/workspace/monarch",
        "mode": "ro",
        "create": False,
        "required": True,
    },
    "binds": [
        {
            "name": "run",
            "host": "run://qwen3",
            "sandbox": "/run/glm52",
            "mode": "rw",
            "create": True,
            "required": True,
        }
    ],
    "environment": {
        "clear": True,
        "values": {"CUDA_VISIBLE_DEVICES": "0"},
        "inherit_allowlist": ["TERM"],
    },
    "command": {
        "cwd": "/workspace/monarch",
        "argv": ["python3", "-c", "print('ok')"],
    },
    "artifacts": {
        "root": "run://qwen3/insula",
        "stdout": "run://qwen3/logs/stdout.log",
        "stderr": "run://qwen3/logs/stderr.log",
        "plan": "run://qwen3/insula/plan.yaml",
        "result": "run://qwen3/insula/result.json",
    },
    "network": "share-net",
    "gpu": "nvidia-if-present",
    "die_with_parent": True,
    "unshare_all": True,
}


def test_invocation_spec_round_trips(tmp_path: Path) -> None:
    spec = invocation_spec_from_mapping(VALID_INVOCATION)
    path = tmp_path / "insula.yaml"

    write_invocation_spec(spec, path)
    loaded = load_invocation_spec(path)

    assert invocation_spec_to_mapping(loaded) == invocation_spec_to_mapping(spec)


def test_invocation_spec_rejects_unknown_fields() -> None:
    data = dict(VALID_INVOCATION)
    data["unexpected"] = True

    with pytest.raises(InsulaConfigError, match="unknown field"):
        invocation_spec_from_mapping(data)


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("repo", "host"), "/data02/repo", "portable host paths must use logical refs"),
        (("repo", "sandbox"), "workspace/monarch", "sandbox path must be absolute"),
        (("command", "argv"), [], "command.argv must be non-empty"),
        (("environment", "clear"), False, "environment.clear must be true"),
        (("binds", 0, "mode"), "maybe", "bind mode must be one of"),
        (("rootfs_ref",), "repo://rootfs", "rootfs_ref must use rootfs://"),
    ],
)
def test_invocation_spec_rejects_invalid_values(path: tuple[object, ...], value: object, match: str) -> None:
    data = yaml.safe_load(yaml.safe_dump(VALID_INVOCATION))
    cursor = data
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value

    with pytest.raises(InsulaConfigError, match=match):
        invocation_spec_from_mapping(data)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_schema.py -q
```

Expected: import failure for `ginkgo.insula`.

- [ ] **Step 3: Implement schema dataclasses and validation**

Create `ginkgo/insula/schema.py` with the dataclasses listed in Public
Interfaces. Validation requirements:

- reject unknown fields by comparing mapping keys exactly;
- require `schema_version == 1`;
- require portable host fields to start with `repo://`, `cache://`, `temp://`, `run://`, `results://`, or `rootfs://`;
- require `rootfs_ref.startswith("rootfs://")`;
- require sandbox paths to start with `/`;
- require bind mode in `{"ro", "rw", "dev"}`;
- require `environment.clear is True`;
- require command argv as non-empty list of non-empty strings.

- [ ] **Step 4: Re-export stable symbols**

Create `ginkgo/insula/__init__.py`:

```python
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import InsulaInvocationSpec
from ginkgo.insula.schema import load_invocation_spec
from ginkgo.insula.schema import write_invocation_spec

__all__ = [
    "InsulaConfigError",
    "InsulaInvocationSpec",
    "load_invocation_spec",
    "write_invocation_spec",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_schema.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```sh
git add ginkgo/insula/__init__.py ginkgo/insula/schema.py python/tests/test_ginkgo_insula_schema.py
git commit -m "Add Insula invocation schema" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 2: Local Environment And Ref Resolution

**Files:**
- Create: `ginkgo/insula/local_environment.py`
- Create: `ginkgo/insula/refs.py`
- Create: `python/tests/test_ginkgo_insula_materialize.py`

**Interfaces:**
- Consumes: schema dataclasses from Task 1
- Produces: `load_local_environment`, `local_environment_from_mapping`, `resolve_path_ref`

- [ ] **Step 1: Write failing tests for local environment parsing and refs**

Create `python/tests/test_ginkgo_insula_materialize.py` with:

```python
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ginkgo.insula.local_environment import load_local_environment
from ginkgo.insula.refs import resolve_path_ref
from ginkgo.insula.schema import InsulaConfigError


def write_local_env(tmp_path: Path) -> Path:
    data = {
        "schema_version": 1,
        "repo": str(tmp_path / "repo"),
        "rootfs": {"monarch-default": str(tmp_path / "rootfs")},
        "cache": str(tmp_path / "cache"),
        "temp": str(tmp_path / "temp"),
        "run": str(tmp_path / "run"),
        "results": str(tmp_path / "results"),
        "shared_memory": {"mode": "host_path", "host_path": str(tmp_path / "shm"), "sandbox_path": "/dev/shm"},
        "gpu": {"mode": "nvidia", "devices": "0"},
    }
    path = tmp_path / "local-env.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_local_environment_resolves_refs(tmp_path: Path) -> None:
    env = load_local_environment(write_local_env(tmp_path))

    assert resolve_path_ref(env, "repo://ginkgo") == str(tmp_path / "repo" / "ginkgo")
    assert resolve_path_ref(env, "cache://qwen3") == str(tmp_path / "cache" / "qwen3")
    assert resolve_path_ref(env, "temp://run-a") == str(tmp_path / "temp" / "run-a")
    assert resolve_path_ref(env, "run://run-a/logs") == str(tmp_path / "run" / "run-a" / "logs")
    assert resolve_path_ref(env, "results://run-a") == str(tmp_path / "results" / "run-a")
    assert resolve_path_ref(env, "rootfs://monarch-default") == str(tmp_path / "rootfs")


def test_local_environment_rejects_relative_paths(tmp_path: Path) -> None:
    path = write_local_env(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["cache"] = "relative-cache"
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InsulaConfigError, match="cache must be an absolute path"):
        load_local_environment(path)


def test_resolve_path_ref_rejects_unknown_ref(tmp_path: Path) -> None:
    env = load_local_environment(write_local_env(tmp_path))

    with pytest.raises(InsulaConfigError, match="unsupported path ref"):
        resolve_path_ref(env, "unknown://x")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_materialize.py -q
```

Expected: import failure for `ginkgo.insula.local_environment`.

- [ ] **Step 3: Implement local environment parser**

Implement `InsulaLocalEnvironment` parsing in `ginkgo/insula/local_environment.py`.
Reject unknown fields and require absolute paths for `repo`, `cache`, `temp`,
`run`, `results`, and all `rootfs` values.

- [ ] **Step 4: Implement ref resolver**

Implement `resolve_path_ref(env, ref)` in `ginkgo/insula/refs.py`.
Use `Path(base) / suffix` for non-root refs. Strip exactly one leading slash
from suffix after the `://` marker.

- [ ] **Step 5: Run tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_materialize.py python/tests/test_ginkgo_insula_schema.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```sh
git add ginkgo/insula/local_environment.py ginkgo/insula/refs.py python/tests/test_ginkgo_insula_materialize.py
git commit -m "Add Insula local environment resolution" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 3: Materialized Invocation

**Files:**
- Create: `ginkgo/insula/materialize.py`
- Modify: `python/tests/test_ginkgo_insula_materialize.py`

**Interfaces:**
- Consumes: `InsulaInvocationSpec`, `InsulaLocalEnvironment`, `resolve_path_ref`
- Produces: `materialize_invocation`

- [ ] **Step 1: Add failing materialization test**

Append to `python/tests/test_ginkgo_insula_materialize.py`:

```python
from ginkgo.insula.materialize import materialize_invocation
from ginkgo.insula.schema import invocation_spec_from_mapping
from test_ginkgo_insula_schema import VALID_INVOCATION


def test_materialize_invocation_resolves_all_host_paths(tmp_path: Path) -> None:
    local_env = load_local_environment(write_local_env(tmp_path))
    spec = invocation_spec_from_mapping(VALID_INVOCATION)

    materialized = materialize_invocation(
        spec=spec,
        local_environment=local_env,
        invocation_id="run-1",
        compatibility={"adapter": "unit-test"},
    )

    assert materialized.invocation_id == "run-1"
    assert materialized.rootfs_path == str(tmp_path / "rootfs")
    assert materialized.repo_root == str(tmp_path / "repo")
    assert materialized.binds[0].host == str(tmp_path / "repo")
    assert materialized.binds[1].host == str(tmp_path / "run" / "qwen3")
    assert materialized.artifacts["stdout"] == str(tmp_path / "run" / "qwen3" / "logs" / "stdout.log")
    assert materialized.compatibility["adapter"] == "unit-test"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_materialize.py::test_materialize_invocation_resolves_all_host_paths -q
```

Expected: import failure for `ginkgo.insula.materialize`.

- [ ] **Step 3: Implement `materialize_invocation`**

Implementation requirements:

- resolve `rootfs_ref` through `rootfs://`;
- resolve repo bind and append it before extra binds;
- resolve every artifact ref;
- set `cache_root` from local env;
- preserve command cwd and argv;
- create no directories in this task;
- leave `bwrap_argv` empty until Task 4;
- populate `compatibility` with passed mapping or `{}`.

- [ ] **Step 4: Run materialization tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_materialize.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```sh
git add ginkgo/insula/materialize.py python/tests/test_ginkgo_insula_materialize.py
git commit -m "Materialize Insula invocation specs" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 4: Bwrap Plan And Argv Generation

**Files:**
- Create: `ginkgo/insula/bwrap_plan.py`
- Create: `python/tests/test_ginkgo_insula_bwrap_plan.py`
- Modify: `ginkgo/insula/materialize.py`

**Interfaces:**
- Consumes: `MaterializedInsulaInvocation`
- Produces: `build_bwrap_argv`, `emit_plan`, `validate_plan`

- [ ] **Step 1: Write failing bwrap plan tests**

Create `python/tests/test_ginkgo_insula_bwrap_plan.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from ginkgo.insula.bwrap_plan import build_bwrap_argv
from ginkgo.insula.bwrap_plan import emit_plan
from ginkgo.insula.bwrap_plan import validate_plan
from ginkgo.insula.local_environment import load_local_environment
from ginkgo.insula.materialize import materialize_invocation
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import invocation_spec_from_mapping
from test_ginkgo_insula_materialize import write_local_env
from test_ginkgo_insula_schema import VALID_INVOCATION


def materialized(tmp_path: Path):
    env = load_local_environment(write_local_env(tmp_path))
    spec = invocation_spec_from_mapping(VALID_INVOCATION)
    return materialize_invocation(
        spec=spec,
        local_environment=env,
        invocation_id="run-1",
        compatibility={"adapter": "unit-test"},
    )


def test_build_bwrap_argv_contains_rootfs_mounts_env_and_command(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    argv = build_bwrap_argv(invocation)

    assert argv[0] == "bwrap"
    assert "--ro-bind" in argv
    assert invocation.rootfs_path in argv
    assert "/workspace/monarch" in argv
    assert "--clearenv" in argv
    assert "--setenv" in argv
    assert "CUDA_VISIBLE_DEVICES" in argv
    assert "--" in argv
    assert argv[-3:] == ["python3", "-c", "print('ok')"]


def test_emit_and_validate_plan(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    plan = emit_plan(invocation)
    result = validate_plan(invocation, plan)

    assert result["status"] == "passed"
    assert plan.command_argv == ["python3", "-c", "print('ok')"]


def test_validate_plan_rejects_command_drift(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    plan = emit_plan(invocation)
    drifted = plan.__class__(**{**plan.__dict__, "command_argv": ["python3", "-c", "print('bad')"]})

    with pytest.raises(InsulaConfigError, match="command argv mismatch"):
        validate_plan(invocation, drifted)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_bwrap_plan.py -q
```

Expected: import failure for `ginkgo.insula.bwrap_plan`.

- [ ] **Step 3: Implement bwrap argv generation**

Implement `build_bwrap_argv(invocation)` in `ginkgo/insula/bwrap_plan.py`.
For this task, mirror current `enter_rootfs.sh` semantics enough for tests:

- start with `bwrap`;
- `--ro-bind <rootfs> /`;
- `--proc /proc`;
- `--tmpfs /tmp`;
- `--dev /dev`;
- `--tmpfs /home`;
- `--dir /home/monarch`;
- `--unshare-all`;
- `--share-net` when network is `share-net`;
- `--die-with-parent`;
- `--clearenv`;
- `--chdir <command.cwd>`;
- bind repo and extra binds with `--ro-bind`, `--bind`, or `--dev-bind`;
- set env values with `--setenv`;
- append `--` and command argv.

- [ ] **Step 4: Implement plan emission and validation**

`emit_plan(invocation)` should construct an `InsulaPlan` from the materialized
invocation and the generated argv. `validate_plan(invocation, plan)` should
compare rootfs path, cwd, command argv, env, mounts, and `bwrap_argv_sha256`.

- [ ] **Step 5: Populate `bwrap_argv` during materialization or via helper**

Either update `materialize_invocation` to call `build_bwrap_argv` after import
is safe, or document that callers must use `build_bwrap_argv`. Prefer avoiding
import cycles by keeping `bwrap_argv` empty until `artifacts.py` writes the
final generated argv.

- [ ] **Step 6: Run tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_schema.py python/tests/test_ginkgo_insula_materialize.py python/tests/test_ginkgo_insula_bwrap_plan.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```sh
git add ginkgo/insula/bwrap_plan.py ginkgo/insula/materialize.py python/tests/test_ginkgo_insula_bwrap_plan.py
git commit -m "Add Insula bwrap plan validation" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 5: Artifacts And Executor

**Files:**
- Create: `ginkgo/insula/artifacts.py`
- Create: `ginkgo/insula/executor.py`
- Modify: `python/tests/test_ginkgo_insula_bwrap_plan.py`

**Interfaces:**
- Consumes: `MaterializedInsulaInvocation`, `emit_plan`, `validate_plan`
- Produces: `write_invocation_artifacts`, `execute_invocation`

- [ ] **Step 1: Add failing artifact/executor tests**

Append to `python/tests/test_ginkgo_insula_bwrap_plan.py`:

```python
from ginkgo.insula.artifacts import write_invocation_artifacts
from ginkgo.insula.executor import execute_invocation


def test_write_invocation_artifacts(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    paths = write_invocation_artifacts(invocation)

    assert Path(paths["materialized"]).is_file()
    assert Path(paths["argv"]).is_file()
    assert Path(paths["plan"]).is_file()
    assert Path(paths["validation"]).is_file()


def test_execute_invocation_with_fake_runner_writes_result(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)

    def fake_run(argv, *, stdout, stderr, env):
        stdout.write(b"ok\\n")
        return 0

    result = execute_invocation(invocation, run=fake_run)

    assert result.status == "passed"
    assert result.returncode == 0
    assert Path(result.stdout_path).read_text() == "ok\\n"
    assert Path(result.stderr_path).is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_bwrap_plan.py::test_write_invocation_artifacts python/tests/test_ginkgo_insula_bwrap_plan.py::test_execute_invocation_with_fake_runner_writes_result -q
```

Expected: import failure for artifacts/executor.

- [ ] **Step 3: Implement artifact writing**

`write_invocation_artifacts(invocation)` must:

- create artifact directories;
- write materialized invocation YAML;
- write bwrap argv JSON;
- write env JSON;
- write plan YAML;
- write validation JSON;
- return a dict of artifact paths.

- [ ] **Step 4: Implement executor**

`execute_invocation(invocation, run=None)` must:

- write artifacts first;
- open stdout/stderr artifact files in binary mode;
- call `run(argv, stdout=..., stderr=..., env=...)` when supplied;
- otherwise call `subprocess.run`;
- write `InsulaExecutionResult` JSON;
- return `InsulaExecutionResult`;
- mark nonzero return codes as `failed`.

- [ ] **Step 5: Run tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_bwrap_plan.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```sh
git add ginkgo/insula/artifacts.py ginkgo/insula/executor.py python/tests/test_ginkgo_insula_bwrap_plan.py
git commit -m "Write Insula invocation artifacts" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 6: Rootfs Lifecycle And CLI

**Files:**
- Create: `ginkgo/insula/rootfs_lifecycle.py`
- Create: `ginkgo/insula/cli.py`
- Create: `python/tests/test_ginkgo_insula_compatibility.py`

**Interfaces:**
- Consumes: existing schema/materialization/executor
- Produces: `prepare_rootfs`, CLI commands `run`, `emit-plan`, `monarch-run`, `enter-rootfs-compat`

- [ ] **Step 1: Write failing CLI/lifecycle tests**

Create `python/tests/test_ginkgo_insula_compatibility.py`:

```python
from __future__ import annotations

from pathlib import Path

from ginkgo.insula.cli import build_parser
from ginkgo.insula.rootfs_lifecycle import prepare_rootfs


def test_cli_exposes_required_commands() -> None:
    parser = build_parser()
    subcommands = parser._subparsers._group_actions[0].choices

    assert "run" in subcommands
    assert "emit-plan" in subcommands
    assert "monarch-run" in subcommands
    assert "enter-rootfs-compat" in subcommands


def test_prepare_rootfs_accepts_existing_rootfs_with_contract(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    contract = rootfs / "etc" / "monarch-rootfs-contract"
    contract.parent.mkdir(parents=True)
    contract.write_text("MONARCH_ROOTFS_RECIPE_SHA256=" + "0" * 64 + "\\n")
    (rootfs / "bin").mkdir()
    (rootfs / "bin" / "bash").write_text("#!/bin/sh\\n")
    (rootfs / "bin" / "bash").chmod(0o755)

    evidence = prepare_rootfs(rootfs=rootfs, expected_recipe=None, build=False, verify=False)

    assert evidence["status"] == "ready"
    assert evidence["rootfs"] == str(rootfs)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_compatibility.py -q
```

Expected: import failure for lifecycle/cli.

- [ ] **Step 3: Implement rootfs lifecycle wrapper**

`prepare_rootfs(rootfs, expected_recipe, build, verify)` must:

- require absolute rootfs path;
- check `bin/bash`;
- read `etc/monarch-rootfs-contract` when present;
- call `scripts/rootfs/build_rootfs.sh --dest <rootfs>` only when `build=True`
  and rootfs is missing/stale;
- call `scripts/rootfs/verify_rootfs.py --rootfs <rootfs>` only when
  `verify=True`;
- return evidence dict with `status`, `rootfs`, and `recipe_sha256`.

- [ ] **Step 4: Implement CLI parser**

Create `build_parser()` with subcommands:

- `run --spec PATH --local-environment PATH --invocation-id ID`
- `emit-plan --spec PATH --local-environment PATH --invocation-id ID`
- `monarch-run [--chdir REL] -- <cmd...>`
- `enter-rootfs-compat [--chdir REL] [--repo-readonly] [--rootfs DIR]
  [--emit-plan PATH] [--bind-rw HOST:SANDBOX]... -- <cmd...>`

For this task, `run` and `emit-plan` may call existing schema/materialize APIs.
`monarch-run` and `enter-rootfs-compat` may fail loudly with
`InsulaConfigError("compatibility command not implemented")` until Task 7.

- [ ] **Step 5: Run tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_compatibility.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```sh
git add ginkgo/insula/rootfs_lifecycle.py ginkgo/insula/cli.py python/tests/test_ginkgo_insula_compatibility.py
git commit -m "Add Insula CLI and rootfs lifecycle wrapper" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 7: Compatibility Adapters For `scripts/run` And `enter_rootfs.sh`

**Files:**
- Modify: `ginkgo/insula/compatibility.py`
- Modify: `ginkgo/insula/cli.py`
- Modify: `scripts/run`
- Modify: `scripts/rootfs/enter_rootfs.sh`
- Modify: `python/tests/test_ginkgo_insula_compatibility.py`
- Modify: existing `scripts/rootfs/tests/test_run_gateway.py`
- Modify: existing `scripts/rootfs/tests/test_guarded_entrypoints.py`

**Interfaces:**
- Produces: `monarch_run_spec`, `enter_rootfs_compat_spec`

- [ ] **Step 1: Add failing compatibility tests**

Add tests that monkeypatch `ginkgo.insula.cli.run_insula_from_args` and assert:

- `scripts/run` invokes `python -m ginkgo.insula.cli monarch-run`;
- `scripts/rootfs/enter_rootfs.sh --emit-plan <path> -- python3 -c 'print(1)'`
  invokes `python -m ginkgo.insula.cli enter-rootfs-compat`;
- compatibility specs preserve checkout-relative cwd and payload argv.

- [ ] **Step 2: Run tests to verify failure**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_compatibility.py scripts/rootfs/tests/test_run_gateway.py scripts/rootfs/tests/test_guarded_entrypoints.py -q
```

Expected: failures showing scripts still call legacy implementation directly.

- [ ] **Step 3: Implement compatibility spec builders**

`monarch_run_spec(repo_root, cwd, command, env)` must produce an
`InsulaInvocationSpec` matching current `scripts/run` semantics:

- repo mounted rw;
- cwd mapped under `/workspace/monarch`;
- rootfs ref `rootfs://monarch-default`;
- cache bind under `/workspace/monarch/scripts/rootfs/cache`;
- target bind under `/workspace/monarch/target/bwrap/<recipe>`;
- environment includes current rootfs defaults from `enter_rootfs.sh`.

`enter_rootfs_compat_spec(...)` must preserve documented `enter_rootfs.sh`
flags: `--chdir`, `--repo-readonly`, `--bind-rw`, `--emit-plan`, `--rootfs`.

- [ ] **Step 4: Convert shell scripts to adapters**

Replace rootfs protocol logic in `scripts/run` and `scripts/rootfs/enter_rootfs.sh`
with argument parsing plus `exec python -m ginkgo.insula.cli ...`.

Preserve:

- exit codes;
- `--help` text;
- `MONARCH_ROOTFS` override;
- `MONARCH_ROOTFS_EMIT_PLAN` for `scripts/run`;
- legacy `--emit-plan` behavior for `enter_rootfs.sh`.

- [ ] **Step 5: Run compatibility tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_compatibility.py scripts/rootfs/tests/test_run_gateway.py scripts/rootfs/tests/test_guarded_entrypoints.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Live smoke `scripts/run`**

Run:

```sh
scripts/run python -c "print('insula-run-ok')"
```

Expected: prints `insula-run-ok`, exit 0.

- [ ] **Step 7: Live smoke legacy enter_rootfs**

Run:

```sh
tmp_plan="$(mktemp)"
scripts/rootfs/enter_rootfs.sh --emit-plan "$tmp_plan" -- python3 -c "print('insula-enter-ok')"
python - <<PY
from pathlib import Path
p = Path("$tmp_plan")
assert p.is_file(), p
print(p)
PY
```

Expected: prints `insula-enter-ok` and a plan path.

- [ ] **Step 8: Commit**

```sh
git add ginkgo/insula/compatibility.py ginkgo/insula/cli.py scripts/run scripts/rootfs/enter_rootfs.sh python/tests/test_ginkgo_insula_compatibility.py scripts/rootfs/tests/test_run_gateway.py scripts/rootfs/tests/test_guarded_entrypoints.py
git commit -m "Route rootfs entrypoints through Insula" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 8: Ginkgo SGLang Runtime Integration

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `ginkgo/local_run.py`
- Create: `python/tests/test_ginkgo_insula_runtime_integration.py`
- Modify: `python/tests/test_ginkgo_qwen3_sglang_smoke.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: `ginkgo.insula.compatibility.sglang_invocation_spec`, `execute_invocation`
- Produces: SGLang launch path through Insula artifacts

- [ ] **Step 1: Write failing integration tests**

Create `python/tests/test_ginkgo_insula_runtime_integration.py`:

```python
from __future__ import annotations

from pathlib import Path

import importlib.util
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = REPO_ROOT / "scripts" / "glm52_sglang_runtime.py"
spec = importlib.util.spec_from_file_location("glm52_sglang_runtime", RUNTIME_PATH)
assert spec is not None and spec.loader is not None
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


def test_sglang_runtime_exposes_insula_invocation_builder() -> None:
    assert hasattr(runtime, "build_insula_invocation_spec")


def test_sglang_artifact_paths_include_insula_paths(tmp_path: Path) -> None:
    # Use existing test helpers from test_glm52_sglang_runtime after import if available.
    assert "insula_materialized" in runtime.SGLANG_ARTIFACT_KEYS
    assert "insula_plan" in runtime.SGLANG_ARTIFACT_KEYS
    assert "insula_validation" in runtime.SGLANG_ARTIFACT_KEYS
    assert "insula_result" in runtime.SGLANG_ARTIFACT_KEYS
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_runtime_integration.py -q
```

Expected: missing `build_insula_invocation_spec` or artifact keys.

- [ ] **Step 3: Add SGLang-to-Insula invocation builder**

In `scripts/glm52_sglang_runtime.py`, add:

```python
def build_insula_invocation_spec(config: MaterializedSglangRuntimeConfig) -> InsulaInvocationSpec:
    ...
```

It must convert existing materialized SGLang command/env/binds into an
`InsulaInvocationSpec`.

- [ ] **Step 4: Replace raw rootfs launch with Insula execution**

In `launch_runtime`, replace `_resolved_outer_argv(config)` subprocess launch
with Insula materialization, plan validation, and execution. Preserve process
record semantics for SGLang. If direct long-running process execution needs a
new Insula streaming method, add `start_invocation(...)` to `executor.py` with a
fake-process test first.

- [ ] **Step 5: Add Insula artifacts to Ginkgo evidence**

Update `ginkgo/local_run.py` manifest creation to include Insula artifact paths
from SGLang launch summary.

- [ ] **Step 6: Run integration tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_runtime_integration.py python/tests/test_ginkgo_qwen3_sglang_smoke.py python/tests/test_glm52_sglang_runtime.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```sh
git add scripts/glm52_sglang_runtime.py ginkgo/local_run.py ginkgo/insula python/tests/test_ginkgo_insula_runtime_integration.py python/tests/test_ginkgo_qwen3_sglang_smoke.py python/tests/test_glm52_sglang_runtime.py
git commit -m "Run Ginkgo SGLang through Insula" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

### Task 9: Guardrails, Docs, And Live Verification

**Files:**
- Modify: `python/tests/test_ginkgo_project_contract.py`
- Modify: `scripts/rootfs/tests/test_entrypoint_inventory.py`
- Modify: `ginkgo/docs/operator-workflow.md`
- Modify: `ginkgo/README.md`
- Modify: `.scratch/ginkgo-insula/spec.md`

**Interfaces:**
- Consumes: all previous tasks
- Produces: guardrails and final evidence

- [ ] **Step 1: Add guardrail tests**

Add tests that scan tracked source files and fail if direct `bwrap` or
`scripts/rootfs/enter_rootfs.sh` argv construction appears outside:

- `ginkgo/insula/**`
- `scripts/rootfs/build_rootfs.sh`
- tests explicitly named as fixtures

The test must allow string mentions in docs, but reject executable construction
patterns such as `subprocess.Popen(["bwrap"` or `outer_argv = ["scripts/rootfs/enter_rootfs.sh"`.

- [ ] **Step 2: Run guardrail tests to verify they fail if bypasses remain**

Run:

```sh
scripts/run python -m pytest python/tests/test_ginkgo_project_contract.py scripts/rootfs/tests/test_entrypoint_inventory.py -q
```

Expected: fail until old bypasses are removed or whitelisted as compatibility
adapters.

- [ ] **Step 3: Update docs**

Update:

- `ginkgo/README.md` with Insula ownership.
- `ginkgo/docs/operator-workflow.md` with Insula artifact names and live run
  expectations.
- `.scratch/ginkgo-insula/spec.md` status from `ready-for-human` to
  `ready-for-agent` after implementation evidence is present.

- [ ] **Step 4: Run full focused test suite**

Run:

```sh
scripts/run python -m pytest \
  python/tests/test_ginkgo_insula_schema.py \
  python/tests/test_ginkgo_insula_materialize.py \
  python/tests/test_ginkgo_insula_bwrap_plan.py \
  python/tests/test_ginkgo_insula_compatibility.py \
  python/tests/test_ginkgo_insula_runtime_integration.py \
  python/tests/test_ginkgo_qwen3_sglang_smoke.py \
  python/tests/test_ginkgo_project_contract.py \
  python/tests/test_glm52_sglang_runtime.py \
  scripts/rootfs/tests/test_entrypoint_inventory.py \
  scripts/rootfs/tests/test_execution_contract.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  scripts/rootfs/tests/test_run_gateway.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 5: Run live `scripts/run` smoke**

Run:

```sh
scripts/run python -c "print('insula-run-ok')"
```

Expected: prints `insula-run-ok`.

- [ ] **Step 6: Run live legacy enter smoke**

Run:

```sh
tmp_plan="$(mktemp)"
scripts/rootfs/enter_rootfs.sh --emit-plan "$tmp_plan" -- python3 -c "print('insula-enter-ok')"
test -s "$tmp_plan"
```

Expected: prints `insula-enter-ok` and writes a non-empty plan.

- [ ] **Step 7: Run live Qwen3 SGLang smoke twice**

Run:

```sh
./ginkgo/scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh --port 19017
./ginkgo/scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh --port 19018
```

Expected for each run:

- evidence manifest `status=passed`;
- non-empty generated text;
- `teardown.status=teardown_passed`;
- manifest includes Insula materialized invocation, plan, validation, and result
  paths;
- serving port is closed after teardown.

- [ ] **Step 8: Commit**

```sh
git add python/tests/test_ginkgo_project_contract.py scripts/rootfs/tests/test_entrypoint_inventory.py ginkgo/docs/operator-workflow.md ginkgo/README.md .scratch/ginkgo-insula/spec.md
git commit -m "Document and guard Insula rootfs ownership" -m "Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

## Execution Notes

- Use a separate feature worktree for implementation because this migration
  touches foundational scripts.
- Preserve unrelated dirty files in the root checkout.
- Prefer one task per subagent. Task 7 and Task 8 are high-risk and should each
  receive independent review before landing.
- If any live rootfs smoke fails after Task 7, stop and diagnose before moving
  to Ginkgo SGLang integration.
- Do not weaken `scripts/run` gateway semantics to make tests pass.
- Do not skip live Qwen3 verification in the final task.

## Self-Review Checklist

- Spec coverage: Tasks cover schema, local env, materialization, plan, executor,
  lifecycle, compatibility adapters, SGLang integration, guardrails, docs, and
  live verification.
- No placeholders: Every task has concrete files, interfaces, commands, and
  expected outcomes.
- Type consistency: Data model names match `.scratch/ginkgo-insula/spec.md`.
- Scope: Dynamo and GLM live serving remain downstream and are not included in
  this Insula migration.
