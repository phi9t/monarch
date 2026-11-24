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
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from typing import Protocol
from typing import TextIO


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QWEN3_DECLARED_SPEC = REPO_ROOT / "ginkgo" / "configs" / "smoke-qwen3-dense.yaml"
LOG_TAIL_BYTES = 65536
DISALLOWED_FALLBACK_PORTS = {8000, 8080, 18080}


class LocalRunError(RuntimeError):
    """Raised when a Ginkgo local-run contract is invalid."""


@dataclass(frozen=True)
class LocalRunResult:
    status: str
    run_id: str
    port: int
    generated_text: str
    evidence_manifest: Path
    teardown_status: str | None = None


@dataclass(frozen=True)
class EvidencePaths:
    run_dir: Path
    materialized_config: Path
    manifest: Path
    stdout_log: Path
    stderr_log: Path
    telemetry_log: Path


class SglangWorkload(Protocol):
    name: str
    default_declared_spec: Path
    manifest_name: str
    model_output_title: str

    def validate_declared(self, declared: Any, *, requested_port: int | None) -> None:
        ...

    def validate_materialized(self, config: Any) -> None:
        ...

    def extract_generated_text(self, chat: dict[str, Any]) -> str:
        ...

    def manifest_metadata(self, config: Any) -> dict[str, Any]:
        ...


class RuntimeBackedLocalRunAdapter:
    """Thin adapter over the SGLang runtime module used by Ginkgo local runs."""

    RuntimeConfigError: type[Exception]

    def __init__(self, runtime_module: Any | None = None) -> None:
        self.runtime = runtime_module or load_runtime_module()
        self.RuntimeConfigError = getattr(self.runtime, "RuntimeConfigError", RuntimeError)

    def load_declared(self, path: Path) -> Any:
        return self.runtime.load_declared_spec(path)

    def load_local_environment(self, path: Path) -> Any:
        return self.runtime.load_local_environment(path)

    def materialize(
        self,
        *,
        declared: Any,
        local_environment: Any,
        run_id: str,
        port: int | None,
    ) -> Any:
        config = self.runtime.materialize_runtime_config(
            declared=declared,
            local_environment=local_environment,
            run_id=run_id,
            port=port,
        )
        return self.runtime.with_stable_preparation_record_paths(
            config,
            declared=declared,
            local_environment=local_environment,
        )

    def write_materialized_config(self, config: Any, path: Path) -> None:
        self.runtime.write_materialized_config(config, path)

    def ensure_prepared(
        self,
        *,
        config: Any,
        declared_spec: Path,
        local_environment: Path,
        logger: StageLogger,
    ) -> None:
        try:
            self.runtime.validate_preparation_records(config=config)
            return
        except Exception as error:
            if not self.is_refreshable_preparation_error(error):
                raise

        logger.stage("prepare_sglang_venv", {"run_id": "prepare-venv"})
        self.runtime.prepare_sglang_venv(
            declared_path=declared_spec,
            local_environment_path=local_environment,
        )
        logger.stage("prepare_model_cache", {"run_id": "prepare-model"})
        self.runtime.prepare_model_cache(
            declared_path=declared_spec,
            local_environment_path=local_environment,
        )
        self.runtime.validate_preparation_records(config=config)

    def is_refreshable_preparation_error(self, error: Exception) -> bool:
        text = str(error)
        return (
            "missing SGLang venv preparation record:" in text
            or "missing model cache preparation record:" in text
            or "preparation record rootfs recipe digest mismatch" in text
            or "preparation record bwrap plan digest mismatch" in text
            or "preparation bwrap plan env mismatch:" in text
            or "mount host path mismatch:" in text
            or "SGLang venv preparation record package contract mismatch" in text
            or "SGLang venv preparation record missing installed package:" in text
            or "SGLang venv preparation record missing CPU platform proof" in text
            or "SGLang venv preparation record missing utils.is_cpu proof" in text
            or "SGLang venv preparation record missing rotary CPU proof" in text
            or "SGLang venv preparation record reports CUDA rotary mode for CPU route" in text
            or "SGLang venv preparation record missing CUDA platform proof" in text
            or "SGLang venv preparation record missing rotary CUDA proof" in text
            or "SGLang venv preparation record reports CPU platform for CUDA route" in text
            or "SGLang venv preparation record reports CPU rotary mode for CUDA route" in text
        )

    def launch(self, config: Any, *, local_environment: Any) -> dict[str, Any]:
        return self.runtime.launch_runtime(config, local_environment=local_environment)

    def wait_for_gpu_free_window(
        self,
        config: Any,
        *,
        timeout_seconds: int,
        stable_seconds: int = 0,
    ) -> dict[str, Any]:
        return self.runtime.wait_for_gpu_free_window(
            config,
            timeout_seconds=timeout_seconds,
            stable_seconds=stable_seconds,
        )

    def reload_effective_config(self, path: Path) -> Any:
        return self.runtime.load_materialized_config(path)

    def probe_models(self, config: Any) -> dict[str, Any]:
        return self.runtime.probe_models(config)

    def probe_chat(self, config: Any) -> dict[str, Any]:
        return self.runtime.probe_chat(config)

    def teardown(self, config: Any, *, local_environment: Any) -> dict[str, Any]:
        return self.runtime.teardown_runtime(config, local_environment=local_environment)


