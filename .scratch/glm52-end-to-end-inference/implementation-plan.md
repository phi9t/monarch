# GLM-5.2 End-to-End Local Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a schema-owned end-to-end GLM-5.2 Local Run that launches SGLang, Dynamo, and the Responses adapter on run-owned custom ports, proves real inference through each layer, and tears down cleanly.

**Architecture:** Add a new parent orchestrator, `scripts/glm52_inference_runtime.py`, that composes the existing SGLang runtime with Dynamo and Responses component slices. Keep the SGLang runtime authoritative for rootfs-owned SGLang preparation and launch. The parent orchestrator owns the inference schema, multi-port allocation, component process records, probes, repeatability, and final Contract Artifacts.

**Tech Stack:** Python 3.12, dataclasses, `yaml.safe_load` / `yaml.safe_dump`, `json`, `subprocess`, `urllib.request`, pytest, bash, Monarch `scripts/run`, existing `scripts/glm52_sglang_runtime.py`, existing `scripts/glm52_serving_verifier.py`.

**Spec:** `.scratch/glm52-end-to-end-inference/spec.md`

## Global Constraints

- No fallback. Fail fast, fail loud.
- Do not use ports `8000`, `8080`, or `18080`.
- Portable config must not encode absolute host paths.
- Concrete host paths are allowed only in local environment config and resolved evidence.
- SGLang runs through the existing Hermetic Rootfs contract.
- Dynamo and the Responses adapter are host-controlled initial components, but their command, env, port, upstream URL, logs, and process records must come only from `materialized-inference.yaml`.
- Do not infer or switch execution domains after a command fails.
- Do not start SGLang as an implicit downloader.
- Do not treat fake endpoints or fixture harnesses as live completion evidence.
- `summary.json` reports `ok: true` only when every required gate passes.

---

## File Structure

- Create `scripts/glm52_inference_runtime.py`
  - Owns declared inference schema, materialized inference schema, multi-port allocation, process record handling, component launch/probe/teardown, repeatability, and CLI.
  - Imports `scripts/glm52_sglang_runtime.py` for SGLang parsing, materialization, preparation validation, launch, teardown, and probe helpers.
  - Imports `scripts/glm52_serving_verifier.py` for Chat/Responses verification helpers.
- Create `scripts/run_glm52_inference_runtime.sh`
  - Thin host-control wrapper that invokes `scripts/run python scripts/glm52_inference_runtime.py "$@"`.
- Create `python/tests/test_glm52_inference_runtime.py`
  - Focused tests for schema parsing, materialization, process records, component command construction, probe parsing, and repeatability summaries.
- Create `.scratch/glm52-local-serving/config/inference-local.yaml`
  - Portable declared inference config from the spec.
- Modify no existing GLM verifier, adapter, or SGLang behavior until a task explicitly requires it.

## Public Interfaces

The new orchestrator exports these interfaces:

```python
class InferenceConfigError(RuntimeError): ...
class InferenceLaunchError(RuntimeError): ...

@dataclass(frozen=True)
class InferencePortPolicy:
    mode: str
    bind_host: str
    range_start: int
    range_end: int
    disallowed_ports: list[int]

@dataclass(frozen=True)
class DeclaredInferenceSpec:
    schema_version: int
    run_group: str
    fail_fast: bool
    allow_fallback: bool
    ports: InferencePortPolicy
    components: dict[str, Any]
    probes: dict[str, Any]
    repeatability: dict[str, Any]
    teardown: dict[str, Any]

@dataclass(frozen=True)
class MaterializedInferenceConfig:
    schema_version: int
    run_id: str
    run_dir: str
    declared_path: str
    local_environment_path: str
    ports: dict[str, int]
    components: dict[str, dict[str, Any]]
    probes: dict[str, Any]
    repeatability: dict[str, Any]
    teardown: dict[str, Any]
    artifacts: dict[str, Any]

def load_declared_inference_spec(path: Path) -> DeclaredInferenceSpec: ...
def materialize_inference_config(
    *,
    declared: DeclaredInferenceSpec,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
) -> MaterializedInferenceConfig: ...
def write_materialized_inference_config(config: MaterializedInferenceConfig, path: Path) -> None: ...
def load_materialized_inference_config(path: Path) -> MaterializedInferenceConfig: ...
def launch_component(config: MaterializedInferenceConfig, component: str) -> dict[str, Any]: ...
def teardown_component(config: MaterializedInferenceConfig, component: str) -> dict[str, Any]: ...
def run_one_inference_cycle(config: MaterializedInferenceConfig) -> dict[str, Any]: ...
def run_repeatability_cycles(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
    cycles: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]: ...
```

---

### Task 1: Inference Schema and Materialization

**Files:**
- Create: `scripts/glm52_inference_runtime.py`
- Create: `scripts/run_glm52_inference_runtime.sh`
- Create: `python/tests/test_glm52_inference_runtime.py`
- Create: `.scratch/glm52-local-serving/config/inference-local.yaml`

**Interfaces:**
- Consumes: `glm52_sglang_runtime.load_declared_spec`, `glm52_sglang_runtime.load_local_environment`, `glm52_sglang_runtime.materialize_runtime_config`
- Produces: `load_declared_inference_spec`, `materialize_inference_config`, `write_materialized_inference_config`, `load_materialized_inference_config`

- [ ] **Step 1: Create the failing schema test file**

Create `python/tests/test_glm52_inference_runtime.py` with this import harness:

