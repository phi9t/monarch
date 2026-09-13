# Schema-Driven Local SGLang Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first live-serving gate: schema-backed, no-fallback, repeatable local SGLang launch/probe/teardown on custom allocated ports inside the governed Monarch bwrap rootfs.

**Architecture:** A source-backed Python schema module validates declared YAML specs, materializes concrete SGLang runtime YAML, and validates actual launch records. The rootfs entrypoint emits a resolved bwrap/mount plan, and a new launcher executes only materialized configs, records local telemetry, probes `/v1/models` and `/v1/chat/completions`, and tears down by recorded process group.

**Tech Stack:** Python 3.12, stdlib dataclasses, `yaml.safe_load`/`safe_dump`, `subprocess.Popen`, `urllib.request`, pytest, bash, bubblewrap rootfs via `scripts/rootfs/enter_rootfs.sh`.

**Spec:** `.scratch/glm52-local-serving/sglang-schema-runtime-spec.md`

## Global Constraints

- No fallback. Fail fast, fail loud.
- The declared spec and materialized config are YAML.
- The YAML files must be backed by source code; examples are not the contract.
- Portable config files must not encode absolute host paths in host-layout fields.
- Machine-local absolute host paths are allowed only in local environment config, resolved-path evidence, process evidence, and diagnostic error messages.
- Absolute sandbox paths are allowed in portable config because the sandbox layout is a launch protocol.
- `fail_fast` must be `true`.
- `allow_fallback` must be `false`.
- `port_policy.mode` must be `strict_run_owned_range`.
- `disallowed_ports` must include `8000`, `8080`, and `18080`.
- `model.id`, `model.path`, `model.served_model_name`, and `model.expected_model_ids` must be explicit.
- `model.served_model_name` must be included in `model.expected_model_ids`.
- `runtime.kind` must be `sglang_openai`.
- `sandbox.kind` must be `bwrap_rootfs`.
- `observability.debug_mode` and `observability.leave_running_on_failure` must be explicit.
- Launch commands are generated from materialized YAML only.
- `enter_rootfs.sh` must emit a resolved rootfs plan and the launcher must validate it before SGLang starts.
- SGLang CLI preflight must prove `--served-model-name` is available.
- Repeatability acceptance must run with `debug_mode=false`.
- Every post-launch failure must run teardown in a best-effort `finally` path when `leave_running_on_failure=false`.
- Live completion requires three launch/probe/teardown cycles from the same declared spec.

---

## File Structure

- Create `scripts/glm52_sglang_runtime.py`: source-backed schemas, YAML parsing, materialization, validation, rootfs-plan validation, launch/probe/teardown logic, CLI commands.
- Create `scripts/run_glm52_sglang_runtime.sh`: thin host wrapper that executes the Python launcher through `scripts/run` when safe and directly on host for host-visible teardown/status commands when needed.
- Modify `scripts/rootfs/enter_rootfs.sh`: add `--emit-plan PATH`, make it write a resolved rootfs/bwrap plan before `exec bwrap`, and preserve normal behavior when the flag is omitted.
- Create `python/tests/test_glm52_sglang_runtime.py`: unit tests for schema validation, materialization, command validation, rootfs-plan validation, probe parsing, teardown policy, and CLI behavior with fake subprocess/probe functions.
- Create `python/tests/test_rootfs_enter_plan.py`: host-side tests for `enter_rootfs.sh --emit-plan` argument parsing and plan contents without invoking real bwrap.
- Create `.scratch/glm52-local-serving/config/sglang-local.yaml`: checked-in declared spec example using logical paths and strict custom port allocation.
- Create `.scratch/glm52-local-serving/config/local-environment.example.yaml`: example local environment resolver file. It must be a copy-and-fill template and must not encode this host's absolute paths.

## Interfaces

Implement these public Python interfaces in `scripts/glm52_sglang_runtime.py`:

```python
class RuntimeConfigError(RuntimeError):
    """Raised when declared or materialized runtime config is invalid."""

class RuntimeLaunchError(RuntimeError):
    """Raised when a validated runtime cannot be launched or stopped."""

def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file and require a top-level mapping."""

def load_declared_spec(path: Path) -> DeclaredSglangLaunchSpec:
    """Parse and validate a human-authored declared launch spec."""

def load_local_environment(path: Path) -> LocalEnvironmentConfig:
    """Parse the machine-local path resolver config."""

def materialize_runtime_config(
    *,
    declared: DeclaredSglangLaunchSpec,
    local_environment: LocalEnvironmentConfig,
    run_id: str,
    port: int | None = None,
) -> MaterializedSglangRuntimeConfig:
    """Resolve a declared spec into a concrete executable runtime config."""

def validate_materialized_config(config: MaterializedSglangRuntimeConfig) -> None:
    """Verify command, port, path, model, and probe consistency."""

def write_materialized_config(config: MaterializedSglangRuntimeConfig, path: Path) -> None:
    """Validate and write materialized runtime YAML."""

def load_materialized_config(path: Path) -> MaterializedSglangRuntimeConfig:
    """Read and validate materialized runtime YAML."""

def validate_resolved_rootfs_plan(
    *,
    config: MaterializedSglangRuntimeConfig,
    plan: dict[str, Any],
) -> None:
    """Validate emitted bwrap/rootfs plan against the materialized config."""

def validate_sglang_help(help_text: str) -> None:
    """Require the installed launcher to support --served-model-name."""

def parse_models_response(
    body: bytes,
    *,
    expected_model_ids: list[str],
    served_model_name: str,
) -> dict[str, Any]:
    """Validate /v1/models JSON and served model identity."""

def should_teardown_after_failure(config: MaterializedSglangRuntimeConfig) -> bool:
    """Return whether post-launch failure should trigger best-effort teardown."""
```

The implementation may add private helpers, but later tasks rely on these names.

---

### Task 1: Source-Backed Declared Spec Schema

**Files:**
- Create: `scripts/glm52_sglang_runtime.py`
- Test: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Produces: `RuntimeConfigError`, `load_yaml_mapping`, `load_declared_spec`, `DeclaredSglangLaunchSpec`
- Consumes: none

- [ ] **Step 1: Write failing schema tests**

Add `python/tests/test_glm52_sglang_runtime.py` with the import pattern used by existing GLM tests:

```python
import importlib.util
import sys
from pathlib import Path

import pytest

HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "glm52_sglang_runtime.py"
spec = importlib.util.spec_from_file_location("glm52_sglang_runtime", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_sglang_runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_sglang_runtime
spec.loader.exec_module(glm52_sglang_runtime)

RuntimeConfigError = glm52_sglang_runtime.RuntimeConfigError
load_declared_spec = glm52_sglang_runtime.load_declared_spec


def write_spec(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


VALID_DECLARED = """\
schema_version: 1
run_group: glm52-sglang-local
fail_fast: true
allow_fallback: false
port_policy:
  mode: strict_run_owned_range
  bind_host: 127.0.0.1
  range_start: 19000
  range_end: 19100
  disallowed_ports: [8000, 8080, 18080]
model:
  id: zai-org/GLM-5.2
  path: zai-org/GLM-5.2
  served_model_name: zai-org/GLM-5.2
  expected_model_ids: [zai-org/GLM-5.2]
runtime:
  kind: sglang_openai
  cuda_visible_devices: "0,1,2,3,4,5,6,7"
  tensor_parallel_size: 8
  dtype: bfloat16
  context_length: 262144
  extra_args: []
sandbox:
  kind: bwrap_rootfs
  rootfs_ref: rootfs://monarch-default
  cwd: /workspace/monarch
  network: host_loopback_required
  gpu: required
observability:
  debug_mode: false
  leave_running_on_failure: false
  log_level: info
  telemetry:
    local_artifacts: true
    remote_export: false
local_paths:
  results_root: repo://glm52-serving-results
  scratch_root: repo://.scratch/glm52-local-serving
  cache_root: cache://glm52-local-serving
  temp_root: temp://glm52-local-serving
probes:
  startup_timeout_seconds: 900
  models_required: true
  chat_required: true
  chat_template_kwargs:
    enable_thinking: false
repeatability:
  cycles: 3
"""


def test_load_declared_spec_accepts_complete_spec(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))

    assert declared.run_group == "glm52-sglang-local"
    assert declared.port_policy.range_start == 19000
    assert declared.model.served_model_name == "zai-org/GLM-5.2"
    assert declared.observability.debug_mode is False
    assert declared.repeatability.cycles == 3


@pytest.mark.parametrize(
    ("needle", "replacement", "match"),
    [
        ("fail_fast: true", "fail_fast: false", "fail_fast must be true"),
        ("allow_fallback: false", "allow_fallback: true", "allow_fallback must be false"),
        ("  id: zai-org/GLM-5.2\\n", "", "model.id is required"),
        ("  path: zai-org/GLM-5.2\\n", "", "model.path is required"),
        ("  served_model_name: zai-org/GLM-5.2\\n", "", "model.served_model_name is required"),
        ("expected_model_ids: [zai-org/GLM-5.2]", "expected_model_ids: []", "expected_model_ids must include served_model_name"),
        ("mode: strict_run_owned_range", "mode: best_effort", "port_policy.mode must be strict_run_owned_range"),
        ("disallowed_ports: [8000, 8080, 18080]", "disallowed_ports: [8080]", "disallowed_ports must include"),
        ("results_root: repo://glm52-serving-results", "results_root: /tmp/glm52", "must use logical path refs"),
    ],
)
def test_load_declared_spec_rejects_invalid_policy(
    tmp_path: Path,
    needle: str,
    replacement: str,
    match: str,
) -> None:
    invalid = VALID_DECLARED.replace(needle, replacement)

    with pytest.raises(RuntimeConfigError, match=match):
        load_declared_spec(write_spec(tmp_path / "declared.yaml", invalid))


def test_load_declared_spec_rejects_unknown_fields(tmp_path: Path) -> None:
    invalid = VALID_DECLARED + "surprise: true\\n"

    with pytest.raises(RuntimeConfigError, match="unknown field"):
        load_declared_spec(write_spec(tmp_path / "declared.yaml", invalid))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: fail because `scripts/glm52_sglang_runtime.py` does not exist.

- [ ] **Step 3: Implement minimal schema loader**

Create `scripts/glm52_sglang_runtime.py`:

```python
#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class RuntimeConfigError(RuntimeError):
    pass


class RuntimeLaunchError(RuntimeError):
    pass


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"{path} must be a mapping")
    return value


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise RuntimeConfigError(f"unknown field at {path}: {unknown[0]}")