class StageLogger:
    def __init__(self, output: TextIO) -> None:
        self.output = output
        self.events: list[dict[str, Any]] = []
        self.current_stage = "not_started"

    def stage(self, name: str, details: dict[str, Any] | None = None) -> None:
        self.current_stage = name
        timestamp = datetime.now(timezone.utc).isoformat()
        details = details or {}
        event = {
            "stage": name,
            "timestamp": timestamp,
            "elapsed_seconds": round(perf_counter(), 6),
            "details": details,
        }
        self.events.append(event)
        detail_text = " ".join(f"{key}={value}" for key, value in details.items())
        suffix = f" {detail_text}" if detail_text else ""
        print(f"[ginkgo] stage={name}{suffix}", file=self.output)


class SglangLocalRun:
    def __init__(
        self,
        *,
        workload: SglangWorkload,
        runtime: RuntimeBackedLocalRunAdapter | None = None,
    ) -> None:
        self.workload = workload
        self.runtime = runtime or RuntimeBackedLocalRunAdapter()

    def run(
        self,
        *,
        declared_spec: Path,
        local_environment: Path,
        run_id: str | None = None,
        port: int | None = None,
        output: TextIO | None = None,
        wait_for_gpu_free_seconds: int = 0,
        gpu_free_stable_seconds: int = 0,
    ) -> LocalRunResult:
        if wait_for_gpu_free_seconds < 0:
            raise LocalRunError("wait_for_gpu_free_seconds must be non-negative")
        if gpu_free_stable_seconds < 0:
            raise LocalRunError("gpu_free_stable_seconds must be non-negative")
        if gpu_free_stable_seconds and wait_for_gpu_free_seconds < gpu_free_stable_seconds:
            raise LocalRunError("gpu_free_stable_seconds must not exceed wait_for_gpu_free_seconds")
        output = output or sys.stdout
        logger = StageLogger(output)
        print(f"========== GINKGO {self.workload.name.upper()} SGLANG LOCAL RUN ==========", file=output)

        config: Any | None = None
        local_env: Any | None = None
        paths: EvidencePaths | None = None
        launch_summary: dict[str, Any] | None = None
        teardown_summary: dict[str, Any] | None = None
        gpu_wait_summary: dict[str, Any] | None = None
        models: dict[str, Any] | None = None
        chat: dict[str, Any] | None = None
        generated_text = ""
        selected_run_id: str | None = run_id

        try:
            logger.stage("load_declared", {"declared_spec": str(declared_spec)})
            declared = self.runtime.load_declared(declared_spec)
            self.workload.validate_declared(declared, requested_port=port)
            logger.stage("load_local_environment", {"local_environment": str(local_environment)})
            local_env = self.runtime.load_local_environment(local_environment)
            selected_run_id = run_id or _default_run_id(_declared_run_group(declared))
            logger.stage(
                "materialize",
                {
                    "run_id": selected_run_id,
                    "requested_port": port,
                    "run_group": _declared_run_group(declared),
                },
            )
            config = self.runtime.materialize(
                declared=declared,
                local_environment=local_env,
                run_id=selected_run_id,
                port=port,
            )
            self.workload.validate_materialized(config)
            paths = self._evidence_paths(config)
            paths.run_dir.mkdir(parents=True, exist_ok=True)
            logger.stage("write_materialized_config", {"path": str(paths.materialized_config)})
            self.runtime.write_materialized_config(config, paths.materialized_config)
            logger.stage("validate_preparation_records", {"run_dir": str(paths.run_dir)})
            self.runtime.ensure_prepared(
                config=config,
                declared_spec=declared_spec,
                local_environment=local_environment,
                logger=logger,
            )
            if wait_for_gpu_free_seconds:
                logger.stage(
                    "wait_for_gpu_free",
                    {
                        "timeout_seconds": wait_for_gpu_free_seconds,
                        "stable_seconds": gpu_free_stable_seconds,
                    },
                )
                gpu_wait_summary = self.runtime.wait_for_gpu_free_window(
                    config,
                    timeout_seconds=wait_for_gpu_free_seconds,
                    stable_seconds=gpu_free_stable_seconds,
                )
            logger.stage(
                "launch_sglang",
                {
                    "port": _config_port(config),
                    "model": _config_model(config).get("served_model_name"),
                },
            )
            launch_summary = self.runtime.launch(config, local_environment=local_env)
            config = self.runtime.reload_effective_config(paths.materialized_config)
            self.workload.validate_materialized(config)
            paths = self._evidence_paths(config)
            logger.stage("models_probe", {"url": _config_probe_url(config, "models_url")})
            models = self.runtime.probe_models(config)
            logger.stage("inference_request", {"url": _config_probe_url(config, "chat_url")})
            chat = self.runtime.probe_chat(config)
            generated_text = self.workload.extract_generated_text(chat)
            if not generated_text:
                raise LocalRunError("chat probe returned empty generated text")
        except Exception as error:
            failed_stage = logger.current_stage
            if failed_stage == "wait_for_gpu_free" and gpu_wait_summary is None:
                gpu_wait_summary = {
                    "status": "failed",
                    "error": str(error),
                }
                blocked_gpus = getattr(error, "blocked_gpus", None)
                if blocked_gpus is not None:
                    gpu_wait_summary["blocked_gpus"] = _json_safe(blocked_gpus)
            if launch_summary is not None and config is not None and local_env is not None:
                logger.stage("teardown", {"run_id": _config_run_id(config)})
                teardown_summary = self.runtime.teardown(config, local_environment=local_env)
            self._emit_failure(
                error=error,
                failed_stage=failed_stage,
                logger=logger,
                output=output,
                config=config,
                paths=paths,
                launch_summary=launch_summary,
                teardown_summary=teardown_summary,
                gpu_wait_summary=gpu_wait_summary,
            )
            raise

        logger.stage("teardown", {"run_id": _config_run_id(config)})
        teardown_summary = self.runtime.teardown(config, local_environment=local_env)
        logs = self._read_logs(paths)
        self._print_observation(output, logs=logs, generated_text=generated_text)

        manifest = self._manifest(
            status="passed",
            logger=logger,
            config=config,
            paths=paths,
            logs=logs,
            models=models,
            chat=chat,
            generated_text=generated_text,
            launch_summary=launch_summary,
            teardown_summary=teardown_summary,
            gpu_wait_summary=gpu_wait_summary,
        )
        logger.stage("write_evidence_manifest", {"path": str(paths.manifest)})
        paths.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"[ginkgo] evidence_manifest={paths.manifest}", file=output)
        return LocalRunResult(
            status="passed",
            run_id=_config_run_id(config),
            port=_config_port(config),
            generated_text=generated_text,
            evidence_manifest=paths.manifest,
            teardown_status=_teardown_status(teardown_summary),
        )

    def _emit_failure(
        self,
        *,
        error: Exception,
        failed_stage: str,
        logger: StageLogger,
        output: TextIO,
        config: Any | None,
        paths: EvidencePaths | None,
        launch_summary: dict[str, Any] | None,
        teardown_summary: dict[str, Any] | None,
        gpu_wait_summary: dict[str, Any] | None,
    ) -> None:
        logs = self._read_logs(paths) if paths is not None else _empty_logs()
        print("========== GINKGO FAILURE ==========", file=output)
        print(f"[ginkgo] failure stage={failed_stage}", file=output)
        if config is not None:
            print(f"[ginkgo] failure run_id={_config_run_id(config)} port={_config_port(config)}", file=output)
        if paths is not None:
            print(f"[ginkgo] failure materialized_config={paths.materialized_config}", file=output)
        print(f"[ginkgo] failure {type(error).__name__}: {error}", file=output)
        if paths is None:
            return
        failure_manifest = self._manifest(
            status="failed",
            logger=logger,
            config=config,
            paths=paths,
            logs=logs,
            models=None,
            chat=None,
            generated_text="",
            launch_summary=launch_summary,
            teardown_summary=teardown_summary,
            gpu_wait_summary=gpu_wait_summary,
        )
        failure_manifest["failure"] = {
            "stage": failed_stage,
            "exception_type": type(error).__name__,
            "message": str(error),
        }
        blocked_gpus = getattr(error, "blocked_gpus", None)
        if blocked_gpus is not None:
            failure_manifest["failure"]["blocked_gpus"] = _json_safe(blocked_gpus)
        paths.manifest.write_text(json.dumps(failure_manifest, indent=2, sort_keys=True) + "\n")
        print(f"[ginkgo] failure_manifest={paths.manifest}", file=output)

    def _manifest(
        self,
        *,
        status: str,
        logger: StageLogger,
        config: Any | None,
        paths: EvidencePaths,
        logs: dict[str, str],
        models: dict[str, Any] | None,
        chat: dict[str, Any] | None,
        generated_text: str,
        launch_summary: dict[str, Any] | None,
        teardown_summary: dict[str, Any] | None,
        gpu_wait_summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "status": status,
            "workload": self.workload.name,
            "control_plane": logger.events,
            "launch": launch_summary,
            "teardown": teardown_summary,
            "gpu_wait": gpu_wait_summary,
            "logs": logs,
            "artifacts": {
                "run_dir": str(paths.run_dir),
                "materialized_config": str(paths.materialized_config),
                "manifest": str(paths.manifest),
                "stdout_log": str(paths.stdout_log),
                "stderr_log": str(paths.stderr_log),
                "telemetry_log": str(paths.telemetry_log),
            },
        }
        if config is not None:
            service = _config_service(config)
            model = _config_model(config)
            port = _config_port(config)
            teardown_status = None
            if isinstance(teardown_summary, dict):
                teardown_status = teardown_summary.get("status")
            manifest.update(
                {
                    "run_id": _config_run_id(config),
                    "run_group": _config_run_group(config),
                    "port": port,
                    "openai_base_url": service.get("base_url"),
                    "generated_text": generated_text,
                    "teardown_status": teardown_status,
                    "evidence_boundary": "live_qwen3_sglang_smoke",
                    "model_id": model.get("id"),
                    "served_model_name": model.get("served_model_name"),
                    "expected_model_ids": model.get("expected_model_ids"),
                    "service": service,
                    "model": model,
                    "request": {
                        "url": _config_probe_url(config, "chat_url"),
                        "payload": _config_probe_payload(config, "chat_payload"),
                    },
                    "response": {
                        "generated_text": generated_text,
                        "payload": chat.get("payload", chat) if chat is not None else None,
                    },
                    "models": models,
                }
            )
            metadata = self.workload.manifest_metadata(config)
            manifest["metadata"] = metadata
            manifest.update(metadata)
        return manifest

    def _print_observation(
        self,
        output: TextIO,
        *,
        logs: dict[str, str],
        generated_text: str,
    ) -> None:
        print("========== SGLANG STDOUT TAIL ==========", file=output)
        print(logs["stdout_tail"].rstrip() or "<empty>", file=output)
        print("========== SGLANG STDERR TAIL ==========", file=output)
        print(logs["stderr_tail"].rstrip() or "<empty>", file=output)
        print("========== SGLANG TELEMETRY TAIL ==========", file=output)
        print(logs["telemetry_tail"].rstrip() or "<empty>", file=output)
        print(f"========== {self.workload.model_output_title} ==========", file=output)
        print(generated_text, file=output)

    def _evidence_paths(self, config: Any) -> EvidencePaths:
        run_dir = _resolve_run_dir(config)
        return EvidencePaths(
            run_dir=run_dir,
            materialized_config=run_dir / "materialized-sglang-runtime.yaml",
            manifest=run_dir / self.workload.manifest_name,
            stdout_log=run_dir / "logs" / "stdout.log",
            stderr_log=run_dir / "logs" / "stderr.log",
            telemetry_log=run_dir / "logs" / "telemetry.jsonl",
        )

    def _read_logs(self, paths: EvidencePaths) -> dict[str, str]:
        return {
            "stdout_tail": _read_tail(paths.stdout_log),
            "stderr_tail": _read_tail(paths.stderr_log),
            "telemetry_tail": _read_tail(paths.telemetry_log),
        }


