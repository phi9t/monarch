#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


def _load_script_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise InferenceConfigError(f"cannot load helper module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DISALLOWED_PORTS = {8000, 8080, 18080}
COMPONENT_ORDER = ["sglang_backend", "dynamo_frontend", "responses_adapter"]
DEFAULT_MODEL = "zai-org/GLM-5.2"
DYNAMO_SGLANG_PACKAGES = ["ai-dynamo==1.4.0", "ai-dynamo-runtime==1.4.0", "sglang==0.5.17", "blake3"]
GLM52_RUNTIME_DEPENDENCY_GROUP = "glm52-runtime"
GLM52_RUNTIME_LOCKFILE_REF = "repo://uv.lock"
DYNAMO_REQUIRED_HELP_FLAGS = {
    "dynamo.frontend": ["--http-host", "--http-port", "--model-name", "--dyn-chat-processor"],
    "dynamo.sglang": ["--model-path", "--served-model-name", "--device", "--host", "--port", "--disaggregation-mode"],
}
REPO_ROOT = Path(__file__).resolve().parents[1]
glm52_sglang_runtime = _load_script_module("glm52_sglang_runtime", REPO_ROOT / "scripts" / "glm52_sglang_runtime.py")
glm52_serving_verifier = _load_script_module("glm52_serving_verifier", REPO_ROOT / "scripts" / "glm52_serving_verifier.py")
DYNAMO_FRONTEND_SUPPORTED_FLAGS = {
    "--discovery-backend",
    "--dump-config-to",
    "--dyn-chat-processor",
    "--dyn-debug-perf",
    "--dyn-preprocess-workers",
    "--enable-anthropic-api",
    "--enable-streaming-reasoning-dispatch",
    "--enable-streaming-tool-dispatch",
    "--exclude-tools-when-tool-choice-none",
    "--frontend-route-extension",
    "--grpc-metrics-port",
    "--http-host",
    "--http-port",
    "--interactive",
    "--kserve-grpc-server",
    "--kv-cache-block-size",
    "--metrics-prefix",
    "--migration-limit",
    "--migration-max-seq-len",
    "--model-name",
    "--model-path",
    "--namespace",
    "--namespace-prefix",
    "--request-plane",
    "--serve-indexer",
    "--strip-anthropic-preamble",
    "--tls-cert-path",
    "--tls-key-path",
    "--tokenizer",
    "--trust-remote-code",
    "--version",
}


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


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        payload = yaml.safe_load(handle)
    return _require_mapping(payload, str(path))


def load_declared_inference_spec(path: Path) -> DeclaredInferenceSpec:
    data = load_yaml_mapping(path)
    _reject_unknown(
        data,
        {
            "schema_version",
            "run_group",
            "fail_fast",
            "allow_fallback",
            "ports",
            "components",
            "probes",
            "repeatability",
            "teardown",
        },
        str(path),
    )
    schema_version = _required_int(data, "schema_version", str(path))
    if schema_version != 1:
        raise InferenceConfigError("schema_version must be 1")
    fail_fast = _required_bool(data, "fail_fast", str(path))
    if not fail_fast:
        raise InferenceConfigError("fail_fast must be true")
    allow_fallback = _required_bool(data, "allow_fallback", str(path))
    if allow_fallback:
        raise InferenceConfigError("allow_fallback must be false")
    return DeclaredInferenceSpec(
        schema_version=schema_version,
        run_group=_required_str(data, "run_group", str(path)),
        fail_fast=fail_fast,
        allow_fallback=allow_fallback,
        ports=_parse_ports(data.get("ports")),
        components=_parse_components(data.get("components")),
        probes=_require_mapping(data.get("probes"), "probes"),
        repeatability=_require_mapping(data.get("repeatability"), "repeatability"),
        teardown=_require_mapping(data.get("teardown"), "teardown"),
    )


def materialize_inference_config(
    *,
    declared: DeclaredInferenceSpec,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
) -> MaterializedInferenceConfig:
    local_environment = glm52_sglang_runtime.load_local_environment(local_environment_path)
    used_ports: set[int] = set()
    ports = {component: _allocate_port(declared.ports, used_ports) for component in COMPONENT_ORDER}
    run_dir = f"repo://glm52-serving-results/{run_id}"
    sglang_url = f"http://{declared.ports.bind_host}:{ports['sglang_backend']}/v1"
    dynamo_url = f"http://{declared.ports.bind_host}:{ports['dynamo_frontend']}/v1"
    responses_url = f"http://{declared.ports.bind_host}:{ports['responses_adapter']}/v1"
    model_name = DEFAULT_MODEL
    dynamo_file_kv_root = _resolve_local_path_ref(local_environment, f"{run_dir}/components/dynamo/file-kv")
    dynamo_topology = declared.components["dynamo_frontend"]["topology"]
    dynamo_venv = _rootfs_projected_cache_path(dynamo_topology, local_environment)
    dynamo_python = str(Path(dynamo_venv) / "bin" / "python")
    dynamo_env = {
        "DYN_DISCOVERY_BACKEND": declared.components["dynamo_frontend"]["topology"]["discovery_backend"],
        "DYN_FILE_KV": dynamo_file_kv_root,
        "DYN_REQUEST_PLANE": declared.components["dynamo_frontend"]["topology"]["request_plane"],
    }
    components = {
        "sglang_backend": {
            "openai_base_url": sglang_url,
            "served_model_name": model_name,
            "declared_ref": declared.components["sglang_backend"]["declared_ref"],
            "required_records": declared.components["sglang_backend"]["required_records"],
            "process_record": f"{run_dir}/components/sglang/process.json",
            "materialized_config": f"{run_dir}-sglang/materialized-sglang-runtime.yaml",
        },
        "dynamo_frontend": {
            "execution_domain": "host_controlled",
            "openai_base_url": dynamo_url,
            "upstream_url": sglang_url,
            "served_model_name": model_name,
            "topology": dynamo_topology,
            "host_control_venv": dynamo_topology["host_control_venv"],
            "rootfs_cache_projection": dynamo_topology["rootfs_cache_projection"],
            "host_control_venv_resolved": dynamo_venv,
            "host_control_python": dynamo_python,
            "packages": list(dynamo_topology["packages"]),
            "rootfs_tools": list(dynamo_topology["rootfs_tools"]),
            "integration_contract": {
                "kind": "integrated_dynamo_sglang_worker",
                "http_bridge_to_external_sglang": False,
                "required_help_flags": DYNAMO_REQUIRED_HELP_FLAGS,
            },
            "env": dynamo_env,
            "argv": _dynamo_argv(
                declared.components["dynamo_frontend"],
                python=dynamo_python,
                host=declared.ports.bind_host,
                port=ports["dynamo_frontend"],
                model_name=model_name,
                run_dir=run_dir,
            ),
            "worker_argv": _dynamo_worker_argv(
                declared.components["dynamo_frontend"],
                python=dynamo_python,
                model_name=model_name,
            ),
            "process_record": f"{run_dir}/components/dynamo/process.json",
            "worker_process_record": f"{run_dir}/components/dynamo/worker-process.json",
        },
        "responses_adapter": {
            "execution_domain": "host_controlled",
            "openai_base_url": responses_url,
            "upstream_url": dynamo_url,
            "served_model_name": model_name,
            "timeout_seconds": declared.components["responses_adapter"]["timeout_seconds"],
            "argv": _responses_adapter_argv(
                host=declared.ports.bind_host,
                port=ports["responses_adapter"],
                upstream_url=dynamo_url,
                model_name=model_name,
                timeout_seconds=declared.components["responses_adapter"]["timeout_seconds"],
            ),
            "process_record": f"{run_dir}/components/responses-adapter/process.json",
        },
    }
    artifacts = {
        "summary": f"{run_dir}/summary.json",
        "port_allocation": f"{run_dir}/port-allocation.json",
        "teardown": f"{run_dir}/teardown",
    }
    return MaterializedInferenceConfig(
        schema_version=1,
        run_id=run_id,
        run_dir=run_dir,
        declared_path=str(declared_path),
        local_environment_path=str(local_environment_path),
        ports=ports,
        components=components,
        probes=declared.probes,
        repeatability=declared.repeatability,
        teardown=declared.teardown,
        artifacts=artifacts,
    )


def write_materialized_inference_config(config: MaterializedInferenceConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_config_to_mapping(config), sort_keys=False))


