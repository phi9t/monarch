#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DECLARED_SPEC = REPO_ROOT / "ginkgo" / "configs" / "smoke-qwen3-dense.yaml"
DEFAULT_MANIFEST_NAME = "qwen3-sglang-smoke-evidence.json"
LOG_TAIL_BYTES = 65536


class SmokeError(RuntimeError):
    """Raised when the Qwen3 SGLang smoke contract is invalid."""


def load_runtime_module() -> Any:
    path = REPO_ROOT / "scripts" / "glm52_sglang_runtime.py"
    spec = importlib.util.spec_from_file_location("glm52_sglang_runtime", path)
    if spec is None or spec.loader is None:
        raise SmokeError(f"cannot load runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_smoke(
    *,
    declared_spec: Path,
    local_environment: Path,
    run_id: str | None = None,
    port: int | None = None,
    runtime: Any | None = None,
) -> dict[str, Any]:
    runtime = runtime or load_runtime_module()
    declared = runtime.load_declared_spec(declared_spec)
    _validate_declared_smoke_contract(declared, requested_port=port)
    local_env = runtime.load_local_environment(local_environment)
    selected_run_id = run_id or _default_run_id(_declared_run_group(declared))
    config = runtime.materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id=selected_run_id,
        port=port,
    )
    _validate_materialized_smoke_contract(config)

    paths = _evidence_paths(config)
    paths["run_dir"].mkdir(parents=True, exist_ok=True)
    runtime.write_materialized_config(config, paths["materialized_config"])
    runtime.validate_preparation_records(config=config)

    launch_summary: dict[str, Any] | None = None
    teardown_summary: dict[str, Any] | None = None
    try:
        launch_summary = runtime.launch_runtime(config, local_environment=local_env)
        models = runtime.probe_models(config)
        chat = runtime.probe_chat(config)
    finally:
        if launch_summary is not None:
            teardown_summary = runtime.teardown_runtime(config, local_environment=local_env)

    generated_text = _extract_generated_text(chat)
    if not generated_text:
        raise SmokeError("chat probe returned empty generated text")

    manifest = {
        "schema_version": 1,
        "status": "passed",
        "run_id": _config_run_id(config),
        "run_group": _config_run_group(config),
        "port": _config_port(config),
        "service": _config_service(config),
        "model": _config_model(config),
        "request": {
            "url": _config_probe_url(config, "chat_url"),
            "payload": _config_probe_payload(config, "chat_payload"),
        },
        "response": {
            "generated_text": generated_text,
            "payload": chat.get("payload", chat),
        },
        "models": models,
        "launch": launch_summary,
        "teardown": teardown_summary,
        "logs": {
            "stdout_tail": _read_tail(paths["stdout_log"]),
            "stderr_tail": _read_tail(paths["stderr_log"]),
            "telemetry_tail": _read_tail(paths["telemetry_log"]),
        },
        "artifacts": {
            "run_dir": str(paths["run_dir"]),
            "materialized_config": str(paths["materialized_config"]),
            "manifest": str(paths["manifest"]),
            "stdout_log": str(paths["stdout_log"]),
            "stderr_log": str(paths["stderr_log"]),
            "telemetry_log": str(paths["telemetry_log"]),
        },
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {
        "status": "passed",
        "run_id": _config_run_id(config),
        "port": _config_port(config),
        "generated_text": generated_text,
        "evidence_manifest": paths["manifest"],
    }


def _validate_declared_smoke_contract(declared: Any, *, requested_port: int | None) -> None:
    disallowed = set(_declared_disallowed_ports(declared))
    if {8000, 8080, 18080} - disallowed:
        raise SmokeError("declared smoke config must disallow default fallback ports")
    if requested_port in disallowed:
        raise SmokeError(f"disallowed serving port requested: {requested_port}")
    if requested_port is not None:
        start = _declared_port_range_start(declared)
        end = _declared_port_range_end(declared)
        if requested_port < start or requested_port > end:
            raise SmokeError(f"requested port outside declared run-owned range: {requested_port}")


def _validate_materialized_smoke_contract(config: Any) -> None:
    if _config_port(config) in {8000, 8080, 18080}:
        raise SmokeError(f"disallowed serving port materialized: {_config_port(config)}")
    service = _config_service(config)
    if service.get("base_url") != f"http://127.0.0.1:{_config_port(config)}/v1":
        raise SmokeError("materialized service base_url must use the run-owned localhost port")
    if _config_probe_url(config, "chat_url") != f"http://127.0.0.1:{_config_port(config)}/v1/chat/completions":
        raise SmokeError("materialized chat probe URL must derive from the run-owned service port")


def _evidence_paths(config: Any) -> dict[str, Path]:
    run_dir = _resolve_run_dir(config)
    return {
        "run_dir": run_dir,
        "materialized_config": run_dir / "materialized-sglang-runtime.yaml",
        "manifest": run_dir / DEFAULT_MANIFEST_NAME,
        "stdout_log": run_dir / "logs" / "stdout.log",
        "stderr_log": run_dir / "logs" / "stderr.log",
        "telemetry_log": run_dir / "logs" / "telemetry.jsonl",
    }


def _resolve_run_dir(config: Any) -> Path:
    run_dir = getattr(config, "run_dir", None)
    if isinstance(run_dir, Path):
        return run_dir
    host_layout = _mapping_attr(config, "host_layout")
    resolved_paths = _mapping_attr(config, "resolved_paths")
    logical = str(host_layout.get("run_dir", ""))
    if not logical.startswith("repo://"):
        raise SmokeError("materialized host_layout.run_dir must use repo://")
    repo = resolved_paths.get("repo")
    if not isinstance(repo, str) or not repo.startswith("/"):
        raise SmokeError("materialized resolved_paths.repo must be an absolute host path")
    return Path(repo) / logical.removeprefix("repo://")


def _read_tail(path: Path) -> str:
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > LOG_TAIL_BYTES:
            handle.seek(size - LOG_TAIL_BYTES)
        return handle.read().decode("utf-8", errors="replace")


def _extract_generated_text(chat: dict[str, Any]) -> str:
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


def _mapping_attr(value: Any, name: str) -> dict[str, Any]:
    item = getattr(value, name)
    if not isinstance(item, dict):
        raise SmokeError(f"materialized {name} must be a mapping")
    return item


def _config_run_id(config: Any) -> str:
    return str(getattr(config, "run_id"))


def _config_run_group(config: Any) -> str:
    run_group = getattr(config, "run_group", None)
    if not isinstance(run_group, str) or not run_group:
        raise SmokeError("materialized run_group is required")
    return run_group


def _config_port(config: Any) -> int:
    port = getattr(config, "port", None)
    if isinstance(port, int):
        return port
    service = _mapping_attr(config, "service")
    value = service.get("port")
    if not isinstance(value, int):
        raise SmokeError("materialized service.port must be an integer")
    return value


def _config_service(config: Any) -> dict[str, Any]:
    return _mapping_attr(config, "service")


def _config_model(config: Any) -> dict[str, Any]:
    return _mapping_attr(config, "model")


def _config_probe_url(config: Any, key: str) -> str:
    probes = _mapping_attr(config, "probes")
    value = probes.get(key)
    if not isinstance(value, str) or not value:
        raise SmokeError(f"materialized probes.{key} is required")
    return value


def _config_probe_payload(config: Any, key: str) -> dict[str, Any]:
    probes = _mapping_attr(config, "probes")
    value = probes.get(key)
    if isinstance(value, dict):
        return dict(value)
    raise SmokeError(f"materialized probes.{key} is required")


def _declared_run_group(declared: Any) -> str:
    return str(getattr(declared, "run_group"))


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


def _default_run_id(run_group: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{run_group}-{stamp}-{uuid.uuid4().hex[:8]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Ginkgo Qwen3 dense SGLang serving smoke")
    parser.add_argument("--declared-spec", type=Path, default=DEFAULT_DECLARED_SPEC)
    parser.add_argument("--local-environment", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--port", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_smoke(
            declared_spec=args.declared_spec,
            local_environment=args.local_environment,
            run_id=args.run_id,
            port=args.port,
        )
    except SmokeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({**result, "evidence_manifest": str(result["evidence_manifest"])}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
