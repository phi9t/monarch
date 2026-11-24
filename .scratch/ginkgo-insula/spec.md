# Ginkgo Insula Rootfs Invocation Spec

Status: ready-for-human

Created: 2026-08-18T00:00:00Z

## Purpose

Insula is the single module responsible for bwrap-rootfs behavior in this
checkout. Every local rootfs execution path must cross Insula's schema-backed
interface before it can build, verify, enter, or execute inside the rootfs.

The first implementation preserves the existing operator commands while moving
ownership of the rootfs protocol into `ginkgo/insula`. Shell entrypoints such as
`scripts/run` and `scripts/rootfs/enter_rootfs.sh` become compatibility
adapters. Ginkgo serving, including the Qwen3 SGLang bwrap run, uses the same
Insula invocation machinery as human and automation entrypoints.

## First Principle

No fallback. Fail fast, fail loud.

Insula must not fall back to host Python, host packages, ambient bwrap commands,
implicit rootfs paths, default serving ports, unvalidated mount plans, or
unrecorded execution. If an invocation cannot be described, materialized,
validated, and proven through Insula artifacts, it must fail before executing the
payload command.

## Scope

### In Scope

- Source-backed schema for all rootfs invocation data.
- Local-environment schema for concrete host roots.
- Materialization from logical refs to concrete host paths.
- Rootfs contract preparation and verification.
- Direct ownership of bwrap argv construction.
- Structured bwrap plan emission before execution.
- Plan validation against the materialized invocation.
- Execution result artifacts for every Insula-run command.
- Compatibility adapters for `scripts/run` and `scripts/rootfs/enter_rootfs.sh`.
- Ginkgo SGLang runtime launch through Insula instead of raw `outer_argv`.
- Guardrail tests that forbid new rootfs callers from bypassing Insula.
- Live verification with normal `scripts/run`, legacy `enter_rootfs.sh`, and the
  Qwen3 SGLang bwrap run.

### Out of Scope For The First Landing

- Removing `scripts/rootfs/build_rootfs.sh` or `scripts/rootfs/verify_rootfs.py`.
  Insula may call them while owning the rootfs lifecycle interface.
- Rewriting the Docker rootfs build recipe.
- Changing the rootfs contents, Python version, Rust toolchain, or CUDA
  baseline.
- Migrating non-local execution domains such as GitHub Actions, macOS, installed
  wheels, Meta-internal builds, or remote workers.
- Launching Dynamo or GLM-5.2 as part of the Insula migration. Those remain
  downstream consumers after the Qwen3 proof passes.

## Ownership Model

Insula owns the rootfs protocol. Other modules own their domain commands.

- `scripts/run` owns the human/agent development command interface, but not the
  rootfs protocol.
- `scripts/rootfs/enter_rootfs.sh` owns legacy CLI compatibility, but not bwrap
  argv semantics.
- `scripts/glm52_sglang_runtime.py` owns SGLang command, env, probes, process
  records, and teardown, but not rootfs invocation translation.
- `ginkgo.local_run` owns Local Run orchestration and evidence, but not bwrap
  translation.
- `ginkgo/insula` owns rootfs selection, projection, bwrap plan, env isolation,
  execution, and rootfs invocation artifacts.

No code outside `ginkgo/insula`, `scripts/rootfs/build_rootfs.sh`, and test
fixtures may construct a raw bwrap argv or a raw rootfs entry argv.

## Data Model

All public Insula operations consume or produce these schema types. The Python
implementation should use frozen dataclasses and explicit parser/serializer
functions. YAML is used for durable artifacts; JSON is allowed for argv/env
artifacts that are naturally arrays or maps.

### `InsulaLocalEnvironment`

Concrete host roots for one machine.

```python
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
```

Rules:

- Every host path is absolute.
- `rootfs` keys are symbolic names such as `monarch-default`.
- `cache`, `temp`, `run`, and `results` must not be inside the rootfs export.
- `repo` must resolve to the current checkout unless an explicit test fixture
  says otherwise.