def load_materialized_inference_config(path: Path) -> MaterializedInferenceConfig:
    data = load_yaml_mapping(path)
    return MaterializedInferenceConfig(
        schema_version=_required_int(data, "schema_version", str(path)),
        run_id=_required_str(data, "run_id", str(path)),
        run_dir=_required_str(data, "run_dir", str(path)),
        declared_path=_required_str(data, "declared_path", str(path)),
        local_environment_path=_required_str(data, "local_environment_path", str(path)),
        ports=_require_str_int_mapping(data.get("ports"), "ports"),
        components=_require_component_mapping(data.get("components"), "components"),
        probes=_require_mapping(data.get("probes"), "probes"),
        repeatability=_require_mapping(data.get("repeatability"), "repeatability"),
        teardown=_require_mapping(data.get("teardown"), "teardown"),
        artifacts=_require_mapping(data.get("artifacts"), "artifacts"),
    )


def stable_json_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_process_record(
    path: Path,
    *,
    run_id: str,
    component: str,
    process: Any,
    argv: list[str],
    endpoint_url: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(process.pid, int) or process.pid <= 0:
        raise InferenceConfigError("process pid must be positive")
    try:
        process_group = os.getpgid(process.pid)
    except ProcessLookupError:
        process_group = process.pid
    record = {
        "run_id": run_id,
        "component": component,
        "pid": process.pid,
        "process_group": process_group,
        "argv": argv,
        "argv_digest": stable_json_digest(argv),
        "endpoint_url": endpoint_url,
        "created_at": _utc_stamp(),
    }
    if env is not None:
        record["env"] = env
        record["env_digest"] = stable_json_digest(env)
    validate_process_record(record, run_id=run_id, component=component)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def load_process_record(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise InferenceConfigError(f"invalid process record JSON: {path}") from error
    return _require_mapping(payload, str(path))


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
    argv = record.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) and item for item in argv):
        raise InferenceConfigError("process record argv must be a non-empty string list")
    endpoint_url = _required_str(record, "endpoint_url", "process record")
    port = _parsed_url_port(endpoint_url, "process record endpoint_url")
    if port in DISALLOWED_PORTS:
        raise InferenceConfigError("disallowed endpoint port")
    if record.get("argv_digest") != stable_json_digest(argv):
        raise InferenceConfigError("process record argv digest mismatch")
    _required_str(record, "created_at", "process record")


def prove_port_closed(host: str, port: int) -> dict[str, Any]:
    if _is_port_open(host, port):
        raise InferenceLaunchError(f"port still open: {host}:{port}")
    return {"host": host, "port": port, "closed": True}


def launch_sglang_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    sglang_slice = _materialize_sglang_slice(config)
    local_environment = glm52_sglang_runtime.load_local_environment(Path(config.local_environment_path))
    result = glm52_sglang_runtime.launch_runtime(sglang_slice, local_environment=local_environment)
    return {"ok": True, "component": "sglang_backend", "result": result}


def probe_sglang_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    sglang_slice = _materialize_sglang_slice(config)
    return {
        "models": glm52_sglang_runtime.probe_models(sglang_slice),
        "chat": glm52_sglang_runtime.probe_chat(sglang_slice),
    }


def launch_dynamo_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    component = config.components["dynamo_frontend"]
    preflight = validate_dynamo_prerequisite(config)
    stdout_path = _artifact_path(config, "components/dynamo/stdout.log")
    stderr_path = _artifact_path(config, "components/dynamo/stderr.log")
    process_record_path = _artifact_path_from_ref(config, component["process_record"])
    worker_record_path = _artifact_path_from_ref(config, component["worker_process_record"])
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    file_kv_root = Path(component["env"]["DYN_FILE_KV"])
    file_kv_root.mkdir(parents=True, exist_ok=True)
    process_env = {**os.environ, **component["env"]}
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        worker_process = subprocess.Popen(
            component["worker_argv"],
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            cwd=str(REPO_ROOT),
            env=process_env,
        )
        frontend_process = subprocess.Popen(
            component["argv"],
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            cwd=str(REPO_ROOT),
            env=process_env,
        )
    worker_record = write_process_record(
        worker_record_path,
        run_id=config.run_id,
        component="dynamo_worker",
        process=worker_process,
        argv=component["worker_argv"],
        endpoint_url=component["openai_base_url"],
        env=component["env"],
    )
    frontend_record = write_process_record(
        process_record_path,
        run_id=config.run_id,
        component="dynamo_frontend",
        process=frontend_process,
        argv=component["argv"],
        endpoint_url=component["openai_base_url"],
        env=component["env"],
    )
    try:
        probe = wait_for_dynamo_readiness(
            config,
            {"worker": worker_process, "frontend": frontend_process},
        )
    except Exception:
        _mark_and_stop_process_record(worker_record_path, worker_record, stop_reason="launch_failed")
        _mark_and_stop_process_record(process_record_path, frontend_record, stop_reason="launch_failed")
        raise
    return {
        "ok": True,
        "component": "dynamo_frontend",
        "environment": preflight,
        "processes": {
            "worker": worker_record,
            "frontend": frontend_record,
        },
        "probe": probe,
    }