```python
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "glm52_inference_runtime.py"
spec = importlib.util.spec_from_file_location("glm52_inference_runtime", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_inference_runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_inference_runtime
spec.loader.exec_module(glm52_inference_runtime)

InferenceConfigError = glm52_inference_runtime.InferenceConfigError
load_declared_inference_spec = glm52_inference_runtime.load_declared_inference_spec
materialize_inference_config = glm52_inference_runtime.materialize_inference_config
write_materialized_inference_config = glm52_inference_runtime.write_materialized_inference_config
load_materialized_inference_config = glm52_inference_runtime.load_materialized_inference_config


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


VALID_INFERENCE = """\
schema_version: 1
run_group: glm52-inference-local
fail_fast: true
allow_fallback: false
ports:
  mode: strict_run_owned_range
  bind_host: 127.0.0.1
  range_start: 19000
  range_end: 19200
  disallowed_ports: [8000, 8080, 18080]
components:
  sglang_backend:
    enabled: true
    declared_ref: repo://.scratch/glm52-local-serving/config/sglang-local.yaml
    required_records:
      venv: repo://glm52-serving-results/prepare-venv/sglang-venv.json
      model_cache: repo://glm52-serving-results/prepare-model/model-cache.json
  dynamo_frontend:
    enabled: true
    kind: local_dynamo_sglang
    execution_domain: host_controlled
    bind_host: 127.0.0.1
    upstream_ref: component://sglang_backend/openai_base_url
    model_name_ref: component://sglang_backend/served_model_name
    config_root: repo://.scratch/glm52-local-serving/dynamo
    logs_root: run://logs/dynamo
    startup_timeout_seconds: 300
    argv: [python, -m, dynamo.frontend]
  responses_adapter:
    enabled: true
    execution_domain: host_controlled
    bind_host: 127.0.0.1
    upstream_ref: component://dynamo_frontend/openai_base_url
    model_name_ref: component://sglang_backend/served_model_name
    logs_root: run://logs/responses-adapter
    startup_timeout_seconds: 120
probes:
  sglang:
    models_required: true
    chat_required: true
  dynamo:
    models_required: true
    chat_required: true
  responses:
    models_required: true
    nonstream_required: true
    stream_required: true
    tool_call_required: true
repeatability:
  cycles: 3
teardown:
  process_group_required: true
  port_closed_required: true
  orphan_scan_required: true
"""
```

- [ ] **Step 2: Add failing acceptance and rejection tests**

Append these tests:

```python
def test_load_declared_inference_spec_accepts_complete_spec(tmp_path: Path) -> None:
    spec_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)

    declared = load_declared_inference_spec(spec_path)

    assert declared.run_group == "glm52-inference-local"
    assert declared.fail_fast is True
    assert declared.allow_fallback is False
    assert declared.ports.mode == "strict_run_owned_range"
    assert declared.ports.bind_host == "127.0.0.1"
    assert {8000, 8080, 18080}.issubset(set(declared.ports.disallowed_ports))
    assert declared.components["dynamo_frontend"]["upstream_ref"] == "component://sglang_backend/openai_base_url"
    assert declared.repeatability["cycles"] == 3


@pytest.mark.parametrize(
    ("needle", "replacement", "match"),
    [
        ("allow_fallback: false", "allow_fallback: true", "allow_fallback must be false"),
        ("fail_fast: true", "fail_fast: false", "fail_fast must be true"),
        ("range_start: 19000", "range_start: 8000", "disallowed port"),
        ("repo://.scratch/glm52-local-serving/config/sglang-local.yaml", "/tmp/sglang-local.yaml", "must use logical path refs"),
        ("upstream_ref: component://sglang_backend/openai_base_url", "upstream_ref: http://127.0.0.1:8000/v1", "must use component refs"),
    ],
)
def test_load_declared_inference_spec_rejects_invalid_spec(
    tmp_path: Path,
    needle: str,
    replacement: str,
    match: str,
) -> None:
    spec_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE.replace(needle, replacement))

    with pytest.raises(InferenceConfigError, match=match):
        load_declared_inference_spec(spec_path)
```

- [ ] **Step 3: Run the red test**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
```

Expected: collection fails because `scripts/glm52_inference_runtime.py` does not exist.

- [ ] **Step 4: Implement the schema parser**

Create `scripts/glm52_inference_runtime.py` with minimal parser support:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import yaml

DISALLOWED_PORTS = {8000, 8080, 18080}
COMPONENT_ORDER = ["sglang_backend", "dynamo_frontend", "responses_adapter"]


class InferenceConfigError(RuntimeError):
    """Raised when an inference config violates the schema."""


class InferenceLaunchError(RuntimeError):
    """Raised when an inference component cannot be launched or probed."""


@dataclass(frozen=True)
class InferencePortPolicy:
    mode: str
    bind_host: str
    range_start: int
    range_end: int
    disallowed_ports: list[int]


@dataclass(frozen=True)
class DeclaredInferenceSpec:
    schema_version: int
    run_group: str
    fail_fast: bool
    allow_fallback: bool
    ports: InferencePortPolicy
    components: dict[str, Any]
    probes: dict[str, Any]
    repeatability: dict[str, Any]
    teardown: dict[str, Any]


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        payload = yaml.safe_load(handle)
    return _require_mapping(payload, str(path))


def load_declared_inference_spec(path: Path) -> DeclaredInferenceSpec:
    data = load_yaml_mapping(path)
    _reject_unknown(data, {"schema_version", "run_group", "fail_fast", "allow_fallback", "ports", "components", "probes", "repeatability", "teardown"}, str(path))
    schema_version = _required_int(data, "schema_version", str(path))
    if schema_version != 1:
        raise InferenceConfigError("schema_version must be 1")
    fail_fast = _required_bool(data, "fail_fast", str(path))
    if not fail_fast:
        raise InferenceConfigError("fail_fast must be true")
    allow_fallback = _required_bool(data, "allow_fallback", str(path))
    if allow_fallback:
        raise InferenceConfigError("allow_fallback must be false")
    ports = _parse_ports(data.get("ports"))
    components = _parse_components(data.get("components"))
    return DeclaredInferenceSpec(
        schema_version=schema_version,
        run_group=_required_str(data, "run_group", str(path)),
        fail_fast=fail_fast,
        allow_fallback=allow_fallback,
        ports=ports,
        components=components,
        probes=_require_mapping(data.get("probes"), "probes"),
        repeatability=_require_mapping(data.get("repeatability"), "repeatability"),
        teardown=_require_mapping(data.get("teardown"), "teardown"),
    )
```

