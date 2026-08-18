#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "glm52_inference_runtime.py"
spec = importlib.util.spec_from_file_location("glm52_inference_runtime", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_inference_runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_inference_runtime
spec.loader.exec_module(glm52_inference_runtime)

InferenceConfigError = glm52_inference_runtime.InferenceConfigError
InferenceLaunchError = glm52_inference_runtime.InferenceLaunchError
load_declared_inference_spec = glm52_inference_runtime.load_declared_inference_spec
load_materialized_inference_config = glm52_inference_runtime.load_materialized_inference_config
materialize_inference_config = glm52_inference_runtime.materialize_inference_config
validate_process_record = glm52_inference_runtime.validate_process_record
write_materialized_inference_config = glm52_inference_runtime.write_materialized_inference_config
prepare_dynamo_venv = glm52_inference_runtime.prepare_dynamo_venv
audit_parent_manifest = glm52_inference_runtime.audit_parent_manifest


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
    topology:
      mode: local_frontend_worker
      package: ai-dynamo
      version: "1.4.0"
      discovery_backend: file
      request_plane: tcp
      namespace: glm52
      file_kv_root: run://components/dynamo/file-kv
      host_control_venv: cache://glm52/venvs/dynamo
      rootfs_cache_projection: /workspace/monarch/scripts/rootfs/cache/glm52-local-serving
      packages:
        - ai-dynamo==1.4.0
        - ai-dynamo-runtime==1.4.0
        - sglang==0.5.17
        - blake3
      rootfs_tools:
        - uv
      frontend:
        module: dynamo.frontend
        chat_processor: sglang
      worker:
        module: dynamo.sglang
        component: backend
        endpoint: generate
        endpoint_types: chat,completions
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
    assert declared.components["dynamo_frontend"]["topology"]["mode"] == "local_frontend_worker"
    assert declared.components["dynamo_frontend"]["topology"]["packages"] == [
        "ai-dynamo==1.4.0",
        "ai-dynamo-runtime==1.4.0",
        "sglang==0.5.17",
        "blake3",
    ]
    assert declared.components["dynamo_frontend"]["topology"]["rootfs_tools"] == ["uv"]
    assert (
        declared.components["dynamo_frontend"]["topology"]["rootfs_cache_projection"]
        == "/workspace/monarch/scripts/rootfs/cache/glm52-local-serving"
    )
    assert declared.repeatability["cycles"] == 3


@pytest.mark.parametrize(
    ("needle", "replacement", "match"),
    [
        ("allow_fallback: false", "allow_fallback: true", "allow_fallback must be false"),
        ("fail_fast: true", "fail_fast: false", "fail_fast must be true"),
        ("range_start: 19000", "range_start: 8000", "disallowed port"),
        (
            "repo://.scratch/glm52-local-serving/config/sglang-local.yaml",
            "/tmp/sglang-local.yaml",
            "must use logical path refs",
        ),
        (
            "upstream_ref: component://sglang_backend/openai_base_url",
            "upstream_ref: http://127.0.0.1:8000/v1",
            "must use component refs",
        ),
        (
            "topology:",
            "argv: [python, -m, dynamo.frontend]\n    topology:",
            "unknown field\\(s\\): argv",
        ),
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
    expected_dynamo_venv = Path("/workspace/monarch/scripts/rootfs/cache/glm52-local-serving/glm52/venvs/dynamo")
    expected_dynamo_python = str(expected_dynamo_venv / "bin" / "python")
    assert config.components["dynamo_frontend"]["host_control_venv"] == "cache://glm52/venvs/dynamo"
    assert config.components["dynamo_frontend"]["rootfs_cache_projection"] == "/workspace/monarch/scripts/rootfs/cache/glm52-local-serving"
    assert config.components["dynamo_frontend"]["host_control_venv_resolved"] == str(expected_dynamo_venv)
    assert config.components["dynamo_frontend"]["host_control_python"] == expected_dynamo_python
    assert config.components["dynamo_frontend"]["env"]["DYN_FILE_KV"] == str(
        tmp_path / "repo" / "glm52-serving-results" / "run-001" / "components" / "dynamo" / "file-kv"
    )
    assert config.components["dynamo_frontend"]["env"]["DYN_DISCOVERY_BACKEND"] == "file"
    assert config.components["dynamo_frontend"]["env"]["DYN_REQUEST_PLANE"] == "tcp"
    assert config.components["dynamo_frontend"]["packages"] == [
        "ai-dynamo==1.4.0",
        "ai-dynamo-runtime==1.4.0",
        "sglang==0.5.17",
        "blake3",
    ]
    assert config.components["dynamo_frontend"]["rootfs_tools"] == ["uv"]
    assert config.components["dynamo_frontend"]["integration_contract"]["kind"] == "integrated_dynamo_sglang_worker"
    assert config.components["dynamo_frontend"]["integration_contract"]["http_bridge_to_external_sglang"] is False
    assert config.components["dynamo_frontend"]["integration_contract"]["required_help_flags"]["dynamo.sglang"] == [
        "--model-path",
        "--served-model-name",
        "--device",
        "--host",
        "--port",
        "--disaggregation-mode",
    ]
    assert config.components["dynamo_frontend"]["argv"] == [
        expected_dynamo_python,
        "-m",
        "dynamo.frontend",
        "--http-host",
        "127.0.0.1",
        "--http-port",
        str(config.ports["dynamo_frontend"]),
        "--model-name",
        "zai-org/GLM-5.2",
        "--discovery-backend",
        "file",
        "--request-plane",
        "tcp",
        "--namespace",
        "glm52",
        "--dyn-chat-processor",
        "sglang",
    ]
    assert config.components["dynamo_frontend"]["worker_argv"] == [
        expected_dynamo_python,
        "-m",
        "dynamo.sglang",
        "--model-path",
        "zai-org/GLM-5.2",
        "--served-model-name",
        "zai-org/GLM-5.2",
        "--discovery-backend",
        "file",
        "--request-plane",
        "tcp",
        "--namespace",
        "glm52",
        "--endpoint",
        "dyn://glm52.backend.generate",
        "--endpoint-types",
        "chat,completions",
    ]
    assert "--upstream-url" not in config.components["dynamo_frontend"]["argv"]


def test_materialized_inference_config_round_trips(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", local_env_text(tmp_path))
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


def materialized_config_for_test(tmp_path: Path, *, run_id: str = "run-test"):
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", local_env_text(tmp_path))
    declared = load_declared_inference_spec(declared_path)
    return materialize_inference_config(
        declared=declared,
        declared_path=declared_path,
        local_environment_path=local_env_path,
        run_id=run_id,
    )


def replace_component_argv(config, component: str, argv: list[str]):
    components = {
        name: dict(component_config)
        for name, component_config in config.components.items()
    }
    components[component]["argv"] = argv
    return glm52_inference_runtime.MaterializedInferenceConfig(
        schema_version=config.schema_version,
        run_id=config.run_id,
        run_dir=config.run_dir,
        declared_path=config.declared_path,
        local_environment_path=config.local_environment_path,
        ports=config.ports,
        components=components,
        probes=config.probes,
        repeatability=config.repeatability,
        teardown=config.teardown,
        artifacts=config.artifacts,
    )


def local_env_text(tmp_path: Path) -> str:
    return f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
"""


def test_cli_materialize_writes_config(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", local_env_text(tmp_path))
    output = tmp_path / "materialized.yaml"

    rc = glm52_inference_runtime.main(
        [
            "materialize",
            "--declared",
            str(declared_path),
            "--local-env",
            str(local_env_path),
            "--run-id",
            "run-cli",
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    assert load_materialized_inference_config(output).run_id == "run-cli"


def test_process_record_rejects_wrong_component() -> None:
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
        validate_process_record(record, run_id="run-001", component="responses_adapter")


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
        validate_process_record(record, run_id="run-001", component="responses_adapter")


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


def test_prove_port_closed_rejects_open_port(monkeypatch) -> None:
    monkeypatch.setattr(glm52_inference_runtime, "_is_port_open", lambda host, port: True)

    with pytest.raises(InferenceLaunchError, match="port still open"):
        glm52_inference_runtime.prove_port_closed("127.0.0.1", 19003)


def test_launch_sglang_component_delegates_to_sglang_runtime(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    calls = []

    def fake_launch_runtime(sglang_config, *, local_environment):
        calls.append((sglang_config, local_environment))
        return {"ok": True, "process": {"pid": 111}, "models_probe": {"models": ["zai-org/GLM-5.2"]}}

    monkeypatch.setattr(glm52_inference_runtime.glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)

    result = glm52_inference_runtime.launch_sglang_component(config)

    assert result["ok"] is True
    assert result["component"] == "sglang_backend"
    assert calls


def test_materialize_sglang_slice_uses_parent_required_records(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path)

    sglang_config = glm52_inference_runtime._materialize_sglang_slice(config)

    assert sglang_config.artifacts["preparation"]["sglang_venv_record"] == "repo://glm52-serving-results/prepare-venv/sglang-venv.json"
    assert sglang_config.artifacts["preparation"]["model_cache_record"] == "repo://glm52-serving-results/prepare-model/model-cache.json"
    assert sglang_config.resolved_paths["preparation"]["sglang_venv_record"] == str(
        tmp_path / "repo" / "glm52-serving-results" / "prepare-venv" / "sglang-venv.json"
    )
    assert sglang_config.resolved_paths["preparation"]["model_cache_record"] == str(
        tmp_path / "repo" / "glm52-serving-results" / "prepare-model" / "model-cache.json"
    )


def test_materialize_sglang_slice_keeps_active_moe_runner_profile(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    active_sglang_config = repo / ".scratch" / "glm52-local-serving" / "config" / "sglang-local.yaml"
    active_sglang_config.parent.mkdir(parents=True)
    active_sglang_config.write_text(
        (Path(__file__).resolve().parents[2] / ".scratch" / "glm52-local-serving" / "config" / "sglang-local.yaml").read_text()
    )
    config = materialized_config_for_test(tmp_path)

    sglang_config = glm52_inference_runtime._materialize_sglang_slice(config)

    assert sglang_config.runtime["extra_args"][-2:] == ["--moe-runner-backend", "triton"]
    assert "--moe-runner-backend" in sglang_config.launch["inner_argv"]
    assert sglang_config.launch["inner_argv"][-2:] == ["--moe-runner-backend", "triton"]


def test_dynamo_argv_rejects_disallowed_upstream_port(tmp_path: Path) -> None:
    declared_path = write_text(
        tmp_path / "inference.yaml",
        VALID_INFERENCE.replace(
            "upstream_ref: component://sglang_backend/openai_base_url",
            "upstream_ref: http://127.0.0.1:8000/v1",
        ),
    )

    with pytest.raises(InferenceConfigError, match="must use component refs"):
        load_declared_inference_spec(declared_path)


def test_launch_dynamo_component_writes_process_record(tmp_path: Path, monkeypatch) -> None:
    base_config = materialized_config_for_test(tmp_path)
    fake_frontend = FakeProcess(pid=5555)
    fake_worker = FakeProcess(pid=5556)
    popen_calls: list[list[str]] = []

    def fake_popen(argv, **kwargs):
        popen_calls.append(argv)
        assert kwargs["start_new_session"] is True
        assert kwargs["env"]["DYN_FILE_KV"].endswith("components/dynamo/file-kv")
        if argv == config.components["dynamo_frontend"]["argv"]:
            assert "--http-port" in argv
            return fake_frontend
        if argv == config.components["dynamo_frontend"]["worker_argv"]:
            assert "dyn://glm52.backend.generate" in argv
            return fake_worker
        raise AssertionError(f"unexpected argv: {argv}")

    config = base_config

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        glm52_inference_runtime,
        "validate_dynamo_prerequisite",
        lambda config: {"status": "ok", "reason": "python_module_importable"},
    )
    monkeypatch.setattr(glm52_inference_runtime, "wait_for_dynamo_readiness", lambda config, processes: {"models": {}, "chat": {}})

    result = glm52_inference_runtime.launch_dynamo_component(config)

    assert result["ok"] is True
    assert popen_calls == [
        config.components["dynamo_frontend"]["worker_argv"],
        config.components["dynamo_frontend"]["argv"],
    ]
    assert result["processes"]["worker"]["pid"] == 5556
    assert result["processes"]["frontend"]["pid"] == 5555
    assert result["processes"]["worker"]["env"]["DYN_FILE_KV"].endswith("components/dynamo/file-kv")
    assert result["processes"]["frontend"]["env"]["DYN_FILE_KV"].endswith("components/dynamo/file-kv")
    worker_record_path = (
        Path(__file__).resolve().parents[2]
        / "glm52-serving-results"
        / config.run_id
        / "components"
        / "dynamo"
        / "worker-process.json"
    )
    assert worker_record_path.exists()
    assert result["probe"] == {"models": {}, "chat": {}}


def test_teardown_dynamo_component_stops_worker_and_frontend_records(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    component = config.components["dynamo_frontend"]
    frontend_path = Path(__file__).resolve().parents[2] / component["process_record"].removeprefix("repo://")
    worker_path = Path(__file__).resolve().parents[2] / component["worker_process_record"].removeprefix("repo://")
    glm52_inference_runtime.write_process_record(
        frontend_path,
        run_id=config.run_id,
        component="dynamo_frontend",
        process=FakeProcess(pid=5560),
        argv=component["argv"],
        endpoint_url=component["openai_base_url"],
    )
    glm52_inference_runtime.write_process_record(
        worker_path,
        run_id=config.run_id,
        component="dynamo_worker",
        process=FakeProcess(pid=5561),
        argv=component["worker_argv"],
        endpoint_url=component["openai_base_url"],
    )
    killed: list[int] = []

    monkeypatch.setattr(glm52_inference_runtime.os, "killpg", lambda pgid, _signal: killed.append(pgid))
    monkeypatch.setattr(glm52_inference_runtime, "prove_port_closed", lambda host, port: {"host": host, "port": port, "closed": True})

    result = glm52_inference_runtime.teardown_component(config, "dynamo_frontend")

    assert result["ok"] is True
    assert result["processes"]["worker"]["stop_reason"] == "teardown"
    assert result["processes"]["frontend"]["stop_reason"] == "teardown"
    assert len(killed) == 2
    assert json.loads(worker_path.read_text())["stop_reason"] == "teardown"
    assert json.loads(frontend_path.read_text())["stop_reason"] == "teardown"


def test_launch_dynamo_component_tears_down_worker_and_frontend_after_probe_failure(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    component = config.components["dynamo_frontend"]
    frontend_path = Path(__file__).resolve().parents[2] / component["process_record"].removeprefix("repo://")
    worker_path = Path(__file__).resolve().parents[2] / component["worker_process_record"].removeprefix("repo://")
    fake_frontend = FakeProcess(pid=5562)
    fake_worker = FakeProcess(pid=5563)
    killed: list[int] = []

    def fake_popen(argv, **kwargs):
        if argv == component["worker_argv"]:
            return fake_worker
        if argv == component["argv"]:
            return fake_frontend
        raise AssertionError(f"unexpected argv: {argv}")

    def fail_probe(_config, _processes):
        raise InferenceLaunchError("dynamo probe failed")

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        glm52_inference_runtime,
        "validate_dynamo_prerequisite",
        lambda config: {"status": "ok", "reason": "python_module_importable"},
    )
    monkeypatch.setattr(glm52_inference_runtime, "wait_for_dynamo_readiness", fail_probe)
    monkeypatch.setattr(glm52_inference_runtime.os, "killpg", lambda pgid, _signal: killed.append(pgid))

    with pytest.raises(InferenceLaunchError, match="dynamo probe failed"):
        glm52_inference_runtime.launch_dynamo_component(config)

    assert len(killed) == 2
    assert json.loads(worker_path.read_text())["stop_reason"] == "launch_failed"
    assert json.loads(frontend_path.read_text())["stop_reason"] == "launch_failed"


def test_wait_for_dynamo_readiness_retries_connection_refused(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    attempts = []

    def fake_probe(_config):
        attempts.append(time.monotonic())
        if len(attempts) == 1:
            raise glm52_inference_runtime.glm52_serving_verifier.VerificationError("request failed: connection refused")
        return {"models": {"data": [{"id": "zai-org/GLM-5.2"}]}, "chat": {"content": "ok"}}

    monkeypatch.setattr(glm52_inference_runtime, "probe_dynamo_component", fake_probe)
    monkeypatch.setattr(glm52_inference_runtime.time, "sleep", lambda _seconds: None)

    result = glm52_inference_runtime.wait_for_dynamo_readiness(
        config,
        {"worker": FakeProcess(pid=5570), "frontend": FakeProcess(pid=5571)},
    )

    assert result["ok"] is True
    assert len(attempts) == 2
    readiness_path = Path(__file__).resolve().parents[2] / "glm52-serving-results" / config.run_id / "components" / "dynamo" / "readiness.json"
    payload = json.loads(readiness_path.read_text())
    assert payload["status"] == "ok"
    assert len(payload["attempts"]) == 2


def test_validate_dynamo_prerequisite_rejects_worker_help_import_failure(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.frontend"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                0,
                stdout="--http-host\n--http-port\n--model-name\n--dyn-chat-processor\n",
                stderr="",
            )
        if command[:3] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.sglang"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="ModuleNotFoundError: No module named 'sglang'\n",
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "run", fake_run)

    with pytest.raises(InferenceLaunchError, match="Dynamo prerequisite missing"):
        glm52_inference_runtime.launch_dynamo_component(config)

    assert commands == [
        [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.frontend", "--help"],
        [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.sglang", "--help"],
    ]
    environment_path = Path(__file__).resolve().parents[2] / "glm52-serving-results" / config.run_id / "components" / "dynamo" / "environment.json"
    payload = json.loads(environment_path.read_text())
    assert payload["status"] == "missing_prerequisite"
    assert payload["reason"] == "module_not_executable"
    assert payload["module"] == "dynamo.sglang"
    assert payload["popen_attempted"] is False


def test_launch_dynamo_component_rejects_placeholder_before_popen(tmp_path: Path, monkeypatch) -> None:
    base_config = materialized_config_for_test(tmp_path)
    config = replace_component_argv(
        base_config,
        "dynamo_frontend",
        [
            "python",
            "-m",
            "dynamo.frontend",
            "--host",
            "127.0.0.1",
            "--port",
            str(base_config.ports["dynamo_frontend"]),
            "--upstream-url",
            base_config.components["sglang_backend"]["openai_base_url"],
            "--model",
            base_config.components["dynamo_frontend"]["served_model_name"],
        ],
    )

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("Dynamo placeholder must fail before Popen")

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", forbidden_popen)

    with pytest.raises(InferenceLaunchError, match="Dynamo prerequisite missing"):
        glm52_inference_runtime.launch_dynamo_component(config)

    environment_path = (
        Path(__file__).resolve().parents[2]
        / "glm52-serving-results"
        / config.run_id
        / "components"
        / "dynamo"
        / "environment.json"
    )
    payload = json.loads(environment_path.read_text())
    assert payload["status"] == "missing_prerequisite"
    assert payload["reason"] == "placeholder_argv"
    assert payload["popen_attempted"] is False


def test_launch_dynamo_component_rejects_missing_module_before_popen(tmp_path: Path, monkeypatch) -> None:
    config = replace_component_argv(
        materialized_config_for_test(tmp_path),
        "dynamo_frontend",
        ["python", "-m", "missing_dynamo_frontend_for_test"],
    )

    def fake_run(command, **kwargs):
        return glm52_inference_runtime.subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="No module named missing_dynamo_frontend_for_test\n",
        )

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "run", fake_run)

    with pytest.raises(InferenceLaunchError, match="Dynamo prerequisite missing"):
        glm52_inference_runtime.launch_dynamo_component(config)

    environment_path = (
        Path(__file__).resolve().parents[2]
        / "glm52-serving-results"
        / config.run_id
        / "components"
        / "dynamo"
        / "environment.json"
    )
    payload = json.loads(environment_path.read_text())
    assert payload["status"] == "missing_prerequisite"
    assert payload["reason"] == "module_not_executable"
    assert payload["module"] == "missing_dynamo_frontend_for_test"
    assert payload["popen_attempted"] is False


def test_launch_dynamo_component_classifies_real_frontend_topology_as_nonexecutable_module(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert command[:2] == [config.components["dynamo_frontend"]["host_control_python"], "-m"]
        assert kwargs["text"] is True
        return glm52_inference_runtime.subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="No module named dynamo.frontend\n",
        )

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("missing Dynamo frontend package must fail before Popen")

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", forbidden_popen)

    with pytest.raises(InferenceLaunchError, match="Dynamo prerequisite missing"):
        glm52_inference_runtime.launch_dynamo_component(config)

    environment_path = (
        Path(__file__).resolve().parents[2]
        / "glm52-serving-results"
        / config.run_id
        / "components"
        / "dynamo"
        / "environment.json"
    )
    payload = json.loads(environment_path.read_text())
    assert payload["status"] == "missing_prerequisite"
    assert payload["reason"] == "module_not_executable"
    assert payload["module"] == "dynamo.frontend"
    assert payload["popen_attempted"] is False
    assert calls


def test_validate_dynamo_prerequisite_uses_host_control_python(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.frontend"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                0,
                stdout="--http-host\n--http-port\n--model-name\n--dyn-chat-processor\n",
                stderr="",
            )
        if command[:3] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.sglang"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                0,
                stdout="--model-path\n--served-model-name\n--device\n--host\n--port\n--disaggregation-mode\n",
                stderr="",
            )
        return glm52_inference_runtime.subprocess.CompletedProcess(
            command,
            0,
            stdout="help\n",
            stderr="",
        )

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "run", fake_run)

    payload = glm52_inference_runtime.validate_dynamo_prerequisite(config)

    assert payload["status"] == "ok"
    assert payload["reason"] == "python_modules_executable"
    assert payload["python"] == config.components["dynamo_frontend"]["host_control_python"]
    assert payload["checks"]["dynamo.frontend"]["ok"] is True
    assert payload["checks"]["dynamo.sglang"]["ok"] is True
    assert payload["checks"]["dynamo.sglang"]["required_flags_present"] == [
        "--model-path",
        "--served-model-name",
        "--device",
        "--host",
        "--port",
        "--disaggregation-mode",
    ]
    assert commands[0] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.frontend", "--help"]
    assert commands[1] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.sglang", "--help"]


def test_validate_dynamo_prerequisite_rejects_worker_help_missing_required_flag(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)

    def fake_run(command, **kwargs):
        if command[:3] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.frontend"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                0,
                stdout="--http-host\n--http-port\n--model-name\n--dyn-chat-processor\n",
                stderr="",
            )
        if command[:3] == [config.components["dynamo_frontend"]["host_control_python"], "-m", "dynamo.sglang"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                0,
                stdout="--model-path\n--device\n--host\n--port\n--disaggregation-mode\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "run", fake_run)

    with pytest.raises(InferenceLaunchError, match="Dynamo prerequisite missing"):
        glm52_inference_runtime.launch_dynamo_component(config)

    environment_path = Path(__file__).resolve().parents[2] / "glm52-serving-results" / config.run_id / "components" / "dynamo" / "environment.json"
    payload = json.loads(environment_path.read_text())
    assert payload["status"] == "missing_prerequisite"
    assert payload["reason"] == "module_help_contract_mismatch"
    assert payload["module"] == "dynamo.sglang"
    assert payload["missing_flags"] == ["--served-model-name"]
    assert payload["popen_attempted"] is False


def test_prepare_dynamo_venv_creates_run_owned_venv_and_records_module_probes(tmp_path: Path) -> None:
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
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command == ["uv", "--version"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(command, 0, stdout="uv 0.8.0\n", stderr="")
        if command[0:2] == ["uv", "venv"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(command, 0, stdout="created\n", stderr="")
        if command[0:3] == ["uv", "pip", "install"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(command, 0, stdout="installed\n", stderr="")
        if command[1:3] == ["-m", "dynamo.frontend"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                0,
                stdout="--http-host\n--http-port\n--model-name\n--dyn-chat-processor\n",
                stderr="",
            )
        if command[1:3] == ["-m", "dynamo.sglang"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(
                command,
                0,
                stdout="--model-path\n--served-model-name\n--device\n--host\n--port\n--disaggregation-mode\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    record = prepare_dynamo_venv(
        declared_path=declared_path,
        local_environment_path=local_env_path,
        run_id="prepare-dynamo-test",
        run=fake_run,
    )

    expected_venv = "/workspace/monarch/scripts/rootfs/cache/glm52-local-serving/glm52/venvs/dynamo"
    expected_python = str(Path(expected_venv) / "bin" / "python")
    assert commands[0] == ["uv", "--version"]
    assert commands[1] == ["uv", "venv", "--python", sys.executable, expected_venv]
    assert commands[2] == [
        "uv",
        "pip",
        "install",
        "--python",
        expected_python,
        "ai-dynamo==1.4.0",
        "ai-dynamo-runtime==1.4.0",
        "sglang==0.5.17",
        "blake3",
    ]
    assert commands[3] == [expected_python, "-m", "dynamo.frontend", "--help"]
    assert commands[4] == [expected_python, "-m", "dynamo.sglang", "--help"]
    assert record["venv"]["path"] == "cache://glm52/venvs/dynamo"
    assert record["venv"]["python"] == expected_python
    assert record["packages"] == ["ai-dynamo==1.4.0", "ai-dynamo-runtime==1.4.0", "sglang==0.5.17", "blake3"]
    assert record["tools"]["uv"]["ok"] is True
    assert record["checks"]["modules"]["dynamo.frontend"]["ok"] is True
    assert record["checks"]["modules"]["dynamo.sglang"]["ok"] is True


def test_prepare_dynamo_venv_rejects_missing_rootfs_tool_before_install(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", local_env_text(tmp_path))
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command == ["uv", "--version"]:
            return glm52_inference_runtime.subprocess.CompletedProcess(command, 127, stdout="", stderr="uv: command not found\n")
        raise AssertionError(f"unexpected command after missing tool: {command}")

    with pytest.raises(InferenceLaunchError, match="required rootfs tool failed: uv"):
        prepare_dynamo_venv(
            declared_path=declared_path,
            local_environment_path=local_env_path,
            run_id="prepare-dynamo-missing-tool",
            run=fake_run,
        )

    assert commands == [["uv", "--version"]]


def test_teardown_sglang_component_uses_exact_child_materialized_config(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    child_materialized = tmp_path / "repo" / "glm52-serving-results" / "run-test-sglang" / "materialized-sglang-runtime.yaml"
    child_materialized.parent.mkdir(parents=True)
    child_materialized.write_text("schema_version: 1\n")
    config.components["sglang_backend"]["materialized_config"] = "repo://glm52-serving-results/run-test-sglang/materialized-sglang-runtime.yaml"
    loaded_paths = []

    def fake_load_materialized_sglang_runtime(path):
        loaded_paths.append(path)
        return {"loaded": str(path)}

    monkeypatch.setattr(glm52_inference_runtime.glm52_sglang_runtime, "load_materialized_config", fake_load_materialized_sglang_runtime)
    monkeypatch.setattr(
        glm52_inference_runtime.glm52_sglang_runtime,
        "load_local_environment",
        lambda path: SimpleNamespace(repo=str(tmp_path / "repo"), cache=str(tmp_path / "cache"), temp=str(tmp_path / "tmp")),
    )
    monkeypatch.setattr(
        glm52_inference_runtime.glm52_sglang_runtime,
        "teardown_runtime",
        lambda sglang_config, *, local_environment: {"stopped": sglang_config, "local": local_environment},
    )

    result = glm52_inference_runtime.teardown_component(config, "sglang_backend")

    assert result["ok"] is True
    assert loaded_paths == [child_materialized]


def test_launch_dynamo_component_rejects_unsupported_frontend_flags_before_popen(tmp_path: Path, monkeypatch) -> None:
    config = replace_component_argv(
        materialized_config_for_test(tmp_path),
        "dynamo_frontend",
        ["python", "-m", "real_dynamo.frontend", "--upstream-url", "http://127.0.0.1:19000/v1"],
    )

    def fake_run(command, **kwargs):
        return glm52_inference_runtime.subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"ok": True, "module": "real_dynamo.frontend", "origin": "/venv/frontend.py"}) + "\n",
            stderr="",
        )

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("unsupported Dynamo frontend flags must fail before Popen")

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", forbidden_popen)

    with pytest.raises(InferenceLaunchError, match="Dynamo prerequisite missing"):
        glm52_inference_runtime.launch_dynamo_component(config)

    environment_path = (
        Path(__file__).resolve().parents[2]
        / "glm52-serving-results"
        / config.run_id
        / "components"
        / "dynamo"
        / "environment.json"
    )
    payload = json.loads(environment_path.read_text())
    assert payload["status"] == "missing_prerequisite"
    assert payload["reason"] == "unsupported_argv_flag"
    assert payload["flag"] == "--upstream-url"
    assert payload["popen_attempted"] is False


def test_probe_dynamo_component_requires_model_identity(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)

    class FakeClient:
        def __init__(self, api_key=None, timeout_seconds=300.0):
            pass

        def get_json(self, url):
            return {"data": [{"id": "wrong-model"}]}

    monkeypatch.setattr(glm52_inference_runtime.glm52_serving_verifier, "JsonHttpClient", FakeClient)

    with pytest.raises(InferenceLaunchError, match="Dynamo /models did not advertise served model"):
        glm52_inference_runtime.probe_dynamo_component(config)


def test_responses_adapter_argv_uses_materialized_dynamo_url(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path)
    argv = config.components["responses_adapter"]["argv"]

    assert "--chat-base-url" in argv
    assert config.components["dynamo_frontend"]["openai_base_url"] in argv
    assert "8080" not in argv
    assert "http://127.0.0.1:8000/v1" not in argv


def test_launch_responses_adapter_writes_process_record(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    fake = FakeProcess(pid=6666)

    def fake_popen(argv, **kwargs):
        assert "scripts/glm52_responses_adapter.py" in argv
        assert "--port" in argv
        assert str(config.ports["responses_adapter"]) in argv
        assert kwargs["start_new_session"] is True
        return fake

    monkeypatch.setattr(glm52_inference_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        glm52_inference_runtime,
        "probe_responses_adapter_component",
        lambda config: {"models": {}, "nonstream": {}, "stream": {}, "tool_call": {}},
    )

    result = glm52_inference_runtime.launch_responses_adapter_component(config)

    assert result["ok"] is True
    assert result["process"]["component"] == "responses_adapter"


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


def test_run_one_inference_cycle_launches_and_tears_down_in_order(tmp_path: Path, monkeypatch) -> None:
    base_config = materialized_config_for_test(tmp_path)
    config = replace_component_argv(
        base_config,
        "dynamo_frontend",
        [
            "real-dynamo-frontend",
            "--upstream-url",
            base_config.components["sglang_backend"]["openai_base_url"],
        ],
    )
    events = []

    monkeypatch.setattr(glm52_inference_runtime.shutil, "which", lambda executable: f"/usr/bin/{executable}")
    monkeypatch.setattr(glm52_inference_runtime, "launch_sglang_component", lambda config: events.append("launch-sglang") or {"ok": True})
    monkeypatch.setattr(glm52_inference_runtime, "launch_dynamo_component", lambda config: events.append("launch-dynamo") or {"ok": True})
    monkeypatch.setattr(
        glm52_inference_runtime,
        "launch_responses_adapter_component",
        lambda config: events.append("launch-responses") or {"ok": True},
    )
    monkeypatch.setattr(
        glm52_inference_runtime,
        "teardown_component",
        lambda config, component: events.append(f"teardown-{component}") or {"ok": True},
    )
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


def test_run_one_inference_cycle_tears_down_after_dynamo_failure(tmp_path: Path, monkeypatch) -> None:
    base_config = materialized_config_for_test(tmp_path)
    config = replace_component_argv(
        base_config,
        "dynamo_frontend",
        [
            "real-dynamo-frontend",
            "--upstream-url",
            base_config.components["sglang_backend"]["openai_base_url"],
        ],
    )
    events = []

    monkeypatch.setattr(glm52_inference_runtime.shutil, "which", lambda executable: f"/usr/bin/{executable}")
    monkeypatch.setattr(glm52_inference_runtime, "launch_sglang_component", lambda config: events.append("launch-sglang") or {"ok": True})

    def fail_dynamo(config):
        events.append("launch-dynamo")
        raise InferenceLaunchError("dynamo failed")

    monkeypatch.setattr(glm52_inference_runtime, "launch_dynamo_component", fail_dynamo)
    monkeypatch.setattr(
        glm52_inference_runtime,
        "teardown_component",
        lambda config, component: events.append(f"teardown-{component}") or {"ok": True},
    )

    with pytest.raises(InferenceLaunchError, match="dynamo failed"):
        glm52_inference_runtime.run_one_inference_cycle(config)

    assert "teardown-sglang_backend" in events


def test_run_one_inference_cycle_rejects_missing_dynamo_before_sglang_launch(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path, run_id="run-test-missing-dynamo-before-sglang")

    def forbidden_launch_sglang(config):
        raise AssertionError("missing Dynamo prerequisite must fail before SGLang launch")

    monkeypatch.setattr(glm52_inference_runtime, "launch_sglang_component", forbidden_launch_sglang)

    with pytest.raises(InferenceLaunchError, match="Dynamo prerequisite missing"):
        glm52_inference_runtime.run_one_inference_cycle(config)

    environment_path = (
        Path(__file__).resolve().parents[2]
        / "glm52-serving-results"
        / config.run_id
        / "components"
        / "dynamo"
        / "environment.json"
    )
    payload = json.loads(environment_path.read_text())
    assert payload["status"] == "missing_prerequisite"
    assert payload["reason"] == "module_not_executable"
    assert payload["module"] in {"dynamo.frontend", "dynamo.sglang"}


def test_run_repeatability_cycles_rejects_false_cycle(tmp_path: Path, monkeypatch) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", local_env_text(tmp_path))
    monkeypatch.setattr(glm52_inference_runtime, "run_one_inference_cycle", lambda config: {"ok": False})

    with pytest.raises(InferenceLaunchError, match="cycle 1 returned ok=false"):
        glm52_inference_runtime.run_repeatability_cycles(
            declared_path=declared_path,
            local_environment_path=local_env_path,
            run_id="repeat-fail",
            cycles=1,
        )


def test_run_repeatability_cycles_writes_benchmark_ready_parent_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", local_env_text(tmp_path))

    def fake_run_one_inference_cycle(config):
        return {
            "ok": True,
            "run_id": config.run_id,
            "components": {
                "sglang_backend": {
                    "result": {"process": {"pid": 111}},
                    "probe": {"chat": {"text": "glm"}},
                },
                "dynamo_frontend": {"probe": {"chat": {"text": "dynamo"}}},
                "responses_adapter": {
                    "process": {"endpoint_url": "http://127.0.0.1:19002/v1"},
                    "probe": {
                        "nonstream": {"output_text": "nonstream"},
                        "stream": {"output_text": "stream"},
                        "tool_call": {"name": "calculator"},
                    }
                },
            },
            "teardown": {
                "responses_adapter": {"ok": True},
                "dynamo_frontend": {"ok": True},
                "sglang_backend": {"ok": True},
            },
            "clean": {
                "ok": True,
                "ports": {
                    "sglang_backend": {"closed": True},
                    "dynamo_frontend": {"closed": True},
                    "responses_adapter": {"closed": True},
                },
                "orphan_scan": {"ok": True},
            },
        }

    monkeypatch.setattr(glm52_inference_runtime, "run_one_inference_cycle", fake_run_one_inference_cycle)

    summary = glm52_inference_runtime.run_repeatability_cycles(
        declared_path=declared_path,
        local_environment_path=local_env_path,
        run_id="repeat-parent-manifest",
        cycles=3,
    )

    manifest_path = Path(summary["parent_manifest"])
    audit = audit_parent_manifest(manifest_path)
    assert audit["status"] == "completed"
    assert audit["run_id"] == "repeat-parent-manifest"
    assert audit["responses_base_url"].endswith("/v1")
    assert json.loads(manifest_path.read_text())["repeatability"]["cycle_count"] == 3


def test_cli_repeatability_dry_run_writes_summary(tmp_path: Path) -> None:
    declared_path = write_text(tmp_path / "inference.yaml", VALID_INFERENCE)
    local_env_path = write_text(tmp_path / "local-env.yaml", local_env_text(tmp_path))

    rc = glm52_inference_runtime.main(
        [
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
        ]
    )

    assert rc == 0


def test_cli_audit_parent_manifest_accepts_completed_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "parent-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "parent-run",
                "model": "zai-org/GLM-5.2",
                "evidence_level": "benchmark-ready",
                "completed_responses_base_url": "http://127.0.0.1:19002/v1",
                "repeatability": {"cycle_count": 3, "ok": True},
                "components": {
                    "sglang_backend": {"evidence_level": "completion", "chat": {"text": "ok"}},
                    "dynamo_frontend": {"evidence_level": "completion", "chat": {"text": "ok"}},
                    "responses_adapter": {
                        "evidence_level": "completion",
                        "nonstream": {"output_text": "ok"},
                        "stream": {"output_text": "ok"},
                        "tool_call": {"name": "calculator"},
                    },
                },
                "teardown": {"ok": True, "port_closure": {"ok": True}, "orphan_scan": {"ok": True}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    rc = glm52_inference_runtime.main(["audit-parent-manifest", "--manifest", str(manifest_path)])

    assert rc == 0


def test_cli_launch_runs_materialized_cycle(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    config_path = tmp_path / "materialized.yaml"
    write_materialized_inference_config(config, config_path)
    launched: list[str] = []

    def fake_run_one_inference_cycle(loaded_config):
        launched.append(loaded_config.run_id)
        return {"ok": True, "run_id": loaded_config.run_id}

    monkeypatch.setattr(glm52_inference_runtime, "run_one_inference_cycle", fake_run_one_inference_cycle)

    rc = glm52_inference_runtime.main(
        [
            "launch",
            "--materialized-config",
            str(config_path),
        ]
    )

    assert rc == 0
    assert launched == [config.run_id]


def test_cli_teardown_runs_materialized_component_teardown(tmp_path: Path, monkeypatch) -> None:
    config = materialized_config_for_test(tmp_path)
    config_path = tmp_path / "materialized.yaml"
    write_materialized_inference_config(config, config_path)
    torn_down: list[tuple[str, str]] = []

    def fake_teardown_component(loaded_config, component):
        torn_down.append((loaded_config.run_id, component))
        return {"ok": True, "component": component}

    monkeypatch.setattr(glm52_inference_runtime, "teardown_component", fake_teardown_component)

    rc = glm52_inference_runtime.main(
        [
            "teardown",
            "--materialized-config",
            str(config_path),
            "--component",
            "responses_adapter",
        ]
    )

    assert rc == 0
    assert torn_down == [(config.run_id, "responses_adapter")]


def test_audit_parent_manifest_accepts_completed_glm_responses_url(tmp_path: Path) -> None:
    manifest_path = tmp_path / "parent-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "parent-run",
                "model": "zai-org/GLM-5.2",
                "evidence_level": "benchmark-ready",
                "completed_responses_base_url": "http://127.0.0.1:19002/v1",
                "repeatability": {"cycle_count": 3, "ok": True},
                "components": {
                    "sglang_backend": {"evidence_level": "completion", "chat": {"text": "ok"}},
                    "dynamo_frontend": {"evidence_level": "completion", "chat": {"text": "ok"}},
                    "responses_adapter": {
                        "evidence_level": "completion",
                        "nonstream": {"output_text": "ok"},
                        "stream": {"output_text": "ok"},
                        "tool_call": {"name": "calculator"},
                    },
                },
                "teardown": {"ok": True, "port_closure": {"ok": True}, "orphan_scan": {"ok": True}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    audit = audit_parent_manifest(manifest_path)

    assert audit["status"] == "completed"
    assert audit["run_id"] == "parent-run"
    assert audit["responses_base_url"] == "http://127.0.0.1:19002/v1"
    assert audit["evidence_level"] == "benchmark-ready"


def test_audit_parent_manifest_rejects_models_only_or_default_port(tmp_path: Path) -> None:
    manifest_path = tmp_path / "parent-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "parent-run",
                "model": "zai-org/GLM-5.2",
                "evidence_level": "benchmark-ready",
                "completed_responses_base_url": "http://127.0.0.1:8080/v1",
                "repeatability": {"cycle_count": 3, "ok": True},
                "components": {
                    "sglang_backend": {"evidence_level": "readiness", "models": {"data": []}},
                    "dynamo_frontend": {"evidence_level": "completion", "chat": {"text": "ok"}},
                    "responses_adapter": {
                        "evidence_level": "completion",
                        "nonstream": {"output_text": "ok"},
                        "stream": {"output_text": "ok"},
                        "tool_call": {"name": "calculator"},
                    },
                },
                "teardown": {"ok": True, "port_closure": {"ok": True}, "orphan_scan": {"ok": True}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    with pytest.raises(InferenceConfigError, match="disallowed Responses port"):
        audit_parent_manifest(manifest_path)


def test_inference_runtime_wrapper_is_host_controlled() -> None:
    wrapper = Path(__file__).resolve().parents[2] / "scripts" / "run_glm52_inference_runtime.sh"
    text = wrapper.read_text()

    assert 'exec "${PYTHON_BIN}"' in text
    assert "scripts/run" not in text