def validate_dynamo_prerequisite(config: MaterializedInferenceConfig) -> dict[str, Any]:
    component = config.components["dynamo_frontend"]
    argv = component["argv"]
    if not isinstance(argv, list) or not all(isinstance(item, str) and item for item in argv):
        raise InferenceConfigError("Dynamo argv must be a non-empty string list")
    if _is_placeholder_dynamo_argv(argv):
        return _write_missing_dynamo_prerequisite(
            config,
            argv=argv,
            reason="placeholder_argv",
            message="Dynamo argv is still the placeholder python -m dynamo.frontend",
        )
    module_name = _python_module_from_argv(argv)
    if module_name is not None:
        unsupported = _unsupported_dynamo_frontend_flag(argv)
        if unsupported is not None:
            return _write_missing_dynamo_prerequisite(
                config,
                argv=argv,
                reason="unsupported_argv_flag",
                message=f"Dynamo frontend argv contains unsupported flag: {unsupported}",
                extra={"module": module_name, "flag": unsupported},
            )
        checks = {}
        for candidate in _required_dynamo_modules(config):
            module_probe = _probe_python_module_executable(argv[0], candidate)
            if module_probe.get("ok"):
                module_probe = _validate_module_help_contract(candidate, module_probe)
            checks[candidate] = module_probe
            if not module_probe.get("ok"):
                return _write_missing_dynamo_prerequisite(
                    config,
                    argv=argv,
                    reason="module_not_executable",
                    message=f"Dynamo Python module is not executable: {candidate}",
                    extra={
                        "module": candidate,
                        "python": argv[0],
                        "probe": module_probe,
                    },
                )
            if not module_probe.get("help_contract_ok", True):
                return _write_missing_dynamo_prerequisite(
                    config,
                    argv=argv,
                    reason="module_help_contract_mismatch",
                    message=f"Dynamo Python module help contract mismatch: {candidate}",
                    extra={
                        "module": candidate,
                        "python": argv[0],
                        "missing_flags": module_probe["required_flags_missing"],
                        "probe": module_probe,
                    },
                )
        return _write_dynamo_environment(
            config,
            {
                "status": "ok",
                "reason": "python_modules_executable",
                "checks": checks,
                "python": argv[0],
                "popen_attempted": False,
            },
        )
    executable = argv[0]
    if _resolve_executable(executable) is None:
        return _write_missing_dynamo_prerequisite(
            config,
            argv=argv,
            reason="missing_executable",
            message=f"Dynamo executable is not available in the host-control domain: {executable}",
            extra={"executable": executable},
        )
    return _write_dynamo_environment(
        config,
        {
            "status": "ok",
            "reason": "executable_available",
            "executable": executable,
            "resolved_executable": _resolve_executable(executable),
            "popen_attempted": False,
        },
    )


def probe_dynamo_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    component = config.components["dynamo_frontend"]
    model = component["served_model_name"]
    client = glm52_serving_verifier.JsonHttpClient(api_key=None, timeout_seconds=300.0)
    models = client.get_json(glm52_serving_verifier.join_url(component["openai_base_url"], "/models"))
    if not glm52_serving_verifier.model_list_contains(models, model):
        raise InferenceLaunchError("Dynamo /models did not advertise served model")
    chat = glm52_serving_verifier.run_chat_health(
        client,
        base_url=component["openai_base_url"],
        model=model,
        max_tokens=256,
    )
    return {"models": models, "chat": chat}


def wait_for_dynamo_readiness(
    config: MaterializedInferenceConfig,
    processes: dict[str, Any],
) -> dict[str, Any]:
    component = config.components["dynamo_frontend"]
    timeout_seconds = float(component.get("startup_timeout_seconds", 300))
    deadline = time.monotonic() + timeout_seconds
    attempts: list[dict[str, Any]] = []
    last_error = "not probed"
    while True:
        exited = {
            name: process.poll()
            for name, process in processes.items()
            if process.poll() is not None
        }
        if exited:
            payload = {
                "status": "failed",
                "reason": "process_exited",
                "run_id": config.run_id,
                "component": "dynamo_frontend",
                "exited": exited,
                "attempts": attempts,
                "created_at": _utc_stamp(),
            }
            _write_dynamo_readiness(config, payload)
            raise InferenceLaunchError(f"Dynamo process exited before readiness: {exited}")
        try:
            probe = probe_dynamo_component(config)
            payload = {
                "status": "ok",
                "run_id": config.run_id,
                "component": "dynamo_frontend",
                "attempts": [*attempts, {"status": "ok", "created_at": _utc_stamp()}],
                "probe": probe,
                "created_at": _utc_stamp(),
            }
            _write_dynamo_readiness(config, payload)
            return {"ok": True, **probe}
        except Exception as error:
            last_error = str(error)
            attempts.append({"status": "retry", "error": last_error, "created_at": _utc_stamp()})
            if time.monotonic() >= deadline:
                payload = {
                    "status": "failed",
                    "reason": "readiness_timeout",
                    "run_id": config.run_id,
                    "component": "dynamo_frontend",
                    "timeout_seconds": timeout_seconds,
                    "last_error": last_error,
                    "attempts": attempts,
                    "created_at": _utc_stamp(),
                }
                _write_dynamo_readiness(config, payload)
                raise InferenceLaunchError(f"Dynamo readiness timed out: {last_error}") from error
            time.sleep(2.0)


def launch_responses_adapter_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    component = config.components["responses_adapter"]
    stdout_path = _artifact_path(config, "components/responses-adapter/stdout.log")
    stderr_path = _artifact_path(config, "components/responses-adapter/stderr.log")
    process_record_path = _artifact_path_from_ref(config, component["process_record"])
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            component["argv"],
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            cwd=str(REPO_ROOT),
        )
    record = write_process_record(
        process_record_path,
        run_id=config.run_id,
        component="responses_adapter",
        process=process,
        argv=component["argv"],
        endpoint_url=component["openai_base_url"],
    )
    probe = probe_responses_adapter_component(config)
    return {"ok": True, "component": "responses_adapter", "process": record, "probe": probe}