Add helper functions in the same file:

```python
def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InferenceConfigError(f"{path} must be a mapping")
    return value


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise InferenceConfigError(f"{path} contains unknown field(s): {', '.join(unknown)}")


def _required_str(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise InferenceConfigError(f"{path}.{key} must be a non-empty string")
    return value


def _required_int(mapping: dict[str, Any], key: str, path: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise InferenceConfigError(f"{path}.{key} must be an integer")
    return value


def _required_bool(mapping: dict[str, Any], key: str, path: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise InferenceConfigError(f"{path}.{key} must be a boolean")
    return value


def _required_int_list(mapping: dict[str, Any], key: str, path: str) -> list[int]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise InferenceConfigError(f"{path}.{key} must be a list of integers")
    return value


def _logical_ref(value: str, path: str) -> str:
    if value.startswith("/"):
        raise InferenceConfigError(f"{path} must use logical path refs")
    if "://" not in value:
        raise InferenceConfigError(f"{path} must use logical path refs")
    return value


def _component_ref(value: str, path: str) -> str:
    if not value.startswith("component://"):
        raise InferenceConfigError(f"{path} must use component refs")
    return value
```

Add port and component parsing:

```python
def _parse_ports(value: Any) -> InferencePortPolicy:
    mapping = _require_mapping(value, "ports")
    _reject_unknown(mapping, {"mode", "bind_host", "range_start", "range_end", "disallowed_ports"}, "ports")
    policy = InferencePortPolicy(
        mode=_required_str(mapping, "mode", "ports"),
        bind_host=_required_str(mapping, "bind_host", "ports"),
        range_start=_required_int(mapping, "range_start", "ports"),
        range_end=_required_int(mapping, "range_end", "ports"),
        disallowed_ports=_required_int_list(mapping, "disallowed_ports", "ports"),
    )
    if policy.mode != "strict_run_owned_range":
        raise InferenceConfigError("ports.mode must be strict_run_owned_range")
    if policy.bind_host != "127.0.0.1":
        raise InferenceConfigError("ports.bind_host must be 127.0.0.1")
    if policy.range_start > policy.range_end:
        raise InferenceConfigError("ports range_start must be <= range_end")
    blocked = DISALLOWED_PORTS.intersection(range(policy.range_start, policy.range_end + 1))
    if blocked:
        raise InferenceConfigError(f"port range includes disallowed port(s): {sorted(blocked)}")
    if not DISALLOWED_PORTS.issubset(set(policy.disallowed_ports)):
        raise InferenceConfigError("disallowed_ports must include 8000, 8080, and 18080")
    return policy


def _parse_components(value: Any) -> dict[str, Any]:
    mapping = _require_mapping(value, "components")
    _reject_unknown(mapping, set(COMPONENT_ORDER), "components")
    for component in COMPONENT_ORDER:
        if component not in mapping:
            raise InferenceConfigError(f"components.{component} is required")
    sglang = _require_mapping(mapping["sglang_backend"], "components.sglang_backend")
    _logical_ref(_required_str(sglang, "declared_ref", "components.sglang_backend"), "components.sglang_backend.declared_ref")
    records = _require_mapping(sglang.get("required_records"), "components.sglang_backend.required_records")
    _logical_ref(_required_str(records, "venv", "components.sglang_backend.required_records"), "components.sglang_backend.required_records.venv")
    _logical_ref(_required_str(records, "model_cache", "components.sglang_backend.required_records"), "components.sglang_backend.required_records.model_cache")

    dynamo = _require_mapping(mapping["dynamo_frontend"], "components.dynamo_frontend")
    _component_ref(_required_str(dynamo, "upstream_ref", "components.dynamo_frontend"), "components.dynamo_frontend.upstream_ref")
    _component_ref(_required_str(dynamo, "model_name_ref", "components.dynamo_frontend"), "components.dynamo_frontend.model_name_ref")
    _logical_ref(_required_str(dynamo, "config_root", "components.dynamo_frontend"), "components.dynamo_frontend.config_root")
    _logical_ref(_required_str(dynamo, "logs_root", "components.dynamo_frontend"), "components.dynamo_frontend.logs_root")

    responses = _require_mapping(mapping["responses_adapter"], "components.responses_adapter")
    _component_ref(_required_str(responses, "upstream_ref", "components.responses_adapter"), "components.responses_adapter.upstream_ref")
    _component_ref(_required_str(responses, "model_name_ref", "components.responses_adapter"), "components.responses_adapter.model_name_ref")
    _logical_ref(_required_str(responses, "logs_root", "components.responses_adapter"), "components.responses_adapter.logs_root")
    return mapping
```

