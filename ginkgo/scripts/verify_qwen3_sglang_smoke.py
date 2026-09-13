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


DEFAULT_EXPECTED_EVIDENCE_BOUNDARY = "live_qwen3_sglang_smoke"
DEFAULT_EXPECTED_MODEL_ID = "Qwen/Qwen3-0.6B"


class VerificationError(RuntimeError):
    pass


PortProbe = Callable[[str, int, float], int]


def verify_manifest(
    manifest_path: Path,
    *,
    expected_evidence_boundary: str = DEFAULT_EXPECTED_EVIDENCE_BOUNDARY,
    expected_generated_text: str | None = None,
    expected_device: str | None = None,
    expected_model_id: str = DEFAULT_EXPECTED_MODEL_ID,
    check_port_closed: bool = True,
    port_probe: PortProbe | None = None,
) -> dict[str, Any]:
    manifest = _load_json_object(manifest_path, "Qwen3 SGLang smoke manifest")
    _require_equal(manifest.get("status"), "passed", "status")
    _require_equal(manifest.get("workload"), "qwen3", "workload")
    _require_equal(manifest.get("evidence_boundary"), expected_evidence_boundary, "evidence_boundary")
    run_id = _require_str(manifest.get("run_id"), "run_id")
    port = _parse_port(manifest.get("port"), "port")
    expected_base_url = f"http://127.0.0.1:{port}/v1"
    _require_equal(manifest.get("openai_base_url"), expected_base_url, "openai_base_url")
    _require_equal(manifest.get("teardown_status"), "teardown_passed", "teardown_status")

    generated_text = _require_str(manifest.get("generated_text"), "generated_text")
    if expected_generated_text is not None:
        _require_equal(generated_text, expected_generated_text, "generated_text")
    device = _require_str(manifest.get("device"), "device")
    if expected_device is not None:
        _require_equal(device, expected_device, "device")

    _require_equal(manifest.get("model_id"), expected_model_id, "model_id")
    served_model_name = _require_str(manifest.get("served_model_name"), "served_model_name")
    expected_model_ids = _require_list(manifest.get("expected_model_ids"), "expected_model_ids")
    if expected_model_id not in expected_model_ids:
        raise VerificationError(f"expected_model_ids does not include {expected_model_id!r}")

    request = _require_mapping(manifest.get("request"), "request")
    _require_equal(request.get("url"), f"{expected_base_url}/chat/completions", "request.url")
    request_payload = _require_mapping(request.get("payload"), "request.payload")
    _require_equal(request_payload.get("model"), served_model_name, "request.payload.model")

    response = _require_mapping(manifest.get("response"), "response")
    _require_equal(response.get("generated_text"), generated_text, "response.generated_text")
    _require_mapping(response.get("payload"), "response.payload")

    models = _require_mapping(manifest.get("models"), "models")
    observed_model_ids = _model_ids(models)
    if expected_model_id not in observed_model_ids:
        raise VerificationError(f"models probe does not include {expected_model_id!r}: {observed_model_ids!r}")

    teardown = _require_mapping(manifest.get("teardown"), "teardown")
    _require_equal(teardown.get("status"), "teardown_passed", "teardown.status")

    if check_port_closed:
        probe = port_probe or _connect_ex
        connect_result = probe("127.0.0.1", port, 1.0)
        if connect_result == 0:
            raise VerificationError(f"serving port is still open after teardown: 127.0.0.1:{port}")

    return {
        "status": "passed",
        "run_id": run_id,
        "port": port,
        "openai_base_url": expected_base_url,
        "generated_text": generated_text,
        "teardown_status": "teardown_passed",
        "evidence_boundary": expected_evidence_boundary,
        "device": device,
        "model_id": expected_model_id,
        "served_model_name": served_model_name,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a Ginkgo Qwen3 SGLang smoke artifact")
    parser.add_argument("manifest_path", type=Path)
    parser.add_argument("--expected-evidence-boundary", default=DEFAULT_EXPECTED_EVIDENCE_BOUNDARY)
    parser.add_argument("--expected-generated-text")
    parser.add_argument("--expected-device", choices=["cpu", "cuda"])
    parser.add_argument("--expected-model-id", default=DEFAULT_EXPECTED_MODEL_ID)
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
            expected_evidence_boundary=args.expected_evidence_boundary,
            expected_generated_text=args.expected_generated_text,
            expected_device=args.expected_device,
            expected_model_id=args.expected_model_id,
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


def _require_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise VerificationError(f"{field} must be a list")
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


def _model_ids(models: dict[str, Any]) -> list[str]:
    observed: list[str] = []
    flat_models = models.get("models")
    if isinstance(flat_models, list):
        observed.extend(item for item in flat_models if isinstance(item, str))
    payload = models.get("payload")
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    observed.append(item["id"])
    return observed


def _connect_ex(host: str, port: int, timeout_seconds: float) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        return sock.connect_ex((host, port))
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