def probe_responses_adapter_component(config: MaterializedInferenceConfig) -> dict[str, Any]:
    component = config.components["responses_adapter"]
    model = component["served_model_name"]
    client = glm52_serving_verifier.JsonHttpClient(api_key=None, timeout_seconds=300.0)
    models = client.get_json(glm52_serving_verifier.join_url(component["openai_base_url"], "/models"))
    if not glm52_serving_verifier.model_list_contains(models, model):
        raise InferenceLaunchError("Responses /models did not advertise served model")
    nonstream = glm52_serving_verifier.agent_run_json(
        glm52_serving_verifier.run_responses_agent(
            client,
            base_url=component["openai_base_url"],
            model=model,
            max_tokens=512,
            max_turns=8,
            stream=False,
        )
    )
    stream = glm52_serving_verifier.agent_run_json(
        glm52_serving_verifier.run_responses_agent(
            client,
            base_url=component["openai_base_url"],
            model=model,
            max_tokens=512,
            max_turns=8,
            stream=True,
        )
    )
    return {"models": models, "nonstream": nonstream, "stream": stream, "tool_call": stream}


def teardown_component(config: MaterializedInferenceConfig, component: str) -> dict[str, Any]:
    if component == "sglang_backend":
        local_environment = glm52_sglang_runtime.load_local_environment(Path(config.local_environment_path))
        materialized_ref = config.components["sglang_backend"].get("materialized_config")
        if materialized_ref:
            sglang_slice = glm52_sglang_runtime.load_materialized_config(
                Path(_resolve_local_path_ref(local_environment, materialized_ref))
            )
        else:
            sglang_slice = _materialize_sglang_slice(config)
        result = glm52_sglang_runtime.teardown_runtime(sglang_slice, local_environment=local_environment)
        return {"ok": True, "component": component, "result": result}
    if component in {"dynamo_frontend", "responses_adapter"}:
        return _teardown_host_controlled_component(config, component)
    raise InferenceConfigError(f"unsupported component teardown: {component}")


def prove_cycle_clean(config: MaterializedInferenceConfig) -> dict[str, Any]:
    ports = {
        component: prove_port_closed("127.0.0.1", port)
        for component, port in config.ports.items()
    }
    return {"ok": True, "ports": ports, "orphan_scan": {"ok": True, "checked": []}}


def prepare_dynamo_venv(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str = "prepare-dynamo-venv",
    run: Any | None = None,
) -> dict[str, Any]:
    declared = load_declared_inference_spec(declared_path)
    config = materialize_inference_config(
        declared=declared,
        declared_path=declared_path,
        local_environment_path=local_environment_path,
        run_id=run_id,
    )
    component = config.components["dynamo_frontend"]
    venv_ref = _required_str(component, "host_control_venv", "components.dynamo_frontend")
    venv_path = str(Path(component["host_control_python"]).parent.parent)
    python = component["host_control_python"]
    packages = _required_str_list(component, "packages", "components.dynamo_frontend")
    rootfs_tools = _required_str_list(component, "rootfs_tools", "components.dynamo_frontend")
    tool_checks = {
        tool: _verify_rootfs_tool(tool, run=run)
        for tool in rootfs_tools
    }
    create_command = ["uv", "venv", "--clear", "--python", sys.executable, venv_path]
    install_command = _locked_dependency_sync_command(python)
    commands = [
        _run_prepare_command(create_command, run=run),
        _run_prepare_command(install_command, run=run, env=_locked_dependency_sync_env(venv_path)),
    ]
    module_checks = {
        module: _validate_module_help_contract(module, _probe_python_module_executable(python, module, run=run))
        for module in ("dynamo.frontend", "dynamo.sglang")
    }
    for module, check in module_checks.items():
        if check.get("ok") is not True:
            raise InferenceLaunchError(f"Dynamo venv module probe failed: {module}")
        if check.get("help_contract_ok") is not True:
            raise InferenceLaunchError(f"Dynamo venv help contract failed: {module}")
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "venv": {
            "path": venv_ref,
            "resolved_path": venv_path,
            "python": python,
        },
        "packages": packages,
        "dependency_resolution": _locked_dependency_resolution_record(),
        "tools": tool_checks,
        "checks": {
            "modules": module_checks,
        },
        "commands": commands,
        "created_at": _utc_stamp(),
    }
    record_path = _artifact_path(config, "components/dynamo/dynamo-venv.json")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def run_one_inference_cycle(config: MaterializedInferenceConfig) -> dict[str, Any]:
    launched: list[str] = []
    cycle: dict[str, Any] = {"ok": False, "components": {}}
    try:
        cycle["components"]["dynamo_preflight"] = validate_dynamo_prerequisite(config)
        cycle["components"]["sglang_backend"] = launch_sglang_component(config)
        launched.append("sglang_backend")
        cycle["components"]["dynamo_frontend"] = launch_dynamo_component(config)
        launched.append("dynamo_frontend")
        cycle["components"]["responses_adapter"] = launch_responses_adapter_component(config)
        launched.append("responses_adapter")
        cycle["teardown"] = {}
        for component in reversed(launched):
            cycle["teardown"][component] = teardown_component(config, component)
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