class Qwen3SglangWorkload:
    name = "qwen3"
    default_declared_spec = DEFAULT_QWEN3_DECLARED_SPEC
    manifest_name = "qwen3-sglang-smoke-evidence.json"
    model_output_title = "MODEL OUTPUT"

    def validate_declared(self, declared: Any, *, requested_port: int | None) -> None:
        disallowed = set(_declared_disallowed_ports(declared))
        if DISALLOWED_FALLBACK_PORTS - disallowed:
            raise LocalRunError("declared smoke config must disallow default fallback ports")
        if requested_port in disallowed:
            raise LocalRunError(f"disallowed serving port requested: {requested_port}")
        device = _declared_device(declared)
        cuda_visible_devices = _declared_cuda_visible_devices(declared)
        if device == "cpu":
            if _visible_cuda_devices(cuda_visible_devices):
                raise LocalRunError("Qwen3 CPU SGLang smoke must not expose CUDA devices")
        elif device == "cuda":
            if len(_visible_cuda_devices(cuda_visible_devices)) != 1:
                raise LocalRunError("Qwen3 SGLang smoke must use exactly one visible GPU")
        else:
            raise LocalRunError("Qwen3 SGLang smoke device must be cpu or cuda")
        if _declared_tensor_parallel_size(declared) != 1:
            raise LocalRunError("Qwen3 SGLang smoke tensor_parallel_size must be 1")
        if requested_port is not None:
            start = _declared_port_range_start(declared)
            end = _declared_port_range_end(declared)
            if requested_port < start or requested_port > end:
                raise LocalRunError(f"requested port outside declared run-owned range: {requested_port}")

    def validate_materialized(self, config: Any) -> None:
        if _config_port(config) in DISALLOWED_FALLBACK_PORTS:
            raise LocalRunError(f"disallowed serving port materialized: {_config_port(config)}")
        service = _config_service(config)
        if service.get("base_url") != f"http://127.0.0.1:{_config_port(config)}/v1":
            raise LocalRunError("materialized service base_url must use the run-owned localhost port")
        if _config_probe_url(config, "chat_url") != f"http://127.0.0.1:{_config_port(config)}/v1/chat/completions":
            raise LocalRunError("materialized chat probe URL must derive from the run-owned service port")
        device = _config_device(config)
        sandbox_gpu = _config_sandbox(config).get("gpu")
        if device == "cpu" and sandbox_gpu != "none":
            raise LocalRunError("materialized CPU SGLang smoke must use sandbox.gpu=none")
        if device == "cuda" and sandbox_gpu != "required":
            raise LocalRunError("materialized CUDA SGLang smoke must require a GPU")

    def extract_generated_text(self, chat: dict[str, Any]) -> str:
        content = chat.get("content")
        if isinstance(content, str):
            return content.strip()
        payload = chat.get("payload")
        if isinstance(payload, dict):
            choices = payload.get("choices")
            if isinstance(choices, list):
                fragments: list[str] = []
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    message = choice.get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        fragments.append(message["content"])
                    if isinstance(choice.get("text"), str):
                        fragments.append(choice["text"])
                return "".join(fragments).strip()
        return ""

    def manifest_metadata(self, config: Any) -> dict[str, Any]:
        return {"smoke_kind": "qwen3_sglang", "device": _config_device(config)}