- `shared_memory.sandbox_path` must be `/dev/shm` when present.
- Unknown fields fail parsing.

### `InsulaPathRef`

Logical path references used in portable specs and materialized Ginkgo configs.

Supported refs:

- `repo://...`
- `cache://...`
- `temp://...`
- `run://...`
- `results://...`
- `rootfs://<name>`

Rules:

- Portable specs must not use absolute host paths.
- Materialized invocation artifacts may contain concrete host paths only in
  resolved fields.
- Sandbox paths are absolute strings, not path refs.

### `InsulaBindSpec`

One declared host-to-sandbox projection.

```python
@dataclass(frozen=True)
class InsulaBindSpec:
    name: str
    host: str
    sandbox: str
    mode: Literal["ro", "rw", "dev"]
    create: bool
    required: bool
```

Rules:

- `host` is a logical ref before materialization and an absolute path after
  materialization.
- `sandbox` is absolute and cannot be `/`.
- `mode` is explicit.
- Writable binds must be under declared writable roots.
- `create: true` is required before Insula creates a host directory.

### `InsulaEnvironmentSpec`

Environment contract for the rootfs payload.

```python
@dataclass(frozen=True)
class InsulaEnvironmentSpec:
    clear: bool
    values: dict[str, str]
    inherit_allowlist: list[str]
```

Rules:

- `clear` must be true for governed rootfs runs.
- Every inherited variable must be named in `inherit_allowlist`.
- Host compiler, Python, linker, and package variables are never inherited
  unless a compatibility mode explicitly proves they are safe.
- Materialized env values must be concrete strings.

### `InsulaCommandSpec`

The command to execute inside the rootfs.

```python
@dataclass(frozen=True)
class InsulaCommandSpec:
    cwd: str
    argv: list[str]
```

Rules:

- `cwd` is an absolute sandbox path.
- `argv` is non-empty.
- Shell command strings are rejected.
- For serving invocations, default ports `8000`, `8080`, and `18080` are
  rejected anywhere in known host/port/url fields.

### `InsulaInvocationSpec`

Portable rootfs invocation.

```python
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
    network: Literal["share-net", "private"]
    gpu: Literal["none", "nvidia-if-present", "nvidia-required"]
    die_with_parent: bool
    unshare_all: bool
```

Rules:

- `rootfs_ref` uses `rootfs://`.
- `repo.sandbox` is `/workspace/monarch` for this checkout.
- `die_with_parent` and `unshare_all` are true for governed local rootfs runs.
- `network` must be explicit.
- `gpu` must be explicit.
- Artifact refs must resolve under declared run/results roots.

### `MaterializedInsulaInvocation`

Fully concrete invocation ready for plan emission and execution.

```python
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
```

Rules:

- No logical refs remain.
- Every host path is absolute.
- `bwrap_argv` is generated by Insula only.
- `compatibility` records the adapter that requested the invocation, such as
  `scripts-run`, `enter-rootfs`, or `ginkgo-sglang`.

### `InsulaPlan`

Structured plan emitted before execution.

```python
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
```

Rules:

- The plan must be derivable from `MaterializedInsulaInvocation`.
- Validation compares rootfs, cwd, env, command, mounts, and bwrap digest.
- Extra writable mounts fail unless explicitly allowed by compatibility mode.

### `InsulaExecutionResult`

Execution artifact.

```python
@dataclass(frozen=True)
class InsulaExecutionResult:
    schema_version: int
    invocation_id: str
    status: Literal["passed", "failed"]
    returncode: int
    started_at: str
    completed_at: str
    stdout_path: str
    stderr_path: str
    materialized_path: str
    plan_path: str
    validation_path: str
```

Rules:

- Every execution writes this artifact.
- Nonzero payload exit code is `failed`.
- Plan validation failure stops before payload execution and still writes
  failure evidence.