def _required_str(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeConfigError(f"{path}.{key} is required")
    return value


def _required_int(mapping: dict[str, Any], key: str, path: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise RuntimeConfigError(f"{path}.{key} is required")
    return value


def _required_bool(mapping: dict[str, Any], key: str, path: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise RuntimeConfigError(f"{path}.{key} is required")
    return value


def _string_list(mapping: dict[str, Any], key: str, path: str) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RuntimeConfigError(f"{path}.{key} must be a non-empty string list")
    return list(value)


def _int_list(mapping: dict[str, Any], key: str, path: str) -> list[int]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise RuntimeConfigError(f"{path}.{key} must be an integer list")
    return list(value)


def _logical_ref(value: str, path: str) -> str:
    if value.startswith("/"):
        raise RuntimeConfigError(f"{path} must use logical path refs")
    if not value.startswith(("repo://", "run://", "cache://", "temp://", "rootfs://")):
        raise RuntimeConfigError(f"{path} must use logical path refs")
    return value


@dataclass(frozen=True)
class PortPolicy:
    mode: str
    bind_host: str
    range_start: int
    range_end: int
    disallowed_ports: list[int]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    path: str
    served_model_name: str
    expected_model_ids: list[str]


@dataclass(frozen=True)
class SglangRuntimeSpec:
    kind: str
    cuda_visible_devices: str
    tensor_parallel_size: int
    dtype: str
    context_length: int
    extra_args: list[str]


@dataclass(frozen=True)
class SandboxSpec:
    kind: str
    rootfs_ref: str
    cwd: str
    network: str
    gpu: str


@dataclass(frozen=True)
class ObservabilitySpec:
    debug_mode: bool
    leave_running_on_failure: bool
    log_level: str
    telemetry_local_artifacts: bool
    telemetry_remote_export: bool


@dataclass(frozen=True)
class LocalPathsSpec:
    results_root: str
    scratch_root: str
    cache_root: str
    temp_root: str


@dataclass(frozen=True)
class ProbeSpec:
    startup_timeout_seconds: int
    models_required: bool
    chat_required: bool
    chat_template_kwargs: dict[str, Any]


@dataclass(frozen=True)
class RepeatabilitySpec:
    cycles: int


@dataclass(frozen=True)
class DeclaredSglangLaunchSpec:
    schema_version: int
    run_group: str
    fail_fast: bool
    allow_fallback: bool
    port_policy: PortPolicy
    model: ModelSpec
    runtime: SglangRuntimeSpec
    sandbox: SandboxSpec
    observability: ObservabilitySpec
    local_paths: LocalPathsSpec
    probes: ProbeSpec
    repeatability: RepeatabilitySpec


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = yaml.safe_load(handle)
    return _require_mapping(data, str(path))


def _parse_port_policy(data: Any) -> PortPolicy:
    mapping = _require_mapping(data, "port_policy")
    _reject_unknown(mapping, {"mode", "bind_host", "range_start", "range_end", "disallowed_ports"}, "port_policy")
    mode = _required_str(mapping, "mode", "port_policy")
    if mode != "strict_run_owned_range":
        raise RuntimeConfigError("port_policy.mode must be strict_run_owned_range")
    disallowed = _int_list(mapping, "disallowed_ports", "port_policy")
    required = {8000, 8080, 18080}
    if not required.issubset(set(disallowed)):
        raise RuntimeConfigError("disallowed_ports must include 8000, 8080, and 18080")
    range_start = _required_int(mapping, "range_start", "port_policy")
    range_end = _required_int(mapping, "range_end", "port_policy")
    if range_start <= 0 or range_end < range_start:
        raise RuntimeConfigError("port_policy range must be valid")
    if all(port in disallowed for port in range(range_start, range_end + 1)):
        raise RuntimeConfigError("port range contains only disallowed ports")
    return PortPolicy(
        mode=mode,
        bind_host=_required_str(mapping, "bind_host", "port_policy"),
        range_start=range_start,
        range_end=range_end,
        disallowed_ports=disallowed,
    )


def _parse_model(data: Any) -> ModelSpec:
    mapping = _require_mapping(data, "model")
    _reject_unknown(mapping, {"id", "path", "served_model_name", "expected_model_ids"}, "model")
    model = ModelSpec(
        id=_required_str(mapping, "id", "model"),
        path=_required_str(mapping, "path", "model"),
        served_model_name=_required_str(mapping, "served_model_name", "model"),
        expected_model_ids=_string_list(mapping, "expected_model_ids", "model"),
    )
    if model.served_model_name not in model.expected_model_ids:
        raise RuntimeConfigError("expected_model_ids must include served_model_name")
    return model


def _parse_runtime(data: Any) -> SglangRuntimeSpec:
    mapping = _require_mapping(data, "runtime")
    _reject_unknown(
        mapping,
        {"kind", "cuda_visible_devices", "tensor_parallel_size", "dtype", "context_length", "extra_args"},
        "runtime",
    )
    kind = _required_str(mapping, "kind", "runtime")
    if kind != "sglang_openai":
        raise RuntimeConfigError("runtime.kind must be sglang_openai")
    extra_args = mapping.get("extra_args")
    if not isinstance(extra_args, list) or not all(isinstance(arg, str) for arg in extra_args):
        raise RuntimeConfigError("runtime.extra_args must be a string list")
    return SglangRuntimeSpec(
        kind=kind,
        cuda_visible_devices=_required_str(mapping, "cuda_visible_devices", "runtime"),
        tensor_parallel_size=_required_int(mapping, "tensor_parallel_size", "runtime"),
        dtype=_required_str(mapping, "dtype", "runtime"),
        context_length=_required_int(mapping, "context_length", "runtime"),
        extra_args=list(extra_args),
    )


def _parse_sandbox(data: Any) -> SandboxSpec:
    mapping = _require_mapping(data, "sandbox")
    _reject_unknown(mapping, {"kind", "rootfs_ref", "cwd", "network", "gpu"}, "sandbox")
    kind = _required_str(mapping, "kind", "sandbox")
    if kind != "bwrap_rootfs":
        raise RuntimeConfigError("sandbox.kind must be bwrap_rootfs")
    rootfs_ref = _required_str(mapping, "rootfs_ref", "sandbox")
    if not rootfs_ref.startswith("rootfs://"):
        raise RuntimeConfigError("sandbox.rootfs_ref must use rootfs://")
    cwd = _required_str(mapping, "cwd", "sandbox")
    if not cwd.startswith("/"):
        raise RuntimeConfigError("sandbox.cwd must be an absolute sandbox path")
    return SandboxSpec(
        kind=kind,
        rootfs_ref=rootfs_ref,
        cwd=cwd,
        network=_required_str(mapping, "network", "sandbox"),
        gpu=_required_str(mapping, "gpu", "sandbox"),
    )


def _parse_observability(data: Any) -> ObservabilitySpec:
    mapping = _require_mapping(data, "observability")
    _reject_unknown(mapping, {"debug_mode", "leave_running_on_failure", "log_level", "telemetry"}, "observability")
    telemetry = _require_mapping(mapping.get("telemetry"), "observability.telemetry")
    _reject_unknown(telemetry, {"local_artifacts", "remote_export"}, "observability.telemetry")
    debug_mode = _required_bool(mapping, "debug_mode", "observability")
    leave_running = _required_bool(mapping, "leave_running_on_failure", "observability")
    if leave_running and not debug_mode:
        raise RuntimeConfigError("leave_running_on_failure requires debug_mode")
    return ObservabilitySpec(
        debug_mode=debug_mode,
        leave_running_on_failure=leave_running,
        log_level=_required_str(mapping, "log_level", "observability"),
        telemetry_local_artifacts=_required_bool(telemetry, "local_artifacts", "observability.telemetry"),
        telemetry_remote_export=_required_bool(telemetry, "remote_export", "observability.telemetry"),
    )


def _parse_local_paths(data: Any) -> LocalPathsSpec:
    mapping = _require_mapping(data, "local_paths")
    _reject_unknown(mapping, {"results_root", "scratch_root", "cache_root", "temp_root"}, "local_paths")
    return LocalPathsSpec(
        results_root=_logical_ref(_required_str(mapping, "results_root", "local_paths"), "local_paths.results_root"),
        scratch_root=_logical_ref(_required_str(mapping, "scratch_root", "local_paths"), "local_paths.scratch_root"),
        cache_root=_logical_ref(_required_str(mapping, "cache_root", "local_paths"), "local_paths.cache_root"),
        temp_root=_logical_ref(_required_str(mapping, "temp_root", "local_paths"), "local_paths.temp_root"),
    )


def _parse_probes(data: Any) -> ProbeSpec:
    mapping = _require_mapping(data, "probes")
    _reject_unknown(mapping, {"startup_timeout_seconds", "models_required", "chat_required", "chat_template_kwargs"}, "probes")
    chat_template_kwargs = _require_mapping(mapping.get("chat_template_kwargs"), "probes.chat_template_kwargs")
    if chat_template_kwargs.get("enable_thinking") is not False:
        raise RuntimeConfigError("probes.chat_template_kwargs.enable_thinking must be false")
    return ProbeSpec(
        startup_timeout_seconds=_required_int(mapping, "startup_timeout_seconds", "probes"),
        models_required=_required_bool(mapping, "models_required", "probes"),
        chat_required=_required_bool(mapping, "chat_required", "probes"),
        chat_template_kwargs=dict(chat_template_kwargs),
    )


def _parse_repeatability(data: Any) -> RepeatabilitySpec:
    mapping = _require_mapping(data, "repeatability")
    _reject_unknown(mapping, {"cycles"}, "repeatability")
    cycles = _required_int(mapping, "cycles", "repeatability")
    if cycles < 1:
        raise RuntimeConfigError("repeatability.cycles must be positive")
    return RepeatabilitySpec(cycles=cycles)


def load_declared_spec(path: Path) -> DeclaredSglangLaunchSpec:
    mapping = load_yaml_mapping(path)
    _reject_unknown(
        mapping,
        {
            "schema_version",
            "run_group",
            "fail_fast",
            "allow_fallback",
            "port_policy",
            "model",
            "runtime",
            "sandbox",
            "observability",
            "local_paths",
            "probes",
            "repeatability",
        },
        "declared_spec",
    )
    fail_fast = _required_bool(mapping, "fail_fast", "declared_spec")
    if not fail_fast:
        raise RuntimeConfigError("fail_fast must be true")
    allow_fallback = _required_bool(mapping, "allow_fallback", "declared_spec")
    if allow_fallback:
        raise RuntimeConfigError("allow_fallback must be false")
    return DeclaredSglangLaunchSpec(
        schema_version=_required_int(mapping, "schema_version", "declared_spec"),
        run_group=_required_str(mapping, "run_group", "declared_spec"),
        fail_fast=fail_fast,
        allow_fallback=allow_fallback,
        port_policy=_parse_port_policy(mapping.get("port_policy")),
        model=_parse_model(mapping.get("model")),
        runtime=_parse_runtime(mapping.get("runtime")),
        sandbox=_parse_sandbox(mapping.get("sandbox")),
        observability=_parse_observability(mapping.get("observability")),
        local_paths=_parse_local_paths(mapping.get("local_paths")),
        probes=_parse_probes(mapping.get("probes")),
        repeatability=_parse_repeatability(mapping.get("repeatability")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: all Task 1 tests pass.

---

### Task 2: Local Environment Resolution and Materialization

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: `DeclaredSglangLaunchSpec`, `RuntimeConfigError`
- Produces: `LocalEnvironmentConfig`, `MaterializedSglangRuntimeConfig`, `load_local_environment`, `materialize_runtime_config`, `write_materialized_config`, `load_materialized_config`, `validate_materialized_config`

- [ ] **Step 1: Write failing materialization tests**

Append to `python/tests/test_glm52_sglang_runtime.py`:

```python
load_local_environment = glm52_sglang_runtime.load_local_environment
materialize_runtime_config = glm52_sglang_runtime.materialize_runtime_config
validate_materialized_config = glm52_sglang_runtime.validate_materialized_config
write_materialized_config = glm52_sglang_runtime.write_materialized_config
load_materialized_config = glm52_sglang_runtime.load_materialized_config


VALID_LOCAL_ENV = """\
schema_version: 1
roots:
  repo: /repo/monarch
  cache: /repo/monarch/.scratch/glm52-local-serving/cache
  temp: /repo/monarch/.scratch/glm52-local-serving/tmp
rootfs:
  monarch-default: /repo/monarch/scripts/rootfs/rootfs
"""


def test_materialize_runtime_config_writes_custom_port_everywhere(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )

    assert config.service["port"] == 19017
    assert config.service["base_url"] == "http://127.0.0.1:19017/v1"
    assert config.probes["models_url"] == "http://127.0.0.1:19017/v1/models"
    assert config.probes["chat_url"] == "http://127.0.0.1:19017/v1/chat/completions"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--port") + 1] == "19017"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--served-model-name") + 1] == "zai-org/GLM-5.2"
    assert "8000" not in " ".join(config.launch["outer_argv"])
    assert config.host_layout["run_dir"].startswith("repo://glm52-serving-results/glm52-sglang-local-001")


def test_materialized_config_rejects_port_command_drift(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    inner = list(config.launch["inner_argv"])
    inner[inner.index("--port") + 1] = "19018"
    drifted = config.replace_launch_inner(inner)

    with pytest.raises(RuntimeConfigError, match="service.port must match"):
        validate_materialized_config(drifted)


def test_materialized_config_rejects_outer_inner_drift(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    outer = list(config.launch["outer_argv"])
    outer[-1] = "float16"
    drifted = config.replace_launch_outer(outer)

    with pytest.raises(RuntimeConfigError, match="outer_argv SGLang tail must equal inner_argv"):
        validate_materialized_config(drifted)


def test_write_and_load_materialized_config_round_trip(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    path = tmp_path / "materialized.yaml"

    write_materialized_config(config, path)
    loaded = load_materialized_config(path)

    assert loaded == config
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: fail because materialization functions do not exist.

- [ ] **Step 3: Implement materialization and validation**

Append focused dataclasses and helpers to `scripts/glm52_sglang_runtime.py`:

```python
@dataclass(frozen=True)
class LocalEnvironmentConfig:
    repo: str
    cache: str
    temp: str
    rootfs: dict[str, str]


@dataclass(frozen=True)
class MaterializedSglangRuntimeConfig:
    schema_version: int
    run_id: str
    run_group: str
    fail_fast: bool
    allow_fallback: bool
    service: dict[str, Any]
    model: dict[str, Any]
    runtime: dict[str, Any]
    observability: dict[str, Any]
    host_layout: dict[str, Any]
    sandbox: dict[str, Any]
    launch: dict[str, Any]
    probes: dict[str, Any]
    artifacts: dict[str, Any]

    def replace_launch_inner(self, inner_argv: list[str]) -> "MaterializedSglangRuntimeConfig":
        launch = dict(self.launch)
        launch["inner_argv"] = inner_argv
        return MaterializedSglangRuntimeConfig(
            self.schema_version,
            self.run_id,
            self.run_group,
            self.fail_fast,
            self.allow_fallback,
            self.service,
            self.model,
            self.runtime,
            self.observability,
            self.host_layout,
            self.sandbox,
            launch,
            self.probes,
            self.artifacts,
        )

    def replace_launch_outer(self, outer_argv: list[str]) -> "MaterializedSglangRuntimeConfig":
        launch = dict(self.launch)
        launch["outer_argv"] = outer_argv
        return MaterializedSglangRuntimeConfig(
            self.schema_version,
            self.run_id,
            self.run_group,
            self.fail_fast,
            self.allow_fallback,
            self.service,
            self.model,
            self.runtime,
            self.observability,
            self.host_layout,
            self.sandbox,
            launch,
            self.probes,
            self.artifacts,
        )


def load_local_environment(path: Path) -> LocalEnvironmentConfig:
    mapping = load_yaml_mapping(path)
    _reject_unknown(mapping, {"schema_version", "roots", "rootfs"}, "local_environment")
    roots = _require_mapping(mapping.get("roots"), "local_environment.roots")
    _reject_unknown(roots, {"repo", "cache", "temp"}, "local_environment.roots")
    rootfs = _require_mapping(mapping.get("rootfs"), "local_environment.rootfs")
    return LocalEnvironmentConfig(
        repo=_required_str(roots, "repo", "local_environment.roots"),
        cache=_required_str(roots, "cache", "local_environment.roots"),
        temp=_required_str(roots, "temp", "local_environment.roots"),
        rootfs={str(key): str(value) for key, value in rootfs.items()},
    )


def _argv_value(argv: list[str], flag: str) -> str:
    if flag not in argv:
        raise RuntimeConfigError(f"missing {flag}")
    index = argv.index(flag)
    try:
        return argv[index + 1]
    except IndexError as error:
        raise RuntimeConfigError(f"missing value for {flag}") from error


def _contains_disallowed_port(value: Any, disallowed: set[int]) -> bool:
    if isinstance(value, str):
        return any(str(port) in value for port in disallowed)
    if isinstance(value, list):
        return any(_contains_disallowed_port(item, disallowed) for item in value)
    if isinstance(value, dict):
        return any(_contains_disallowed_port(item, disallowed) for item in value.values())
    return False


def materialize_runtime_config(
    *,
    declared: DeclaredSglangLaunchSpec,
    local_environment: LocalEnvironmentConfig,
    run_id: str,
    port: int | None = None,
) -> MaterializedSglangRuntimeConfig:
    selected_port = port if port is not None else declared.port_policy.range_start
    if selected_port in declared.port_policy.disallowed_ports:
        raise RuntimeConfigError(f"selected port is disallowed: {selected_port}")
    if selected_port < declared.port_policy.range_start or selected_port > declared.port_policy.range_end:
        raise RuntimeConfigError(f"selected port outside declared range: {selected_port}")
    base_url = f"http://{declared.port_policy.bind_host}:{selected_port}/v1"
    inner_argv = [
        "python",
        "-m",
        "sglang.launch_server",
        "--model-path",
        declared.model.path,
        "--served-model-name",
        declared.model.served_model_name,
        "--host",
        declared.port_policy.bind_host,
        "--port",
        str(selected_port),
        "--tp",
        str(declared.runtime.tensor_parallel_size),
        "--dtype",
        declared.runtime.dtype,
        *declared.runtime.extra_args,
    ]
    outer_argv = [
        "scripts/rootfs/enter_rootfs.sh",
        "--emit-plan",
        "run://sandbox/resolved-bwrap-plan.yaml",
        "--",
        *inner_argv,
    ]
    config = MaterializedSglangRuntimeConfig(
        schema_version=1,
        run_id=run_id,
        run_group=declared.run_group,
        fail_fast=True,
        allow_fallback=False,
        service={
            "kind": "sglang_openai",
            "bind_host": declared.port_policy.bind_host,
            "port": selected_port,
            "base_url": base_url,
            "expected_model_ids": declared.model.expected_model_ids,
        },
        model={
            "id": declared.model.id,
            "path": declared.model.path,
            "served_model_name": declared.model.served_model_name,
            "expected_model_ids": declared.model.expected_model_ids,
        },
        runtime={
            "kind": declared.runtime.kind,
            "cuda_visible_devices": declared.runtime.cuda_visible_devices,
            "tensor_parallel_size": declared.runtime.tensor_parallel_size,
            "dtype": declared.runtime.dtype,
            "context_length": declared.runtime.context_length,
            "extra_args": declared.runtime.extra_args,
        },
        observability={
            "debug_mode": declared.observability.debug_mode,
            "leave_running_on_failure": declared.observability.leave_running_on_failure,
            "log_level": declared.observability.log_level,
            "telemetry": {
                "local_artifacts": declared.observability.telemetry_local_artifacts,
                "remote_export": declared.observability.telemetry_remote_export,
            },
        },
        host_layout={
            "results_root": declared.local_paths.results_root,
            "run_dir": f"{declared.local_paths.results_root}/{run_id}",
            "logs_dir": "run://logs",
            "tmp_dir": f"temp://{run_id}",
            "cache_dir": "cache://glm52-sglang-local",
            "materialized_config": "run://materialized-sglang-runtime.yaml",
        },
        sandbox={
            "kind": declared.sandbox.kind,
            "rootfs_ref": declared.sandbox.rootfs_ref,
            "cwd": declared.sandbox.cwd,
            "network": declared.sandbox.network,
            "gpu": declared.sandbox.gpu,
            "env_allowlist": [],
            "env": {
                "CUDA_VISIBLE_DEVICES": declared.runtime.cuda_visible_devices,
                "HF_HOME": "/tmp/glm52/hf-home",
            },
            "mounts": [
                {"host_path_ref": "repo://", "sandbox_path": "/workspace/monarch", "mode": "ro"},
                {"host_path_ref": "run://", "sandbox_path": "/run/glm52", "mode": "rw"},
                {"host_path_ref": f"temp://{run_id}", "sandbox_path": "/tmp/glm52", "mode": "rw"},
                {"host_path_ref": "cache://glm52-sglang-local", "sandbox_path": "/cache/glm52", "mode": "rw"},
            ],
        },
        launch={
            "outer_argv": outer_argv,
            "inner_argv": inner_argv,
            "env": {
                "CUDA_VISIBLE_DEVICES": declared.runtime.cuda_visible_devices,
                "HF_HOME": "/tmp/glm52/hf-home",
            },
        },
        probes={
            "models_url": f"{base_url}/models",
            "chat_url": f"{base_url}/chat/completions",
            "chat_payload": {
                "model": declared.model.served_model_name,
                "messages": [{"role": "user", "content": "Reply with GLM52_HEALTH_OK"}],
                "max_tokens": 64,
                "chat_template_kwargs": declared.probes.chat_template_kwargs,
            },
        },
        artifacts={
            "declared_spec_copy": "run://declared-spec.yaml",
            "materialized_config": "run://materialized-sglang-runtime.yaml",
            "resolved_local_paths": "run://resolved-local-paths.yaml",
            "process_record": "run://process.yaml",
            "launch_summary": "run://launch-summary.json",
            "teardown_summary": "run://teardown-summary.json",
            "resolved_rootfs_plan": "run://sandbox/resolved-bwrap-plan.yaml",
            "models_probe": "run://probes/models.json",
            "chat_probe": "run://probes/chat-completions.json",
            "stdout_log": "run://logs/stdout.log",
            "stderr_log": "run://logs/stderr.log",
            "telemetry_log": "run://logs/telemetry.jsonl",
            "sglang_cli_help": "run://sandbox/sglang-launch-server-help.txt",
        },
    )
    validate_materialized_config(config)
    return config


def validate_materialized_config(config: MaterializedSglangRuntimeConfig) -> None:
    port = int(config.service["port"])
    inner = list(config.launch["inner_argv"])
    outer = list(config.launch["outer_argv"])
    if _argv_value(inner, "--port") != str(port):
        raise RuntimeConfigError("service.port must match launch.inner_argv --port")
    if _argv_value(inner, "--host") != config.service["bind_host"]:
        raise RuntimeConfigError("service.bind_host must match launch.inner_argv --host")
    if _argv_value(inner, "--model-path") != config.model["path"]:
        raise RuntimeConfigError("model.path must match launch.inner_argv --model-path")
    if _argv_value(inner, "--served-model-name") != config.model["served_model_name"]:
        raise RuntimeConfigError("model.served_model_name must match launch.inner_argv --served-model-name")
    if _argv_value(inner, "--tp") != str(config.runtime["tensor_parallel_size"]):
        raise RuntimeConfigError("runtime.tensor_parallel_size must match launch.inner_argv --tp")
    if _argv_value(inner, "--dtype") != config.runtime["dtype"]:
        raise RuntimeConfigError("runtime.dtype must match launch.inner_argv --dtype")
    marker = outer.index("--")
    if outer[marker + 1 :] != inner:
        raise RuntimeConfigError("outer_argv SGLang tail must equal inner_argv")
    base_url = config.service["base_url"].rstrip("/")
    if config.probes["models_url"] != f"{base_url}/models":
        raise RuntimeConfigError("probe URLs must derive from service.base_url")
    if config.probes["chat_url"] != f"{base_url}/chat/completions":
        raise RuntimeConfigError("probe URLs must derive from service.base_url")
    if config.launch["env"].get("CUDA_VISIBLE_DEVICES") != config.sandbox["env"].get("CUDA_VISIBLE_DEVICES"):
        raise RuntimeConfigError("CUDA_VISIBLE_DEVICES in launch env must equal sandbox env")
    if _contains_disallowed_port(config.launch, {8000, 8080, 18080}):
        raise RuntimeConfigError("disallowed fallback port appears in launch")
    if _contains_disallowed_port(config.probes, {8000, 8080, 18080}):
        raise RuntimeConfigError("disallowed fallback port appears in probes")


def _config_to_mapping(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "run_id": config.run_id,
        "run_group": config.run_group,
        "fail_fast": config.fail_fast,
        "allow_fallback": config.allow_fallback,
        "service": config.service,
        "model": config.model,
        "runtime": config.runtime,
        "observability": config.observability,
        "host_layout": config.host_layout,
        "sandbox": config.sandbox,
        "launch": config.launch,
        "probes": config.probes,
        "artifacts": config.artifacts,
    }


def write_materialized_config(config: MaterializedSglangRuntimeConfig, path: Path) -> None:
    validate_materialized_config(config)
    path.write_text(yaml.safe_dump(_config_to_mapping(config), sort_keys=False))


def load_materialized_config(path: Path) -> MaterializedSglangRuntimeConfig:
    mapping = load_yaml_mapping(path)
    config = MaterializedSglangRuntimeConfig(
        schema_version=_required_int(mapping, "schema_version", "materialized"),
        run_id=_required_str(mapping, "run_id", "materialized"),
        run_group=_required_str(mapping, "run_group", "materialized"),
        fail_fast=_required_bool(mapping, "fail_fast", "materialized"),
        allow_fallback=_required_bool(mapping, "allow_fallback", "materialized"),
        service=_require_mapping(mapping.get("service"), "materialized.service"),
        model=_require_mapping(mapping.get("model"), "materialized.model"),
        runtime=_require_mapping(mapping.get("runtime"), "materialized.runtime"),
        observability=_require_mapping(mapping.get("observability"), "materialized.observability"),
        host_layout=_require_mapping(mapping.get("host_layout"), "materialized.host_layout"),
        sandbox=_require_mapping(mapping.get("sandbox"), "materialized.sandbox"),
        launch=_require_mapping(mapping.get("launch"), "materialized.launch"),
        probes=_require_mapping(mapping.get("probes"), "materialized.probes"),
        artifacts=_require_mapping(mapping.get("artifacts"), "materialized.artifacts"),
    )
    validate_materialized_config(config)
    return config
```

- [ ] **Step 4: Run test to verify it passes**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: all Task 1 and Task 2 tests pass.

---

### Task 3: Rootfs Plan Emission

**Files:**
- Modify: `scripts/rootfs/enter_rootfs.sh`
- Create: `python/tests/test_rootfs_enter_plan.py`

**Interfaces:**
- Consumes: materialized requirement that `enter_rootfs.sh --emit-plan PATH -- <cmd>` writes a plan before launch
- Produces: resolved rootfs plan YAML with `outer_argv`, `inner_argv`, `rootfs`, `cwd`, `mounts`, `env`, `env_allowlist`, `network`, `gpu`, `repo_projection_mode`

- [ ] **Step 1: Write failing host-side plan test**

Create `python/tests/test_rootfs_enter_plan.py`:

```python
import json
import os
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ENTER_ROOTFS = REPO_ROOT / "scripts" / "rootfs" / "enter_rootfs.sh"


def test_enter_rootfs_emit_plan_writes_plan_without_bwrap(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-m",
            "sglang.launch_server",
            "--host",
            "127.0.0.1",
            "--port",
            "19017",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["schema_version"] == 1
    assert plan["rootfs"].endswith("scripts/rootfs/rootfs")
    assert plan["cwd"] == "/workspace/monarch"
    assert plan["inner_argv"][:3] == ["python", "-m", "sglang.launch_server"]
    assert plan["repo_projection_mode"] in {"rw", "ro"}
    assert any(mount["sandbox_path"] == "/workspace/monarch" for mount in plan["mounts"])
    assert plan["network"] == "share-net"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest python/tests/test_rootfs_enter_plan.py -q`

Expected: fail because `--emit-plan` is unknown.

- [ ] **Step 3: Add `--emit-plan` support**

Modify `scripts/rootfs/enter_rootfs.sh`:

- Add `emit_plan=""` near `checkout_rel`.
- Parse `--emit-plan PATH` and `--emit-plan=PATH`.
- Update help text with `--emit-plan PATH`.
- After `bwrap_args` are fully assembled, before the final `exec bwrap`, call a shell function that writes YAML.
- If `MONARCH_ROOTFS_EMIT_PLAN_ONLY=1`, write the plan and `exit 0`.
- Otherwise, write the plan and continue to `exec bwrap`.

Use a shell function with explicit YAML lines:

```bash
write_emit_plan() {
  local plan_path="$1"
  local command_json
  mkdir -p "$(dirname -- "$plan_path")"
  python3 - "$plan_path" "$ROOTFS" "$REPO_MNT${checkout_rel:+/$checkout_rel}" "$REPO_ROOT" "$@" <<'PY'
import json
import sys
from pathlib import Path

import yaml

plan_path = Path(sys.argv[1])
rootfs = sys.argv[2]
cwd = sys.argv[3]
repo_root = sys.argv[4]
inner_argv = sys.argv[5:]
plan = {
    "schema_version": 1,
    "rootfs": rootfs,
    "cwd": cwd,
    "inner_argv": inner_argv,
    "repo_projection_mode": "rw",
    "network": "share-net",
    "gpu": "dev-bind-nvidia-when-present",
    "env_allowlist": [],
    "env": {key: value for key, value in sorted(__import__("os").environ.items()) if key in {"CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "MONARCH_IN_ROOTFS"}},
    "mounts": [
        {"host_path": rootfs, "sandbox_path": "/", "mode": "ro"},
        {"host_path": repo_root, "sandbox_path": "/workspace/monarch", "mode": "rw"},
    ],
}
plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))
PY
}
```

Then call:

```bash
if [[ -n "$emit_plan" ]]; then
  write_emit_plan "$emit_plan" "$@"
  if [[ "${MONARCH_ROOTFS_EMIT_PLAN_ONLY:-}" == "1" ]]; then
    exit 0
  fi
fi
```

This first pass records the current repo projection mode as `rw`; later launcher validation will fail when a GLM SGLang config requires `ro`, forcing Task 4 to decide whether to use a GLM-specific bwrap path or extend rootfs entry to support read-only repo projection.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest python/tests/test_rootfs_enter_plan.py -q`

Expected: pass.

---

### Task 4: Rootfs Plan Validation

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`
- Modify: `scripts/rootfs/enter_rootfs.sh`

**Interfaces:**
- Consumes: `MaterializedSglangRuntimeConfig`, resolved rootfs plan dict
- Produces: `validate_resolved_rootfs_plan(config, plan)`

- [ ] **Step 1: Write failing rootfs-plan validation tests**

Append to `python/tests/test_glm52_sglang_runtime.py`:

```python
validate_resolved_rootfs_plan = glm52_sglang_runtime.validate_resolved_rootfs_plan


def materialized_for_tests(tmp_path: Path):
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    return materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )


def valid_rootfs_plan(config) -> dict[str, object]:
    return {
        "schema_version": 1,
        "rootfs": "/repo/monarch/scripts/rootfs/rootfs",
        "cwd": "/workspace/monarch",
        "inner_argv": config.launch["inner_argv"],
        "repo_projection_mode": "ro",
        "network": "share-net",
        "gpu": "dev-bind-nvidia-when-present",
        "env_allowlist": [],
        "env": config.launch["env"],
        "mounts": [
            {"host_path_ref": "repo://", "sandbox_path": "/workspace/monarch", "mode": "ro"},
            {"host_path_ref": "run://", "sandbox_path": "/run/glm52", "mode": "rw"},
            {"host_path_ref": "temp://glm52-sglang-local-001", "sandbox_path": "/tmp/glm52", "mode": "rw"},
            {"host_path_ref": "cache://glm52-sglang-local", "sandbox_path": "/cache/glm52", "mode": "rw"},
        ],
    }


def test_validate_resolved_rootfs_plan_accepts_matching_plan(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)

    validate_resolved_rootfs_plan(config=config, plan=valid_rootfs_plan(config))


def test_validate_resolved_rootfs_plan_rejects_writable_repo_mount(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["repo_projection_mode"] = "rw"

    with pytest.raises(RuntimeConfigError, match="repo projection must be ro"):
        validate_resolved_rootfs_plan(config=config, plan=plan)


def test_validate_resolved_rootfs_plan_rejects_inner_argv_drift(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["inner_argv"] = ["python", "-m", "sglang.launch_server"]

    with pytest.raises(RuntimeConfigError, match="inner_argv must match"):
        validate_resolved_rootfs_plan(config=config, plan=plan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: fail because `validate_resolved_rootfs_plan` does not exist or does not enforce repo read-only.

- [ ] **Step 3: Implement rootfs plan validation**

Append to `scripts/glm52_sglang_runtime.py`:

```python
def validate_resolved_rootfs_plan(
    *,
    config: MaterializedSglangRuntimeConfig,
    plan: dict[str, Any],
) -> None:
    if plan.get("inner_argv") != config.launch["inner_argv"]:
        raise RuntimeConfigError("resolved rootfs plan inner_argv must match materialized config")
    if plan.get("cwd") != config.sandbox["cwd"]:
        raise RuntimeConfigError("resolved rootfs plan cwd must match materialized sandbox cwd")
    if plan.get("repo_projection_mode") != "ro":
        raise RuntimeConfigError("repo projection must be ro")
    plan_env = _require_mapping(plan.get("env"), "resolved_rootfs_plan.env")
    for key, value in config.launch["env"].items():
        if plan_env.get(key) != value:
            raise RuntimeConfigError(f"resolved rootfs plan env mismatch: {key}")
    mounts = plan.get("mounts")
    if not isinstance(mounts, list):
        raise RuntimeConfigError("resolved rootfs plan mounts must be a list")
    by_sandbox = {
        mount.get("sandbox_path"): mount
        for mount in mounts
        if isinstance(mount, dict)
    }
    for expected in config.sandbox["mounts"]:
        mount = by_sandbox.get(expected["sandbox_path"])
        if mount is None:
            raise RuntimeConfigError(f"missing sandbox mount: {expected['sandbox_path']}")
        if mount.get("mode") != expected["mode"]:
            raise RuntimeConfigError(f"mount mode mismatch: {expected['sandbox_path']}")
```

- [ ] **Step 4: Extend `enter_rootfs.sh` for read-only repo projection**

Modify `scripts/rootfs/enter_rootfs.sh` to support a GLM launcher-only flag:

```bash
repo_projection_mode="rw"
```

Parse:

```bash
--repo-readonly) repo_projection_mode="ro"; shift ;;
```

When building `bwrap_args`, use:

```bash
if [[ "$repo_projection_mode" == "ro" ]]; then
  bwrap_args+=(--ro-bind "$REPO_ROOT" "$REPO_MNT")
else
  bwrap_args+=(--bind "$REPO_ROOT" "$REPO_MNT")
fi
```

Make the emitted plan write `repo_projection_mode` and the repo mount mode consistently. Keep `scripts/run` default behavior unchanged by not passing `--repo-readonly` there.

Update materialization so `outer_argv` includes:

```python
"--repo-readonly",
```

before `--emit-plan`.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
python -m pytest python/tests/test_rootfs_enter_plan.py -q
```

Expected: both pass. Update `test_rootfs_enter_plan.py` to assert `repo_projection_mode == "ro"` when `--repo-readonly` is passed and keep a separate test showing the default remains `"rw"`.

---

### Task 5: SGLang CLI and Probe Validation

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: materialized config probe fields
- Produces: `validate_sglang_help`, `parse_models_response`

- [ ] **Step 1: Write failing CLI/probe tests**

Append to `python/tests/test_glm52_sglang_runtime.py`:

```python
validate_sglang_help = glm52_sglang_runtime.validate_sglang_help
parse_models_response = glm52_sglang_runtime.parse_models_response


def test_validate_sglang_help_requires_served_model_name_flag() -> None:
    validate_sglang_help("usage: launch_server --model-path X --served-model-name NAME\\n")

    with pytest.raises(RuntimeConfigError, match="--served-model-name"):
        validate_sglang_help("usage: launch_server --model-path X\\n")


def test_parse_models_response_accepts_served_model_name() -> None:
    parsed = parse_models_response(
        b'{"object":"list","data":[{"id":"zai-org/GLM-5.2"}]}',
        expected_model_ids=["zai-org/GLM-5.2"],
        served_model_name="zai-org/GLM-5.2",
    )

    assert parsed["models"] == ["zai-org/GLM-5.2"]


def test_parse_models_response_rejects_path_identity_when_served_name_expected() -> None:
    with pytest.raises(RuntimeConfigError, match="model identity mismatch"):
        parse_models_response(
            b'{"object":"list","data":[{"id":"/models/glm52"}]}',
            expected_model_ids=["zai-org/GLM-5.2"],
            served_model_name="zai-org/GLM-5.2",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: fail because the functions do not exist.

- [ ] **Step 3: Implement CLI and models parsing**

Append to `scripts/glm52_sglang_runtime.py`:

```python
import json


def validate_sglang_help(help_text: str) -> None:
    if "--served-model-name" not in help_text:
        raise RuntimeConfigError("installed SGLang launcher does not support --served-model-name")


def parse_models_response(
    body: bytes,
    *,
    expected_model_ids: list[str],
    served_model_name: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeConfigError("invalid_json") from error
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeConfigError("invalid_http_response")
    models = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            models.append(item["id"])
    if served_model_name not in models:
        raise RuntimeConfigError("model identity mismatch")
    if not set(models).intersection(expected_model_ids):
        raise RuntimeConfigError("model identity mismatch")
    return {"models": models, "payload": payload}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: all tests pass.

---

### Task 6: Launch, Teardown, and Failure Lifecycle

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: materialized config and validation helpers
- Produces: `should_teardown_after_failure`, launch/teardown helpers used by CLI

- [ ] **Step 1: Write failing lifecycle tests**

Append to `python/tests/test_glm52_sglang_runtime.py`:

```python
should_teardown_after_failure = glm52_sglang_runtime.should_teardown_after_failure


def test_should_teardown_after_failure_defaults_true(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)

    assert should_teardown_after_failure(config) is True


def test_debug_mode_can_leave_process_running_only_when_explicit(tmp_path: Path) -> None:
    declared_text = VALID_DECLARED.replace("debug_mode: false", "debug_mode: true").replace(
        "leave_running_on_failure: false",
        "leave_running_on_failure: true",
    )
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", declared_text))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-debug",
        port=19017,
    )

    assert should_teardown_after_failure(config) is False


def test_leave_running_without_debug_is_rejected(tmp_path: Path) -> None:
    declared_text = VALID_DECLARED.replace(
        "leave_running_on_failure: false",
        "leave_running_on_failure: true",
    )

    with pytest.raises(RuntimeConfigError, match="leave_running_on_failure requires debug_mode"):
        load_declared_spec(write_spec(tmp_path / "declared.yaml", declared_text))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: fail because `should_teardown_after_failure` does not exist.

- [ ] **Step 3: Implement lifecycle policy helper**

Append to `scripts/glm52_sglang_runtime.py`:

```python
def should_teardown_after_failure(config: MaterializedSglangRuntimeConfig) -> bool:
    return not (
        bool(config.observability.get("debug_mode"))
        and bool(config.observability.get("leave_running_on_failure"))
    )
```

If time remains in this task, add private helpers for later CLI use:

```python
def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n")


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: all tests pass.

---

### Task 7: CLI Commands and Wrapper

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Create: `scripts/run_glm52_sglang_runtime.sh`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: all schema/materialization/probe helpers
- Produces: CLI subcommands `materialize`, `validate`, `launch`, `teardown`, `repeat`

- [ ] **Step 1: Write failing CLI tests**

Append to `python/tests/test_glm52_sglang_runtime.py`:

```python
main = glm52_sglang_runtime.main


def test_materialize_cli_writes_config(tmp_path: Path) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV)
    output = tmp_path / "materialized.yaml"

    rc = main([
        "materialize",
        "--declared-spec",
        str(declared),
        "--local-environment",
        str(local_env),
        "--run-id",
        "glm52-sglang-local-001",
        "--port",
        "19017",
        "--output",
        str(output),
    ])

    assert rc == 0
    loaded = load_materialized_config(output)
    assert loaded.service["port"] == 19017


def test_validate_cli_rejects_drifted_materialized_config(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    drifted = config.replace_launch_inner(["python", "-m", "sglang.launch_server"])
    path = tmp_path / "bad.yaml"
    path.write_text(glm52_sglang_runtime.yaml.safe_dump(glm52_sglang_runtime._config_to_mapping(drifted), sort_keys=False))

    rc = main(["validate", "--materialized-config", str(path)])

    assert rc == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: fail because `main` does not exist.

- [ ] **Step 3: Implement CLI parser**

Append to `scripts/glm52_sglang_runtime.py`:

```python
import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Schema-driven GLM-5.2 SGLang runtime launcher")
    sub = parser.add_subparsers(dest="command", required=True)

    materialize = sub.add_parser("materialize")
    materialize.add_argument("--declared-spec", type=Path, required=True)
    materialize.add_argument("--local-environment", type=Path, required=True)
    materialize.add_argument("--run-id", required=True)
    materialize.add_argument("--port", type=int)
    materialize.add_argument("--output", type=Path, required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--materialized-config", type=Path, required=True)

    launch = sub.add_parser("launch")
    launch.add_argument("--materialized-config", type=Path, required=True)

    teardown = sub.add_parser("teardown")
    teardown.add_argument("--materialized-config", type=Path, required=True)

    repeat = sub.add_parser("repeat")
    repeat.add_argument("--declared-spec", type=Path, required=True)
    repeat.add_argument("--local-environment", type=Path, required=True)
    repeat.add_argument("--cycles", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "materialize":
            declared = load_declared_spec(args.declared_spec)
            local_environment = load_local_environment(args.local_environment)
            config = materialize_runtime_config(
                declared=declared,
                local_environment=local_environment,
                run_id=args.run_id,
                port=args.port,
            )
            write_materialized_config(config, args.output)
            return 0
        if args.command == "validate":
            load_materialized_config(args.materialized_config)
            return 0
        if args.command in {"launch", "teardown", "repeat"}:
            raise RuntimeConfigError(f"{args.command} requires the runtime lifecycle task")
    except RuntimeConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Add missing `import sys` near the top.

- [ ] **Step 4: Add thin wrapper**

Create `scripts/run_glm52_sglang_runtime.sh`. This wrapper stays in the
host-control execution domain because the launcher starts and tears down the
outer bwrap/rootfs process and must observe host PIDs and ports:

```bash
#!/usr/bin/env bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$REPO_ROOT/scripts/glm52_sglang_runtime.py" "$@"
```

Run: `chmod +x scripts/run_glm52_sglang_runtime.sh`

- [ ] **Step 5: Run tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
bash -n scripts/run_glm52_sglang_runtime.sh
```

Expected: tests pass and bash syntax check passes.

---

### Task 8: Live Launch/Probe/Teardown Implementation

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: CLI, materialized config, rootfs plan validation, probe validation
- Produces: working `launch`, `teardown`, and `repeat` CLI subcommands

- [ ] **Step 1: Write failing launch flow test with fake process/probes**

Append to `python/tests/test_glm52_sglang_runtime.py`:

```python
def test_launch_failure_tears_down_when_not_debug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    config_path = tmp_path / "materialized.yaml"
    write_materialized_config(config, config_path)
    events: list[str] = []

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            events.append("wait")
            return 0

    monkeypatch.setattr(glm52_sglang_runtime, "run_sglang_help_preflight", lambda _config: "--served-model-name")
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "emit_and_load_rootfs_plan",
        lambda config, *, resolved_plan_path: valid_rootfs_plan(config),
    )
    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(glm52_sglang_runtime, "wait_for_models_probe", lambda _config: (_ for _ in ()).throw(RuntimeConfigError("model identity mismatch")))

    rc = main(["launch", "--materialized-config", str(config_path)])

    assert rc == 2
    assert events == ["terminate", "wait"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py::test_launch_failure_tears_down_when_not_debug -q`

Expected: fail because launch is not implemented.

- [ ] **Step 3: Implement launch helpers**

In `scripts/glm52_sglang_runtime.py`, import `os`, `signal`, `subprocess`, `time`, and `urllib.request`.

Add:

```python
def run_sglang_help_preflight(config: MaterializedSglangRuntimeConfig) -> str:
    process = subprocess.run(
        config.launch["outer_argv"][: config.launch["outer_argv"].index("--") + 1]
        + ["python", "-m", "sglang.launch_server", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    help_text = process.stdout + process.stderr
    validate_sglang_help(help_text)
    return help_text


def emit_and_load_rootfs_plan(
    config: MaterializedSglangRuntimeConfig,
    *,
    resolved_plan_path: Path,
) -> dict[str, Any]:
    command = list(config.launch["outer_argv"])
    command[command.index("run://sandbox/resolved-bwrap-plan.yaml")] = str(resolved_plan_path)
    env = {**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"}
    process = subprocess.run(command, capture_output=True, text=True, check=False, env=env)
    if process.returncode != 0:
        raise RuntimeConfigError(f"rootfs plan emission failed: {process.stderr}")
    plan = load_yaml_mapping(resolved_plan_path)
    validate_resolved_rootfs_plan(config=config, plan=plan)
    return plan


def wait_for_models_probe(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    deadline = time.time() + 900
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(config.probes["models_url"], timeout=5) as response:
                body = response.read()
            return parse_models_response(
                body,
                expected_model_ids=list(config.service["expected_model_ids"]),
                served_model_name=str(config.model["served_model_name"]),
            )
        except Exception as error:
            last_error = error
            time.sleep(2)
    raise RuntimeConfigError(f"models probe timed out: {last_error}")


def terminate_process(process: Any) -> None:
    process.terminate()
    process.wait(timeout=30)
```

Implement a minimal `launch_runtime(config)` that:

- runs help preflight;
- emits and validates rootfs plan;
- resolves run artifact paths before calling `emit_and_load_rootfs_plan`;
- opens stdout/stderr logs from the resolved artifact paths;
- calls `subprocess.Popen(config.launch["outer_argv"], env=config.launch["env"], start_new_session=True, stdout=stdout_handle, stderr=stderr_handle)`;
- writes process record when path resolution exists;
- runs `wait_for_models_probe`;
- on any exception after process creation, calls `terminate_process(process)` if `should_teardown_after_failure(config)`;
- re-raises `RuntimeConfigError`.

Wire `main(["launch", ...])` to call `launch_runtime`.

- [ ] **Step 4: Run the fake launch test**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py::test_launch_failure_tears_down_when_not_debug -q`

Expected: pass.

- [ ] **Step 5: Implement real artifact path resolution and teardown**

Add a resolver that maps:

- `repo://x` to `LocalEnvironmentConfig.repo / x`;
- `run://x` to the resolved `host_layout.run_dir / x`;
- `cache://x` to `LocalEnvironmentConfig.cache / x`;
- `temp://x` to `LocalEnvironmentConfig.temp / x`.

Update CLI `launch` and `teardown` to require:

```text
--local-environment PATH
```

for resolving paths. Make `launch` write:

- `declared-spec.yaml` when supplied by repeat flow;
- `materialized-sglang-runtime.yaml`;
- `resolved-local-paths.yaml`;
- `process.yaml`;
- `launch-summary.json`;
- `logs/telemetry.jsonl`;
- `sandbox/sglang-launch-server-help.txt`;
- `sandbox/resolved-bwrap-plan.yaml`;
- `probes/models.json`.

Make `teardown` read `process.yaml`, terminate the recorded process group, wait for port release, write `teardown-summary.json`, and return zero for a second teardown with `already_stopped`.

- [ ] **Step 6: Run focused tests**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`

Expected: pass.

---

### Task 9: Example Configs and Repeat Command

**Files:**
- Create: `.scratch/glm52-local-serving/config/sglang-local.yaml`
- Create: `.scratch/glm52-local-serving/config/local-environment.example.yaml`
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: declared spec schema and CLI
- Produces: `repeat` command and repo-local example configs

- [ ] **Step 1: Add example configs**

Create `.scratch/glm52-local-serving/config/sglang-local.yaml` using `VALID_DECLARED` from Task 1, with `range_start: 19000`, `range_end: 19100`, `debug_mode: false`, and `leave_running_on_failure: false`.

Create `.scratch/glm52-local-serving/config/local-environment.example.yaml`:

```yaml
schema_version: 1
roots:
  repo: <absolute-path-to-monarch-checkout>
  cache: <absolute-path-to-local-glm52-cache>
  temp: <absolute-path-to-local-glm52-temp>
rootfs:
  monarch-default: <absolute-path-to-built-bwrap-rootfs>
```

- [ ] **Step 2: Write failing repeat CLI test**

Append to `python/tests/test_glm52_sglang_runtime.py`:

```python
def test_repeat_cli_runs_requested_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV)
    runs: list[str] = []

    def fake_launch_runtime(config):
        runs.append(config.run_id)
        return {"status": "passed", "run_id": config.run_id}

    def fake_teardown_runtime(config, local_environment):
        return {"status": "teardown_passed", "run_id": config.run_id}

    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)

    rc = main([
        "repeat",
        "--declared-spec",
        str(declared),
        "--local-environment",
        str(local_env),
        "--cycles",
        "3",
    ])

    assert rc == 0
    assert len(runs) == 3
    assert len(set(runs)) == 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py::test_repeat_cli_runs_requested_cycles -q`

Expected: fail because `repeat` is not implemented.

- [ ] **Step 4: Implement repeat command**

In `main`, implement `repeat`:

- load declared spec and local environment;
- determine cycles from `--cycles` or declared spec;
- for each cycle, build a run ID like `glm52-sglang-local-<UTC>-<cycle>`;
- materialize a config with the next available non-disallowed port in range;
- write materialized config into the resolved run dir;
- call `launch_runtime(config)`;
- call `teardown_runtime(config, local_environment)`;
- collect cycle summaries;
- write a loop summary to `glm52-serving-results/<run-group>-repeat-<timestamp>/loop-summary.json`.

Keep the first implementation simple: if any cycle fails, stop and return nonzero after teardown.

- [ ] **Step 5: Run focused tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
bash -n scripts/run_glm52_sglang_runtime.sh
```

Expected: pass.

---

### Task 10: Live Verification Gate

**Files:**
- No source edits unless earlier tasks exposed defects
- Uses: `.scratch/glm52-local-serving/config/sglang-local.yaml`
- Uses: local copy of `.scratch/glm52-local-serving/config/local-environment.example.yaml`

**Interfaces:**
- Consumes: `scripts/run_glm52_sglang_runtime.sh repeat`
- Produces: live three-cycle evidence under `glm52-serving-results/`

- [ ] **Step 1: Prepare local environment config**

Copy the example to a machine-local file under `.scratch/glm52-local-serving/tmp/`:

```sh
mkdir -p .scratch/glm52-local-serving/tmp
cp .scratch/glm52-local-serving/config/local-environment.example.yaml \
  .scratch/glm52-local-serving/tmp/local-environment.yaml
```

Edit the local file only if this checkout/rootfs path differs.

- [ ] **Step 2: Run schema validation**

Run:

```sh
scripts/run_glm52_sglang_runtime.sh materialize \
  --declared-spec .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-environment .scratch/glm52-local-serving/tmp/local-environment.yaml \
  --run-id glm52-sglang-local-validation \
  --port 19017 \
  --output .scratch/glm52-local-serving/tmp/materialized-sglang-runtime.yaml

scripts/run_glm52_sglang_runtime.sh validate \
  --materialized-config .scratch/glm52-local-serving/tmp/materialized-sglang-runtime.yaml
```

Expected: both exit zero.

- [ ] **Step 3: Run live repeat gate**

Run:

```sh
scripts/run_glm52_sglang_runtime.sh repeat \
  --declared-spec .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-environment .scratch/glm52-local-serving/tmp/local-environment.yaml \
  --cycles 3
```

Expected: exits zero and writes a loop summary with three passed launch/probe/teardown cycles.

- [ ] **Step 4: Inspect artifacts**

For each run listed in the loop summary, verify these files exist:

```text
declared-spec.yaml
materialized-sglang-runtime.yaml
resolved-local-paths.yaml
process.yaml
launch-summary.json
teardown-summary.json
probes/models.json
probes/chat-completions.json
logs/stdout.log
logs/stderr.log
logs/telemetry.jsonl
sandbox/resolved-bwrap-plan.yaml
sandbox/sglang-launch-server-help.txt
```

Expected: every run has those artifacts, `/v1/models` includes `zai-org/GLM-5.2`, teardown status is `teardown_passed`, and selected ports are released.

- [ ] **Step 5: Record completion evidence**

Append a short completion note to `.scratch/glm52-local-serving/completion-audit-2026-08-16.md` with:

- loop summary path;
- three run IDs;
- three selected ports;
- probe status for each run;
- teardown status for each run;
- any remaining SGLang/Dynamo follow-up blockers.

Do not claim Dynamo, Responses, Harbor, EvalPlus, or conformance readiness from this milestone.

---

## Self-Review Checklist

- Spec coverage: Tasks 1-2 cover source-backed declared/materialized schema; Task 3-4 cover rootfs plan emission and validation; Task 5 covers served model name and probe parsing; Task 6 covers failure teardown and debug policy; Task 7-9 cover CLI, examples, and repeatability; Task 10 covers live three-cycle evidence.
- No fallback: every task preserves explicit ports, explicit served model name, no ambient GLM env defaults, and no fixture or fake success path for live completion.
- Test seam: unit tests drive schema, materialization, rootfs plan validation, CLI preflight, lifecycle policy, and repeat orchestration before live execution.
- Remaining risk: exact SGLang CLI behavior is verified by runtime help preflight because the installed version may differ from docs.
