#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any
from typing import Callable

from ginkgo.scripts import verify_qwen3_sglang_smoke


DEFAULT_EXPECTED_EXECUTION_MODE = "monarch-actor-control"
DEFAULT_EXPECTED_EVIDENCE_BOUNDARY = "live_qwen3_in_process_actor_smoke"
DEFAULT_EXPECTED_CHILD_EVIDENCE_BOUNDARY = "live_qwen3_sglang_smoke"
DEFAULT_EXPECTED_CHILD_MODEL_ID = "Qwen/Qwen3-0.6B"
DEFAULT_EXPECTED_CHILD_DEVICE = "cpu"
DEFAULT_COMPONENT = "sglang_backend"


class VerificationError(RuntimeError):
    pass


PortProbe = Callable[[str, int, float], int]


def verify_manifest(
    manifest_path: Path,
    *,
    expected_execution_mode: str = DEFAULT_EXPECTED_EXECUTION_MODE,
    expected_evidence_boundary: str = DEFAULT_EXPECTED_EVIDENCE_BOUNDARY,
    expected_child_evidence_boundary: str = DEFAULT_EXPECTED_CHILD_EVIDENCE_BOUNDARY,
    expected_child_model_id: str = DEFAULT_EXPECTED_CHILD_MODEL_ID,
    expected_child_device: str = DEFAULT_EXPECTED_CHILD_DEVICE,
    expected_generated_text: str | None = None,
    component_name: str = DEFAULT_COMPONENT,
    check_port_closed: bool = True,
    port_probe: PortProbe | None = None,
) -> dict[str, Any]:
    parent = _load_json_object(manifest_path, "parent manifest")
    _require_equal(parent.get("status"), "passed", "parent status")
    _require_equal(parent.get("execution_mode"), expected_execution_mode, "execution_mode")
    _require_equal(parent.get("evidence_boundary"), expected_evidence_boundary, "evidence_boundary")
    run_id = _require_str(parent.get("run_id"), "parent run_id")

    actor_status = _require_mapping(parent.get("actor_status"), "actor_status")
    _require_equal(actor_status.get("status"), "passed", "actor_status.status")
    _require_equal(actor_status.get("phase"), "probe:sglang_backend", "actor_status.phase")
    _require_equal(actor_status.get("teardown_errors"), [], "actor_status.teardown_errors")
    completed_components = actor_status.get("completed_components")
    if completed_components != [component_name]:
        raise VerificationError(f"actor_status.completed_components mismatch: {completed_components!r}")

    components = _require_mapping(parent.get("components"), "components")
    component = _require_mapping(components.get(component_name), f"components.{component_name}")
    _require_equal(component.get("status"), "passed", f"components.{component_name}.status")
    if component.get("teardown_status") != "teardown_passed":
        raise VerificationError("component teardown_status must be teardown_passed")
    child_run_id = _require_str(component.get("run_id"), f"components.{component_name}.run_id")
    if child_run_id != f"{run_id}-{component_name}":
        raise VerificationError(f"component run_id mismatch: {child_run_id!r}")
    port = _parse_port(component.get("port"), f"components.{component_name}.port")
    expected_base_url = f"http://127.0.0.1:{port}/v1"
    _require_equal(component.get("openai_base_url"), expected_base_url, f"components.{component_name}.openai_base_url")
    generated_text = _require_str(component.get("generated_text"), f"components.{component_name}.generated_text")
    if expected_generated_text is not None and generated_text != expected_generated_text:
        raise VerificationError(f"generated_text mismatch: {generated_text!r}")

    child_manifest_path = Path(
        _require_str(component.get("evidence_manifest"), f"components.{component_name}.evidence_manifest")
    )
    child_verification = _verify_child_manifest(
        child_manifest_path,
        expected_child_evidence_boundary=expected_child_evidence_boundary,
        expected_child_model_id=expected_child_model_id,
        expected_child_device=expected_child_device,
        expected_generated_text=generated_text,
        check_port_closed=False,
        port_probe=port_probe,
    )
    child = _load_json_object(child_manifest_path, "child evidence manifest")
    _require_equal(child.get("run_id"), child_run_id, "child run_id")
    _require_equal(child.get("port"), port, "child port")
    _require_equal(child.get("openai_base_url"), expected_base_url, "child openai_base_url")
    _require_equal(child.get("generated_text"), generated_text, "child generated_text")
    child_teardown_status = child.get("teardown_status")
    if child_teardown_status is None:
        teardown = _require_mapping(child.get("teardown"), "child teardown")
        child_teardown_status = teardown.get("status")
    _require_equal(child_teardown_status, "teardown_passed", "child teardown_status")

    if check_port_closed:
        probe = port_probe or _connect_ex
        connect_result = probe("127.0.0.1", port, 1.0)
        if connect_result == 0:
            raise VerificationError(f"serving port is still open after teardown: 127.0.0.1:{port}")

    return {
        "status": "passed",
        "run_id": run_id,
        "component": component_name,
        "child_run_id": child_run_id,
        "port": port,
        "generated_text": generated_text,
        "teardown_status": "teardown_passed",
        "evidence_boundary": expected_evidence_boundary,
        "child_evidence_boundary": expected_child_evidence_boundary,
        "child_model_id": child_verification["model_id"],
        "child_device": child_verification["device"],
        "execution_mode": expected_execution_mode,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a Ginkgo Qwen3 Monarch control-plane smoke artifact")
    parser.add_argument("manifest_path", type=Path)
    parser.add_argument("--expected-execution-mode", default=DEFAULT_EXPECTED_EXECUTION_MODE)
    parser.add_argument("--expected-evidence-boundary", default=DEFAULT_EXPECTED_EVIDENCE_BOUNDARY)
    parser.add_argument("--expected-child-evidence-boundary", default=DEFAULT_EXPECTED_CHILD_EVIDENCE_BOUNDARY)
    parser.add_argument("--expected-child-model-id", default=DEFAULT_EXPECTED_CHILD_MODEL_ID)
    parser.add_argument("--expected-child-device", choices=["cpu", "cuda"], default=DEFAULT_EXPECTED_CHILD_DEVICE)
    parser.add_argument("--expected-generated-text")
    parser.add_argument("--component", default=DEFAULT_COMPONENT)
    parser.add_argument(
        "--skip-port-closed-check",
        action="store_true",
        help="skip the post-teardown localhost port probe",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_manifest(
            args.manifest_path,
            expected_execution_mode=args.expected_execution_mode,
            expected_evidence_boundary=args.expected_evidence_boundary,
            expected_child_evidence_boundary=args.expected_child_evidence_boundary,
            expected_child_model_id=args.expected_child_model_id,
            expected_child_device=args.expected_child_device,
            expected_generated_text=args.expected_generated_text,
            component_name=args.component,
            check_port_closed=not args.skip_port_closed_check,
        )
    except VerificationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except OSError as error:
        raise VerificationError(f"{label} cannot be read: {path}") from error
    except json.JSONDecodeError as error:
        raise VerificationError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise VerificationError(f"{label} must be a JSON object: {path}")
    return payload


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{field} must be a mapping")
    return value


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise VerificationError(f"{field} must be a non-empty string")
    return value


def _require_equal(actual: object, expected: object, field: str) -> None:
    if actual != expected:
        raise VerificationError(f"{field} mismatch: expected {expected!r}, got {actual!r}")


def _parse_port(value: object, field: str) -> int:
    if isinstance(value, int):
        port = value
    elif isinstance(value, str) and value.isdigit():
        port = int(value)
    else:
        raise VerificationError(f"{field} must be an integer port")
    if port <= 0 or port > 65535:
        raise VerificationError(f"{field} is outside TCP port range: {port}")
    return port


def _verify_child_manifest(
    manifest_path: Path,
    *,
    expected_child_evidence_boundary: str,
    expected_child_model_id: str,
    expected_child_device: str,
    expected_generated_text: str,
    check_port_closed: bool,
    port_probe: PortProbe | None,
) -> dict[str, Any]:
    try:
        return verify_qwen3_sglang_smoke.verify_manifest(
            manifest_path,
            expected_evidence_boundary=expected_child_evidence_boundary,
            expected_generated_text=expected_generated_text,
            expected_device=expected_child_device,
            expected_model_id=expected_child_model_id,
            check_port_closed=check_port_closed,
            port_probe=port_probe,
        )
    except verify_qwen3_sglang_smoke.VerificationError as error:
        raise VerificationError(f"child artifact verification failed: {error}") from error


def _connect_ex(host: str, port: int, timeout_seconds: float) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        return sock.connect_ex((host, port))
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