## Architecture

Target call graph:

```text
scripts/run
  -> python -m ginkgo.insula.cli monarch-run -- <cmd>
    -> InsulaRunner
      -> RootfsLifecycle
      -> materialize
      -> emit_plan
      -> validate_plan
      -> execute_bwrap

scripts/rootfs/enter_rootfs.sh
  -> python -m ginkgo.insula.cli enter-rootfs-compat ...
    -> InsulaRunner

ginkgo Qwen3 SGLang
  -> ginkgo.local_run
    -> scripts.glm52_sglang_runtime materializes serving command/env
      -> ginkgo.insula
        -> execute_bwrap
```

During migration, Insula may use existing shell helpers for rootfs build and
verification. It must not delegate bwrap argv ownership to them after the direct
executor task lands.

## File Layout

```text
ginkgo/insula/
  __init__.py
  schema.py
  local_environment.py
  refs.py
  rootfs_lifecycle.py
  materialize.py
  bwrap_plan.py
  executor.py
  artifacts.py
  compatibility.py
  cli.py
  verify.py

python/tests/
  test_ginkgo_insula_schema.py
  test_ginkgo_insula_materialize.py
  test_ginkgo_insula_bwrap_plan.py
  test_ginkgo_insula_compatibility.py
  test_ginkgo_insula_runtime_integration.py
```

## Verification Gates

### Gate 1: Schema

- Schema parsers reject unknown fields.
- Portable specs reject absolute host paths.
- Sandbox paths must be absolute.
- Command argv must be structured.
- Environment inheritance is allowlisted.

### Gate 2: Materialization

- Every logical ref resolves through `InsulaLocalEnvironment`.
- No unresolved refs remain in `MaterializedInsulaInvocation`.
- Writable host binds stay under declared roots.
- Creatable dirs are created only when declared.
- Materialized output is deterministic and serializable.

### Gate 3: Plan

- Insula emits a structured plan without executing payload.
- Plan validation rejects rootfs, cwd, env, command, mount, and digest drift.
- Direct bwrap argv generation matches the plan.

### Gate 4: Compatibility

- `scripts/run` works through Insula.
- `scripts/rootfs/enter_rootfs.sh --emit-plan` works through Insula.
- Existing rootfs shell behavior stays compatible for documented flags.
- Guardrail tests reject direct rootfs invocation construction outside Insula.

### Gate 5: Ginkgo Serving

- Qwen3 SGLang materialization includes Insula artifacts.
- Qwen3 SGLang launch uses Insula, not raw `outer_argv`.
- Qwen3 live run passes on a run-owned port.
- Evidence manifest links materialized invocation, plan, validation, and result.
- Teardown passes and the serving port is closed.

## Acceptance Criteria

- `ginkgo/insula` is the sole code path that constructs bwrap argv for governed
  local rootfs runs.
- `scripts/run` and `scripts/rootfs/enter_rootfs.sh` are compatibility adapters
  over Insula.
- Ginkgo serving does not assemble raw `enter_rootfs.sh` or bwrap argv.
- Insula writes materialized invocation, bwrap argv, plan, validation, env, and
  execution result artifacts.
- Plan validation catches rootfs, bind, cwd, env, command, GPU, and projection
  drift.
- Existing focused rootfs tests pass.
- Existing Ginkgo SGLang runtime tests pass.
- Live `scripts/run python -c "print('ok')"` passes.
- Live `scripts/rootfs/enter_rootfs.sh --emit-plan <path> -- python3 -c "print('ok')"`
  passes.
- Live Qwen3 SGLang bwrap run passes and tears down cleanly.

## Migration Constraints

- Preserve existing dirty user files.
- Do not change rootfs contents unless a task explicitly requires it.
- Do not change the rootfs build recipe in the first task set.
- Do not regenerate `uv.lock`.
- Do not push.
- Each task must be test-first.
- Keep compatibility adapters thin and explicit.