def load_runtime_module() -> Any:
    path = REPO_ROOT / "scripts" / "glm52_sglang_runtime.py"
    spec = importlib.util.spec_from_file_location("glm52_sglang_runtime", path)
    if spec is None or spec.loader is None:
        raise LocalRunError(f"cannot load runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _empty_logs() -> dict[str, str]:
    return {"stdout_tail": "", "stderr_tail": "", "telemetry_tail": ""}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _resolve_run_dir(config: Any) -> Path:
    run_dir = getattr(config, "run_dir", None)
    if isinstance(run_dir, Path):
        return run_dir
    host_layout = _mapping_attr(config, "host_layout")
    resolved_paths = _mapping_attr(config, "resolved_paths")
    logical = str(host_layout.get("run_dir", ""))
    if not logical.startswith("repo://"):
        raise LocalRunError("materialized host_layout.run_dir must use repo://")
    repo = resolved_paths.get("repo")
    if not isinstance(repo, str) or not repo.startswith("/"):
        raise LocalRunError("materialized resolved_paths.repo must be an absolute host path")
    return Path(repo) / logical.removeprefix("repo://")


def _read_tail(path: Path) -> str:
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > LOG_TAIL_BYTES:
            handle.seek(size - LOG_TAIL_BYTES)
        return handle.read().decode("utf-8", errors="replace")


def _mapping_attr(value: Any, name: str) -> dict[str, Any]:
    item = getattr(value, name)
    if not isinstance(item, dict):
        raise LocalRunError(f"materialized {name} must be a mapping")
    return item


def _config_run_id(config: Any) -> str:
    return str(getattr(config, "run_id"))


def _config_run_group(config: Any) -> str:
    run_group = getattr(config, "run_group", None)
    if not isinstance(run_group, str) or not run_group:
        raise LocalRunError("materialized run_group is required")
    return run_group


def _config_port(config: Any) -> int:
    port = getattr(config, "port", None)
    if isinstance(port, int):
        return port
    service = _mapping_attr(config, "service")
    value = service.get("port")
    if not isinstance(value, int):
        raise LocalRunError("materialized service.port must be an integer")
    return value


def _config_service(config: Any) -> dict[str, Any]:
    return _mapping_attr(config, "service")


def _config_model(config: Any) -> dict[str, Any]:
    return _mapping_attr(config, "model")


def _config_probe_url(config: Any, key: str) -> str:
    probes = _mapping_attr(config, "probes")
    value = probes.get(key)
    if not isinstance(value, str) or not value:
        raise LocalRunError(f"materialized probes.{key} is required")
    return value


def _config_probe_payload(config: Any, key: str) -> dict[str, Any]:
    probes = _mapping_attr(config, "probes")
    value = probes.get(key)
    if isinstance(value, dict):
        return dict(value)
    raise LocalRunError(f"materialized probes.{key} is required")


def _declared_run_group(declared: Any) -> str:
    return str(getattr(declared, "run_group"))


def _teardown_status(teardown_summary: dict[str, Any] | None) -> str | None:
    if not isinstance(teardown_summary, dict):
        return None
    status = teardown_summary.get("status")
    if isinstance(status, str):
        return status
    return None


def _declared_port_range_start(declared: Any) -> int:
    value = getattr(declared, "port_range_start", None)
    if isinstance(value, int):
        return value
    return int(declared.port_policy.range_start)


def _declared_port_range_end(declared: Any) -> int:
    value = getattr(declared, "port_range_end", None)
    if isinstance(value, int):
        return value
    return int(declared.port_policy.range_end)


def _declared_disallowed_ports(declared: Any) -> list[int]:
    value = getattr(declared, "disallowed_ports", None)
    if isinstance(value, list):
        return [int(port) for port in value]
    return [int(port) for port in declared.port_policy.disallowed_ports]


def _declared_device(declared: Any) -> str:
    value = getattr(declared, "device", None)
    if isinstance(value, str):
        return value
    return str(declared.runtime.device)


def _declared_cuda_visible_devices(declared: Any) -> str:
    value = getattr(declared, "cuda_visible_devices", None)
    if isinstance(value, str):
        return value
    return str(declared.runtime.cuda_visible_devices)


def _declared_tensor_parallel_size(declared: Any) -> int:
    value = getattr(declared, "tensor_parallel_size", None)
    if isinstance(value, int):
        return value
    return int(declared.runtime.tensor_parallel_size)


def _visible_cuda_devices(cuda_visible_devices: str) -> list[str]:
    return [device.strip() for device in cuda_visible_devices.split(",") if device.strip()]


def _config_device(config: Any) -> str:
    runtime = _mapping_attr(config, "runtime")
    value = runtime.get("device")
    if not isinstance(value, str):
        raise LocalRunError("materialized runtime.device is required")
    return value


def _config_sandbox(config: Any) -> dict[str, Any]:
    return _mapping_attr(config, "sandbox")


def _default_run_id(run_group: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{run_group}-{stamp}-{uuid.uuid4().hex[:8]}"