def run_repeatability_cycles(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
    cycles: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    declared = load_declared_inference_spec(declared_path)
    cycle_count = cycles if cycles is not None else int(declared.repeatability.get("cycles", 1))
    if cycle_count <= 0:
        raise InferenceConfigError("repeatability cycles must be positive")

    summaries: list[dict[str, Any]] = []
    for index in range(1, cycle_count + 1):
        cycle_config = materialize_inference_config(
            declared=declared,
            declared_path=declared_path,
            local_environment_path=local_environment_path,
            run_id=f"{run_id}-cycle-{index}",
        )
        if dry_run:
            cycle_summary = {"ok": True, "dry_run": True, "materialized": _config_to_mapping(cycle_config)}
        else:
            cycle_summary = run_one_inference_cycle(cycle_config)
        if not cycle_summary.get("ok"):
            summary = _repeatability_summary(run_id=run_id, ok=False, cycles=[*summaries, cycle_summary], dry_run=dry_run)
            _write_repeatability_summary(run_id, summary)
            raise InferenceLaunchError(f"cycle {index} returned ok=false")
        summaries.append(cycle_summary)

    summary = _repeatability_summary(run_id=run_id, ok=True, cycles=summaries, dry_run=dry_run)
    _write_repeatability_summary(run_id, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Schema-driven GLM-5.2 end-to-end inference launcher")
    subcommands = parser.add_subparsers(dest="command", required=True)

    materialize = subcommands.add_parser("materialize")
    materialize.add_argument("--declared", type=Path, required=True)
    materialize.add_argument("--local-env", type=Path, required=True)
    materialize.add_argument("--run-id", required=True)
    materialize.add_argument("--output", type=Path, required=True)

    validate = subcommands.add_parser("validate")
    validate.add_argument("--materialized-config", type=Path, required=True)

    prepare_dynamo = subcommands.add_parser("prepare-dynamo-venv")
    prepare_dynamo.add_argument("--declared", type=Path, required=True)
    prepare_dynamo.add_argument("--local-env", type=Path, required=True)
    prepare_dynamo.add_argument("--run-id", default="prepare-dynamo-venv")

    launch = subcommands.add_parser("launch")
    launch.add_argument("--materialized-config", type=Path, required=True)

    teardown = subcommands.add_parser("teardown")
    teardown.add_argument("--materialized-config", type=Path, required=True)
    teardown.add_argument("--component", choices=COMPONENT_ORDER, required=True)

    repeatability = subcommands.add_parser("repeatability")
    repeatability.add_argument("--declared", type=Path, required=True)
    repeatability.add_argument("--local-env", type=Path, required=True)
    repeatability.add_argument("--run-id", required=True)
    repeatability.add_argument("--cycles", type=int)
    repeatability.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "materialize":
            declared = load_declared_inference_spec(args.declared)
            config = materialize_inference_config(
                declared=declared,
                declared_path=args.declared,
                local_environment_path=args.local_env,
                run_id=args.run_id,
            )
            write_materialized_inference_config(config, args.output)
            return 0
        if args.command == "validate":
            load_materialized_inference_config(args.materialized_config)
            return 0
        if args.command == "prepare-dynamo-venv":
            prepare_dynamo_venv(
                declared_path=args.declared,
                local_environment_path=args.local_env,
                run_id=args.run_id,
            )
            return 0
        if args.command == "launch":
            config = load_materialized_inference_config(args.materialized_config)
            run_one_inference_cycle(config)
            return 0
        if args.command == "teardown":
            config = load_materialized_inference_config(args.materialized_config)
            teardown_component(config, args.component)
            return 0
        if args.command == "repeatability":
            run_repeatability_cycles(
                declared_path=args.declared,
                local_environment_path=args.local_env,
                run_id=args.run_id,
                cycles=args.cycles,
                dry_run=args.dry_run,
            )
            return 0
        raise InferenceConfigError("command is not implemented yet")
    except (InferenceConfigError, InferenceLaunchError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


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


def _required_str_list(mapping: dict[str, Any], key: str, path: str) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise InferenceConfigError(f"{path}.{key} must be a list of non-empty strings")
    return value


def _logical_ref(value: str, path: str) -> str:
    if value.startswith("/") or "://" not in value:
        raise InferenceConfigError(f"{path} must use logical path refs")
    return value


def _rootfs_cache_projection(value: str, path: str) -> str:
    prefix = "/workspace/monarch/scripts/rootfs/cache/"
    if not value.startswith(prefix):
        raise InferenceConfigError(f"{path} must be under {prefix.rstrip('/')}")
    if "/../" in f"{value}/":
        raise InferenceConfigError(f"{path} must stay under the rootfs cache projection")
    return value


def _component_ref(value: str, path: str) -> str:
    if not value.startswith("component://"):
        raise InferenceConfigError(f"{path} must use component refs")
    return value


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
    _reject_unknown(sglang, {"enabled", "declared_ref", "required_records"}, "components.sglang_backend")
    _require_enabled(sglang, "components.sglang_backend")
    _logical_ref(_required_str(sglang, "declared_ref", "components.sglang_backend"), "components.sglang_backend.declared_ref")
    records = _require_mapping(sglang.get("required_records"), "components.sglang_backend.required_records")
    _reject_unknown(records, {"venv", "model_cache"}, "components.sglang_backend.required_records")
    _logical_ref(_required_str(records, "venv", "components.sglang_backend.required_records"), "components.sglang_backend.required_records.venv")
    _logical_ref(
        _required_str(records, "model_cache", "components.sglang_backend.required_records"),
        "components.sglang_backend.required_records.model_cache",
    )

    dynamo = _require_mapping(mapping["dynamo_frontend"], "components.dynamo_frontend")
    _reject_unknown(
        dynamo,
        {
            "enabled",
            "kind",
            "execution_domain",
            "bind_host",
            "upstream_ref",
            "model_name_ref",
            "config_root",
            "logs_root",
            "startup_timeout_seconds",
            "topology",
        },
        "components.dynamo_frontend",
    )
    _require_enabled(dynamo, "components.dynamo_frontend")
    _require_host_controlled(dynamo, "components.dynamo_frontend")
    _component_ref(_required_str(dynamo, "upstream_ref", "components.dynamo_frontend"), "components.dynamo_frontend.upstream_ref")
    _component_ref(_required_str(dynamo, "model_name_ref", "components.dynamo_frontend"), "components.dynamo_frontend.model_name_ref")
    _logical_ref(_required_str(dynamo, "config_root", "components.dynamo_frontend"), "components.dynamo_frontend.config_root")
    _logical_ref(_required_str(dynamo, "logs_root", "components.dynamo_frontend"), "components.dynamo_frontend.logs_root")
    _parse_dynamo_topology(dynamo.get("topology"))

    responses = _require_mapping(mapping["responses_adapter"], "components.responses_adapter")
    _reject_unknown(
        responses,
        {
            "enabled",
            "execution_domain",
            "bind_host",
            "upstream_ref",
            "model_name_ref",
            "logs_root",
            "startup_timeout_seconds",
            "timeout_seconds",
        },
        "components.responses_adapter",
    )
    _require_enabled(responses, "components.responses_adapter")
    _require_host_controlled(responses, "components.responses_adapter")
    _component_ref(_required_str(responses, "upstream_ref", "components.responses_adapter"), "components.responses_adapter.upstream_ref")
    _component_ref(_required_str(responses, "model_name_ref", "components.responses_adapter"), "components.responses_adapter.model_name_ref")
    _logical_ref(_required_str(responses, "logs_root", "components.responses_adapter"), "components.responses_adapter.logs_root")
    timeout_seconds = _required_int(responses, "timeout_seconds", "components.responses_adapter")
    if timeout_seconds <= 0:
        raise InferenceConfigError("components.responses_adapter.timeout_seconds must be positive")
    return mapping


def _require_enabled(mapping: dict[str, Any], path: str) -> None:
    if _required_bool(mapping, "enabled", path) is not True:
        raise InferenceConfigError(f"{path}.enabled must be true")


def _require_host_controlled(mapping: dict[str, Any], path: str) -> None:
    if _required_str(mapping, "execution_domain", path) != "host_controlled":
        raise InferenceConfigError(f"{path}.execution_domain must be host_controlled")


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


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _parse_dynamo_topology(value: Any) -> dict[str, Any]:
    topology = _require_mapping(value, "components.dynamo_frontend.topology")
    _reject_unknown(
        topology,
        {
            "mode",
            "package",
            "version",
            "discovery_backend",
            "request_plane",
            "namespace",
            "file_kv_root",
            "host_control_venv",
            "rootfs_cache_projection",
            "packages",
            "rootfs_tools",
            "frontend",
            "worker",
        },
        "components.dynamo_frontend.topology",
    )
    if _required_str(topology, "mode", "components.dynamo_frontend.topology") != "local_frontend_worker":
        raise InferenceConfigError("components.dynamo_frontend.topology.mode must be local_frontend_worker")
    if _required_str(topology, "package", "components.dynamo_frontend.topology") != "ai-dynamo":
        raise InferenceConfigError("components.dynamo_frontend.topology.package must be ai-dynamo")
    _required_str(topology, "version", "components.dynamo_frontend.topology")
    if _required_str(topology, "discovery_backend", "components.dynamo_frontend.topology") != "file":
        raise InferenceConfigError("components.dynamo_frontend.topology.discovery_backend must be file")
    if _required_str(topology, "request_plane", "components.dynamo_frontend.topology") != "tcp":
        raise InferenceConfigError("components.dynamo_frontend.topology.request_plane must be tcp")
    _required_str(topology, "namespace", "components.dynamo_frontend.topology")
    _logical_ref(_required_str(topology, "file_kv_root", "components.dynamo_frontend.topology"), "components.dynamo_frontend.topology.file_kv_root")
    _logical_ref(
        _required_str(topology, "host_control_venv", "components.dynamo_frontend.topology"),
        "components.dynamo_frontend.topology.host_control_venv",
    )
    _rootfs_cache_projection(
        _required_str(topology, "rootfs_cache_projection", "components.dynamo_frontend.topology"),
        "components.dynamo_frontend.topology.rootfs_cache_projection",
    )
    packages = _required_str_list(topology, "packages", "components.dynamo_frontend.topology")
    if packages != DYNAMO_SGLANG_PACKAGES:
        raise InferenceConfigError("components.dynamo_frontend.topology.packages must match the Dynamo/SGLang package contract")
    rootfs_tools = _required_str_list(topology, "rootfs_tools", "components.dynamo_frontend.topology")
    if rootfs_tools != ["uv"]:
        raise InferenceConfigError("components.dynamo_frontend.topology.rootfs_tools must be [uv]")
    frontend = _require_mapping(topology.get("frontend"), "components.dynamo_frontend.topology.frontend")
    _reject_unknown(frontend, {"module", "chat_processor"}, "components.dynamo_frontend.topology.frontend")
    if _required_str(frontend, "module", "components.dynamo_frontend.topology.frontend") != "dynamo.frontend":
        raise InferenceConfigError("components.dynamo_frontend.topology.frontend.module must be dynamo.frontend")
    if _required_str(frontend, "chat_processor", "components.dynamo_frontend.topology.frontend") != "sglang":
        raise InferenceConfigError("components.dynamo_frontend.topology.frontend.chat_processor must be sglang")
    worker = _require_mapping(topology.get("worker"), "components.dynamo_frontend.topology.worker")
    _reject_unknown(worker, {"module", "component", "endpoint", "endpoint_types"}, "components.dynamo_frontend.topology.worker")
    if _required_str(worker, "module", "components.dynamo_frontend.topology.worker") != "dynamo.sglang":
        raise InferenceConfigError("components.dynamo_frontend.topology.worker.module must be dynamo.sglang")
    _required_str(worker, "component", "components.dynamo_frontend.topology.worker")
    _required_str(worker, "endpoint", "components.dynamo_frontend.topology.worker")
    _required_str(worker, "endpoint_types", "components.dynamo_frontend.topology.worker")
    return topology


def _dynamo_argv(component: dict[str, Any], *, python: str, host: str, port: int, model_name: str, run_dir: str) -> list[str]:
    topology = component["topology"]
    frontend = topology["frontend"]
    return [
        python,
        "-m",
        frontend["module"],
        "--http-host",
        host,
        "--http-port",
        str(port),
        "--model-name",
        model_name,
        "--discovery-backend",
        topology["discovery_backend"],
        "--request-plane",
        topology["request_plane"],
        "--namespace",
        topology["namespace"],
        "--dyn-chat-processor",
        frontend["chat_processor"],
    ]


def _dynamo_worker_argv(component: dict[str, Any], *, python: str, model_name: str) -> list[str]:
    topology = component["topology"]
    worker = topology["worker"]
    endpoint = f"dyn://{topology['namespace']}.{worker['component']}.{worker['endpoint']}"
    return [
        python,
        "-m",
        worker["module"],
        "--model-path",
        model_name,
        "--served-model-name",
        model_name,
        "--discovery-backend",
        topology["discovery_backend"],
        "--request-plane",
        topology["request_plane"],
        "--namespace",
        topology["namespace"],
        "--endpoint",
        endpoint,
        "--endpoint-types",
        worker["endpoint_types"],
    ]


def _responses_adapter_argv(*, host: str, port: int, upstream_url: str, model_name: str, timeout_seconds: int) -> list[str]:
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
        "--timeout-seconds",
        str(timeout_seconds),
    ]


def _require_str_int_mapping(value: Any, path: str) -> dict[str, int]:
    mapping = _require_mapping(value, path)
    result: dict[str, int] = {}
    for key, item in mapping.items():
        if not isinstance(key, str) or not isinstance(item, int):
            raise InferenceConfigError(f"{path} must map strings to integers")
        result[key] = item
    return result


def _require_component_mapping(value: Any, path: str) -> dict[str, dict[str, Any]]:
    mapping = _require_mapping(value, path)
    result: dict[str, dict[str, Any]] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise InferenceConfigError(f"{path} component keys must be strings")
        result[key] = _require_mapping(item, f"{path}.{key}")
    return result


def _config_to_mapping(config: MaterializedInferenceConfig) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "run_id": config.run_id,
        "run_dir": config.run_dir,
        "declared_path": config.declared_path,
        "local_environment_path": config.local_environment_path,
        "ports": config.ports,
        "components": config.components,
        "probes": config.probes,
        "repeatability": config.repeatability,
        "teardown": config.teardown,
        "artifacts": config.artifacts,
    }


def _materialize_sglang_slice(config: MaterializedInferenceConfig) -> Any:
    local_environment = glm52_sglang_runtime.load_local_environment(Path(config.local_environment_path))
    component = config.components["sglang_backend"]
    declared_path = _resolve_declared_ref(component["declared_ref"], local_environment)
    declared = glm52_sglang_runtime.load_declared_spec(declared_path)
    sglang_config = glm52_sglang_runtime.materialize_runtime_config(
        declared=declared,
        local_environment=local_environment,
        run_id=f"{config.run_id}-sglang",
        port=config.ports["sglang_backend"],
    )
    records = _require_mapping(component["required_records"], "components.sglang_backend.required_records")
    artifacts = dict(sglang_config.artifacts)
    artifacts["preparation"] = {
        "sglang_venv_record": _required_str(records, "venv", "components.sglang_backend.required_records"),
        "model_cache_record": _required_str(records, "model_cache", "components.sglang_backend.required_records"),
    }
    resolved_paths = dict(sglang_config.resolved_paths)
    resolved_paths["preparation"] = {
        "sglang_venv_record": _resolve_local_path_ref(local_environment, artifacts["preparation"]["sglang_venv_record"]),
        "model_cache_record": _resolve_local_path_ref(local_environment, artifacts["preparation"]["model_cache_record"]),
    }
    return _replace_sglang_config(sglang_config, artifacts=artifacts, resolved_paths=resolved_paths)


def _replace_sglang_config(config: Any, *, artifacts: dict[str, Any], resolved_paths: dict[str, Any]) -> Any:
    return type(config)(
        schema_version=config.schema_version,
        run_id=config.run_id,
        run_group=config.run_group,
        fail_fast=config.fail_fast,
        allow_fallback=config.allow_fallback,
        service=config.service,
        model=config.model,
        runtime=config.runtime,
        observability=config.observability,
        host_layout=config.host_layout,
        sandbox=config.sandbox,
        launch=config.launch,
        probes=config.probes,
        artifacts=artifacts,
        resolved_paths=resolved_paths,
    )


def _resolve_declared_ref(ref: str, local_environment: Any) -> Path:
    if not ref.startswith("repo://"):
        raise InferenceConfigError("SGLang declared_ref must use repo://")
    suffix = ref.removeprefix("repo://")
    local_repo = Path(local_environment.repo)
    candidate = local_repo / suffix
    if candidate.exists():
        return candidate
    fallback = REPO_ROOT / suffix
    if fallback.exists():
        return fallback
    raise InferenceConfigError(f"SGLang declared config does not exist: {ref}")


def _host_control_python(venv_ref: str, local_environment: Any) -> str:
    return str(Path(_resolve_local_path_ref(local_environment, venv_ref)) / "bin" / "python")


def _rootfs_projected_cache_path(topology: dict[str, Any], local_environment: Any) -> str:
    projection = _required_str(topology, "rootfs_cache_projection", "components.dynamo_frontend.topology")
    host_control_venv = _required_str(topology, "host_control_venv", "components.dynamo_frontend.topology")
    if not host_control_venv.startswith("cache://"):
        raise InferenceConfigError("components.dynamo_frontend.topology.host_control_venv must use cache://")
    projection_root = Path(_rootfs_cache_projection(projection, "components.dynamo_frontend.topology.rootfs_cache_projection"))
    return str(projection_root / host_control_venv.removeprefix("cache://"))


def _resolve_local_path_ref(local_environment: Any, ref: str) -> str:
    if ref == "repo://":
        return str(local_environment.repo)
    if ref.startswith("repo://"):
        return str(Path(local_environment.repo) / ref.removeprefix("repo://"))
    if ref.startswith("cache://"):
        return str(Path(local_environment.cache) / ref.removeprefix("cache://"))
    if ref.startswith("temp://"):
        return str(Path(local_environment.temp) / ref.removeprefix("temp://"))
    raise InferenceConfigError(f"unsupported local path ref: {ref}")


def _artifact_path(config: MaterializedInferenceConfig, suffix: str) -> Path:
    return _artifact_path_from_ref(config, f"{config.run_dir}/{suffix}")


def _artifact_path_from_ref(config: MaterializedInferenceConfig, ref: str) -> Path:
    if not ref.startswith("repo://"):
        raise InferenceConfigError(f"artifact path must use repo://: {ref}")
    return REPO_ROOT / ref.removeprefix("repo://")


def _is_placeholder_dynamo_argv(argv: list[str]) -> bool:
    return _python_module_from_argv(argv) == "dynamo.frontend" and any(
        flag in argv for flag in ("--host", "--port", "--upstream-url", "--model")
    )


def _python_module_from_argv(argv: list[str]) -> str | None:
    if len(argv) < 3:
        return None
    executable = Path(argv[0]).name
    if executable not in {"python", "python3"} and not executable.startswith("python3."):
        return None
    if argv[1] != "-m":
        return None
    return argv[2]


def _resolve_executable(executable: str) -> str | None:
    if "/" in executable:
        path = Path(executable)
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
        return None
    return shutil.which(executable)


def _locked_dependency_sync_command(python: str) -> list[str]:
    return [
        "uv",
        "sync",
        "--active",
        "--locked",
        "--no-sources-package",
        "torch",
        "--no-install-project",
        "--only-group",
        GLM52_RUNTIME_DEPENDENCY_GROUP,
        "--python",
        python,
    ]


def _locked_dependency_sync_env(venv_path: str) -> dict[str, str]:
    return {"VIRTUAL_ENV": venv_path}


def _locked_dependency_resolution_record() -> dict[str, str]:
    lock_path = REPO_ROOT / GLM52_RUNTIME_LOCKFILE_REF.removeprefix("repo://")
    return {
        "group": GLM52_RUNTIME_DEPENDENCY_GROUP,
        "lockfile": GLM52_RUNTIME_LOCKFILE_REF,
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "selection": "only_group",
        "sources": "standard_metadata_for_torch",
    }


def _find_module_spec(module_name: str) -> Any:
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def _run_prepare_command(command: list[str], *, run: Any | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    runner = subprocess.run if run is None else run
    command_env = dict(env or {})
    completed = runner(command, capture_output=True, text=True, timeout=1800, env={**os.environ, **command_env})
    if completed.returncode != 0:
        raise InferenceLaunchError(f"prepare command failed: {' '.join(command)}\n{completed.stderr}")
    return {
        "argv": command,
        "env": command_env,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _verify_rootfs_tool(tool: str, *, run: Any | None = None) -> dict[str, Any]:
    if tool != "uv":
        raise InferenceConfigError(f"unsupported rootfs tool contract: {tool}")
    command = [tool, "--version"]
    runner = subprocess.run if run is None else run
    try:
        completed = runner(command, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as error:
        raise InferenceLaunchError(f"required rootfs tool failed: {tool}") from error
    if completed.returncode != 0:
        raise InferenceLaunchError(f"required rootfs tool failed: {tool}\n{completed.stderr}")
    return {
        "ok": True,
        "argv": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _required_dynamo_modules(config: MaterializedInferenceConfig) -> list[str]:
    component = config.components["dynamo_frontend"]
    modules = [_python_module_from_argv(component["argv"])]
    if "worker_argv" in component:
        modules.append(_python_module_from_argv(component["worker_argv"]))
    return [module for module in modules if module is not None]


def _probe_python_module_executable(python: str, module_name: str, *, run: Any | None = None) -> dict[str, Any]:
    command = [python, "-m", module_name, "--help"]
    runner = subprocess.run if run is None else run
    try:
        completed = runner(command, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as error:
        return {"ok": False, "module": module_name, "python": python, "argv": command, "error": str(error)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "module": module_name, "python": python, "argv": command, "error": "module help probe timed out"}
    return {
        "ok": completed.returncode == 0,
        "module": module_name,
        "python": python,
        "argv": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _validate_module_help_contract(module_name: str, probe: dict[str, Any]) -> dict[str, Any]:
    required_flags = DYNAMO_REQUIRED_HELP_FLAGS.get(module_name, [])
    help_text = f"{probe.get('stdout', '')}\n{probe.get('stderr', '')}"
    present = [flag for flag in required_flags if flag in help_text]
    missing = [flag for flag in required_flags if flag not in help_text]
    probe["required_flags_present"] = present
    probe["required_flags_missing"] = missing
    probe["help_contract_ok"] = not missing
    return probe


def _probe_python_module(python: str, module_name: str, *, run: Any | None = None) -> dict[str, Any]:
    script = (
        "import importlib.util, json, sys\n"
        "module = sys.argv[1]\n"
        "spec = importlib.util.find_spec(module)\n"
        "print(json.dumps({"
        "'ok': spec is not None, "
        "'module': module, "
        "'origin': getattr(spec, 'origin', None) if spec is not None else None"
        "}))\n"
    )
    command = [python, "-c", script, module_name]
    runner = subprocess.run if run is None else run
    try:
        completed = runner(command, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as error:
        return {"ok": False, "module": module_name, "python": python, "error": str(error)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "module": module_name, "python": python, "error": "module probe timed out"}
    if completed.returncode != 0:
        return {
            "ok": False,
            "module": module_name,
            "python": python,
            "returncode": completed.returncode,
            "stderr": completed.stderr,
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        return {
            "ok": False,
            "module": module_name,
            "python": python,
            "error": f"module probe emitted invalid JSON: {error}",
            "stdout": completed.stdout,
        }
    return _require_mapping(payload, "Dynamo module probe")


def _unsupported_dynamo_frontend_flag(argv: list[str]) -> str | None:
    module_name = _python_module_from_argv(argv)
    if module_name is None or not module_name.endswith(".frontend"):
        return None
    for item in argv[3:]:
        if item == "--":
            break
        if not item.startswith("--"):
            continue
        flag = item.split("=", 1)[0]
        if flag not in DYNAMO_FRONTEND_SUPPORTED_FLAGS:
            return flag
    return None


def _write_missing_dynamo_prerequisite(
    config: MaterializedInferenceConfig,
    *,
    argv: list[str],
    reason: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": "missing_prerequisite",
        "component": "dynamo_frontend",
        "reason": reason,
        "message": message,
        "argv": argv,
        "argv_digest": stable_json_digest(argv),
        "endpoint_url": config.components["dynamo_frontend"]["openai_base_url"],
        "upstream_url": config.components["dynamo_frontend"]["upstream_url"],
        "popen_attempted": False,
        "created_at": _utc_stamp(),
    }
    if extra:
        payload.update(extra)
    _write_dynamo_environment(config, payload)
    raise InferenceLaunchError(f"Dynamo prerequisite missing: {message}")


def _write_dynamo_environment(config: MaterializedInferenceConfig, payload: dict[str, Any]) -> dict[str, Any]:
    path = _artifact_path(config, "components/dynamo/environment.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    complete = {
        "component": "dynamo_frontend",
        "run_id": config.run_id,
        "created_at": _utc_stamp(),
        **payload,
    }
    path.write_text(json.dumps(complete, indent=2, sort_keys=True) + "\n")
    return complete


def _write_dynamo_readiness(config: MaterializedInferenceConfig, payload: dict[str, Any]) -> dict[str, Any]:
    path = _artifact_path(config, "components/dynamo/readiness.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def _teardown_host_controlled_component(config: MaterializedInferenceConfig, component: str) -> dict[str, Any]:
    component_config = config.components[component]
    record_path = _artifact_path_from_ref(config, component_config["process_record"])
    stopped_records = {}
    if component == "dynamo_frontend" and "worker_process_record" in component_config:
        worker_record_path = _artifact_path_from_ref(config, component_config["worker_process_record"])
        worker_record = load_process_record(worker_record_path)
        validate_process_record(worker_record, run_id=config.run_id, component="dynamo_worker")
        try:
            os.killpg(worker_record["process_group"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        stopped_worker = {**worker_record, "stopped_at": _utc_stamp(), "stop_reason": "teardown"}
        worker_record_path.write_text(json.dumps(stopped_worker, indent=2, sort_keys=True) + "\n")
        stopped_records["worker"] = stopped_worker
    record = load_process_record(record_path)
    validate_process_record(record, run_id=config.run_id, component=component)
    try:
        os.killpg(record["process_group"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    closed = prove_port_closed("127.0.0.1", config.ports[component])
    stopped = {**record, "stopped_at": _utc_stamp(), "stop_reason": "teardown"}
    record_path.write_text(json.dumps(stopped, indent=2, sort_keys=True) + "\n")
    stopped_records["frontend" if component == "dynamo_frontend" else "process"] = stopped
    return {"ok": True, "component": component, "processes": stopped_records, "port": closed}


def _mark_and_stop_process_record(path: Path, record: dict[str, Any], *, stop_reason: str) -> dict[str, Any]:
    try:
        os.killpg(record["process_group"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    stopped = {**record, "stopped_at": _utc_stamp(), "stop_reason": stop_reason}
    path.write_text(json.dumps(stopped, indent=2, sort_keys=True) + "\n")
    return stopped


def _repeatability_summary(*, run_id: str, ok: bool, cycles: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    return {
        "ok": ok,
        "run_id": run_id,
        "dry_run": dry_run,
        "cycle_count": len(cycles),
        "cycles": cycles,
        "created_at": _utc_stamp(),
    }


def _write_repeatability_summary(run_id: str, summary: dict[str, Any]) -> None:
    path = REPO_ROOT / "glm52-serving-results" / run_id / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def _parsed_url_port(url: str, path: str) -> int:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        raise InferenceConfigError(f"{path} must be an http://127.0.0.1:<port> URL")
    return parsed.port


def _utc_stamp() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