- [ ] **Step 5: Run the schema tests green**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
```

Expected: the schema tests pass.

- [ ] **Step 6: Add materialization tests**

Append:

```python
def test_materialize_inference_config_allocates_three_custom_ports(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    declared = load_declared_inference_spec(declared_path)

    config = materialize_inference_config(
        declared=declared,
        declared_path=declared_path,
        local_environment_path=local_env_path,
        run_id="run-001",
    )

    assert set(config.ports) == {"sglang_backend", "dynamo_frontend", "responses_adapter"}
    assert len(set(config.ports.values())) == 3
    assert {8000, 8080, 18080}.isdisjoint(set(config.ports.values()))
    assert config.components["sglang_backend"]["openai_base_url"].endswith(f":{config.ports['sglang_backend']}/v1")
    assert config.components["dynamo_frontend"]["upstream_url"] == config.components["sglang_backend"]["openai_base_url"]
    assert config.components["responses_adapter"]["upstream_url"] == config.components["dynamo_frontend"]["openai_base_url"]


def test_materialized_inference_config_round_trips(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", "schema_version: 1\nroots: {}\nrootfs: {}\n")
    declared = load_declared_inference_spec(declared_path)
    config = materialize_inference_config(
        declared=declared,
        declared_path=declared_path,
        local_environment_path=local_env_path,
        run_id="run-002",
    )
    output = tmp_path / "materialized.yaml"

    write_materialized_inference_config(config, output)
    loaded = load_materialized_inference_config(output)

    assert loaded.run_id == "run-002"
    assert loaded.ports == config.ports
    assert loaded.components["responses_adapter"]["argv"] == config.components["responses_adapter"]["argv"]
```

- [ ] **Step 7: Add the shared test materialization helper**

Add this helper under the materialization tests so later tasks can reuse it:

```python
def materialized_config_for_test(tmp_path: Path):
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    declared = load_declared_inference_spec(declared_path)
    return materialize_inference_config(
        declared=declared,
        declared_path=declared_path,
        local_environment_path=local_env_path,
        run_id="run-test",
    )
```

- [ ] **Step 8: Implement materialization**

Add `MaterializedInferenceConfig`, port allocation, component URL derivation, and YAML round-trip helpers:

```python
@dataclass(frozen=True)
class MaterializedInferenceConfig:
    schema_version: int
    run_id: str
    run_dir: str
    declared_path: str
    local_environment_path: str
    ports: dict[str, int]
    components: dict[str, dict[str, Any]]
    probes: dict[str, Any]
    repeatability: dict[str, Any]
    teardown: dict[str, Any]
    artifacts: dict[str, Any]
```

```python
def materialize_inference_config(
    *,
    declared: DeclaredInferenceSpec,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
) -> MaterializedInferenceConfig:
    used_ports: set[int] = set()
    ports = {component: _allocate_port(declared.ports, used_ports) for component in COMPONENT_ORDER}
    run_dir = f"repo://glm52-serving-results/{run_id}"
    sglang_url = f"http://{declared.ports.bind_host}:{ports['sglang_backend']}/v1"
    dynamo_url = f"http://{declared.ports.bind_host}:{ports['dynamo_frontend']}/v1"
    responses_url = f"http://{declared.ports.bind_host}:{ports['responses_adapter']}/v1"
    model_name = "zai-org/GLM-5.2"
    components = {
        "sglang_backend": {
            "openai_base_url": sglang_url,
            "served_model_name": model_name,
            "declared_ref": declared.components["sglang_backend"]["declared_ref"],
            "process_record": f"{run_dir}/components/sglang/process.json",
        },
        "dynamo_frontend": {
            "execution_domain": "host_controlled",
            "openai_base_url": dynamo_url,
            "upstream_url": sglang_url,
            "served_model_name": model_name,
            "argv": _dynamo_argv(declared.components["dynamo_frontend"], host=declared.ports.bind_host, port=ports["dynamo_frontend"], upstream_url=sglang_url, model_name=model_name),
            "process_record": f"{run_dir}/components/dynamo/process.json",
        },
        "responses_adapter": {
            "execution_domain": "host_controlled",
            "openai_base_url": responses_url,
            "upstream_url": dynamo_url,
            "served_model_name": model_name,
            "argv": _responses_adapter_argv(host=declared.ports.bind_host, port=ports["responses_adapter"], upstream_url=dynamo_url, model_name=model_name),
            "process_record": f"{run_dir}/components/responses-adapter/process.json",
        },
    }
    artifacts = {
        "summary": f"{run_dir}/summary.json",
        "port_allocation": f"{run_dir}/port-allocation.json",
        "teardown": f"{run_dir}/teardown",
    }
    return MaterializedInferenceConfig(1, run_id, run_dir, str(declared_path), str(local_environment_path), ports, components, declared.probes, declared.repeatability, declared.teardown, artifacts)
```

```python
def _allocate_port(policy: InferencePortPolicy, used_ports: set[int]) -> int:
    for port in range(policy.range_start, policy.range_end + 1):
        if port in used_ports or port in policy.disallowed_ports or port in DISALLOWED_PORTS:
            continue
        if _is_port_bindable(policy.bind_host, port):
            used_ports.add(port)
            return port
    raise InferenceConfigError("no free run-owned port available")


def _is_port_bindable(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _dynamo_argv(component: dict[str, Any], *, host: str, port: int, upstream_url: str, model_name: str) -> list[str]:
    argv = component.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) and item for item in argv):
        raise InferenceConfigError("components.dynamo_frontend.argv must be a non-empty string list")
    return [*argv, "--host", host, "--port", str(port), "--upstream-url", upstream_url, "--model", model_name]


def _responses_adapter_argv(*, host: str, port: int, upstream_url: str, model_name: str) -> list[str]:
    return [
        "python",
        "scripts/glm52_responses_adapter.py",
        "--host",
        host,
        "--port",
        str(port),
        "--model",
        model_name,
        "--chat-base-url",
        upstream_url,
    ]
```

Add `to_mapping`, `from_mapping`, `write_materialized_inference_config`, and `load_materialized_inference_config` with the exact keys from `MaterializedInferenceConfig`.

- [ ] **Step 9: Create the portable example config**

Create `.scratch/glm52-local-serving/config/inference-local.yaml` using the `VALID_INFERENCE` contents from the test.

- [ ] **Step 10: Create the wrapper**

Create `scripts/run_glm52_inference_runtime.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${REPO_ROOT}/scripts/run" python scripts/glm52_inference_runtime.py "$@"
```

Set executable bit:

```sh
chmod +x scripts/run_glm52_inference_runtime.sh
```

- [ ] **Step 11: Add CLI tests and implementation**

Add tests for:

```python
def test_cli_materialize_writes_config(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", "schema_version: 1\nroots: {}\nrootfs: {}\n")
    output = tmp_path / "materialized.yaml"

    rc = glm52_inference_runtime.main([
        "materialize",
        "--declared",
        str(declared_path),
        "--local-env",
        str(local_env_path),
        "--run-id",
        "run-cli",
        "--output",
        str(output),
    ])

    assert rc == 0
    assert load_materialized_inference_config(output).run_id == "run-cli"
```

Implement `build_parser()` and `main()` with `materialize` and `validate` commands only in this task. `launch`, `teardown`, and `repeatability` must exist and fail with `InferenceConfigError("command is not implemented yet")` until later tasks wire them.

- [ ] **Step 12: Run Task 1 verification**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
bash -n scripts/run_glm52_inference_runtime.sh
```

Expected: all Task 1 tests pass and shell syntax check exits zero.

---

### Task 2: Shared Process Records and Teardown Proof

**Files:**
- Modify: `scripts/glm52_inference_runtime.py`
- Modify: `python/tests/test_glm52_inference_runtime.py`

**Interfaces:**
- Consumes: `MaterializedInferenceConfig`
- Produces: `OwnedProcessRecord`, `write_process_record`, `load_process_record`, `validate_process_record`, `terminate_owned_process`, `prove_port_closed`, `prove_no_owned_orphans`

- [ ] **Step 1: Add failing process-record tests**

Append:

```python
def test_process_record_rejects_wrong_component(tmp_path: Path) -> None:
    record = {
        "run_id": "run-001",
        "component": "dynamo_frontend",
        "pid": 123,
        "process_group": 123,
        "argv": ["python", "-m", "dynamo.frontend"],
        "argv_digest": "abc",
        "endpoint_url": "http://127.0.0.1:19001/v1",
        "created_at": "2026-08-17T00:00:00Z",
    }

    with pytest.raises(InferenceConfigError, match="process record component mismatch"):
        glm52_inference_runtime.validate_process_record(record, run_id="run-001", component="responses_adapter")


def test_process_record_rejects_disallowed_endpoint_port() -> None:
    record = {
        "run_id": "run-001",
        "component": "responses_adapter",
        "pid": 123,
        "process_group": 123,
        "argv": ["python", "scripts/glm52_responses_adapter.py"],
        "argv_digest": "abc",
        "endpoint_url": "http://127.0.0.1:8080/v1",
        "created_at": "2026-08-17T00:00:00Z",
    }

    with pytest.raises(InferenceConfigError, match="disallowed endpoint port"):
        glm52_inference_runtime.validate_process_record(record, run_id="run-001", component="responses_adapter")
```

- [ ] **Step 2: Run red**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py::test_process_record_rejects_wrong_component python/tests/test_glm52_inference_runtime.py::test_process_record_rejects_disallowed_endpoint_port -q
```

Expected: fail because the process-record helpers do not exist.

- [ ] **Step 3: Implement process record helpers**

Add:

```python
@dataclass(frozen=True)
class OwnedProcessRecord:
    run_id: str
    component: str
    pid: int
    process_group: int
    argv: list[str]
    argv_digest: str
    endpoint_url: str
    created_at: str
```

```python
def stable_json_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_process_record(record: dict[str, Any], *, run_id: str, component: str) -> None:
    if record.get("run_id") != run_id:
        raise InferenceConfigError("process record run_id mismatch")
    if record.get("component") != component:
        raise InferenceConfigError("process record component mismatch")
    pid = record.get("pid")
    process_group = record.get("process_group")
    if not isinstance(pid, int) or pid <= 0:
        raise InferenceConfigError("process record pid must be positive")
    if not isinstance(process_group, int) or process_group <= 0:
        raise InferenceConfigError("process record process_group must be positive")
    endpoint_url = _required_str(record, "endpoint_url", "process record")
    port = _parsed_url_port(endpoint_url, "process record endpoint_url")
    if port in DISALLOWED_PORTS:
        raise InferenceConfigError("disallowed endpoint port")
```

Also add `_parsed_url_port`, `write_process_record`, and `load_process_record`.

- [ ] **Step 4: Add fake-process launch and teardown tests**

Add a fake process object:

```python
class FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        return 0
```

Add:

```python
def test_process_record_written_after_launch(tmp_path: Path) -> None:
    process = FakeProcess()
    path = tmp_path / "process.json"

    record = glm52_inference_runtime.write_process_record(
        path,
        run_id="run-001",
        component="dynamo_frontend",
        process=process,
        argv=["python", "-m", "dynamo.frontend"],
        endpoint_url="http://127.0.0.1:19002/v1",
    )

    assert path.exists()
    assert record["pid"] == 4321
    assert record["component"] == "dynamo_frontend"
    validate_process_record(record, run_id="run-001", component="dynamo_frontend")
```

- [ ] **Step 5: Implement fake-test support without real process launching**

Implement `write_process_record` using `os.getpgid(process.pid)` when available and `process.pid` as fallback in tests. Do not send signals in unit tests.

- [ ] **Step 6: Add port proof tests**

Add:

```python
def test_prove_port_closed_rejects_open_port(monkeypatch) -> None:
    monkeypatch.setattr(glm52_inference_runtime, "_is_port_open", lambda host, port: True)

    with pytest.raises(InferenceLaunchError, match="port still open"):
        glm52_inference_runtime.prove_port_closed("127.0.0.1", 19003)
```

- [ ] **Step 7: Implement port proof**

Add:

```python
def prove_port_closed(host: str, port: int) -> dict[str, Any]:
    if _is_port_open(host, port):
        raise InferenceLaunchError(f"port still open: {host}:{port}")
    return {"host": host, "port": port, "closed": True}
```

- [ ] **Step 8: Run Task 2 verification**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
```

Expected: all Task 1 and Task 2 tests pass.

---

### Task 3: SGLang and Dynamo Component Lifecycle

**Files:**
- Modify: `scripts/glm52_inference_runtime.py`
- Modify: `python/tests/test_glm52_inference_runtime.py`

**Interfaces:**
- Consumes: `MaterializedInferenceConfig`, `write_process_record`, `validate_process_record`
- Produces: `launch_sglang_component`, `probe_sglang_component`, `launch_dynamo_component`, `probe_dynamo_component`, `teardown_component`

- [ ] **Step 1: Add tests that SGLang launch delegates to the SGLang runtime**

Append:

```python
def test_launch_sglang_component_delegates_to_sglang_runtime(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    calls = []

    def fake_launch_runtime(sglang_config, *, local_environment):
        calls.append((sglang_config, local_environment))
        return {"ok": True, "process": {"pid": 111}, "models_probe": {"models": ["zai-org/GLM-5.2"]}}

    monkeypatch.setattr(glm52_inference_runtime.glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)

    result = glm52_inference_runtime.launch_sglang_component(config)

    assert result["ok"] is True
    assert calls
```

The helper `materialized_config_for_test` should create a valid Task 1 materialized config.

- [ ] **Step 2: Implement SGLang delegation**

Implement:

```python
def launch_sglang_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    sglang_slice = _materialize_sglang_slice(config)
    local_environment = glm52_sglang_runtime.load_local_environment(Path(config.local_environment_path))
    result = glm52_sglang_runtime.launch_runtime(sglang_slice, local_environment=local_environment)
    return {"ok": True, "component": "sglang_backend", "result": result}
```

`_materialize_sglang_slice` may initially load the referenced SGLang declared config and call `glm52_sglang_runtime.materialize_runtime_config` with the already allocated SGLang port.

- [ ] **Step 3: Add Dynamo command rejection tests**

Add:

```python
def test_dynamo_argv_rejects_disallowed_upstream_port(tmp_path: Path) -> None:
    declared_path = write_text(
        tmp_path / "inference.yaml",
        VALID_INFERENCE.replace("upstream_ref: component://sglang_backend/openai_base_url", "upstream_ref: http://127.0.0.1:8000/v1"),
    )

    with pytest.raises(InferenceConfigError, match="must use component refs"):
        load_declared_inference_spec(declared_path)
```

- [ ] **Step 4: Add Dynamo fake-launch tests**

Add:

```python
def test_launch_dynamo_component_writes_process_record(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    fake = FakeProcess(pid=5555)

    def fake_popen(argv, **kwargs):
        assert "--upstream-url" in argv
        assert config.components["sglang_backend"]["openai_base_url"] in argv
        return fake

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(glm52_inference_runtime, "wait_for_models", lambda url, model, timeout_seconds: {"models": [model]})

    result = glm52_inference_runtime.launch_dynamo_component(config)

    assert result["ok"] is True
    assert result["process"]["pid"] == 5555
```

- [ ] **Step 5: Implement host-controlled Dynamo launch**

Implement `launch_dynamo_component` with `subprocess.Popen` using only `config.components["dynamo_frontend"]["argv"]`. Open stdout and stderr files from the materialized artifact paths. Write the process record after `Popen` returns. Then call `probe_dynamo_component`.

- [ ] **Step 6: Implement Dynamo probes**

Use `glm52_serving_verifier.JsonHttpClient`, `join_url`, `model_list_contains`, and `run_chat_health`:

```python
def probe_dynamo_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    component = config.components["dynamo_frontend"]
    model = component["served_model_name"]
    client = glm52_serving_verifier.JsonHttpClient(api_key=None, timeout_seconds=300.0)
    models = client.get_json(glm52_serving_verifier.join_url(component["openai_base_url"], "/models"))
    if not glm52_serving_verifier.model_list_contains(models, model):
        raise InferenceLaunchError("Dynamo /models did not advertise served model")
    chat = glm52_serving_verifier.run_chat_health(client, base_url=component["openai_base_url"], model=model, max_tokens=256)
    return {"models": models, "chat": chat}
```

- [ ] **Step 7: Implement `teardown_component` for SGLang and Dynamo**

For `sglang_backend`, delegate to `glm52_sglang_runtime.teardown_runtime`. For `dynamo_frontend`, load and validate the process record, terminate the process group, mark the record stopped, and prove port closure.

- [ ] **Step 8: Run Task 3 verification**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
```

Expected: all Task 1-3 tests pass.

---

### Task 4: Responses Adapter Lifecycle and Probes

**Files:**
- Modify: `scripts/glm52_inference_runtime.py`
- Modify: `python/tests/test_glm52_inference_runtime.py`

**Interfaces:**
- Consumes: `launch_dynamo_component`, `write_process_record`, `glm52_serving_verifier`
- Produces: `launch_responses_adapter_component`, `probe_responses_adapter_component`

- [ ] **Step 1: Add adapter argv tests**

Append:

```python
def test_responses_adapter_argv_uses_materialized_dynamo_url(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path)
    argv = config.components["responses_adapter"]["argv"]

    assert "--chat-base-url" in argv
    assert config.components["dynamo_frontend"]["openai_base_url"] in argv
    assert "8080" not in argv
    assert "http://127.0.0.1:8000/v1" not in argv
```

- [ ] **Step 2: Add fake adapter launch test**

Add:

```python
def test_launch_responses_adapter_writes_process_record(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    fake = FakeProcess(pid=6666)

    def fake_popen(argv, **kwargs):
        assert "scripts/glm52_responses_adapter.py" in argv
        assert "--port" in argv
        assert str(config.ports["responses_adapter"]) in argv
        return fake

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(glm52_inference_runtime, "probe_responses_adapter_component", lambda config: {"models": {}, "nonstream": {}, "stream": {}, "tool_call": {}})

    result = glm52_inference_runtime.launch_responses_adapter_component(config)

    assert result["ok"] is True
    assert result["process"]["component"] == "responses_adapter"
```

- [ ] **Step 3: Implement adapter launch**

Implement `launch_responses_adapter_component` with `subprocess.Popen` using the materialized argv, stdout/stderr artifacts, process record writing, and probe call.

- [ ] **Step 4: Add probe tests with monkeypatched verifier helpers**

Add:

```python
def test_probe_responses_adapter_requires_model_identity(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)

    class FakeClient:
        def __init__(self, api_key=None, timeout_seconds=300.0):
            pass

        def get_json(self, url):
            return {"data": [{"id": "wrong-model"}]}

    monkeypatch.setattr(glm52_inference_runtime.glm52_serving_verifier, "JsonHttpClient", FakeClient)

    with pytest.raises(InferenceLaunchError, match="Responses /models did not advertise served model"):
        glm52_inference_runtime.probe_responses_adapter_component(config)
```

- [ ] **Step 5: Implement Responses probes**

Use:

- `JsonHttpClient.get_json` for `/models`;
- `run_responses_agent(..., stream=False)` for non-stream;
- `run_responses_agent(..., stream=True)` for stream;
- `agent_run_json(...)` for artifacts;
- `run_terminal_bench_responses` only if a future config enables it. For this milestone, tool-call proof comes from `run_responses_agent` because it exercises virtual tool calls.

Implementation shape:

```python
def probe_responses_adapter_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    component = config.components["responses_adapter"]
    model = component["served_model_name"]
    client = glm52_serving_verifier.JsonHttpClient(api_key=None, timeout_seconds=300.0)
    models = client.get_json(glm52_serving_verifier.join_url(component["openai_base_url"], "/models"))
    if not glm52_serving_verifier.model_list_contains(models, model):
        raise InferenceLaunchError("Responses /models did not advertise served model")
    nonstream = glm52_serving_verifier.agent_run_json(
        glm52_serving_verifier.run_responses_agent(client, base_url=component["openai_base_url"], model=model, max_tokens=512, max_turns=8, stream=False)
    )
    stream = glm52_serving_verifier.agent_run_json(
        glm52_serving_verifier.run_responses_agent(client, base_url=component["openai_base_url"], model=model, max_tokens=512, max_turns=8, stream=True)
    )
    return {"models": models, "nonstream": nonstream, "stream": stream, "tool_call": stream}
```

- [ ] **Step 6: Wire adapter teardown**

Extend `teardown_component` to support `responses_adapter`, using the same host-controlled process-record path as Dynamo.

- [ ] **Step 7: Run Task 4 verification**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
```

Expected: all Task 1-4 tests pass.

---

### Task 5: End-to-End Repeatability and Summary

**Files:**
- Modify: `scripts/glm52_inference_runtime.py`
- Modify: `python/tests/test_glm52_inference_runtime.py`
- Modify: `scripts/run_glm52_inference_runtime.sh` only if new CLI behavior requires wrapper changes

**Interfaces:**
- Consumes: `launch_sglang_component`, `launch_dynamo_component`, `launch_responses_adapter_component`, `teardown_component`
- Produces: `run_one_inference_cycle`, `run_repeatability_cycles`, CLI `repeatability`

- [ ] **Step 1: Add cycle success test**

Append:

```python
def test_run_one_inference_cycle_launches_and_tears_down_in_order(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    events = []

    monkeypatch.setattr(glm52_inference_runtime, "launch_sglang_component", lambda config: events.append("launch-sglang") or {"ok": True})
    monkeypatch.setattr(glm52_inference_runtime, "launch_dynamo_component", lambda config: events.append("launch-dynamo") or {"ok": True})
    monkeypatch.setattr(glm52_inference_runtime, "launch_responses_adapter_component", lambda config: events.append("launch-responses") or {"ok": True})
    monkeypatch.setattr(glm52_inference_runtime, "teardown_component", lambda config, component: events.append(f"teardown-{component}") or {"ok": True})
    monkeypatch.setattr(glm52_inference_runtime, "prove_cycle_clean", lambda config: events.append("prove-clean") or {"ok": True})

    result = glm52_inference_runtime.run_one_inference_cycle(config)

    assert result["ok"] is True
    assert events == [
        "launch-sglang",
        "launch-dynamo",
        "launch-responses",
        "teardown-responses_adapter",
        "teardown-dynamo_frontend",
        "teardown-sglang_backend",
        "prove-clean",
    ]
```

- [ ] **Step 2: Add failure teardown test**

Add:

```python
def test_run_one_inference_cycle_tears_down_after_dynamo_failure(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    events = []

    monkeypatch.setattr(glm52_inference_runtime, "launch_sglang_component", lambda config: events.append("launch-sglang") or {"ok": True})

    def fail_dynamo(config):
        events.append("launch-dynamo")
        raise InferenceLaunchError("dynamo failed")

    monkeypatch.setattr(glm52_inference_runtime, "launch_dynamo_component", fail_dynamo)
    monkeypatch.setattr(glm52_inference_runtime, "teardown_component", lambda config, component: events.append(f"teardown-{component}") or {"ok": True})

    with pytest.raises(InferenceLaunchError, match="dynamo failed"):
        glm52_inference_runtime.run_one_inference_cycle(config)

    assert "teardown-sglang_backend" in events
```

- [ ] **Step 3: Implement cycle orchestration**

Implement `run_one_inference_cycle`:

```python
def run_one_inference_cycle(config: MaterializedInferenceConfig) -> dict[str, Any]:
    launched: list[str] = []
    cycle: dict[str, Any] = {"ok": False, "components": {}}
    try:
        cycle["components"]["sglang_backend"] = launch_sglang_component(config)
        launched.append("sglang_backend")
        cycle["components"]["dynamo_frontend"] = launch_dynamo_component(config)
        launched.append("dynamo_frontend")
        cycle["components"]["responses_adapter"] = launch_responses_adapter_component(config)
        launched.append("responses_adapter")
        for component in reversed(launched):
            cycle.setdefault("teardown", {})[component] = teardown_component(config, component)
        cycle["clean"] = prove_cycle_clean(config)
        cycle["ok"] = True
        return cycle
    except Exception:
        for component in reversed(launched):
            try:
                cycle.setdefault("teardown", {})[component] = teardown_component(config, component)
            except Exception as teardown_error:
                cycle.setdefault("teardown_errors", []).append(str(teardown_error))
        raise
```

- [ ] **Step 4: Add repeatability summary tests**

Add:

```python
def test_run_repeatability_cycles_rejects_false_cycle(tmp_path: Path, monkeypatch) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", "schema_version: 1\nroots: {}\nrootfs: {}\n")
    monkeypatch.setattr(glm52_inference_runtime, "run_one_inference_cycle", lambda config: {"ok": False})

    with pytest.raises(InferenceLaunchError, match="cycle 1 returned ok=false"):
        glm52_inference_runtime.run_repeatability_cycles(
            declared_path=declared_path,
            local_environment_path=local_env_path,
            run_id="repeat-fail",
            cycles=1,
        )
```

- [ ] **Step 5: Implement repeatability**

Implement `run_repeatability_cycles` to load declared config, materialize once per cycle with a cycle run ID suffix, run cycles, write `summary.json`, and raise if any cycle returns `ok: false`.

- [ ] **Step 6: Wire CLI**

Update `main()` so:

- `repeatability --declared <yaml> --local-env <yaml> --run-id <id> --cycles <n>` runs the repeatability loop;
- `--dry-run` materializes configs and writes summary without launching components;
- `launch` and `teardown` remain component-aware only if all required materialized config paths are provided.

- [ ] **Step 7: Add CLI repeatability tests**

Add:

```python
def test_cli_repeatability_dry_run_writes_summary(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", "schema_version: 1\nroots: {}\nrootfs: {}\n")

    rc = glm52_inference_runtime.main([
        "repeatability",
        "--declared",
        str(declared_path),
        "--local-env",
        str(local_env_path),
        "--run-id",
        "dry-run",
        "--cycles",
        "1",
        "--dry-run",
    ])

    assert rc == 0
```

- [ ] **Step 8: Run focused verification**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
bash -n scripts/run_glm52_inference_runtime.sh
```

Expected: all end-to-end orchestrator unit tests pass and shell syntax check exits zero.

- [ ] **Step 9: Run broader GLM regression checks**

Run:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_inference_runtime.py \
  python/tests/test_glm52_sglang_runtime.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  -q
```

Expected: all selected GLM tests pass. If untracked older GLM tests are not intended for this branch, document that and run at minimum `test_glm52_inference_runtime.py` and `test_glm52_sglang_runtime.py`.

---

## Live Evidence Gate

After Tasks 1-5 are green, live completion still requires real preparation records and a real run:

```sh
scripts/run_glm52_sglang_runtime.sh prepare-venv \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml

scripts/run_glm52_sglang_runtime.sh prepare-model \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml

scripts/run_glm52_inference_runtime.sh repeatability \
  --declared .scratch/glm52-local-serving/config/inference-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml \
  --run-id glm52-e2e-live \
  --cycles 3
```

Acceptance requires `glm52-serving-results/glm52-e2e-live/summary.json` with `ok: true` and live Contract Artifacts for direct SGLang chat, Dynamo chat, Responses non-stream, Responses stream, tool-call proof, and clean teardown.

## Plan Self-Review

- Spec coverage: Task 1 covers schema, materialization, strict ports, portable refs, and no fallback URLs. Task 2 covers owned process records, teardown proof, ports, and orphan scaffolding. Task 3 covers SGLang reuse and Dynamo integration. Task 4 covers Responses adapter integration and Responses probes. Task 5 covers repeatability, summary, failure teardown, and live evidence gate.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: public functions named in later tasks are introduced before use, and component names match the spec: `sglang_backend`, `dynamo_frontend`, and `responses_adapter`.
