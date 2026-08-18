from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "ginkgo" / "scripts" / "verify_qwen3_sglang_smoke.py"

spec = importlib.util.spec_from_file_location("verify_qwen3_sglang_smoke", VERIFIER)
assert spec is not None
assert spec.loader is not None
verify_qwen3_sglang_smoke = importlib.util.module_from_spec(spec)
sys.modules["verify_qwen3_sglang_smoke"] = verify_qwen3_sglang_smoke
spec.loader.exec_module(verify_qwen3_sglang_smoke)


def test_verify_qwen3_sglang_smoke_accepts_passed_cuda_artifact(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)

    result = verify_qwen3_sglang_smoke.verify_manifest(
        manifest,
        expected_generated_text="Sure!",
        expected_device="cuda",
        port_probe=lambda host, port, timeout: 111,
    )

    assert result == {
        "status": "passed",
        "run_id": "qwen3-dense-onegpu-verified",
        "port": 19007,
        "openai_base_url": "http://127.0.0.1:19007/v1",
        "generated_text": "Sure!",
        "teardown_status": "teardown_passed",
        "evidence_boundary": "live_qwen3_sglang_smoke",
        "device": "cuda",
        "model_id": "Qwen/Qwen3-0.6B",
        "served_model_name": "Qwen/Qwen3-0.6B",
    }


def test_verify_qwen3_sglang_smoke_requires_evidence_boundary(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, evidence_boundary=None)

    with pytest.raises(verify_qwen3_sglang_smoke.VerificationError, match="evidence_boundary mismatch"):
        verify_qwen3_sglang_smoke.verify_manifest(manifest, port_probe=lambda host, port, timeout: 111)


def test_verify_qwen3_sglang_smoke_checks_generated_text(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)

    with pytest.raises(verify_qwen3_sglang_smoke.VerificationError, match="generated_text mismatch"):
        verify_qwen3_sglang_smoke.verify_manifest(
            manifest,
            expected_generated_text="Different",
            port_probe=lambda host, port, timeout: 111,
        )


def test_verify_qwen3_sglang_smoke_rejects_open_serving_port(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)

    with pytest.raises(verify_qwen3_sglang_smoke.VerificationError, match="serving port is still open"):
        verify_qwen3_sglang_smoke.verify_manifest(manifest, port_probe=lambda host, port, timeout: 0)


def test_verify_qwen3_sglang_smoke_cli_reports_passed_artifact(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            str(manifest),
            "--expected-generated-text",
            "Sure!",
            "--expected-device",
            "cuda",
            "--skip-port-closed-check",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["generated_text"] == "Sure!"
    assert payload["device"] == "cuda"


def _write_manifest(
    tmp_path: Path,
    *,
    evidence_boundary: str | None = "live_qwen3_sglang_smoke",
) -> Path:
    payload = {
        "schema_version": 1,
        "status": "passed",
        "run_id": "qwen3-dense-onegpu-verified",
        "run_group": "ginkgo-smoke-qwen3-dense",
        "workload": "qwen3",
        "evidence_boundary": evidence_boundary,
        "device": "cuda",
        "port": 19007,
        "openai_base_url": "http://127.0.0.1:19007/v1",
        "model_id": "Qwen/Qwen3-0.6B",
        "served_model_name": "Qwen/Qwen3-0.6B",
        "expected_model_ids": ["Qwen/Qwen3-0.6B"],
        "generated_text": "Sure!",
        "teardown_status": "teardown_passed",
        "model": {
            "id": "Qwen/Qwen3-0.6B",
            "served_model_name": "Qwen/Qwen3-0.6B",
            "expected_model_ids": ["Qwen/Qwen3-0.6B"],
        },
        "service": {
            "base_url": "http://127.0.0.1:19007/v1",
            "port": 19007,
        },
        "request": {
            "url": "http://127.0.0.1:19007/v1/chat/completions",
            "payload": {"model": "Qwen/Qwen3-0.6B"},
        },
        "response": {
            "generated_text": "Sure!",
            "payload": {"choices": [{"message": {"content": "Sure!"}}]},
        },
        "models": {
            "models": ["Qwen/Qwen3-0.6B"],
            "payload": {"data": [{"id": "Qwen/Qwen3-0.6B"}]},
        },
        "teardown": {"status": "teardown_passed"},
    }
    path = tmp_path / "qwen3-sglang-smoke-evidence.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path
