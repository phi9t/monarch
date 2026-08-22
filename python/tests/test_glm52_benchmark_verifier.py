# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import importlib.util
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path

import pytest


HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "glm52_benchmark_verifier.py"
)
spec = importlib.util.spec_from_file_location("glm52_benchmark_verifier", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_benchmark_verifier = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_benchmark_verifier
spec.loader.exec_module(glm52_benchmark_verifier)

write_bwrap_smoke_summary = glm52_benchmark_verifier.write_bwrap_smoke_summary
validate_conformance_inputs = glm52_benchmark_verifier.validate_conformance_inputs
write_fixture_benchmark_run = glm52_benchmark_verifier.write_fixture_benchmark_run
write_harbor_environment_failure = (
    glm52_benchmark_verifier.write_harbor_environment_failure
)
load_harbor_smoke_config = glm52_benchmark_verifier.load_harbor_smoke_config
write_harbor_smoke_config_artifact = (
    glm52_benchmark_verifier.write_harbor_smoke_config_artifact
)
write_harbor_run_state = glm52_benchmark_verifier.write_harbor_run_state
write_harbor_success_summary = glm52_benchmark_verifier.write_harbor_success_summary
validate_manifest_suite_coverage = glm52_benchmark_verifier.validate_manifest_suite_coverage
validate_prepare_manifest_revisions = (
    glm52_benchmark_verifier.validate_prepare_manifest_revisions
)
write_prepare_artifact = glm52_benchmark_verifier.write_prepare_artifact
write_bwrap_codegen_smoke_run = glm52_benchmark_verifier.write_bwrap_codegen_smoke_run
extract_static_final_answer = glm52_benchmark_verifier.extract_static_final_answer
score_static_fixture_sample = glm52_benchmark_verifier.score_static_fixture_sample
build_gold_path_preflight = glm52_benchmark_verifier.build_gold_path_preflight
build_cache_preflight = glm52_benchmark_verifier.build_cache_preflight
materialize_prepare_caches = glm52_benchmark_verifier.materialize_prepare_caches
build_image_preflight = glm52_benchmark_verifier.build_image_preflight
resolve_swe_bench_smoke_image_metadata = (
    glm52_benchmark_verifier.resolve_swe_bench_smoke_image_metadata
)
build_parser = glm52_benchmark_verifier.build_parser
load_yaml_object = glm52_benchmark_verifier.load_yaml_object
select_suites = glm52_benchmark_verifier.select_suites
validate_suite_fields = glm52_benchmark_verifier.validate_suite_fields


REQUIRED_FIXTURE_SUITE_IDS = [
    "gsm8k",
    "aime",
    "humaneval",
    "mbpp",
    "terminal-bench-2",
    "swe-bench-verified",
    "ruler",
    "needle-smoke",
]
HARBOR_FIXTURE_REVISION = "9dd349f28b969268aef419e910e1998149b612a5"
TERMINAL_BENCH_FIXTURE_REVISION = "d28711d0da2675d0bb1d56de45ae5df6082438a3"
HARBOR_TERMINAL_BENCH_DATASET = "terminal-bench"
HARBOR_TERMINAL_BENCH_DATASET_VERSION = "2.0"
HARBOR_TERMINAL_BENCH_SMOKE_TASK = "adaptive-rejection-sampler"
SWEBENCH_VERIFIED_HF_DATASET_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
SWEBENCH_HARNESS_REVISION = "4e6126978a16bdfebc6538db8f28cacc2c8b77dc"
SWEBENCH_SMOKE_INSTANCE = "astropy__astropy-12907"
SWEBENCH_SMOKE_ROW_IMAGE = (
    "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"
)
SWEBENCH_SMOKE_IMAGE_DIGEST = (
    "docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907@sha256:"
    "483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_glm52_benchmark_verifier_script_help_runs_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(HELPER_PATH), "--help"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout


class _JsonModelsResponse:
    def __enter__(self) -> "_JsonModelsResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def read(self) -> bytes:
        return b'{"data": [{"id": "zai-org/GLM-5.2"}]}'


class _JsonResponsesResponse:
    def __enter__(self) -> "_JsonResponsesResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def read(self) -> bytes:
        return b'{"id": "resp-test", "output_text": "OK", "usage": {}}'


def test_post_responses_request_uses_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> _JsonResponsesResponse:
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        return _JsonResponsesResponse()

    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)

    response = glm52_benchmark_verifier._post_responses_request(
        responses_base_url="http://127.0.0.1:18081/v1",
        model="zai-org/GLM-5.2",
        prompt="Say OK.",
        decoding_profile={"temperature": 0, "top_p": 1, "max_output_tokens": 1},
        timeout_seconds=180.0,
    )

    assert observed == {
        "url": "http://127.0.0.1:18081/v1/responses",
        "timeout": 180.0,
    }
    assert response["output_text"] == "OK"


def _patch_healthy_responses_models_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(url: str, *, timeout: float) -> _JsonModelsResponse:
        assert url == "http://host.docker.internal:8080/v1/models"
        assert timeout == 2.0
        return _JsonModelsResponse()

    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)


def _simulate_host_control_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONARCH_IN_ROOTFS", raising=False)


@pytest.fixture
def fake_responses_server() -> object:
    class FakeResponsesHandler(http.server.BaseHTTPRequestHandler):
        requests: list[dict[str, object]] = []
        status_code = 200
        output_text = "ORCHID-7194"

        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length))
            self.__class__.requests.append({"path": self.path, "payload": payload})
            if self.__class__.status_code != 200:
                self.send_response(self.__class__.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "responses unavailable"}}')
                return
            body = {
                "id": f"resp-{len(self.__class__.requests)}",
                "output_text": self.__class__.output_text,
                "usage": {
                    "input_tokens": 17,
                    "output_tokens": 3,
                    "total_tokens": 20,
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *_args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), FakeResponsesHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class FakeResponsesServer:
        url = f"http://127.0.0.1:{server.server_port}/v1"
        handler = FakeResponsesHandler

        @property
        def requests(self) -> list[dict[str, object]]:
            return self.handler.requests

        def fail_responses(self) -> None:
            self.handler.status_code = 503

        def set_output_text(self, output_text: str) -> None:
            self.handler.output_text = output_text

    try:
        yield FakeResponsesServer()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _write_gsm8k_cache_and_manifest(tmp_path: Path) -> Path:
    dataset_cache = tmp_path / "benchmarks" / "datasets" / "gsm8k"
    dataset_cache.mkdir(parents=True)
    (dataset_cache / "samples.jsonl").write_text(
        json.dumps(
            {
                "id": "gsm8k-local-0001",
                "question": "What is 40 plus 2?",
                "answer": "40 + 2 = 42\n#### 42",
            }
        )
        + "\n"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                "  - id: gsm8k",
                "    profile: math-reasoning-thinking-disabled",
                "    dataset_revision: openai/gsm8k@local-fixture",
                "    harness_revision: fixture-harness",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "      top_p: 1",
                "      max_output_tokens: 256",
                "      glm_thinking: disabled",
                "    metric: exact_match_final_answer",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_cache}",
                "      revision: local-fixture",
                "      sha256: gsm8k-local-fixture-sha",
                "  - id: aime",
                "    profile: math-reasoning-thinking-enabled",
                "    dataset_revision: aime@fixture-2024",
                "    harness_revision: fixture-harness",
                "    prompt_template: aime-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
            ]
        )
        + "\n"
    )
    return manifest_path


def _write_aime_cache_and_manifest(tmp_path: Path) -> Path:
    dataset_cache = tmp_path / "benchmarks" / "datasets" / "aime"
    dataset_cache.mkdir(parents=True)
    (dataset_cache / "samples.jsonl").write_text(
        json.dumps(
            {
                "id": "aime-local-0001",
                "problem": "Find the integer answer to this local AIME problem.",
                "answer": "42",
            }
        )
        + "\n"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                "  - id: aime",
                "    profile: math-reasoning-thinking-enabled",
                "    dataset_revision: aime@local-fixture",
                "    harness_revision: fixture-harness",
                "    prompt_template: aime-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "      top_p: 1",
                "      max_output_tokens: 256",
                "      glm_thinking: enabled",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_cache}",
                "      revision: local-fixture",
                "      sha256: aime-local-fixture-sha",
                "  - id: gsm8k",
                "    profile: math-reasoning-thinking-disabled",
                "    dataset_revision: openai/gsm8k@fixture",
                "    harness_revision: fixture-harness",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match_final_answer",
            ]
        )
        + "\n"
    )
    return manifest_path


def _write_ruler_cache_and_manifest(tmp_path: Path) -> Path:
    dataset_cache = tmp_path / "benchmarks" / "datasets" / "ruler"
    dataset_cache.mkdir(parents=True)
    (dataset_cache / "samples.jsonl").write_text(
        json.dumps(
            {
                "id": "ruler-local-0001",
                "prompt": "Read the context and answer the question exactly.",
                "context": "Operational note: the deployment cleanup token is ORCHID-7194.",
                "question": "What is the deployment cleanup token?",
                "expected_answer": "ORCHID-7194",
                "needle": "deployment cleanup token",
                "key": "deployment_cleanup_token",
            }
        )
        + "\n"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                "  - id: ruler",
                "    profile: long-context",
                "    dataset_revision: ruler@local-fixture",
                "    harness_revision: lm-evaluation-harness@fixture",
                "    prompt_template: ruler-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "      top_p: 1",
                "      max_output_tokens: 256",
                "      glm_thinking: disabled",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_cache}",
                "      revision: local-fixture",
                "      sha256: ruler-local-fixture-sha",
                "  - id: gsm8k",
                "    profile: math-reasoning-thinking-disabled",
                "    dataset_revision: openai/gsm8k@fixture",
                "    harness_revision: fixture-harness",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match_final_answer",
            ]
        )
        + "\n"
    )
    return manifest_path


def _write_humaneval_manifest(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: humaneval",
                "    profile: coding-benchmark",
                "    dataset_revision: fixture-human-eval",
                "    harness_revision: fixture-harness",
                "    prompt_template: humaneval-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "    metric: pass@1",
            ]
        )
        + "\n"
    )


def _write_mbpp_manifest(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: mbpp",
                "    profile: coding-benchmark",
                "    dataset_revision: fixture-mbpp",
                "    harness_revision: fixture-harness",
                "    prompt_template: mbpp-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "    metric: pass@1",
            ]
        )
        + "\n"
    )


def _write_humaneval_mbpp_manifest(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: humaneval",
                "    profile: coding-benchmark",
                "    dataset_revision: fixture-human-eval",
                "    harness_revision: fixture-harness",
                "    prompt_template: humaneval-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "    metric: pass@1",
                "  - id: mbpp",
                "    profile: coding-benchmark",
                "    dataset_revision: fixture-mbpp",
                "    harness_revision: fixture-harness",
                "    prompt_template: mbpp-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "    metric: pass@1",
            ]
        )
        + "\n"
    )


def test_swe_bench_verified_harbor_smoke_config_pins_single_row_image() -> None:
    manifest = load_yaml_object(
        REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
    )
    manifest_suite = next(
        suite for suite in manifest["suites"] if suite["id"] == "swe-bench-verified"
    )
    config_path = (
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
    )
    lock_path = (
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/datasets/swe-bench-verified.lock.yaml"
    )

    assert config_path.is_file()
    assert lock_path.is_file()

    config = load_yaml_object(config_path)
    lock = load_yaml_object(lock_path)
    for document in [config, lock]:
        assert document["suite"] == "swe-bench-verified"
        assert document["status"] == "ready"
        assert document["runnable"] is True
        assert document["conformance"]["claim"] == "none"
        assert document["conformance"]["comparable_to_published"] is False
        assert "published score" not in document
        assert "score" not in document.get("conformance", {})

    assert config["execution"]["harness"] == "harbor"
    assert config["execution"]["execution_backend"] == "harbor_local_docker"
    assert config["execution"]["docker"] == "required"
    assert config["dataset_source"] == manifest_suite["dataset_source"]
    assert config["harness_source"] == manifest_suite["harness_source"]
    assert lock["dataset_source"] == manifest_suite["dataset_source"]
    assert lock["harness_source"] == manifest_suite["harness_source"]
    assert config["subset"]["smoke_instances"] == ["astropy__astropy-12907"]
    assert lock["smoke_instances"] == ["astropy__astropy-12907"]
    row_image = "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"
    image_digest = (
        "docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907"
        "@sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88"
    )
    assert lock["official_images"] == {
        "status": "resolved",
        "provider": "swebench",
        "per_instance_images": [
            {
                "instance_id": "astropy__astropy-12907",
                "row_image": row_image,
                "image_digest": image_digest,
            }
        ],
    }
    assert resolve_swe_bench_smoke_image_metadata(config, lock) == [
        {
            "suite": "swe-bench-verified",
            "status": "pass",
            "instance_id": "astropy__astropy-12907",
            "row_image": row_image,
            "image_digest": image_digest,
            "provider_namespace": "swebench",
            "source_revision": SWEBENCH_VERIFIED_HF_DATASET_REVISION,
        }
    ]


def test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct() -> None:
    manifest = load_yaml_object(
        REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
    )
    manifest_suite = next(
        suite for suite in manifest["suites"] if suite["id"] == "swe-bench-verified"
    )

    assert (
        manifest_suite["dataset_revision"]
        == f"SWE-bench/SWE-bench_Verified@{SWEBENCH_VERIFIED_HF_DATASET_REVISION}"
    )
    assert manifest_suite["dataset_source"]["revision"] == SWEBENCH_VERIFIED_HF_DATASET_REVISION
    assert manifest_suite["harness_revision"] == f"swebench@{SWEBENCH_HARNESS_REVISION}"
    assert manifest_suite["harness_source"]["revision"] == SWEBENCH_HARNESS_REVISION
    validate_prepare_manifest_revisions({"suites": [manifest_suite]})


def test_write_bwrap_smoke_summary_records_contract_artifacts(tmp_path: Path) -> None:
    smoke_artifact = tmp_path / "run" / "task-001" / "output" / "smoke-artifact.json"
    smoke_artifact.parent.mkdir(parents=True)
    smoke_artifact.write_text(
        json.dumps(
            {
                "task_id": "task-001",
                "work_write": "pass",
                "output_write": "pass",
                "checkout_write": "denied",
                "network": "denied",
            }
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )
    cleanup_ledger = tmp_path / "cleanup.json"
    cleanup_ledger.write_text('{"schema_version": 1, "bwrap_tasks": []}\n')

    summary_path = write_bwrap_smoke_summary(
        results_root=tmp_path / "results",
        run_id="bwrap-smoke-test",
        smoke_result={
            "status": "pass",
            "run_id": "bwrap-smoke-test",
            "task_id": "task-001",
            "artifact": str(smoke_artifact),
            "cleanup_ledger": str(cleanup_ledger),
        },
    )

    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "pass"
    assert summary["suite"] == "bwrap-sandbox-smoke"
    assert summary["execution_backend"] == "bwrap_rootfs"
    assert summary["contract_artifacts"]["smoke_artifact"] == "artifacts/smoke-artifact.json"
    assert summary["contract_artifacts"]["cleanup_ledger"] == "artifacts/cleanup.json"
    archive_manifest = json.loads(
        (summary_path.parent / "archive-manifest.json").read_text()
    )
    assert archive_manifest["summary_status"] == "pass"
    assert archive_manifest["summary_path"] == "summary.json"
    assert "summary.json" in archive_manifest["contract_artifacts"]
    assert "artifacts/smoke-artifact.json" in archive_manifest["contract_artifacts"]
    assert "artifacts/cleanup.json" in archive_manifest["contract_artifacts"]
    assert json.loads((summary_path.parent / "artifacts" / "smoke-artifact.json").read_text())[
        "checkout_write"
    ] == "denied"
    assert json.loads((summary_path.parent / "artifacts" / "cleanup.json").read_text())[
        "schema_version"
    ] == 1


def test_write_fixture_benchmark_run_emits_required_artifacts(tmp_path: Path) -> None:
    manifest = {
        "suites": [
            {
                "id": "needle-smoke",
                "profile": "long-context-smoke",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "needle-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }
    published_scores = {"scores": []}

    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="smoke-test",
        mode="calibration",
        suite_ids=["needle-smoke"],
        manifest=manifest,
        published_scores=published_scores,
        execution_backend="bwrap_rootfs",
    )

    result_dir = summary_path.parent
    assert (result_dir / "run.json").is_file()
    assert (result_dir / "evalrun-state.json").is_file()
    assert (result_dir / "environment.json").is_file()
    assert (result_dir / "benchmark-manifest.json").is_file()
    assert (result_dir / "published-scores.json").is_file()
    assert (result_dir / "summary.json").is_file()
    assert (result_dir / "archive-manifest.json").is_file()
    assert (result_dir / "needle-smoke" / "samples.jsonl").is_file()
    assert (result_dir / "needle-smoke" / "metrics.json").is_file()
    assert (result_dir / "needle-smoke" / "failures.jsonl").is_file()
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "pass"
    assert summary["mode"] == "calibration"
    assert summary["suites"][0]["model_failures"] == 0
    assert summary["suites"][0]["infrastructure_failures"] == 0
    assert summary["suites"][0]["infrastructure_failure_denominator"] == 3
    assert summary["suites"][0]["infrastructure_failure_rate"] == 0.0
    metrics = json.loads((result_dir / "needle-smoke" / "metrics.json").read_text())
    assert metrics["infrastructure_failure_denominator"] == 3
    assert metrics["infrastructure_failure_rate"] == 0.0
    sample = json.loads(
        (result_dir / "needle-smoke" / "samples.jsonl").read_text().splitlines()[0]
    )
    assert sample["profile"] == "long-context-smoke"
    assert sample["decoding_profile"] == {"temperature": 0}
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["run_id"] == "smoke-test"
    assert archive_manifest["summary_status"] == "pass"
    assert archive_manifest["summary_path"] == "summary.json"
    assert "evalrun-state.json" in archive_manifest["contract_artifacts"]
    assert "needle-smoke/samples.jsonl" in archive_manifest["contract_artifacts"]
    assert "needle-smoke/metrics.json" in archive_manifest["contract_artifacts"]
    state = json.loads((result_dir / "evalrun-state.json").read_text())
    run_record = json.loads((result_dir / "run.json").read_text())
    assert state["manifest_sha256"] == run_record["manifest_sha256"]
    assert state["campaign_materialization"]["status"] == "completed"
    assert state["suite_preparation"]["needle-smoke"]["status"] == "completed"
    assert state["trial_generation"]["needle-smoke"]["status"] == "completed"
    assert state["grading"]["needle-smoke"]["status"] == "completed"
    assert state["suite_summary"]["needle-smoke"]["status"] == "pass"
    assert state["campaign_summary"]["status"] == "pass"


def test_write_fixture_benchmark_run_records_serving_inputs(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "needle-smoke",
                "profile": "long-context-smoke",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "needle-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }

    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="serving-inputs",
        mode="smoke",
        suite_ids=["needle-smoke"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
        serving_summary_path=tmp_path / "serving" / "summary.json",
        responses_base_url="http://127.0.0.1:8080/v1",
        chat_base_url="http://127.0.0.1:8000/v1",
    )

    result_run = json.loads((summary_path.parent / "run.json").read_text())
    root_run = json.loads((tmp_path / "run" / "benchmark-serving-inputs.json").read_text())
    expected = {
        "serving_summary_path": str(tmp_path / "serving" / "summary.json"),
        "responses_base_url": "http://127.0.0.1:8080/v1",
        "chat_base_url": "http://127.0.0.1:8000/v1",
    }
    for key, value in expected.items():
        assert result_run[key] == value
        assert root_run[key] == value


def test_write_fixture_benchmark_run_writes_run_lock(tmp_path: Path) -> None:
    manifest = {
        "suites": [
            {
                "id": "needle-smoke",
                "profile": "long-context-smoke",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "needle-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }

    write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="run-lock",
        mode="smoke",
        suite_ids=["needle-smoke"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    lock = json.loads((tmp_path / "run" / "benchmark-run-lock.lock").read_text())
    assert lock["schema_version"] == 1
    assert lock["run_id"] == "run-lock"
    assert lock["mode"] == "smoke"
    assert lock["status"] == "completed"
    assert lock["benchmark_state_path"] == str(
        tmp_path / "run" / "benchmark-run-lock.json"
    )
    assert lock["cleanup_state_path"] == str(tmp_path / "run" / "cleanup-run-lock.json")
    assert lock["result_dir"] == str(tmp_path / "results" / "run-lock")
    assert lock["pid"] > 0


def test_archive_manifest_records_contract_artifact_hashes(tmp_path: Path) -> None:
    manifest = {
        "suites": [
            {
                "id": "needle-smoke",
                "profile": "long-context-smoke",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "needle-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }

    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="archive-hashes",
        mode="smoke",
        suite_ids=["needle-smoke"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    archive_manifest = json.loads(
        (summary_path.parent / "archive-manifest.json").read_text()
    )
    hashes = archive_manifest["contract_artifact_sha256"]
    assert set(hashes) == set(archive_manifest["contract_artifacts"])
    assert hashes["summary.json"]
    assert hashes["needle-smoke/samples.jsonl"]


def test_fixture_benchmark_run_rejects_host_subprocess_backend(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "needle-smoke",
                "profile": "long-context-smoke",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "needle-v1",
                "execution_backend": "host_subprocess",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }

    try:
        write_fixture_benchmark_run(
            results_root=tmp_path / "results",
            run_root=tmp_path / "run",
            run_id="host-subprocess-smoke",
            mode="smoke",
            suite_ids=["needle-smoke"],
            manifest=manifest,
            published_scores=None,
            execution_backend="host_subprocess",
        )
    except Exception as error:
        assert "host_subprocess" in str(error)
        assert "trusted preparation and scoring" in str(error)
    else:
        raise AssertionError("host_subprocess should not run benchmark fixtures")


def test_smoke_command_supports_scripts_run_fixture_backend(tmp_path: Path) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: ruler",
                "    profile: long-context",
                "    dataset_revision: ruler@fixture",
                "    harness_revision: fixture@rev",
                "    prompt_template: ruler-v1",
                "    execution_backend: scripts_run",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "  - id: gsm8k",
                "    profile: fixture",
                "    dataset_revision: gsm8k@fixture",
                "    harness_revision: fixture@rev",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: scripts_run",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
            ]
        )
        + "\n"
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "ruler",
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "scripts_run",
            "--run-id",
            "scripts-run-smoke",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "scripts-run-smoke"
    summary = json.loads((result_dir / "summary.json").read_text())
    run_state = json.loads((tmp_path / "run" / "benchmark-scripts-run-smoke.json").read_text())
    assert summary["execution_backend"] == "scripts_run"
    assert summary["suites"][0]["suite"] == "ruler"
    assert run_state["status"] == "completed"
    assert run_state["suites"][0]["status"] == "completed"
    assert (result_dir / "ruler" / "samples.jsonl").is_file()
    assert not (tmp_path / "run" / "cleanup-scripts-run-smoke.json").read_text().strip() == ""


def test_smoke_command_supports_local_docker_fixture_backend(tmp_path: Path) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: ruler",
                "    profile: long-context",
                "    dataset_revision: ruler@fixture",
                "    harness_revision: fixture@rev",
                "    prompt_template: ruler-v1",
                "    execution_backend: local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "  - id: gsm8k",
                "    profile: fixture",
                "    dataset_revision: gsm8k@fixture",
                "    harness_revision: fixture@rev",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
            ]
        )
        + "\n"
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "ruler",
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "local_docker",
            "--run-id",
            "local-docker-smoke",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "local-docker-smoke"
    summary = json.loads((result_dir / "summary.json").read_text())
    run_state = json.loads((tmp_path / "run" / "benchmark-local-docker-smoke.json").read_text())
    environment = json.loads((result_dir / "environment.json").read_text())
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert summary["execution_backend"] == "local_docker"
    assert summary["suites"][0]["suite"] == "ruler"
    assert run_state["status"] == "completed"
    assert run_state["suites"][0]["status"] == "completed"
    assert environment["execution_backend"] == "local_docker"
    assert (result_dir / "ruler" / "samples.jsonl").is_file()
    assert "summary.json" in archive_manifest["contract_artifacts"]
    assert "environment.json" in archive_manifest["contract_artifacts"]
    assert "run.json" in archive_manifest["contract_artifacts"]


def test_write_fixture_benchmark_run_emits_three_needle_smoke_positions(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "needle-smoke",
                "profile": "long-context-smoke",
                "dataset_revision": "fixture-needle-smoke-v1",
                "harness_revision": "monarch-glm52-fixture-v1",
                "prompt_template": "needle-smoke-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }

    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="needle-positions",
        mode="smoke",
        suite_ids=["needle-smoke"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    suite_dir = summary_path.parent / "needle-smoke"
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert [sample["needle_position"] for sample in samples] == [
        "beginning",
        "middle",
        "end",
    ]
    assert {sample["expected_answer"] for sample in samples} == {"ORCHID-7194"}
    assert all(sample["extracted_answer"] == "ORCHID-7194" for sample in samples)
    assert all(sample["reproducible_seed"] == "needle-smoke-v1" for sample in samples)
    assert all(sample["prompt_sha256"] for sample in samples)
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert metrics["tasks_total"] == 3
    assert metrics["tasks_passed"] == 3


def test_write_fixture_benchmark_run_resumes_completed_matching_suite(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "ruler-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }
    results_root = tmp_path / "results"
    run_root = tmp_path / "run"

    summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-test",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )
    sample_path = summary_path.parent / "ruler" / "samples.jsonl"
    original_sample = sample_path.read_text()
    sample_path.write_text(original_sample.replace("fixture pass", "resumed pass"))

    resumed_summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-test",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    assert sample_path.read_text() != original_sample
    assert "resumed pass" in sample_path.read_text()
    run_record = json.loads((resumed_summary_path.parent / "run.json").read_text())
    assert run_record["status"] == "completed"
    assert run_record["suites"] == [
        {
            "id": "ruler",
            "status": "resumed",
            "tasks_total": 1,
            "tasks_completed": 1,
            "artifact_dir": str(resumed_summary_path.parent / "ruler"),
        }
    ]
    summary = json.loads(resumed_summary_path.read_text())
    assert summary["suites"][0]["suite"] == "ruler"
    assert summary["suites"][0]["tasks_passed"] == 1
    state = json.loads((resumed_summary_path.parent / "evalrun-state.json").read_text())
    assert state["trial_generation"]["ruler"] == {
        "artifacts": ["ruler/samples.jsonl", "ruler/failures.jsonl"],
        "status": "completed",
        "trials_total": 1,
    }


def test_fixture_benchmark_run_rejects_stale_evalrun_state(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "ruler-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }
    results_root = tmp_path / "results"
    run_root = tmp_path / "run"

    summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-stale-state",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )
    state_path = summary_path.parent / "evalrun-state.json"
    state = json.loads(state_path.read_text())
    state["manifest_sha256"] = "different-manifest"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    with pytest.raises(Exception, match="manifest_sha256 mismatch"):
        write_fixture_benchmark_run(
            results_root=results_root,
            run_root=run_root,
            run_id="resume-stale-state",
            mode="smoke",
            suite_ids=["ruler"],
            manifest=manifest,
            published_scores=None,
            execution_backend="bwrap_rootfs",
        )


def test_fixture_benchmark_run_rejects_stale_evalrun_state_when_mode_changes(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "ruler-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }
    results_root = tmp_path / "results"
    run_root = tmp_path / "run"

    summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-stale-state-mode",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )
    state_path = summary_path.parent / "evalrun-state.json"
    state = json.loads(state_path.read_text())
    assert state["mode"] == "smoke"

    with pytest.raises(Exception, match="mode mismatch"):
        write_fixture_benchmark_run(
            results_root=results_root,
            run_root=run_root,
            run_id="resume-stale-state-mode",
            mode="calibration",
            suite_ids=["ruler"],
            manifest=manifest,
            published_scores=None,
            execution_backend="bwrap_rootfs",
        )


@pytest.mark.parametrize(
    ("contents", "match"),
    [
        (None, "invalid_artifact: missing evalrun state"),
        ("not json", "invalid_artifact: malformed evalrun state"),
    ],
)
def test_fixture_benchmark_run_rejects_invalid_evalrun_state(
    tmp_path: Path, contents: str | None, match: str
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "ruler-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }
    results_root = tmp_path / "results"
    run_root = tmp_path / "run"

    summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-invalid-state",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )
    state_path = summary_path.parent / "evalrun-state.json"
    if contents is None:
        state_path.unlink()
    else:
        state_path.write_text(contents)

    with pytest.raises(Exception, match=match):
        write_fixture_benchmark_run(
            results_root=results_root,
            run_root=run_root,
            run_id="resume-invalid-state",
            mode="smoke",
            suite_ids=["ruler"],
            manifest=manifest,
            published_scores=None,
            execution_backend="bwrap_rootfs",
        )


def test_fixture_benchmark_run_does_not_resume_stale_metrics_schema(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "ruler-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }
    results_root = tmp_path / "results"
    run_root = tmp_path / "run"

    summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-stale-metrics",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )
    suite_dir = summary_path.parent / "ruler"
    sample_path = suite_dir / "samples.jsonl"
    metrics_path = suite_dir / "metrics.json"
    sample_path.write_text(
        sample_path.read_text().replace("fixture pass", "stale metrics pass")
    )
    metrics = json.loads(metrics_path.read_text())
    for field in (
        "profile",
        "dataset_revision",
        "harness_revision",
        "prompt_template",
        "execution_backend",
        "decoding_profile",
        "metric",
    ):
        metrics.pop(field)
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")

    rerun_summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-stale-metrics",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    assert "stale metrics pass" not in sample_path.read_text()
    run_record = json.loads((rerun_summary_path.parent / "run.json").read_text())
    assert run_record["suites"][0]["status"] == "completed"
    regenerated_metrics = json.loads(metrics_path.read_text())
    assert regenerated_metrics["profile"] == "long-context"
    assert regenerated_metrics["prompt_template"] == "ruler-v1"


def test_fixture_benchmark_run_rejects_existing_evalrun_state_when_mode_changes(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "fixture-dataset",
                "harness_revision": "fixture-harness",
                "prompt_template": "ruler-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
        ]
    }
    results_root = tmp_path / "results"
    run_root = tmp_path / "run"

    summary_path = write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id="resume-mode-change",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )
    sample_path = summary_path.parent / "ruler" / "samples.jsonl"
    sample_path.write_text(sample_path.read_text().replace("fixture pass", "stale pass"))

    with pytest.raises(Exception, match="mode mismatch"):
        write_fixture_benchmark_run(
            results_root=results_root,
            run_root=run_root,
            run_id="resume-mode-change",
            mode="calibration",
            suite_ids=["ruler"],
            manifest=manifest,
            published_scores=None,
            execution_backend="bwrap_rootfs",
        )
    assert "stale pass" in sample_path.read_text()


def test_static_math_extractors_follow_gsm8k_and_aime_contracts() -> None:
    assert (
        extract_static_final_answer(
            "gsm8k",
            "We add the groups carefully.\n#### 1,234\n",
        )
        == "1234"
    )
    assert (
        extract_static_final_answer(
            "aime",
            "The final integer answer is 042.",
        )
        == "42"
    )

    try:
        extract_static_final_answer("aime", "The final integer answer is 1000.")
    except Exception as error:
        assert "outside AIME answer range" in str(error)
    else:
        raise AssertionError("AIME answers outside [0, 999] should fail extraction")


def test_static_math_scoring_records_normalization() -> None:
    sample = score_static_fixture_sample(
        run_id="math-fixture",
        suite={
            "id": "gsm8k",
            "profile": "math-reasoning-thinking-disabled",
            "dataset_revision": "openai/gsm8k@fixture",
            "harness_revision": "fixture-harness",
            "prompt_template": "gsm8k-v1",
            "execution_backend": "bwrap_rootfs",
            "decoding_profile": {"temperature": 0},
            "metric": "exact_match",
        },
    )

    assert sample["raw_response"].endswith("#### 42")
    assert sample["extracted_answer"] == "42"
    assert sample["expected_answer"] == "42"
    assert sample["normalization"]["kind"] == "gsm8k_final_answer"
    assert sample["passed"] is True


def test_write_fixture_benchmark_run_emits_math_answer_artifacts(tmp_path: Path) -> None:
    manifest = {
        "suites": [
            {
                "id": "gsm8k",
                "profile": "math-reasoning-thinking-disabled",
                "dataset_revision": "openai/gsm8k@fixture",
                "harness_revision": "fixture-harness",
                "prompt_template": "gsm8k-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            },
            {
                "id": "aime",
                "profile": "math-reasoning-thinking-enabled",
                "dataset_revision": "aime@fixture-2024",
                "harness_revision": "fixture-harness",
                "prompt_template": "aime-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            },
        ]
    }

    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="math-static-fixture",
        mode="smoke",
        suite_ids=["gsm8k", "aime"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    gsm8k_sample = json.loads(
        (summary_path.parent / "gsm8k" / "samples.jsonl").read_text()
    )
    aime_sample = json.loads(
        (summary_path.parent / "aime" / "samples.jsonl").read_text()
    )
    assert gsm8k_sample["extracted_answer"] == gsm8k_sample["expected_answer"] == "42"
    assert aime_sample["extracted_answer"] == aime_sample["expected_answer"] == "42"
    assert gsm8k_sample["normalization"]["kind"] == "gsm8k_final_answer"
    assert aime_sample["normalization"]["kind"] == "aime_integer_answer"


def test_calibration_uses_materialized_gsm8k_dataset_cache(
    tmp_path: Path,
) -> None:
    dataset_cache = tmp_path / "benchmarks" / "datasets" / "gsm8k"
    dataset_cache.mkdir(parents=True)
    (dataset_cache / "samples.jsonl").write_text(
        json.dumps(
            {
                "id": "gsm8k-local-0001",
                "question": "What is 40 plus 2?",
                "answer": "40 + 2 = 42\n#### 42",
            }
        )
        + "\n"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: gsm8k",
                "    profile: math-reasoning-thinking-disabled",
                "    dataset_revision: openai/gsm8k@local-fixture",
                "    harness_revision: fixture-harness",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_cache}",
                "      revision: local-fixture",
                "      sha256: gsm8k-local-fixture-sha",
            ]
        )
        + "\n"
    )
    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="gsm8k-cache-calibration",
        mode="calibration",
        suite_ids=["gsm8k"],
        manifest=load_yaml_object(manifest_path),
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    result_dir = summary_path.parent
    sample = json.loads((result_dir / "gsm8k" / "samples.jsonl").read_text())
    assert sample["case_id"] == "gsm8k/gsm8k-local-0001"
    assert sample["dataset_sample_id"] == "gsm8k-local-0001"
    assert sample["prompt"] == "What is 40 plus 2?"
    assert sample["expected_answer"] == "42"
    assert sample["extracted_answer"] == "42"
    assert sample["raw_response"].endswith("#### 42")
    assert sample["endpoint"] == "fixture"
    assert sample["passed"] is True

    metrics = json.loads((result_dir / "gsm8k" / "metrics.json").read_text())
    assert metrics["tasks_total"] == 1
    assert metrics["tasks_passed"] == 1
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    assert metrics["infrastructure_failure_denominator"] == 1
    assert metrics["infrastructure_failure_rate"] == 0.0
    assert (result_dir / "gsm8k" / "failures.jsonl").read_text() == ""
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert "gsm8k/samples.jsonl" in archive_manifest["contract_artifacts"]
    assert "gsm8k/metrics.json" in archive_manifest["contract_artifacts"]
    assert "gsm8k/failures.jsonl" in archive_manifest["contract_artifacts"]


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_humaneval_single_suite_real_adapter_uses_responses_endpoint(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion_text = "def add(a, b):\n    return a + b\n"
    fenced_completion = f"Here is the Python function:\n\n```python\n{completion_text}```"
    fake_responses_server.set_output_text(fenced_completion)
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    run_id = f"humaneval-real-{mode}"

    def fake_bwrap_fixture_score(**kwargs: object) -> dict[str, object]:
        assert kwargs["completion_text"] == completion_text
        task_root = tmp_path / "run" / "bwrap" / run_id / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact = output_dir / "codegen-artifact.json"
        artifact.write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return {
            "suite": "humaneval",
            "case_id": "HumanEval/0",
            "task_root": str(task_root),
            "artifact_path": str(artifact),
            "passed": True,
            "latency_seconds": 0.25,
            "stdout": "fixture passed\n",
            "stderr": "",
        }

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_run_bwrap_codegen_fixture_score",
        fake_bwrap_fixture_score,
    )
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "humaneval",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--responses-timeout-seconds",
            "180",
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "humaneval"
    for relative_path in [
        "humaneval/samples.jsonl",
        "humaneval/metrics.json",
        "humaneval/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "evalrun-state.json",
        "summary.json",
        "archive-manifest.json",
    ]:
        assert (result_dir / relative_path).is_file()
    assert [request["path"] for request in fake_responses_server.requests] == [
        "/v1/responses"
    ]
    assert (
        fake_responses_server.requests[0]["payload"]["input"]
        == "Write a Python function named add that returns the sum of two numbers.\n\n"
        "Return only valid Python code. Do not include Markdown fences or prose."
    )
    sample = json.loads((suite_dir / "samples.jsonl").read_text())
    assert sample["case_id"] == "HumanEval/0"
    assert sample["prompt"] == (
        "Write a Python function named add that returns the sum of two numbers.\n\n"
        "Return only valid Python code. Do not include Markdown fences or prose."
    )
    assert sample["raw_response"] == fenced_completion
    assert sample["completion_text"] == completion_text
    assert sample["generated_code"] == completion_text
    assert sample["passed"] is True
    assert sample["state"] == "passed"
    assert sample["benchmark_scoring"] == "fixture_harness"
    assert sample["pass_at_1"] is None
    assert sample["endpoint"] == fake_responses_server.url
    assert sample["endpoint"] != "fixture"
    assert sample["profile"] == "coding-benchmark"
    assert sample["dataset_revision"] == "fixture-human-eval"
    assert sample["harness_revision"] == "fixture-harness"
    assert sample["prompt_template"] == "humaneval-v1"
    assert sample["prompt_template_sha256"] == hashlib.sha256(
        b"humaneval-v1"
    ).hexdigest()
    assert sample["decoding_profile"] == {"temperature": 0.2}
    assert sample["execution_backend"] == "bwrap_rootfs"
    assert sample["latency_seconds"] >= 0
    assert sample["usage"] == {
        "input_tokens": 17,
        "output_tokens": 3,
        "total_tokens": 20,
    }

    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert metrics["tasks_total"] == 1
    assert metrics["tasks_passed"] == 1
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    assert metrics["score"] == 1.0
    assert metrics["benchmark_scoring"] == "fixture_harness"
    assert metrics["pass_at_1"] is None
    assert (suite_dir / "failures.jsonl").read_text() == ""
    environment = json.loads((result_dir / "environment.json").read_text())
    run_record = json.loads((result_dir / "run.json").read_text())
    summary = json.loads((result_dir / "summary.json").read_text())
    assert environment["mode"] == mode
    assert environment["responses_base_url"] == fake_responses_server.url
    assert run_record["mode"] == mode
    assert run_record["responses_base_url"] == fake_responses_server.url
    assert summary["mode"] == mode
    assert summary["status"] == "pass"
    assert summary["responses_base_url"] == fake_responses_server.url
    assert summary["conformance"] == {
        "claim": "none",
        "comparable_to_published": False,
    }
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert set(archive_manifest["contract_artifacts"]) >= {
        "humaneval/samples.jsonl",
        "humaneval/metrics.json",
        "humaneval/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
        "humaneval/artifacts/humaneval-001-codegen-artifact.json",
    }


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_humaneval_real_adapter_classifies_responses_failure(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
) -> None:
    fake_responses_server.fail_responses()
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    run_id = f"humaneval-real-{mode}-failure"
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "humaneval",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--responses-timeout-seconds",
            "180",
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "humaneval"
    assert (result_dir / "archive-manifest.json").is_file()
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    failures = [
        json.loads(line)
        for line in (suite_dir / "failures.jsonl").read_text().splitlines()
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["infrastructure_failures"] == 1
    assert summary["suites"][0]["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 1
    assert metrics["model_failures"] == 0
    assert failures
    assert all(failure["failure_category"] == "infrastructure" for failure in failures)
    assert all(sample["endpoint"] == fake_responses_server.url for sample in samples)
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "environment_failed"


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_mbpp_single_suite_real_adapter_uses_responses_endpoint(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion_text = "def remove_Occ(s, ch):\n    return s.replace(ch, '', 1)\n"
    fenced_completion = f"```python\n{completion_text}```"
    fake_responses_server.set_output_text(fenced_completion)
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_mbpp_manifest(manifest_path)
    run_id = f"mbpp-real-{mode}"

    def fake_bwrap_fixture_score(**kwargs: object) -> dict[str, object]:
        assert kwargs["completion_text"] == completion_text
        task_root = tmp_path / "run" / "bwrap" / run_id / "mbpp-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact = output_dir / "codegen-artifact.json"
        artifact.write_text(
            json.dumps(
                {
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return {
            "suite": "mbpp",
            "case_id": "MBPP/0",
            "task_root": str(task_root),
            "artifact_path": str(artifact),
            "passed": True,
            "latency_seconds": 0.25,
            "stdout": "fixture passed\n",
            "stderr": "",
        }

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_run_bwrap_codegen_fixture_score",
        fake_bwrap_fixture_score,
    )
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "mbpp",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "mbpp"
    for relative_path in [
        "mbpp/samples.jsonl",
        "mbpp/metrics.json",
        "mbpp/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "evalrun-state.json",
        "summary.json",
        "archive-manifest.json",
    ]:
        assert (result_dir / relative_path).is_file()
    assert [request["path"] for request in fake_responses_server.requests] == [
        "/v1/responses"
    ]
    assert (
        fake_responses_server.requests[0]["payload"]["input"]
        == "Write a Python function named remove_Occ that removes the first occurrence of a character from a string.\n\n"
        "Return only valid Python code. Do not include Markdown fences or prose."
    )
    sample = json.loads((suite_dir / "samples.jsonl").read_text())
    assert sample["case_id"] == "MBPP/0"
    assert sample["prompt"] == (
        "Write a Python function named remove_Occ that removes the first occurrence of a character from a string.\n\n"
        "Return only valid Python code. Do not include Markdown fences or prose."
    )
    assert sample["raw_response"] == fenced_completion
    assert sample["completion_text"] == completion_text
    assert sample["generated_code"] == completion_text
    assert sample["passed"] is True
    assert sample["state"] == "passed"
    assert sample["benchmark_scoring"] == "fixture_harness"
    assert sample["pass_at_1"] is None
    assert sample["endpoint"] == fake_responses_server.url
    assert sample["endpoint"] != "fixture"
    assert sample["profile"] == "coding-benchmark"
    assert sample["dataset_revision"] == "fixture-mbpp"
    assert sample["harness_revision"] == "fixture-harness"
    assert sample["prompt_template"] == "mbpp-v1"
    assert sample["prompt_template_sha256"] == hashlib.sha256(
        b"mbpp-v1"
    ).hexdigest()
    assert sample["decoding_profile"] == {"temperature": 0.2}
    assert sample["execution_backend"] == "bwrap_rootfs"
    assert sample["latency_seconds"] >= 0
    assert sample["usage"] == {
        "input_tokens": 17,
        "output_tokens": 3,
        "total_tokens": 20,
    }

    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert metrics["tasks_total"] == 1
    assert metrics["tasks_passed"] == 1
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    assert metrics["score"] == 1.0
    assert metrics["benchmark_scoring"] == "fixture_harness"
    assert metrics["pass_at_1"] is None
    assert (suite_dir / "failures.jsonl").read_text() == ""
    environment = json.loads((result_dir / "environment.json").read_text())
    run_record = json.loads((result_dir / "run.json").read_text())
    summary = json.loads((result_dir / "summary.json").read_text())
    assert environment["mode"] == mode
    assert environment["responses_base_url"] == fake_responses_server.url
    assert run_record["mode"] == mode
    assert run_record["responses_base_url"] == fake_responses_server.url
    assert summary["mode"] == mode
    assert summary["status"] == "pass"
    assert summary["responses_base_url"] == fake_responses_server.url
    assert summary["conformance"] == {
        "claim": "none",
        "comparable_to_published": False,
    }
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert set(archive_manifest["contract_artifacts"]) >= {
        "mbpp/samples.jsonl",
        "mbpp/metrics.json",
        "mbpp/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
        "mbpp/artifacts/mbpp-001-codegen-artifact.json",
    }


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_mbpp_real_adapter_classifies_responses_failure(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
) -> None:
    fake_responses_server.fail_responses()
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_mbpp_manifest(manifest_path)
    run_id = f"mbpp-real-{mode}-failure"
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "mbpp",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "mbpp"
    assert (result_dir / "archive-manifest.json").is_file()
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    failures = [
        json.loads(line)
        for line in (suite_dir / "failures.jsonl").read_text().splitlines()
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["infrastructure_failures"] == 1
    assert summary["suites"][0]["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 1
    assert metrics["model_failures"] == 0
    assert failures
    assert all(failure["failure_category"] == "infrastructure" for failure in failures)
    assert all(sample["endpoint"] == fake_responses_server.url for sample in samples)
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "environment_failed"


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_gsm8k_single_suite_real_adapter_uses_responses_endpoint(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
) -> None:
    fake_responses_server.set_output_text("40 + 2 = 42\n#### 42")
    manifest_path = _write_gsm8k_cache_and_manifest(tmp_path)
    run_id = f"gsm8k-real-{mode}"
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "gsm8k"
    for relative_path in [
        "gsm8k/samples.jsonl",
        "gsm8k/metrics.json",
        "gsm8k/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
        "archive-manifest.json",
    ]:
        assert (result_dir / relative_path).is_file()
    assert [request["path"] for request in fake_responses_server.requests] == [
        "/v1/responses"
    ]
    assert fake_responses_server.requests[0]["payload"]["input"] == (
        "What is 40 plus 2?\n\n"
        "End your response with a final line exactly in this format: #### <answer>."
    )
    sample = json.loads((suite_dir / "samples.jsonl").read_text())
    assert sample["case_id"] == "gsm8k/gsm8k-local-0001"
    assert sample["dataset_sample_id"] == "gsm8k-local-0001"
    assert sample["prompt"] == (
        "What is 40 plus 2?\n\n"
        "End your response with a final line exactly in this format: #### <answer>."
    )
    assert sample["raw_response"].endswith("#### 42")
    assert sample["expected_answer"] == "42"
    assert sample["extracted_answer"] == "42"
    assert sample["normalization"] == {
        "kind": "gsm8k_final_answer",
        "normalized_answer": "42",
        "expected_normalized_answer": "42",
    }
    assert sample["passed"] is True
    assert sample["endpoint"] == fake_responses_server.url
    assert sample["endpoint"] != "fixture"
    assert sample["profile"] == "math-reasoning-thinking-disabled"
    assert sample["dataset_revision"] == "openai/gsm8k@local-fixture"
    assert sample["harness_revision"] == "fixture-harness"
    assert sample["prompt_template"] == "gsm8k-v1"
    assert sample["prompt_template_sha256"] == hashlib.sha256(
        b"gsm8k-v1"
    ).hexdigest()
    assert sample["decoding_profile"] == {
        "temperature": 0,
        "top_p": 1,
        "max_output_tokens": 256,
        "glm_thinking": "disabled",
    }
    assert sample["execution_backend"] == "bwrap_rootfs"
    assert sample["latency_seconds"] >= 0
    assert sample["usage"] == {
        "input_tokens": 17,
        "output_tokens": 3,
        "total_tokens": 20,
    }

    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert metrics["tasks_total"] == 1
    assert metrics["tasks_passed"] == 1
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    assert metrics["infrastructure_failure_denominator"] == 1
    assert metrics["infrastructure_failure_rate"] == 0.0
    assert (suite_dir / "failures.jsonl").read_text() == ""
    environment = json.loads((result_dir / "environment.json").read_text())
    run_record = json.loads((result_dir / "run.json").read_text())
    summary = json.loads((result_dir / "summary.json").read_text())
    assert environment["mode"] == mode
    assert environment["responses_base_url"] == fake_responses_server.url
    assert run_record["mode"] == mode
    assert run_record["responses_base_url"] == fake_responses_server.url
    assert summary["mode"] == mode
    assert summary["status"] == "pass"
    assert summary["responses_base_url"] == fake_responses_server.url
    assert summary["conformance"] == {
        "claim": "none",
        "comparable_to_published": False,
    }
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert set(archive_manifest["contract_artifacts"]) >= {
        "gsm8k/samples.jsonl",
        "gsm8k/metrics.json",
        "gsm8k/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "evalrun-state.json",
        "summary.json",
    }


def test_gsm8k_calibration_real_adapter_classifies_responses_failure(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    fake_responses_server.fail_responses()
    manifest_path = _write_gsm8k_cache_and_manifest(tmp_path)
    run_id = "gsm8k-real-calibration-failure"
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "gsm8k"
    assert (result_dir / "archive-manifest.json").is_file()
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    failures = [
        json.loads(line)
        for line in (suite_dir / "failures.jsonl").read_text().splitlines()
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["infrastructure_failures"] > 0
    assert summary["suites"][0]["model_failures"] == 0
    assert metrics["infrastructure_failures"] > 0
    assert metrics["model_failures"] == 0
    assert failures
    assert all(failure["failure_category"] == "infrastructure" for failure in failures)
    assert all(sample["endpoint"] == fake_responses_server.url for sample in samples)
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "environment_failed"


def test_gsm8k_calibration_real_adapter_classifies_bad_model_answer(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    fake_responses_server.set_output_text("The answer is forty two.")
    manifest_path = _write_gsm8k_cache_and_manifest(tmp_path)
    run_id = "gsm8k-real-calibration-model-failure"
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "gsm8k"
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    sample = json.loads((suite_dir / "samples.jsonl").read_text())
    assert summary["status"] == "fail"
    assert summary["suites"][0]["model_failures"] == 1
    assert summary["suites"][0]["infrastructure_failures"] == 0
    assert metrics["model_failures"] == 1
    assert metrics["infrastructure_failures"] == 0
    assert sample["failure_category"] == "model"
    assert sample["endpoint"] == fake_responses_server.url
    assert sample["raw_response"] == "The answer is forty two."


def test_gsm8k_mixed_calibration_preserves_fixture_path(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    fake_responses_server.set_output_text("not used\n#### 0")
    manifest_path = _write_gsm8k_cache_and_manifest(tmp_path)
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "gsm8k",
            "--suite",
            "aime",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "gsm8k-mixed-fixture",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "gsm8k-mixed-fixture"
    gsm8k_sample = json.loads((result_dir / "gsm8k" / "samples.jsonl").read_text())
    assert fake_responses_server.requests == []
    assert gsm8k_sample["endpoint"] == "fixture"
    assert gsm8k_sample["extracted_answer"] == "42"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert "responses_base_url" not in summary
    assert "conformance" not in summary


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_aime_single_suite_real_adapter_uses_responses_endpoint(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
) -> None:
    fake_responses_server.set_output_text("The final integer answer is 42.")
    manifest_path = _write_aime_cache_and_manifest(tmp_path)
    run_id = f"aime-real-{mode}"
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "aime",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "aime"
    for relative_path in [
        "aime/samples.jsonl",
        "aime/metrics.json",
        "aime/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
        "archive-manifest.json",
    ]:
        assert (result_dir / relative_path).is_file()
    assert [request["path"] for request in fake_responses_server.requests] == [
        "/v1/responses"
    ]
    assert fake_responses_server.requests[0]["payload"]["input"] == (
        "Find the integer answer to this local AIME problem.\n\n"
        "End your response with the final integer answer and no other trailing numbers."
    )
    sample = json.loads((suite_dir / "samples.jsonl").read_text())
    assert sample["case_id"] == "aime/aime-local-0001"
    assert sample["dataset_sample_id"] == "aime-local-0001"
    assert sample["prompt"] == (
        "Find the integer answer to this local AIME problem.\n\n"
        "End your response with the final integer answer and no other trailing numbers."
    )
    assert sample["raw_response"] == "The final integer answer is 42."
    assert sample["expected_answer"] == "42"
    assert sample["extracted_answer"] == "42"
    assert sample["normalization"] == {
        "kind": "aime_integer_answer",
        "normalized_answer": "42",
        "expected_normalized_answer": "42",
    }
    assert sample["passed"] is True
    assert sample["endpoint"] == fake_responses_server.url
    assert sample["endpoint"] != "fixture"
    assert sample["profile"] == "math-reasoning-thinking-enabled"
    assert sample["dataset_revision"] == "aime@local-fixture"
    assert sample["harness_revision"] == "fixture-harness"
    assert sample["prompt_template"] == "aime-v1"
    assert sample["prompt_template_sha256"] == hashlib.sha256(
        b"aime-v1"
    ).hexdigest()
    assert sample["decoding_profile"] == {
        "temperature": 0,
        "top_p": 1,
        "max_output_tokens": 256,
        "glm_thinking": "enabled",
    }
    assert sample["execution_backend"] == "bwrap_rootfs"
    assert sample["latency_seconds"] >= 0
    assert sample["usage"] == {
        "input_tokens": 17,
        "output_tokens": 3,
        "total_tokens": 20,
    }

    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert metrics["tasks_total"] == 1
    assert metrics["tasks_passed"] == 1
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    assert metrics["infrastructure_failure_denominator"] == 1
    assert metrics["infrastructure_failure_rate"] == 0.0
    assert (suite_dir / "failures.jsonl").read_text() == ""
    environment = json.loads((result_dir / "environment.json").read_text())
    run_record = json.loads((result_dir / "run.json").read_text())
    summary = json.loads((result_dir / "summary.json").read_text())
    assert environment["mode"] == mode
    assert environment["responses_base_url"] == fake_responses_server.url
    assert run_record["mode"] == mode
    assert run_record["responses_base_url"] == fake_responses_server.url
    assert summary["mode"] == mode
    assert summary["status"] == "pass"
    assert summary["responses_base_url"] == fake_responses_server.url
    assert summary["conformance"] == {
        "claim": "none",
        "comparable_to_published": False,
    }
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert set(archive_manifest["contract_artifacts"]) >= {
        "aime/samples.jsonl",
        "aime/metrics.json",
        "aime/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
    }


def test_aime_single_suite_real_adapter_requires_dataset_cache(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    manifest_path = _write_aime_cache_and_manifest(tmp_path)
    for path in (tmp_path / "benchmarks" / "datasets" / "aime").iterdir():
        path.unlink()
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "aime",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "aime-real-missing-cache",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="AIME responses run requires a materialized dataset cache sample",
    ):
        args.func(args)
    assert fake_responses_server.requests == []


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_aime_real_adapter_classifies_responses_failure(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
) -> None:
    fake_responses_server.fail_responses()
    manifest_path = _write_aime_cache_and_manifest(tmp_path)
    run_id = f"aime-real-{mode}-failure"
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "aime",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "aime"
    assert (result_dir / "archive-manifest.json").is_file()
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    failures = [
        json.loads(line)
        for line in (suite_dir / "failures.jsonl").read_text().splitlines()
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["infrastructure_failures"] > 0
    assert summary["suites"][0]["model_failures"] == 0
    assert metrics["infrastructure_failures"] > 0
    assert metrics["model_failures"] == 0
    assert failures
    assert all(failure["failure_category"] == "infrastructure" for failure in failures)
    assert all(sample["endpoint"] == fake_responses_server.url for sample in samples)
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "environment_failed"


def test_aime_calibration_real_adapter_classifies_bad_model_answer(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    fake_responses_server.set_output_text("The answer is outside range 1000.")
    manifest_path = _write_aime_cache_and_manifest(tmp_path)
    run_id = "aime-real-calibration-model-failure"
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "aime",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "aime"
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    sample = json.loads((suite_dir / "samples.jsonl").read_text())
    assert summary["status"] == "fail"
    assert summary["suites"][0]["model_failures"] == 1
    assert summary["suites"][0]["infrastructure_failures"] == 0
    assert metrics["model_failures"] == 1
    assert metrics["infrastructure_failures"] == 0
    assert sample["failure_category"] == "model"
    assert sample["endpoint"] == fake_responses_server.url
    assert sample["raw_response"] == "The answer is outside range 1000."


def test_aime_mixed_calibration_preserves_fixture_path(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    fake_responses_server.set_output_text("not used 0")
    manifest_path = _write_aime_cache_and_manifest(tmp_path)
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "aime",
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "aime-mixed-fixture",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "aime-mixed-fixture"
    aime_sample = json.loads((result_dir / "aime" / "samples.jsonl").read_text())
    assert fake_responses_server.requests == []
    assert aime_sample["endpoint"] == "fixture"
    assert aime_sample["extracted_answer"] == "42"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert "responses_base_url" not in summary
    assert "conformance" not in summary


def test_conformance_validation_rejects_missing_published_score_fields() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            }
        ]
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "metric": "pass@1",
                "score": 0.9,
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "tolerance" in str(error)
    else:
        raise AssertionError("missing tolerance should fail conformance validation")


def test_manifest_suite_validation_requires_profile() -> None:
    try:
        validate_suite_fields(
            {
                "id": "humaneval",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            }
        )
    except Exception as error:
        assert "profile" in str(error)
    else:
        raise AssertionError("suite profile should be required")


def test_manifest_suite_validation_rejects_unknown_execution_backend() -> None:
    try:
        validate_suite_fields(
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "mystery_backend",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            }
        )
    except Exception as error:
        assert "suite humaneval execution_backend is not allowed" in str(error)
    else:
        raise AssertionError("unknown execution backend should fail suite validation")


def test_manifest_selection_rejects_duplicate_suite_ids() -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev-a",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            },
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev-b",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            },
        ]
    }

    try:
        select_suites(manifest, ["humaneval"])
    except Exception as error:
        assert "duplicate suite id: humaneval" in str(error)
    else:
        raise AssertionError("duplicate suite ids should fail manifest selection")


def test_conformance_validation_rejects_backend_override() -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            }
        ]
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override="host_subprocess",
        )
    except Exception as error:
        assert "backend override" in str(error)
    else:
        raise AssertionError("backend override should fail conformance validation")


def test_conformance_validation_rejects_profile_mismatch() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "gsm8k",
                "profile": "math-reasoning-thinking-disabled",
                "dataset_revision": "openai/gsm8k@rev",
                "harness_revision": "lm-evaluation-harness@rev",
                "prompt_template": "gsm8k-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0, "glm_thinking": "disabled"},
                "metric": "exact_match",
            }
        ]
    }
    published_scores = {
        "scores": [
            {
                "suite": "gsm8k",
                "model": "zai-org/GLM-5.2",
                "profile": "math-reasoning-thinking-enabled",
                "metric": "exact_match",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "gsm8k-v1",
                "dataset_revision": "openai/gsm8k@rev",
                "harness_revision": "lm-evaluation-harness@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0, "glm_thinking": "disabled"},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["gsm8k"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "suite profile" in str(error)
    else:
        raise AssertionError("profile mismatch should fail conformance validation")


def test_conformance_validation_rejects_decoding_profile_mismatch() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "aime",
                "profile": "math-reasoning-thinking-enabled",
                "dataset_revision": "aime@rev",
                "harness_revision": "lm-evaluation-harness@rev",
                "prompt_template": "aime-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0, "glm_thinking": "enabled"},
                "metric": "exact_match",
            }
        ]
    }
    published_scores = {
        "scores": [
            {
                "suite": "aime",
                "model": "zai-org/GLM-5.2",
                "profile": "math-reasoning-thinking-enabled",
                "metric": "exact_match",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "aime-v1",
                "dataset_revision": "aime@rev",
                "harness_revision": "lm-evaluation-harness@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0, "glm_thinking": "disabled"},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["aime"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "suite decoding_profile" in str(error)
    else:
        raise AssertionError("decoding mismatch should fail conformance validation")


def test_conformance_validation_rejects_non_url_published_score_source() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ]
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "not-a-url",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published score for humaneval source_url must be an http(s) URL" in str(
            error
        )
    else:
        raise AssertionError("non-URL source_url should fail conformance validation")


def test_conformance_validation_rejects_non_primary_published_score_source() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ]
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/blog-summary",
                "source_type": "secondary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published score for humaneval source_type must be primary" in str(
            error
        )
    else:
        raise AssertionError("secondary source_type should fail conformance validation")


def test_conformance_validation_rejects_published_score_model_mismatch() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "other-org/OtherModel",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published score for humaneval does not match manifest model" in str(
            error
        )
    else:
        raise AssertionError("model mismatch should fail conformance validation")


def test_conformance_validation_requires_manifest_model_identity() -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "benchmark manifest model must be declared" in str(error)
    else:
        raise AssertionError("missing manifest model should fail conformance validation")


def test_conformance_validation_rejects_published_manifest_model_mismatch() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "model": "other-org/OtherModel",
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ],
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published-score manifest model does not match benchmark manifest model" in str(
            error
        )
    else:
        raise AssertionError(
            "published-score manifest model mismatch should fail conformance"
        )


def test_conformance_validation_rejects_non_numeric_tolerance() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": "0.02",
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published score for humaneval tolerance must be numeric" in str(error)
    else:
        raise AssertionError("non-numeric tolerance should fail conformance validation")


def test_conformance_validation_requires_tolerance_basis() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published score for humaneval missing fields: tolerance_basis" in str(
            error
        )
    else:
        raise AssertionError("missing tolerance_basis should fail conformance")


@pytest.mark.parametrize(
    "tolerance_basis",
    [
        {"variance": "fixture"},
        {"sample_size": 1},
    ],
)
def test_conformance_validation_requires_sample_size_and_variance_tolerance_basis(
    tolerance_basis: dict[str, object],
) -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": tolerance_basis,
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published score for humaneval tolerance_basis must be declared" in str(
            error
        )
    else:
        raise AssertionError(
            "tolerance_basis without sample_size and variance should fail conformance"
        )


def test_conformance_validation_rejects_non_numeric_score() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "scores": [
            {
                "suite": "humaneval",
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": "0.9",
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "published score for humaneval score must be numeric" in str(error)
    else:
        raise AssertionError("non-numeric score should fail conformance validation")


def test_conformance_validation_rejects_duplicate_published_score_suites() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    score = {
        "suite": "humaneval",
        "model": "zai-org/GLM-5.2",
        "profile": "coding-benchmark",
        "metric": "pass@1",
        "score": 0.9,
        "tolerance": 0.02,
        "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
        "source_url": "https://example.invalid/primary",
        "source_type": "primary",
        "prompt_template": "humaneval-v1",
        "dataset_revision": "openai/humaneval@rev",
        "harness_revision": "evalplus@rev",
        "execution_backend": "bwrap_rootfs",
        "decoding_profile": {"temperature": 0.2},
    }
    published_scores = {"scores": [score, {**score, "score": 0.91}]}

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "duplicate published score for suite: humaneval" in str(error)
    else:
        raise AssertionError("duplicate published scores should fail conformance")


def test_conformance_validation_rejects_malformed_published_score_entries() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
                "dataset_source": {
                    "type": "local_path",
                    "path": "/tmp/humaneval",
                    "revision": "rev",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": "/tmp/evalplus",
                    "revision": "rev",
                },
            }
        ],
    }
    published_scores = {
        "model": "zai-org/GLM-5.2",
        "scores": [
            {
                "suite": 123,
                "model": "zai-org/GLM-5.2",
                "profile": "coding-benchmark",
                "metric": "pass@1",
                "score": 0.9,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://example.invalid/primary",
                "source_type": "primary",
                "prompt_template": "humaneval-v1",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
            }
        ],
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["humaneval"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "each published score must be an object with string suite" in str(error)
    else:
        raise AssertionError("malformed published score entries should fail")


def test_conformance_validation_rejects_non_comparable_score() -> None:
    manifest = {
        "model": "zai-org/GLM-5.2",
        "suites": [
            {
                "id": "terminal-bench-2",
                "profile": "terminal-agent",
                "dataset_revision": "terminal-bench-2@local-profile",
                "harness_revision": "harbor@local-profile",
                "prompt_template": "terminal-bench-2-v1",
                "execution_backend": "harbor_local_docker",
                "container_image": "ghcr.io/harbor-framework/terminal-bench-2:local-profile",
                "decoding_profile": {"temperature": 0.2, "glm_thinking": "disabled"},
                "metric": "task_success",
            }
        ]
    }
    published_scores = {
        "scores": [
            {
                "suite": "terminal-bench-2",
                "model": "zai-org/GLM-5.2",
                "profile": "terminal-agent",
                "metric": "task_success",
                "score": 0.81,
                "tolerance": 0.02,
                "tolerance_basis": {"sample_size": 1, "variance": "fixture"},
                "source_url": "https://huggingface.co/zai-org/GLM-5.2",
                "source_type": "primary",
                "prompt_template": "terminal-bench-2-v1",
                "dataset_revision": "terminal-bench-2@local-profile",
                "harness_revision": "harbor@local-profile",
                "execution_backend": "harbor_local_docker",
                "decoding_profile": {"temperature": 0.2, "glm_thinking": "disabled"},
                "comparable": False,
                "note": "official score used a different Terminal-Bench profile",
            }
        ]
    }

    try:
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=["terminal-bench-2"],
            execution_backend_override=None,
        )
    except Exception as error:
        assert "non-comparable" in str(error)
    else:
        raise AssertionError("non-comparable published scores should fail conformance")


def test_conformance_command_defaults_to_all_manifest_suites(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    "    dataset_revision: fixture\n"
                    "    harness_revision: fixture\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                *[
                    f"  - suite: {suite_id}\n"
                    "    model: zai-org/GLM-5.2\n"
                    "    profile: fixture\n"
                    "    metric: exact_match\n"
                    "    source_url: TODO-primary-source\n"
                    "    score: TODO\n"
                    "    tolerance: TODO\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    "    dataset_revision: fixture\n"
                    "    harness_revision: fixture\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--run-id",
            "conformance-all",
        ]
    )

    try:
        args.func(args)
    except Exception as error:
        assert "missing fields: score, source_type, source_url, tolerance" in str(
            error
        )
    else:
        raise AssertionError("placeholder published scores should fail conformance")


def test_conformance_command_rejects_placeholder_suite_revisions(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'coding-benchmark' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    dataset_revision: {'openai/humaneval@pinned-placeholder' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    harness_revision: {'evalplus@pinned-placeholder' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    f"      temperature: {0.2 if suite_id == 'humaneval' else 0}\n"
                    "      glm_thinking: disabled\n"
                    f"    metric: {'pass@1' if suite_id == 'humaneval' else 'exact_match'}"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: humaneval",
                "    model: zai-org/GLM-5.2",
                "    profile: coding-benchmark",
                "    metric: pass@1",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: humaneval-v1",
                "    dataset_revision: openai/humaneval@pinned-placeholder",
                "    harness_revision: evalplus@pinned-placeholder",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "humaneval",
            "--run-id",
            "conformance-placeholder-revision",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite humaneval dataset_revision must be pinned",
    ):
        args.func(args)

    assert not (
        tmp_path / "run" / "benchmark-conformance-placeholder-revision.json"
    ).exists()
    assert not (tmp_path / "results" / "conformance-placeholder-revision").exists()


def test_conformance_command_requires_container_image_for_docker_suites(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    dataset_source = tmp_path / "terminal-bench-source"
    harness_source = tmp_path / "harbor-source"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "tasks.jsonl").write_text('{"task_id": "terminal-0"}\n')
    (harness_source / "README.md").write_text("harbor fixture\n")
    required_suite_ids = REQUIRED_FIXTURE_SUITE_IDS
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "      glm_thinking: disabled\n"
                    "    metric: exact_match"
                    + (
                        "\n"
                        "    dataset_source:\n"
                        "      type: local_path\n"
                        f"      path: {dataset_source}\n"
                        "      revision: rev\n"
                        "    harness_source:\n"
                        "      type: local_path\n"
                        f"      path: {harness_source}\n"
                        "      revision: rev"
                        if suite_id == "terminal-bench-2"
                        else ""
                    )
                    for suite_id in required_suite_ids
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: terminal-bench-2",
                "    model: zai-org/GLM-5.2",
                "    profile: terminal-agent",
                "    metric: exact_match",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: terminal-bench-2-v1",
                "    dataset_revision: terminal-bench-2@rev",
                "    harness_revision: harbor@rev",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "terminal-bench-2",
            "--run-id",
            "conformance-missing-image",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite terminal-bench-2 container_image must be pinned",
    ):
        args.func(args)

    assert not (tmp_path / "run" / "benchmark-conformance-missing-image.json").exists()
    assert not (tmp_path / "results" / "conformance-missing-image").exists()


def test_conformance_command_rejects_mutable_container_image_tags(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    dataset_source = tmp_path / "terminal-bench-source"
    harness_source = tmp_path / "harbor-source"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "tasks.jsonl").write_text('{"task_id": "terminal-0"}\n')
    (harness_source / "README.md").write_text("harbor fixture\n")
    required_suite_ids = REQUIRED_FIXTURE_SUITE_IDS
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "      glm_thinking: disabled\n"
                    "    metric: exact_match"
                    + (
                        "\n"
                        "    container_image: ghcr.io/harbor-framework/terminal-bench-2:smoke\n"
                        "    dataset_source:\n"
                        "      type: local_path\n"
                        f"      path: {dataset_source}\n"
                        "      revision: rev\n"
                        "    harness_source:\n"
                        "      type: local_path\n"
                        f"      path: {harness_source}\n"
                        "      revision: rev"
                        if suite_id == "terminal-bench-2"
                        else ""
                    )
                    for suite_id in required_suite_ids
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: terminal-bench-2",
                "    model: zai-org/GLM-5.2",
                "    profile: terminal-agent",
                "    metric: exact_match",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: terminal-bench-2-v1",
                "    dataset_revision: terminal-bench-2@rev",
                "    harness_revision: harbor@rev",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "terminal-bench-2",
            "--run-id",
            "conformance-mutable-image",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite terminal-bench-2 container_image must be digest-pinned",
    ):
        args.func(args)

    assert not (tmp_path / "run" / "benchmark-conformance-mutable-image.json").exists()
    assert not (tmp_path / "results" / "conformance-mutable-image").exists()


def test_conformance_command_requires_swebench_instance_images(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    dataset_source = tmp_path / "swebench-dataset"
    harness_source = tmp_path / "swebench-harness"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "instances.jsonl").write_text('{"instance_id": "swe-0"}\n')
    (harness_source / "README.md").write_text("swe-bench fixture\n")
    image = "ghcr.io/swe-bench/runner@sha256:" + ("a" * 64)
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'swe-bench-verified' else 'fixture'}\n"
                    f"    dataset_revision: {'SWE-bench/SWE-bench_Verified@rev' if suite_id == 'swe-bench-verified' else suite_id + '@rev'}\n"
                    f"    harness_revision: {'swebench@rev' if suite_id == 'swe-bench-verified' else 'fixture@rev'}\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'swe-bench-verified' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "      glm_thinking: disabled\n"
                    f"    metric: {'resolved_instances' if suite_id == 'swe-bench-verified' else 'exact_match'}"
                    + (
                        "\n"
                        f"    container_image: {image}\n"
                        "    dataset_source:\n"
                        "      type: local_path\n"
                        f"      path: {dataset_source}\n"
                        "      revision: rev\n"
                        "    harness_source:\n"
                        "      type: local_path\n"
                        f"      path: {harness_source}\n"
                        "      revision: rev"
                        if suite_id == "swe-bench-verified"
                        else ""
                    )
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: swe-bench-verified",
                "    model: zai-org/GLM-5.2",
                "    profile: terminal-agent",
                "    metric: resolved_instances",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: swe-bench-verified-v1",
                "    dataset_revision: SWE-bench/SWE-bench_Verified@rev",
                "    harness_revision: swebench@rev",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "swe-bench-verified",
            "--run-id",
            "conformance-swebench-images",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite swe-bench-verified instance_images must be declared",
    ):
        args.func(args)

    assert not (tmp_path / "run" / "benchmark-conformance-swebench-images.json").exists()
    assert not (tmp_path / "results" / "conformance-swebench-images").exists()


def test_conformance_command_rejects_mutable_swebench_instance_images(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    dataset_source = tmp_path / "swebench-dataset"
    harness_source = tmp_path / "swebench-harness"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "instances.jsonl").write_text('{"instance_id": "swe-0"}\n')
    (harness_source / "README.md").write_text("swe-bench fixture\n")
    image = "ghcr.io/swe-bench/runner@sha256:" + ("a" * 64)
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'swe-bench-verified' else 'fixture'}\n"
                    f"    dataset_revision: {'SWE-bench/SWE-bench_Verified@rev' if suite_id == 'swe-bench-verified' else suite_id + '@rev'}\n"
                    f"    harness_revision: {'swebench@rev' if suite_id == 'swe-bench-verified' else 'fixture@rev'}\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'swe-bench-verified' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "      glm_thinking: disabled\n"
                    f"    metric: {'resolved_instances' if suite_id == 'swe-bench-verified' else 'exact_match'}"
                    + (
                        "\n"
                        f"    container_image: {image}\n"
                        "    instance_images:\n"
                        "      swe-0: ghcr.io/swe-bench/swe-0:latest\n"
                        "    dataset_source:\n"
                        "      type: local_path\n"
                        f"      path: {dataset_source}\n"
                        "      revision: rev\n"
                        "    harness_source:\n"
                        "      type: local_path\n"
                        f"      path: {harness_source}\n"
                        "      revision: rev"
                        if suite_id == "swe-bench-verified"
                        else ""
                    )
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: swe-bench-verified",
                "    model: zai-org/GLM-5.2",
                "    profile: terminal-agent",
                "    metric: resolved_instances",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: swe-bench-verified-v1",
                "    dataset_revision: SWE-bench/SWE-bench_Verified@rev",
                "    harness_revision: swebench@rev",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "swe-bench-verified",
            "--run-id",
            "conformance-swebench-mutable-image",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite swe-bench-verified instance image swe-0 must be digest-pinned",
    ):
        args.func(args)

    assert not (
        tmp_path / "run" / "benchmark-conformance-swebench-mutable-image.json"
    ).exists()
    assert not (tmp_path / "results" / "conformance-swebench-mutable-image").exists()


def test_conformance_command_requires_source_metadata(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    required_suite_ids = REQUIRED_FIXTURE_SUITE_IDS
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'coding-benchmark' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    dataset_revision: {'openai/humaneval@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    harness_revision: {'evalplus@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    f"      temperature: {0.2 if suite_id == 'humaneval' else 0}\n"
                    "      glm_thinking: disabled\n"
                    f"    metric: {'pass@1' if suite_id == 'humaneval' else 'exact_match'}"
                    for suite_id in required_suite_ids
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: humaneval",
                "    model: zai-org/GLM-5.2",
                "    profile: coding-benchmark",
                "    metric: pass@1",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: humaneval-v1",
                "    dataset_revision: openai/humaneval@rev",
                "    harness_revision: evalplus@rev",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "humaneval",
            "--run-id",
            "conformance-missing-source",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite humaneval dataset_source must be declared",
    ):
        args.func(args)

    assert not (tmp_path / "run" / "benchmark-conformance-missing-source.json").exists()
    assert not (tmp_path / "results" / "conformance-missing-source").exists()


def test_conformance_command_requires_source_metadata_revisions(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    dataset_source = tmp_path / "humaneval-dataset"
    harness_source = tmp_path / "evalplus-harness"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "problems.jsonl").write_text('{"task_id": "HumanEval/0"}\n')
    (harness_source / "README.md").write_text("evalplus fixture\n")
    required_suite_ids = REQUIRED_FIXTURE_SUITE_IDS
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'coding-benchmark' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    dataset_revision: {'openai/humaneval@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    harness_revision: {'evalplus@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    f"      temperature: {0.2 if suite_id == 'humaneval' else 0}\n"
                    "      glm_thinking: disabled\n"
                    f"    metric: {'pass@1' if suite_id == 'humaneval' else 'exact_match'}"
                    + (
                        "\n"
                        "    dataset_source:\n"
                        "      type: local_path\n"
                        f"      path: {dataset_source}\n"
                        "    harness_source:\n"
                        "      type: local_path\n"
                        f"      path: {harness_source}"
                        if suite_id == "humaneval"
                        else ""
                    )
                    for suite_id in required_suite_ids
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: humaneval",
                "    model: zai-org/GLM-5.2",
                "    profile: coding-benchmark",
                "    metric: pass@1",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: humaneval-v1",
                "    dataset_revision: openai/humaneval@rev",
                "    harness_revision: evalplus@rev",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "humaneval",
            "--run-id",
            "conformance-source-revision-missing",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite humaneval dataset_source.revision must be declared",
    ):
        args.func(args)

    assert not (
        tmp_path / "run" / "benchmark-conformance-source-revision-missing.json"
    ).exists()
    assert not (tmp_path / "results" / "conformance-source-revision-missing").exists()


def test_conformance_command_writes_reproducibility_artifact(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    dataset_source = tmp_path / "humaneval-dataset"
    harness_source = tmp_path / "evalplus-harness"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "problems.jsonl").write_text('{"task_id": "HumanEval/0"}\n')
    (harness_source / "README.md").write_text("evalplus fixture\n")
    required_suite_ids = REQUIRED_FIXTURE_SUITE_IDS
    manifest_path.write_text(
        "\n".join(
            [
                "model: zai-org/GLM-5.2",
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'coding-benchmark' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    dataset_revision: {'openai/humaneval@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    harness_revision: {'evalplus@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    f"      temperature: {0.2 if suite_id == 'humaneval' else 0}\n"
                    "      glm_thinking: disabled\n"
                    f"    metric: {'pass@1' if suite_id == 'humaneval' else 'exact_match'}"
                    + (
                        "\n"
                        "    dataset_source:\n"
                        "      type: local_path\n"
                        f"      path: {dataset_source}\n"
                        "      revision: rev\n"
                        "    harness_source:\n"
                        "      type: local_path\n"
                        f"      path: {harness_source}\n"
                        "      revision: rev"
                        if suite_id == "humaneval"
                        else ""
                    )
                    for suite_id in required_suite_ids
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: humaneval",
                "    model: zai-org/GLM-5.2",
                "    profile: coding-benchmark",
                "    metric: pass@1",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: humaneval-v1",
                "    dataset_revision: openai/humaneval@rev",
                "    harness_revision: evalplus@rev",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "humaneval",
            "--run-id",
            "conformance-complete",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "conformance-complete"
    assert (result_dir / "conformance.json").is_file()
    assert (result_dir / "run.json").is_file()
    assert (result_dir / "environment.json").is_file()
    assert (result_dir / "benchmark-manifest.json").is_file()
    assert (result_dir / "published-scores.json").is_file()
    assert (result_dir / "archive-manifest.json").is_file()
    assert (tmp_path / "run" / "benchmark-conformance-complete.json").is_file()
    assert (tmp_path / "run" / "cleanup-conformance-complete.json").is_file()
    artifact = json.loads((result_dir / "conformance.json").read_text())
    assert artifact["status"] == "validated"
    assert artifact["suites"] == ["humaneval"]
    assert artifact["scores"][0]["suite"] == "humaneval"
    assert artifact["scores"][0]["score"] == 0.9
    result_run = json.loads((result_dir / "run.json").read_text())
    root_run = json.loads(
        (tmp_path / "run" / "benchmark-conformance-complete.json").read_text()
    )
    assert result_run == root_run
    assert result_run["status"] == "validated"
    environment = json.loads((result_dir / "environment.json").read_text())
    assert environment["mode"] == "conformance"
    assert environment["python"]
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_path"] == "conformance.json"
    assert archive_manifest["summary_status"] == "validated"
    assert "conformance.json" in archive_manifest["contract_artifacts"]
    assert "run.json" in archive_manifest["contract_artifacts"]
    assert "environment.json" in archive_manifest["contract_artifacts"]
    assert "benchmark-manifest.json" in archive_manifest["contract_artifacts"]
    assert "published-scores.json" in archive_manifest["contract_artifacts"]


def test_conformance_command_rejects_backend_override_before_artifacts(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    published_scores_path = tmp_path / "published-scores.yaml"
    dataset_source = tmp_path / "humaneval-dataset"
    harness_source = tmp_path / "evalplus-harness"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "problems.jsonl").write_text('{"task_id": "HumanEval/0"}\n')
    (harness_source / "README.md").write_text("evalplus fixture\n")
    required_suite_ids = REQUIRED_FIXTURE_SUITE_IDS
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'coding-benchmark' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    dataset_revision: {'openai/humaneval@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    harness_revision: {'evalplus@rev' if suite_id == 'humaneval' else 'fixture'}\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    f"      temperature: {0.2 if suite_id == 'humaneval' else 0}\n"
                    "      glm_thinking: disabled\n"
                    f"    metric: {'pass@1' if suite_id == 'humaneval' else 'exact_match'}"
                    + (
                        "\n"
                        "    dataset_source:\n"
                        "      type: local_path\n"
                        f"      path: {dataset_source}\n"
                        "      revision: rev\n"
                        "    harness_source:\n"
                        "      type: local_path\n"
                        f"      path: {harness_source}\n"
                        "      revision: rev"
                        if suite_id == "humaneval"
                        else ""
                    )
                    for suite_id in required_suite_ids
                ],
            ]
        )
        + "\n"
    )
    published_scores_path.write_text(
        "\n".join(
            [
                "scores:",
                "  - suite: humaneval",
                "    model: zai-org/GLM-5.2",
                "    profile: coding-benchmark",
                "    metric: pass@1",
                "    score: 0.9",
                "    tolerance: 0.02",
                "    tolerance_basis:",
                "      sample_size: 1",
                "      variance: fixture",
                "    source_url: https://example.invalid/primary",
                "    source_type: primary",
                "    prompt_template: humaneval-v1",
                "    dataset_revision: openai/humaneval@rev",
                "    harness_revision: evalplus@rev",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0.2",
                "      glm_thinking: disabled",
                "",
            ]
        )
    )
    args = build_parser().parse_args(
        [
            "conformance",
            "--manifest",
            str(manifest_path),
            "--published-scores",
            str(published_scores_path),
            "--suite",
            "humaneval",
            "--execution-backend",
            "host_subprocess",
            "--run-id",
            "conformance-override",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="backend override is not allowed in conformance mode",
    ):
        args.func(args)

    assert not (tmp_path / "results" / "conformance-override").exists()
    assert not (tmp_path / "run" / "benchmark-conformance-override.json").exists()
    assert not (tmp_path / "run" / "cleanup-conformance-override.json").exists()


def test_smoke_command_defaults_to_manifest_bwrap_fixture_suites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id in {'terminal-bench-2', 'swe-bench-verified'} else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "DEFAULT_BENCHMARK_MANIFEST",
        manifest_path,
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--run-id",
            "default-smoke",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "default-smoke"
    summary = json.loads((result_dir / "summary.json").read_text())
    run_state = json.loads((tmp_path / "run" / "benchmark-default-smoke.json").read_text())
    assert args.suite is None
    assert args.manifest == manifest_path
    assert args.execution_backend is None
    assert summary["status"] == "pass"
    assert {suite["suite"] for suite in summary["suites"]} == {
        "aime",
        "gsm8k",
        "needle-smoke",
        "ruler",
    }
    assert {suite["id"] for suite in run_state["suites"]} == {
        "aime",
        "gsm8k",
        "needle-smoke",
        "ruler",
    }
    assert not (result_dir / "terminal-bench-2").exists()


def test_smoke_command_resumes_completed_matching_fixture_suite(tmp_path: Path) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: ruler",
                "    profile: long-context",
                "    dataset_revision: ruler@rev",
                "    harness_revision: fixture@rev",
                "    prompt_template: ruler-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "  - id: gsm8k",
                "    profile: fixture",
                "    dataset_revision: gsm8k@rev",
                "    harness_revision: fixture@rev",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
            ]
        )
        + "\n"
    )
    base_args = [
        "smoke",
        "--suite",
        "ruler",
        "--suite",
        "gsm8k",
        "--manifest",
        str(manifest_path),
        "--execution-backend",
        "bwrap_rootfs",
        "--run-id",
        "resume-cli",
        "--results-root",
        str(tmp_path / "results"),
        "--run-root",
        str(tmp_path / "run"),
    ]

    first_args = build_parser().parse_args(base_args)
    assert first_args.func(first_args) == 0
    sample_path = tmp_path / "results" / "resume-cli" / "ruler" / "samples.jsonl"
    original_sample = sample_path.read_text()
    sample_path.write_text(original_sample.replace("fixture pass", "cli resumed pass"))

    second_args = build_parser().parse_args(base_args)
    assert second_args.func(second_args) == 0

    assert "cli resumed pass" in sample_path.read_text()
    run_state = json.loads(
        (tmp_path / "run" / "benchmark-resume-cli.json").read_text()
    )
    assert run_state["status"] == "completed"
    ruler_record = next(suite for suite in run_state["suites"] if suite["id"] == "ruler")
    assert ruler_record == {
        "id": "ruler",
        "status": "resumed",
        "tasks_total": 1,
        "tasks_completed": 1,
        "artifact_dir": str(tmp_path / "results" / "resume-cli" / "ruler"),
    }


def test_smoke_command_records_execution_backend_in_fixture_samples(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: ruler",
                "    profile: long-context",
                "    dataset_revision: ruler@rev",
                "    harness_revision: fixture@rev",
                "    prompt_template: ruler-v1",
                "    execution_backend: scripts_run",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "  - id: gsm8k",
                "    profile: fixture",
                "    dataset_revision: gsm8k@rev",
                "    harness_revision: fixture@rev",
                "    prompt_template: gsm8k-v1",
                "    execution_backend: scripts_run",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
            ]
        )
        + "\n"
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "ruler",
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "scripts_run",
            "--run-id",
            "fixture-backend",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    sample = json.loads(
        (tmp_path / "results" / "fixture-backend" / "ruler" / "samples.jsonl").read_text()
    )
    assert sample["execution_backend"] == "scripts_run"


def test_write_fixture_benchmark_run_records_prompt_template_and_metric_in_samples(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "ruler@fixture",
                "harness_revision": "fixture@rev",
                "prompt_template": "ruler-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            },
            {
                "id": "gsm8k",
                "profile": "math-reasoning-thinking-disabled",
                "dataset_revision": "openai/gsm8k@fixture",
                "harness_revision": "fixture-harness",
                "prompt_template": "gsm8k-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match_final_answer",
            },
        ]
    }

    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="fixture-condition-fields",
        mode="smoke",
        suite_ids=["ruler", "gsm8k"],
        manifest=manifest,
        published_scores=None,
        execution_backend="bwrap_rootfs",
    )

    ruler_sample = json.loads(
        (summary_path.parent / "ruler" / "samples.jsonl").read_text()
    )
    gsm8k_sample = json.loads(
        (summary_path.parent / "gsm8k" / "samples.jsonl").read_text()
    )
    assert ruler_sample["prompt_template"] == "ruler-v1"
    assert ruler_sample["metric"] == "exact_match"
    assert gsm8k_sample["prompt_template"] == "gsm8k-v1"
    assert gsm8k_sample["metric"] == "exact_match_final_answer"


def test_write_fixture_benchmark_run_records_manifest_conditions_in_metrics(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "ruler",
                "profile": "long-context",
                "dataset_revision": "ruler@fixture",
                "harness_revision": "fixture@rev",
                "prompt_template": "ruler-v1",
                "execution_backend": "scripts_run",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            },
        ]
    }

    summary_path = write_fixture_benchmark_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="fixture-metric-conditions",
        mode="smoke",
        suite_ids=["ruler"],
        manifest=manifest,
        published_scores=None,
        execution_backend="scripts_run",
    )

    metrics = json.loads(
        (summary_path.parent / "ruler" / "metrics.json").read_text()
    )
    assert metrics["profile"] == "long-context"
    assert metrics["prompt_template"] == "ruler-v1"
    assert metrics["metric"] == "exact_match"
    assert metrics["execution_backend"] == "scripts_run"
    assert metrics["dataset_revision"] == "ruler@fixture"
    assert metrics["harness_revision"] == "fixture@rev"
    assert metrics["decoding_profile"] == {"temperature": 0}


def test_calibration_command_defaults_to_checked_in_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_responses_server: object,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    "    harness_revision: fixture@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    "    execution_backend: bwrap_rootfs\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in [
                        "gsm8k",
                        "aime",
                        "humaneval",
                        "mbpp",
                        "needle-smoke",
                        "ruler",
                    ]
                ],
                "  - id: terminal-bench-2",
                "    profile: terminal-agent",
                "    dataset_revision: terminal-bench-2@rev",
                "    harness_revision: harbor@rev",
                "    prompt_template: terminal-bench-2-v1",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "DEFAULT_BENCHMARK_MANIFEST",
        manifest_path,
    )
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "needle-smoke",
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "default-calibration",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "default-calibration"
    summary = json.loads((result_dir / "summary.json").read_text())
    run_state = json.loads(
        (tmp_path / "run" / "benchmark-default-calibration.json").read_text()
    )
    assert args.manifest == manifest_path
    assert summary["mode"] == "calibration"
    assert [suite["suite"] for suite in summary["suites"]] == ["needle-smoke"]
    assert [suite["id"] for suite in run_state["suites"]] == ["needle-smoke"]
    samples = [
        json.loads(line)
        for line in (result_dir / "needle-smoke" / "samples.jsonl")
        .read_text()
        .splitlines()
    ]
    assert {sample["endpoint"] for sample in samples} == {fake_responses_server.url}
    assert (result_dir / "benchmark-manifest.json").is_file()


def test_checked_in_published_scores_cover_default_conformance_suites() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = load_yaml_object(
        root / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
    )
    published_scores = load_yaml_object(
        root / ".scratch/glm52-local-serving/benchmarks/published-scores.yaml"
    )

    manifest_suites = set(glm52_benchmark_verifier.manifest_suite_ids(manifest))
    published_suites = {
        score.get("suite")
        for score in published_scores.get("scores", [])
        if isinstance(score, dict)
    }

    validate_manifest_suite_coverage(manifest)
    assert manifest_suites <= published_suites


def test_checked_in_benchmark_manifest_has_pinned_prepare_revisions() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = load_yaml_object(
        root / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
    )

    validate_manifest_suite_coverage(manifest)
    validate_prepare_manifest_revisions(manifest)


def test_published_score_manifest_validation() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = load_yaml_object(
        root / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
    )
    published_scores = load_yaml_object(
        root / ".scratch/glm52-local-serving/benchmarks/published-scores.yaml"
    )
    suite_ids = glm52_benchmark_verifier.manifest_suite_ids(manifest)
    published_suites = {
        score.get("suite")
        for score in published_scores.get("scores", [])
        if isinstance(score, dict)
    }

    assert set(suite_ids) <= published_suites
    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match=(
            "published score for needle-smoke missing fields: "
            "score, source_type, source_url, tolerance"
        ),
    ):
        validate_conformance_inputs(
            manifest=manifest,
            published_scores=published_scores,
            suite_ids=suite_ids,
            execution_backend_override=None,
        )


def test_checked_in_published_score_conditions_match_benchmark_manifest() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = load_yaml_object(
        root / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
    )
    published_scores = load_yaml_object(
        root / ".scratch/glm52-local-serving/benchmarks/published-scores.yaml"
    )
    suites = {
        suite["id"]: suite
        for suite in manifest["suites"]
        if isinstance(suite, dict) and isinstance(suite.get("id"), str)
    }
    scores = {
        score["suite"]: score
        for score in published_scores["scores"]
        if isinstance(score, dict) and isinstance(score.get("suite"), str)
    }
    condition_fields = [
        "profile",
        "metric",
        "prompt_template",
        "dataset_revision",
        "harness_revision",
        "execution_backend",
        "decoding_profile",
    ]

    for suite_id, suite in suites.items():
        score = scores[suite_id]
        for field in condition_fields:
            assert score[field] == suite[field], f"{suite_id}.{field}"


def test_checked_in_harbor_smoke_config_has_pinned_sources() -> None:
    root = Path(__file__).resolve().parents[2]
    config = load_harbor_smoke_config(
        root
        / ".scratch/glm52-local-serving/harbor/configs/terminal-bench-2-smoke.yaml"
    )
    lock = load_yaml_object(
        root / ".scratch/glm52-local-serving/harbor/datasets/terminal-bench-2.lock.yaml"
    )

    assert config["harness_source"]["revision"] == HARBOR_FIXTURE_REVISION
    assert config["benchmark_source"]["revision"] == TERMINAL_BENCH_FIXTURE_REVISION
    assert config["execution"]["dataset"] == HARBOR_TERMINAL_BENCH_DATASET
    assert (
        config["execution"]["dataset_version"]
        == HARBOR_TERMINAL_BENCH_DATASET_VERSION
    )
    assert config["execution"]["repo"] == (
        f"harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}"
    )
    assert config["subset"]["smoke_tasks"] == [HARBOR_TERMINAL_BENCH_SMOKE_TASK]
    assert lock["harness_source"]["revision"] == HARBOR_FIXTURE_REVISION
    assert lock["benchmark_source"]["revision"] == TERMINAL_BENCH_FIXTURE_REVISION
    assert lock["dataset"] == HARBOR_TERMINAL_BENCH_DATASET
    assert lock["dataset_version"] == HARBOR_TERMINAL_BENCH_DATASET_VERSION
    assert lock["repo"] == f"harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}"
    assert lock["smoke_tasks"] == [HARBOR_TERMINAL_BENCH_SMOKE_TASK]


def test_checked_in_swe_bench_harbor_smoke_config_is_loadable() -> None:
    config = load_harbor_smoke_config(
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
    )

    assert config["suite"] == "swe-bench-verified"
    assert config["runnable"] is True
    assert config["dataset_source"]["revision"] == SWEBENCH_VERIFIED_HF_DATASET_REVISION
    assert config["harness_source"]["revision"] == SWEBENCH_HARNESS_REVISION
    assert config["subset"]["smoke_instances"] == [SWEBENCH_SMOKE_INSTANCE]
    assert config["official_images"]["per_instance_images"] == [
        {
            "instance_id": SWEBENCH_SMOKE_INSTANCE,
            "row_image": SWEBENCH_SMOKE_ROW_IMAGE,
            "image_digest": SWEBENCH_SMOKE_IMAGE_DIGEST,
        }
    ]
    assert config["conformance"]["claim"] == "none"
    assert config["conformance"]["comparable_to_published"] is False


def test_load_harbor_smoke_config_rejects_unresolved_legacy_harbor_dataset(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench-2",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - tb2-smoke-shell-hello",
                "metric: task_success",
                "",
            ]
        )
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="terminal-bench-2 is not available in Harbor registry",
    ):
        load_harbor_smoke_config(config_path)


def test_write_harbor_environment_failure_records_classified_summary(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    config = load_harbor_smoke_config(config_path)
    manifest = {
        "suites": [
            {
                "id": "terminal-bench-2",
                "profile": "terminal-agent",
                "dataset_revision": "terminal-bench-2@rev",
                "harness_revision": "harbor@rev",
                "prompt_template": "terminal-bench-2-v1",
                "execution_backend": "harbor_local_docker",
                "decoding_profile": {"temperature": 0.2},
                "metric": "task_success",
            }
        ]
    }

    summary_path = write_harbor_environment_failure(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="tbench2-smoke",
        suite_id="terminal-bench-2",
        reason="harbor executable not found",
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        environment_provider="local_docker",
        smoke_config=config,
        manifest=manifest,
    )

    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "environment_setup_failed"
    assert summary["suites"][0]["state"] == "environment_setup_failed"
    assert summary["harbor"]["trials_jsonl"] == "harbor/trials.jsonl"
    assert summary["harbor"]["artifacts_dir"] == "harbor/artifacts"
    assert summary["harbor"]["smoke_config"] == "harbor/configs/terminal-bench-2-smoke.yaml"
    harbor_artifact = summary_path.parent / "harbor" / "trials.jsonl"
    assert harbor_artifact.is_file()
    payload = json.loads(harbor_artifact.read_text().strip())
    assert payload["responses_base_url"] == "http://host.docker.internal:8080/v1"
    assert payload["endpoint"] == "http://host.docker.internal:8080/v1/responses"
    assert payload["local_host_route"] == "host.docker.internal"
    assert payload["agent_version"] == "glm52-harbor-agent-v1"
    assert payload["local_container_runtime"] == "docker"
    assert payload["smoke_config_sha256"]
    copied_config = load_harbor_smoke_config(
        summary_path.parent / "harbor" / "configs" / "terminal-bench-2-smoke.yaml"
    )
    assert copied_config["subset"]["smoke_tasks"] == [HARBOR_TERMINAL_BENCH_SMOKE_TASK]
    copied_manifest = json.loads(
        (summary_path.parent / "benchmark-manifest.json").read_text()
    )
    assert copied_manifest["suites"][0]["id"] == "terminal-bench-2"
    run_record = json.loads((summary_path.parent / "run.json").read_text())
    assert run_record["status"] == "environment_setup_failed"
    assert run_record["suites"][0]["status"] == "environment_setup_failed"
    root_run_record = json.loads((tmp_path / "run" / "benchmark-tbench2-smoke.json").read_text())
    assert root_run_record == run_record
    cleanup_record = json.loads((tmp_path / "run" / "cleanup-tbench2-smoke.json").read_text())
    assert cleanup_record["run_id"] == "tbench2-smoke"
    assert cleanup_record["temp_dirs"] == []
    lock = json.loads((tmp_path / "run" / "benchmark-tbench2-smoke.lock").read_text())
    assert lock["status"] == "environment_setup_failed"
    assert lock["completed_at"]
    environment = json.loads((summary_path.parent / "environment.json").read_text())
    assert environment["execution_backend"] == "harbor_local_docker"
    assert environment["responses_base_url"] == "http://host.docker.internal:8080/v1"
    assert environment["local_host_route"] == "host.docker.internal"
    assert environment["local_container_runtime"] == "docker"
    state = json.loads((summary_path.parent / "evalrun-state.json").read_text())
    assert state["campaign_materialization"]["status"] == "completed"
    assert state["trial_generation"]["terminal-bench-2"]["status"] == "completed"
    assert state["grading"]["terminal-bench-2"]["status"] == "completed"
    assert (
        state["suite_summary"]["terminal-bench-2"]["status"]
        == "environment_setup_failed"
    )
    assert state["campaign_summary"]["status"] == "environment_setup_failed"
    archive_manifest = json.loads(
        (summary_path.parent / "archive-manifest.json").read_text()
    )
    assert "summary.json" in archive_manifest["contract_artifacts"]
    assert "run.json" in archive_manifest["contract_artifacts"]
    assert "environment.json" in archive_manifest["contract_artifacts"]
    assert "benchmark-manifest.json" in archive_manifest["contract_artifacts"]
    assert "evalrun-state.json" in archive_manifest["contract_artifacts"]
    assert "harbor/trials.jsonl" in archive_manifest["contract_artifacts"]
    assert (
        "harbor/configs/terminal-bench-2-smoke.yaml"
        in archive_manifest["contract_artifacts"]
    )


def test_load_harbor_smoke_config_requires_pinned_tasks(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )

    config = load_harbor_smoke_config(config_path)

    assert config["suite"] == "terminal-bench-2"
    assert config["execution"]["execution_backend"] == "harbor_local_docker"
    assert config["subset"]["smoke_tasks"] == [HARBOR_TERMINAL_BENCH_SMOKE_TASK]


def test_load_harbor_smoke_config_rejects_placeholder_source_revisions(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                "  revision: harbor-placeholder-revision",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match=r"harness_source\.revision must be pinned",
    ):
        load_harbor_smoke_config(config_path)


def test_load_harbor_smoke_config_rejects_unpinned_task_list(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks: []",
                "metric: task_success",
                "",
            ]
        )
    )

    try:
        load_harbor_smoke_config(config_path)
    except Exception as error:
        assert "smoke_tasks" in str(error)
    else:
        raise AssertionError("empty smoke task list should fail validation")


def test_write_harbor_smoke_config_artifact_records_sha256(tmp_path: Path) -> None:
    harbor_dir = tmp_path / "harbor"
    config = {
        "schema_version": 1,
        "suite": "terminal-bench-2",
        "profile": "terminal-agent",
        "endpoint": "responses",
        "stream": True,
        "tools": "enabled",
        "harness_source": {
            "type": "git",
            "url": "https://github.com/harbor-framework/harbor",
            "revision": HARBOR_FIXTURE_REVISION,
        },
        "benchmark_source": {
            "type": "web_or_harness_release",
            "url": "https://www.tbench.ai/benchmarks/terminal-bench-2",
            "revision": TERMINAL_BENCH_FIXTURE_REVISION,
        },
        "execution": {
            "harness": "harbor",
            "dataset": HARBOR_TERMINAL_BENCH_DATASET,
            "dataset_version": HARBOR_TERMINAL_BENCH_DATASET_VERSION,
            "repo": f"harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
            "execution_backend": "harbor_local_docker",
            "container": "required",
            "timeout_seconds_per_task": 1800,
        },
        "subset": {"smoke_tasks": [HARBOR_TERMINAL_BENCH_SMOKE_TASK]},
        "metric": "task_success",
    }

    artifact = write_harbor_smoke_config_artifact(harbor_dir, config)

    copied = load_harbor_smoke_config(artifact["path"])
    assert copied["suite"] == "terminal-bench-2"
    assert artifact["sha256"]


def test_build_harbor_subprocess_env_preserves_pythonpath_without_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = str(Path(glm52_benchmark_verifier.__file__).resolve().parents[1])
    existing_entry = "/tmp/existing-pythonpath"
    monkeypatch.setenv("PYTHONPATH", f"{existing_entry}{os.pathsep}{repo_root}")

    env = glm52_benchmark_verifier.build_harbor_subprocess_env()

    pythonpath_entries = env["PYTHONPATH"].split(os.pathsep)
    assert pythonpath_entries[0] == repo_root
    assert pythonpath_entries == [repo_root, existing_entry]


def test_terminal_bench_smoke_classifies_bad_responses_models_endpoint_before_harbor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    class HtmlModelsResponse:
        def __enter__(self) -> "HtmlModelsResponse":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return b"<html><title>SearXNG</title></html>"

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_urlopen(url: str, *, timeout: float) -> HtmlModelsResponse:
        assert url == "http://host.docker.internal:8080/v1/models"
        assert timeout == 2.0
        return HtmlModelsResponse()

    def fail_if_harbor_runs(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Harbor should not run when the Responses /models preflight fails")

    _simulate_host_control_domain(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        fail_if_harbor_runs,
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "terminal-bench-2",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://host.docker.internal:8080/v1",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "tbench2-harbor-bad-responses",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 2

    result_dir = tmp_path / "results" / "tbench2-harbor-bad-responses"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "environment_setup_failed"
    reason = summary["suites"][0]["reason"]
    assert reason == (
        "Responses /models preflight failed for "
        "http://host.docker.internal:8080/v1/models: endpoint did not return "
        "JSON with a non-empty data list"
    )
    trial = json.loads((result_dir / "harbor" / "trials.jsonl").read_text())
    assert trial["state"] == "environment_setup_failed"
    assert trial["reason"] == reason


def test_terminal_bench_smoke_explains_host_docker_route_dns_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "runnable: true",
                "conformance:",
                "  claim: none",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_urlopen(url: str, *, timeout: float) -> object:
        assert url == "http://host.docker.internal:8080/v1/models"
        assert timeout == 2.0
        raise glm52_benchmark_verifier.urllib.error.URLError(
            "[Errno -2] Name or service not known"
        )

    def fail_if_harbor_runs(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Harbor should not run when the host preflight cannot resolve the adapter URL")

    _simulate_host_control_domain(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        fail_if_harbor_runs,
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "terminal-bench-2",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://host.docker.internal:8080/v1",
            "--local-host-route",
            "host.docker.internal",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "tbench2-host-route-dns-failure",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 2

    result_dir = tmp_path / "results" / "tbench2-host-route-dns-failure"
    summary = json.loads((result_dir / "summary.json").read_text())
    reason = summary["suites"][0]["reason"]
    assert "host process could not resolve host.docker.internal" in reason
    assert "use a host-resolvable --responses-base-url" in reason
    assert "keep --local-host-route host.docker.internal for Docker containers" in reason
    trial = json.loads((result_dir / "harbor" / "trials.jsonl").read_text())
    assert trial["reason"] == reason


def test_terminal_bench_smoke_records_rootfs_host_bootstrap_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    monkeypatch.setenv("MONARCH_IN_ROOTFS", "1")
    monkeypatch.setenv("PATH", "/workspace/monarch/.venv-rootfs/bin:/usr/bin")
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", lambda name: None)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "terminal-bench-2",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://host.docker.internal:8080/v1",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "tbench2-rootfs-host-bootstrap",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 2

    result_dir = tmp_path / "results" / "tbench2-rootfs-host-bootstrap"
    summary = json.loads((result_dir / "summary.json").read_text())
    environment = json.loads((result_dir / "environment.json").read_text())
    trial = json.loads((result_dir / "harbor" / "trials.jsonl").read_text())
    diagnostics = summary["environment_diagnostics"]
    assert diagnostics == environment["environment_diagnostics"]
    assert diagnostics == trial["environment_diagnostics"]
    assert diagnostics["execution_domain"] == "scripts_run_rootfs"
    assert diagnostics["host_bootstrap_required"] is True
    assert diagnostics["path"] == "/workspace/monarch/.venv-rootfs/bin:/usr/bin"
    assert diagnostics["tools"]["harbor"]["status"] == "missing"
    assert diagnostics["tools"]["harbor"]["repo_candidate_exists"] is True
    assert diagnostics["tools"]["harbor"]["repo_candidate_shebang"].startswith("#!")
    assert "/data02/home/philip.yang/workspace/monarch/" in (
        diagnostics["tools"]["harbor"]["repo_candidate_shebang"]
    )
    assert diagnostics["tools"]["docker"]["status"] == "missing"
    assert diagnostics["tools"]["docker"]["socket_exists"] is False
    assert summary["suites"][0]["reason"] == (
        "host-control domain required for harbor_local_docker: "
        "running inside scripts/run rootfs"
    )


def test_terminal_bench_smoke_invokes_harbor_and_archives_trials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        run_root = tmp_path / "run"
        benchmark_state = run_root / "benchmark-tbench2-harbor-pass.json"
        lock_state = run_root / "benchmark-tbench2-harbor-pass.lock"
        cleanup_state = run_root / "cleanup-tbench2-harbor-pass.json"
        assert benchmark_state.is_file()
        assert lock_state.is_file()
        assert cleanup_state.is_file()
        assert json.loads(benchmark_state.read_text())["status"] == "running"
        lock = json.loads(lock_state.read_text())
        assert lock["run_id"] == "tbench2-harbor-pass"
        assert lock["mode"] == "smoke"
        assert lock["status"] == "running"
        cleanup = json.loads(cleanup_state.read_text())
        assert cleanup["containers"] == []
        assert command[:3] == ["/usr/bin/harbor", "run", "--config"]
        assert "--yes" in command
        repo_root = str(Path(glm52_benchmark_verifier.__file__).resolve().parents[1])
        assert env["PYTHONPATH"].split(os.pathsep)[0] == repo_root
        job_config = load_yaml_object(Path(command[3]))
        output_dir = Path(job_config["jobs_dir"])
        assert cleanup["temp_dirs"] == [
            {
                "path": str(output_dir),
                "purpose": "harbor_raw_output",
            }
        ]
        (output_dir / "artifacts").mkdir(parents=True)
        (output_dir / "trials.jsonl").write_text(
            json.dumps(
                {
                    "task_id": HARBOR_TERMINAL_BENCH_SMOKE_TASK,
                    "trial_id": "trial-1",
                    "model_id": "zai-org/GLM-5.2",
                    "endpoint": "http://host.docker.internal:8080/v1/responses",
                    "agent_version": "glm52-harbor-agent-v1",
                    "environment_provider": "local_docker",
                    "local_host_route": "host.docker.internal",
                    "state": "passed",
                },
                sort_keys=True,
            )
            + "\n"
        )
        (output_dir / "artifacts" / "trial-1.json").write_text(
            json.dumps({"trial_id": "trial-1"}, sort_keys=True) + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    _simulate_host_control_domain(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    _patch_healthy_responses_models_endpoint(monkeypatch)

    def fake_urlopen(url: str, *, timeout: float) -> _JsonModelsResponse:
        assert url == "http://127.0.0.1:18081/v1/models"
        assert timeout == 2.0
        return _JsonModelsResponse()

    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "terminal-bench-2",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://127.0.0.1:18081/v1",
            "--local-host-route",
            "host.docker.internal",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "tbench2-harbor-pass",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "tbench2-harbor-pass"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "pass"
    assert summary["suites"][0]["tasks_passed"] == 1
    assert summary["harbor"]["trials_jsonl"] == "harbor/trials.jsonl"
    assert summary["responses_base_url"] == "http://127.0.0.1:18081/v1"
    assert (
        summary["harbor_agent_responses_base_url"]
        == "http://host.docker.internal:18081/v1"
    )
    environment = json.loads((result_dir / "environment.json").read_text())
    assert environment["execution_backend"] == "harbor_local_docker"
    assert environment["responses_base_url"] == "http://127.0.0.1:18081/v1"
    assert (
        environment["harbor_agent_responses_base_url"]
        == "http://host.docker.internal:18081/v1"
    )
    assert environment["local_container_runtime"] == "docker"
    copied_manifest = json.loads((result_dir / "benchmark-manifest.json").read_text())
    assert "terminal-bench-2" in {
        suite["id"] for suite in copied_manifest["suites"]
    }
    assert (result_dir / "harbor" / "trials.jsonl").is_file()
    assert (result_dir / "harbor" / "artifacts" / "trial-1.json").is_file()
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert "environment.json" in archive_manifest["contract_artifacts"]
    assert "benchmark-manifest.json" in archive_manifest["contract_artifacts"]
    assert "evalrun-state.json" in archive_manifest["contract_artifacts"]
    assert "harbor/trials.jsonl" in archive_manifest["contract_artifacts"]
    assert "harbor/artifacts/trial-1.json" in archive_manifest["contract_artifacts"]
    state = json.loads((result_dir / "evalrun-state.json").read_text())
    assert state["campaign_materialization"]["status"] == "completed"
    assert state["trial_generation"]["terminal-bench-2"]["status"] == "completed"
    assert state["grading"]["terminal-bench-2"]["status"] == "completed"
    assert state["suite_summary"]["terminal-bench-2"]["status"] == "pass"
    assert state["campaign_summary"]["status"] == "pass"
    final_run_state = json.loads(
        (tmp_path / "run" / "benchmark-tbench2-harbor-pass.json").read_text()
    )
    assert final_run_state["status"] == "completed"
    assert final_run_state["suites"][0]["id"] == "terminal-bench-2"
    final_lock = json.loads(
        (tmp_path / "run" / "benchmark-tbench2-harbor-pass.lock").read_text()
    )
    assert final_lock["status"] == "completed"
    assert final_lock["completed_at"]


def test_terminal_bench_smoke_ingests_harbor_021_native_result_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert command[:3] == ["/usr/bin/harbor", "run", "--config"]
        job_config = load_yaml_object(Path(command[3]))
        output_dir = Path(job_config["jobs_dir"])
        job_dir = output_dir / job_config["job_name"]
        trial_dir = job_dir / "trial-1"
        trial_dir.mkdir(parents=True)
        (job_dir / "result.json").write_text(
            json.dumps(
                {
                    "job_name": job_config["job_name"],
                    "status": "completed",
                    "trials": ["trial-1"],
                },
                sort_keys=True,
            )
            + "\n"
        )
        (trial_dir / "result.json").write_text(
            json.dumps(
                {
                    "agent_info": {
                        "model_info": {
                            "name": "GLM-5.2",
                            "provider": "zai-org",
                        },
                        "name": "glm52-responses",
                        "version": "glm52-harbor-agent-v1",
                    },
                    "exception_info": {
                        "message": "'GLM52HarborAgent' object has no attribute 'setup'",
                        "type": "AttributeError",
                    },
                    "state": "failed",
                    "task_name": HARBOR_TERMINAL_BENCH_SMOKE_TASK,
                    "trial_name": "trial-1",
                },
                sort_keys=True,
            )
            + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    _simulate_host_control_domain(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    _patch_healthy_responses_models_endpoint(monkeypatch)

    def fake_urlopen(url: str, *, timeout: float) -> _JsonModelsResponse:
        assert url == "http://127.0.0.1:18081/v1/models"
        assert timeout == 2.0
        return _JsonModelsResponse()

    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "terminal-bench-2",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://127.0.0.1:18081/v1",
            "--local-host-route",
            "host.docker.internal",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "tbench2-harbor-021",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / "tbench2-harbor-021"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "fail"
    assert summary["suites"][0]["tasks_total"] == 1
    assert summary["suites"][0]["tasks_passed"] == 0
    assert summary["suites"][0]["infrastructure_failures"] == 1
    assert summary["suites"][0]["model_failures"] == 0
    assert summary["harbor"]["trials_jsonl"] == "harbor/trials.jsonl"

    trials = [
        json.loads(line)
        for line in (result_dir / "harbor" / "trials.jsonl").read_text().splitlines()
    ]
    assert len(trials) == 1
    trial = trials[0]
    assert trial["agent_version"] == "glm52-harbor-agent-v1"
    assert trial["endpoint"] == "http://host.docker.internal:18081/v1/responses"
    assert trial["environment_provider"] == "local_docker"
    assert trial["exception_info"] == {
        "message": "'GLM52HarborAgent' object has no attribute 'setup'",
        "type": "AttributeError",
    }
    assert trial["local_host_route"] == "host.docker.internal"
    assert trial["model_id"] == "zai-org/GLM-5.2"
    assert trial["state"] == "environment_crashed"
    assert trial["task_id"] == HARBOR_TERMINAL_BENCH_SMOKE_TASK
    assert trial["trial_id"] == "trial-1"

    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "fail"
    assert "harbor/trials.jsonl" in archive_manifest["contract_artifacts"]
    assert (
        "harbor/artifacts/tbench2-harbor-021/result.json"
        in archive_manifest["contract_artifacts"]
    )
    assert (
        "harbor/artifacts/tbench2-harbor-021/trial-1/result.json"
        in archive_manifest["contract_artifacts"]
    )
    final_run_state = json.loads(
        (tmp_path / "run" / "benchmark-tbench2-harbor-021.json").read_text()
    )
    assert final_run_state["status"] == "completed"
    final_lock = json.loads(
        (tmp_path / "run" / "benchmark-tbench2-harbor-021.lock").read_text()
    )
    assert final_lock["status"] == "completed"
    assert final_lock["completed_at"]


def test_terminal_bench_smoke_invokes_real_harbor_run_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert command[:3] == ["/usr/bin/harbor", "run", "--config"]
        job_config_path = Path(command[3])
        assert "--yes" in command
        repo_root = str(Path(glm52_benchmark_verifier.__file__).resolve().parents[1])
        assert env["PYTHONPATH"].split(os.pathsep)[0] == repo_root
        assert job_config_path.is_file()
        job_config = load_yaml_object(job_config_path)
        assert job_config["job_name"] == "tbench2-harbor-real-cli"
        assert job_config["jobs_dir"] == str(tmp_path / "results" / "tbench2-harbor-real-cli" / "harbor-raw")
        assert job_config["environment"]["type"] == "docker"
        assert job_config["environment"]["extra_allowed_hosts"] == [
            "host.docker.internal"
        ]
        assert job_config["agents"] == [
            {
                "import_path": "scripts.glm52_harbor_agent:GLM52HarborAgent",
                "model_name": "zai-org/GLM-5.2",
                "override_timeout_sec": 1800,
                "kwargs": {
                    "responses_base_url": "http://host.docker.internal:18081/v1",
                    "local_host_route": "host.docker.internal",
                    "responses_timeout_seconds": 1800,
                    "stream": True,
                },
            }
        ]
        assert job_config["datasets"] == [
            {
                "name": HARBOR_TERMINAL_BENCH_DATASET,
                "version": HARBOR_TERMINAL_BENCH_DATASET_VERSION,
                "repo": f"harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "task_names": [HARBOR_TERMINAL_BENCH_SMOKE_TASK],
            }
        ]
        output_dir = tmp_path / "results" / "tbench2-harbor-real-cli" / "harbor-raw"
        (output_dir / "artifacts").mkdir(parents=True)
        (output_dir / "trials.jsonl").write_text(
            json.dumps(
                {
                    "task_id": HARBOR_TERMINAL_BENCH_SMOKE_TASK,
                    "trial_id": "trial-1",
                    "model_id": "zai-org/GLM-5.2",
                    "endpoint": "http://host.docker.internal:18081/v1/responses",
                    "agent_version": "glm52-harbor-agent-v1",
                    "environment_provider": "local_docker",
                    "local_host_route": "host.docker.internal",
                    "state": "passed",
                },
                sort_keys=True,
            )
            + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    _simulate_host_control_domain(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    _patch_healthy_responses_models_endpoint(monkeypatch)

    def fake_urlopen(url: str, *, timeout: float) -> _JsonModelsResponse:
        assert url == "http://127.0.0.1:18081/v1/models"
        assert timeout == 2.0
        return _JsonModelsResponse()

    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "terminal-bench-2",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://127.0.0.1:18081/v1",
            "--local-host-route",
            "host.docker.internal",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "tbench2-harbor-real-cli",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0


def test_swe_bench_smoke_invokes_real_harbor_run_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'swe-bench-verified' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'swebench' if suite_id == 'swe-bench-verified' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'swe-bench-verified' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert command[:3] == ["/usr/bin/harbor", "run", "--config"]
        job_config_path = Path(command[3])
        assert "--yes" in command
        repo_root = str(Path(glm52_benchmark_verifier.__file__).resolve().parents[1])
        assert env["PYTHONPATH"].split(os.pathsep)[0] == repo_root
        job_config = load_yaml_object(job_config_path)
        assert job_config["job_name"] == "swebench-harbor-real-cli"
        assert job_config["jobs_dir"] == str(
            tmp_path / "results" / "swebench-harbor-real-cli" / "harbor-raw"
        )
        assert job_config["environment"]["type"] == "docker"
        assert job_config["environment"]["extra_allowed_hosts"] == [
            "host.docker.internal"
        ]
        assert job_config["agents"] == [
            {
                "import_path": "scripts.glm52_harbor_agent:GLM52HarborAgent",
                "model_name": "zai-org/GLM-5.2",
                "override_timeout_sec": 1800,
                "kwargs": {
                    "responses_base_url": "http://host.docker.internal:18081/v1",
                    "local_host_route": "host.docker.internal",
                    "responses_timeout_seconds": 1800,
                    "stream": True,
                },
            }
        ]
        assert job_config["datasets"] == [
            {
                "name": "swe-bench-verified",
                "adapter": "swebench_verified",
                "dataset_source": {
                    "type": "huggingface_or_swebench",
                    "dataset": "SWE-bench/SWE-bench_Verified",
                    "repo_type": "dataset",
                    "revision": SWEBENCH_VERIFIED_HF_DATASET_REVISION,
                },
                "harness_source": {
                    "type": "git",
                    "url": "https://github.com/SWE-bench/SWE-bench.git",
                    "revision": SWEBENCH_HARNESS_REVISION,
                },
                "instance_ids": [SWEBENCH_SMOKE_INSTANCE],
                "instance_images": [
                    {
                        "instance_id": SWEBENCH_SMOKE_INSTANCE,
                        "row_image": SWEBENCH_SMOKE_ROW_IMAGE,
                        "image_digest": SWEBENCH_SMOKE_IMAGE_DIGEST,
                    }
                ],
            }
        ]
        output_dir = (
            tmp_path / "results" / "swebench-harbor-real-cli" / "harbor-raw"
        )
        (output_dir / "artifacts").mkdir(parents=True)
        (output_dir / "trials.jsonl").write_text(
            json.dumps(
                {
                    "task_id": SWEBENCH_SMOKE_INSTANCE,
                    "trial_id": "trial-1",
                    "model_id": "zai-org/GLM-5.2",
                    "endpoint": "http://host.docker.internal:18081/v1/responses",
                    "agent_version": "glm52-harbor-agent-v1",
                    "environment_provider": "local_docker",
                    "local_host_route": "host.docker.internal",
                    "state": "passed",
                },
                sort_keys=True,
            )
            + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    _simulate_host_control_domain(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    _patch_healthy_responses_models_endpoint(monkeypatch)

    def fake_urlopen(url: str, *, timeout: float) -> _JsonModelsResponse:
        assert url == "http://127.0.0.1:18081/v1/models"
        assert timeout == 2.0
        return _JsonModelsResponse()

    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "swe-bench-verified",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://127.0.0.1:18081/v1",
            "--local-host-route",
            "host.docker.internal",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "swebench-harbor-real-cli",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0


def test_swe_bench_smoke_refuses_harbor_launch_inside_rootfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'swe-bench-verified' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'swebench' if suite_id == 'swe-bench-verified' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'swe-bench-verified' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fail_if_harbor_runs(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Harbor should not launch from inside the Monarch rootfs")

    monkeypatch.setenv("MONARCH_IN_ROOTFS", "1")
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    _patch_healthy_responses_models_endpoint(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fail_if_harbor_runs)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "swe-bench-verified",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://host.docker.internal:8080/v1",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "swebench-harbor-rootfs-domain",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 2

    result_dir = tmp_path / "results" / "swebench-harbor-rootfs-domain"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "environment_setup_failed"
    assert summary["environment_diagnostics"]["execution_domain"] == "scripts_run_rootfs"
    assert summary["environment_diagnostics"]["required_execution_domain"] == "host"
    assert summary["environment_diagnostics"]["host_bootstrap_required"] is True
    assert "host-control domain" in summary["suites"][0]["reason"]
    assert "inside scripts/run rootfs" in summary["suites"][0]["reason"]
    trial = json.loads((result_dir / "harbor" / "trials.jsonl").read_text())
    assert trial["state"] == "environment_setup_failed"
    assert trial["environment_diagnostics"]["required_execution_domain"] == "host"


def test_swe_bench_smoke_classifies_bad_responses_models_endpoint_before_fixture_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'swe-bench-verified' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'swebench' if suite_id == 'swe-bench-verified' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'swe-bench-verified' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    class HtmlModelsResponse:
        def __enter__(self) -> "HtmlModelsResponse":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return b"<html><title>SearXNG</title></html>"

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_urlopen(url: str, *, timeout: float) -> HtmlModelsResponse:
        assert url == "http://host.docker.internal:8080/v1/models"
        assert timeout == 2.0
        return HtmlModelsResponse()

    def fail_if_harbor_runs(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Harbor should not run when the Responses /models preflight fails")

    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        fail_if_harbor_runs,
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "swe-bench-verified",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://host.docker.internal:8080/v1",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "swebench-harbor-bad-responses",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 2

    result_dir = tmp_path / "results" / "swebench-harbor-bad-responses"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "environment_setup_failed"
    assert summary["suites"][0]["suite"] == "swe-bench-verified"
    assert summary["harbor"]["smoke_config"] == (
        "harbor/configs/swe-bench-verified-smoke.yaml"
    )
    assert (result_dir / "harbor" / "trials.jsonl").is_file()
    assert not (result_dir / "swe-bench-verified" / "samples.jsonl").exists()
    run_record = json.loads((result_dir / "run.json").read_text())
    assert run_record["execution_backend"] == "harbor_local_docker"
    assert run_record["suite"] == "swe-bench-verified"


def test_swe_bench_verified_harbor_smoke_config_defaults_to_swe_bench(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'swe-bench-verified' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'swebench' if suite_id == 'swe-bench-verified' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'swe-bench-verified' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    class HtmlModelsResponse:
        def __enter__(self) -> "HtmlModelsResponse":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return b"<html><title>SearXNG</title></html>"

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fake_urlopen(url: str, *, timeout: float) -> HtmlModelsResponse:
        assert url == "http://host.docker.internal:8080/v1/models"
        assert timeout == 2.0
        return HtmlModelsResponse()

    def fail_if_harbor_runs(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Harbor should not run when the Responses /models preflight fails")

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "DEFAULT_HARBOR_SWEBENCH_SMOKE_CONFIG",
        config_path,
    )
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    monkeypatch.setattr(glm52_benchmark_verifier.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        fail_if_harbor_runs,
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "swe-bench-verified",
            "--manifest",
            str(manifest_path),
            "--responses-base-url",
            "http://host.docker.internal:8080/v1",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "swebench-default-smoke-config",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 2

    result_dir = tmp_path / "results" / "swebench-default-smoke-config"
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "environment_setup_failed"
    assert summary["suites"][0]["suite"] == "swe-bench-verified"
    assert summary["harbor"]["smoke_config"] == (
        "harbor/configs/swe-bench-verified-smoke.yaml"
    )
    copied_config = load_harbor_smoke_config(
        result_dir / "harbor" / "configs" / "swe-bench-verified-smoke.yaml"
    )
    assert copied_config["suite"] == "swe-bench-verified"
    assert not (
        result_dir / "harbor" / "configs" / "terminal-bench-2-smoke.yaml"
    ).exists()


def test_terminal_bench_smoke_finalizes_state_after_harbor_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "terminal-bench-2-smoke.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "suite: terminal-bench-2",
                "profile: terminal-agent",
                "endpoint: responses",
                "stream: true",
                "tools: enabled",
                "harness_source:",
                "  type: git",
                "  url: https://github.com/harbor-framework/harbor",
                f"  revision: {HARBOR_FIXTURE_REVISION}",
                "benchmark_source:",
                "  type: web_or_harness_release",
                "  url: https://www.tbench.ai/benchmarks/terminal-bench-2",
                f"  revision: {TERMINAL_BENCH_FIXTURE_REVISION}",
                "execution:",
                "  harness: harbor",
                "  dataset: terminal-bench",
                "  dataset_version: \"2.0\"",
                f"  repo: harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
                "  execution_backend: harbor_local_docker",
                "  container: required",
                "  timeout_seconds_per_task: 1800",
                "subset:",
                "  smoke_tasks:",
                "    - adaptive-rejection-sampler",
                "metric: task_success",
                "",
            ]
        )
    )
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"harbor", "docker"} else None

    def fail_harbor(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        run_root = tmp_path / "run"
        assert (run_root / "benchmark-tbench2-harbor-failure.json").is_file()
        assert (run_root / "cleanup-tbench2-harbor-failure.json").is_file()
        repo_root = str(Path(glm52_benchmark_verifier.__file__).resolve().parents[1])
        assert env["PYTHONPATH"].split(os.pathsep)[0] == repo_root
        return subprocess.CompletedProcess(
            command,
            17,
            stdout="",
            stderr="Harbor provider failed before trial artifacts\n",
        )

    _simulate_host_control_domain(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", fake_which)
    _patch_healthy_responses_models_endpoint(monkeypatch)
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fail_harbor)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "terminal-bench-2",
            "--manifest",
            str(manifest_path),
            "--harbor-smoke-config",
            str(config_path),
            "--responses-base-url",
            "http://host.docker.internal:8080/v1",
            "--local-container-runtime",
            "docker",
            "--run-id",
            "tbench2-harbor-failure",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 2

    result_dir = tmp_path / "results" / "tbench2-harbor-failure"
    summary = json.loads((result_dir / "summary.json").read_text())
    result_run_state = json.loads((result_dir / "run.json").read_text())
    root_run_state = json.loads(
        (tmp_path / "run" / "benchmark-tbench2-harbor-failure.json").read_text()
    )
    assert summary["status"] == "environment_setup_failed"
    assert "Harbor provider failed" in summary["suites"][0]["reason"]
    assert result_run_state["status"] == "environment_setup_failed"
    assert root_run_state["status"] == "environment_setup_failed"
    assert result_run_state["suites"][0]["status"] == "environment_setup_failed"
    assert root_run_state["suites"][0]["status"] == "environment_setup_failed"
    final_lock = json.loads(
        (tmp_path / "run" / "benchmark-tbench2-harbor-failure.lock").read_text()
    )
    assert final_lock["status"] == "environment_setup_failed"
    assert final_lock["completed_at"]


def test_harbor_success_summary_rejects_trial_missing_required_metadata(
    tmp_path: Path,
) -> None:
    config = {
        "schema_version": 1,
        "suite": "terminal-bench-2",
        "profile": "terminal-agent",
        "endpoint": "responses",
        "stream": True,
        "tools": "enabled",
        "harness_source": {
            "type": "git",
            "url": "https://github.com/harbor-framework/harbor",
            "revision": HARBOR_FIXTURE_REVISION,
        },
        "benchmark_source": {
            "type": "web_or_harness_release",
            "url": "https://www.tbench.ai/benchmarks/terminal-bench-2",
            "revision": TERMINAL_BENCH_FIXTURE_REVISION,
        },
        "execution": {
            "harness": "harbor",
            "dataset": HARBOR_TERMINAL_BENCH_DATASET,
            "dataset_version": HARBOR_TERMINAL_BENCH_DATASET_VERSION,
            "repo": f"harbor-framework/harbor@{HARBOR_FIXTURE_REVISION}",
            "execution_backend": "harbor_local_docker",
            "container": "required",
            "timeout_seconds_per_task": 1800,
        },
        "subset": {"smoke_tasks": [HARBOR_TERMINAL_BENCH_SMOKE_TASK]},
        "metric": "task_success",
    }
    results_root = tmp_path / "results"
    run_root = tmp_path / "run"
    run_id = "tbench2-missing-metadata"
    write_harbor_run_state(
        results_root=results_root,
        run_root=run_root,
        run_id=run_id,
        suite_id="terminal-bench-2",
        smoke_config=config,
        manifest=None,
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        environment_provider="local_docker",
    )
    harbor_output_dir = tmp_path / "harbor-raw"
    (harbor_output_dir / "artifacts").mkdir(parents=True)
    (harbor_output_dir / "trials.jsonl").write_text(
        json.dumps(
            {
                "task_id": HARBOR_TERMINAL_BENCH_SMOKE_TASK,
                "trial_id": "trial-1",
                "model_id": "zai-org/GLM-5.2",
                "state": "passed",
            },
            sort_keys=True,
        )
        + "\n"
    )

    try:
        write_harbor_success_summary(
            results_root=results_root,
            run_root=run_root,
            run_id=run_id,
            suite_id="terminal-bench-2",
            harbor_output_dir=harbor_output_dir,
            responses_base_url="http://host.docker.internal:8080/v1",
            local_host_route="host.docker.internal",
            environment_provider="local_docker",
            smoke_config=config,
        )
    except Exception as error:
        assert "Harbor trial trial-1 missing fields" in str(error)
        assert "agent_version" in str(error)
        assert "endpoint" in str(error)
    else:
        raise AssertionError("Harbor trials missing required metadata should fail")


def test_manifest_coverage_requires_all_named_suites() -> None:
    complete_except_swebench = {
        suite_id: {
            "id": suite_id,
            "profile": "fixture",
            "dataset_revision": "fixture",
            "harness_revision": "fixture",
            "prompt_template": f"{suite_id}-v1",
            "execution_backend": "bwrap_rootfs",
            "decoding_profile": {"temperature": 0},
            "metric": "exact_match",
        }
        for suite_id in REQUIRED_FIXTURE_SUITE_IDS
        if suite_id != "swe-bench-verified"
    }
    manifest = {
        "suites": list(complete_except_swebench.values())
    }

    try:
        validate_manifest_suite_coverage(manifest)
    except Exception as error:
        assert "missing suite entries" in str(error)
        assert "swe-bench-verified" in str(error)
    else:
        raise AssertionError("manifest without SWE-bench Verified should fail suite coverage")


def test_write_prepare_artifact_records_manifest_and_rootfs(tmp_path: Path) -> None:
    manifest = {
        "suites": [
            {
                "id": suite_id,
                "profile": "fixture",
                "dataset_revision": "fixture",
                "harness_revision": "fixture",
                "prompt_template": f"{suite_id}-v1",
                "execution_backend": "bwrap_rootfs"
                if suite_id != "terminal-bench-2"
                else "harbor_local_docker",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
            for suite_id in REQUIRED_FIXTURE_SUITE_IDS
        ]
    }

    path = write_prepare_artifact(
        results_root=tmp_path / "results",
        run_id="prepare-test",
        manifest=manifest,
        rootfs_path=tmp_path / "rootfs",
        endpoints_checked=False,
    )

    payload = json.loads(path.read_text())
    assert payload["status"] == "prepared"
    assert payload["manifest_sha256"]
    assert payload["rootfs_path"] == str(tmp_path / "rootfs")
    assert payload["endpoints_checked"] is False
    copied_manifest = json.loads((path.parent / "benchmark-manifest.json").read_text())
    assert copied_manifest == manifest
    run_record = json.loads((path.parent / "run.json").read_text())
    assert run_record["mode"] == "prepare"
    assert run_record["status"] == "prepared"
    assert run_record["artifact"] == str(path)
    environment = json.loads((path.parent / "environment.json").read_text())
    assert environment["mode"] == "prepare"
    assert environment["python"]
    archive_manifest = json.loads((path.parent / "archive-manifest.json").read_text())
    assert archive_manifest["run_id"] == "prepare-test"
    assert archive_manifest["summary_status"] == "prepared"
    assert archive_manifest["summary_path"] == "prepare.json"
    assert archive_manifest["terminal"] is True
    assert "benchmark-manifest.json" in archive_manifest["contract_artifacts"]
    assert "prepare.json" in archive_manifest["contract_artifacts"]
    assert "run.json" in archive_manifest["contract_artifacts"]
    assert "environment.json" in archive_manifest["contract_artifacts"]


def test_write_prepare_artifact_records_endpoint_preflight_results(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": suite_id,
                "profile": "fixture",
                "dataset_revision": "fixture",
                "harness_revision": "fixture",
                "prompt_template": f"{suite_id}-v1",
                "execution_backend": "bwrap_rootfs"
                if suite_id != "terminal-bench-2"
                else "harbor_local_docker",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
            for suite_id in REQUIRED_FIXTURE_SUITE_IDS
        ]
    }

    path = write_prepare_artifact(
        results_root=tmp_path / "results",
        run_id="prepare-endpoints",
        manifest=manifest,
        rootfs_path=tmp_path / "rootfs",
        endpoints_checked=True,
        endpoint_results=[
            {
                "name": "chat",
                "models_url": "http://localhost:8000/v1/models",
                "status": "unavailable",
                "error": "HTTP Error 404: File not found",
            },
            {
                "name": "responses",
                "models_url": "http://localhost:8080/v1/models",
                "status": "ok",
                "models": ["zai-org/GLM-5.2"],
            },
        ],
    )

    payload = json.loads(path.read_text())
    assert payload["endpoints_checked"] is True
    assert payload["endpoint_preflight"] == [
        {
            "name": "chat",
            "models_url": "http://localhost:8000/v1/models",
            "status": "unavailable",
            "error": "HTTP Error 404: File not found",
        },
        {
            "name": "responses",
            "models_url": "http://localhost:8080/v1/models",
            "status": "ok",
            "models": ["zai-org/GLM-5.2"],
        },
    ]


def test_write_prepare_artifact_records_tool_preflight_results(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": suite_id,
                "profile": "fixture",
                "dataset_revision": "fixture",
                "harness_revision": "fixture",
                "prompt_template": f"{suite_id}-v1",
                "execution_backend": "bwrap_rootfs"
                if suite_id != "terminal-bench-2"
                else "harbor_local_docker",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
            for suite_id in REQUIRED_FIXTURE_SUITE_IDS
        ]
    }

    path = write_prepare_artifact(
        results_root=tmp_path / "results",
        run_id="prepare-tools",
        manifest=manifest,
        rootfs_path=tmp_path / "rootfs",
        endpoints_checked=False,
        tool_results=[
            {"name": "bwrap", "status": "ok", "path": "/usr/bin/bwrap"},
            {"name": "docker", "status": "ok", "path": "/usr/bin/docker"},
            {"name": "harbor", "status": "missing"},
        ],
    )

    payload = json.loads(path.read_text())
    assert payload["tool_preflight"] == [
        {"name": "bwrap", "status": "ok", "path": "/usr/bin/bwrap"},
        {"name": "docker", "status": "ok", "path": "/usr/bin/docker"},
        {"name": "harbor", "status": "missing"},
    ]


def test_prepare_command_writes_run_state_and_cleanup_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = "ghcr.io/harbor-framework/terminal-bench-2@sha256:" + ("d" * 64)
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    (
                        f"  - id: {suite_id}\n"
                        "    profile: fixture\n"
                        "    dataset_revision: fixture\n"
                        "    harness_revision: fixture\n"
                        f"    prompt_template: {suite_id}-v1\n"
                        f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    + (
                        f"    container_image: {image}\n"
                        if suite_id == "terminal-bench-2"
                        else ""
                    )
                    + "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    )
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-state",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    exit_code = args.func(args)

    run_state = json.loads((tmp_path / "run" / "benchmark-prepare-state.json").read_text())
    lock = json.loads((tmp_path / "run" / "benchmark-prepare-state.lock").read_text())
    cleanup = json.loads((tmp_path / "run" / "cleanup-prepare-state.json").read_text())
    assert exit_code == 0
    assert run_state["mode"] == "prepare"
    assert run_state["status"] == "prepared"
    assert lock["mode"] == "prepare"
    assert lock["status"] == "prepared"
    assert lock["benchmark_state_path"] == str(
        tmp_path / "run" / "benchmark-prepare-state.json"
    )
    assert run_state["artifact"] == str(
        tmp_path / "results" / "prepare-state" / "prepare.json"
    )
    assert cleanup == {
        "schema_version": 1,
        "run_id": "prepare-state",
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }


def test_prepare_command_rejects_placeholder_suite_revisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@pinned-placeholder\n"
                    "    harness_revision: harness@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-placeholder",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite gsm8k dataset_revision must be pinned",
    ):
        args.func(args)

    assert not (tmp_path / "run" / "benchmark-prepare-placeholder.json").exists()


def test_prepare_command_rejects_source_revision_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_source = tmp_path / "dataset-source"
    harness_source = tmp_path / "harness-source"
    dataset_source.mkdir()
    harness_source.mkdir()
    (dataset_source / "problems.jsonl").write_text('{"task_id": "needle-0"}\n')
    (harness_source / "README.md").write_text("harness fixture\n")
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    "    harness_revision: harness@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in [
                        "gsm8k",
                        "aime",
                        "humaneval",
                        "mbpp",
                        "terminal-bench-2",
                        "ruler",
                    ]
                ],
                "  - id: needle-smoke",
                "    profile: fixture",
                "    dataset_revision: needle-smoke@advertised-rev",
                "    harness_revision: harness@rev",
                "    prompt_template: needle-smoke-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_source}",
                "      revision: fetched-rev",
                "    harness_source:",
                "      type: local_path",
                f"      path: {harness_source}",
                "      revision: rev",
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-source-mismatch",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match=(
            "suite needle-smoke dataset_revision "
            "must match dataset_source.revision"
        ),
    ):
        args.func(args)

    assert not (tmp_path / "run" / "benchmark-prepare-source-mismatch.json").exists()


def test_prepare_command_rejects_mutable_container_image_before_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    (
                        f"  - id: {suite_id}\n"
                        "    profile: fixture\n"
                        f"    dataset_revision: {suite_id}@rev\n"
                        "    harness_revision: harness@rev\n"
                        f"    prompt_template: {suite_id}-v1\n"
                        f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                        + (
                            "    container_image: ghcr.io/harbor-framework/terminal-bench-2:smoke\n"
                            if suite_id == "terminal-bench-2"
                            else ""
                        )
                        + "    decoding_profile:\n"
                        "      temperature: 0.2\n"
                        "    metric: exact_match"
                    )
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "ok", "path": f"/usr/bin/{name}"},
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-mutable-image",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite terminal-bench-2 container_image must be digest-pinned",
    ):
        args.func(args)

    assert not (tmp_path / "results" / "prepare-mutable-image" / "prepare.json").exists()
    assert not (tmp_path / "run" / "benchmark-prepare-mutable-image.json").exists()
    assert not (tmp_path / "run" / "cleanup-prepare-mutable-image.json").exists()


def test_prepare_command_rejects_missing_container_image_before_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    "    harness_revision: harness@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "ok", "path": f"/usr/bin/{name}"},
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-missing-image",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite terminal-bench-2 container_image must be declared",
    ):
        args.func(args)

    assert not (tmp_path / "results" / "prepare-missing-image" / "prepare.json").exists()
    assert not (tmp_path / "run" / "benchmark-prepare-missing-image.json").exists()
    assert not (tmp_path / "run" / "cleanup-prepare-missing-image.json").exists()


def test_prepare_command_rejects_missing_container_image_before_source_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: terminal-bench-2",
                "    profile: terminal-agent",
                "    dataset_revision: terminal-bench-2@dataset-rev",
                "    harness_revision: harbor@harness-rev",
                "    prompt_template: terminal-bench-2-v1",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0.2",
                "    metric: task_success",
                "    dataset_source:",
                "      type: git",
                "      url: https://example.test/terminal-bench.git",
                "      revision: dataset-rev",
                "    harness_source:",
                "      type: git",
                "      url: https://example.test/harbor.git",
                "      revision: harness-rev",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    "    harness_revision: harness@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    "    execution_backend: bwrap_rootfs\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                    if suite_id != "terminal-bench-2"
                ],
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "ok", "path": f"/usr/bin/{name}"},
    )

    def fail_materialize_prepare_caches(
        *_args: object,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        raise AssertionError("source materialization should not run before image validation")

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "materialize_prepare_caches",
        fail_materialize_prepare_caches,
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-missing-image-before-fetch",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="suite terminal-bench-2 container_image must be declared",
    ):
        args.func(args)

    assert not (
        tmp_path / "results" / "prepare-missing-image-before-fetch" / "prepare.json"
    ).exists()
    assert not (
        tmp_path / "run" / "benchmark-prepare-missing-image-before-fetch.json"
    ).exists()


def test_needle_smoke_real_adapter_uses_responses_endpoint(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    run_id = "needle-smoke-real-adapter"
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "needle-smoke",
            "--manifest",
            str(REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--responses-timeout-seconds",
            "180",
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "needle-smoke"
    for relative_path in [
        "needle-smoke/samples.jsonl",
        "needle-smoke/metrics.json",
        "needle-smoke/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
        "archive-manifest.json",
    ]:
        assert (result_dir / relative_path).is_file()
    assert [request["path"] for request in fake_responses_server.requests] == [
        "/v1/responses",
        "/v1/responses",
        "/v1/responses",
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert len(samples) == 3
    assert {sample["endpoint"] for sample in samples} == {fake_responses_server.url}
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    for sample in samples:
        assert sample["responses_timeout_seconds"] == 180.0
        assert sample["profile"] == "long-context-smoke"
        assert sample["dataset_revision"] == "fixture-needle-smoke-v1"
        assert sample["harness_revision"] == "monarch-glm52-fixture-v1"
        assert sample["prompt_template"] == "needle-smoke-v1"
        assert sample["prompt_template_sha256"] == hashlib.sha256(
            b"needle-smoke-v1"
        ).hexdigest()
        assert sample["decoding_profile"] == {
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 256,
            "glm_thinking": "disabled",
        }
        assert sample["execution_backend"] == "bwrap_rootfs"
        assert sample["latency_seconds"] >= 0
        assert sample["usage"] == {
            "input_tokens": 17,
            "output_tokens": 3,
            "total_tokens": 20,
        }
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert metrics["tasks_total"] == 3
    assert metrics["tasks_passed"] == 3
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "pass"
    assert summary["responses_timeout_seconds"] == 180.0
    assert summary["suites"][0]["model_failures"] == 0
    assert summary["suites"][0]["infrastructure_failures"] == 0
    environment = json.loads((result_dir / "environment.json").read_text())
    assert environment["responses_timeout_seconds"] == 180.0
    run_record = json.loads((result_dir / "run.json").read_text())
    assert run_record["responses_timeout_seconds"] == 180.0
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert set(archive_manifest["contract_artifacts"]) >= {
        "needle-smoke/samples.jsonl",
        "needle-smoke/metrics.json",
        "needle-smoke/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
    }


def test_needle_smoke_real_adapter_classifies_responses_failure(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    fake_responses_server.fail_responses()
    run_id = "needle-smoke-real-adapter-failure"
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "needle-smoke",
            "--manifest",
            str(REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "needle-smoke"
    assert (result_dir / "run.json").is_file()
    assert (result_dir / "archive-manifest.json").is_file()
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    failures = [
        json.loads(line)
        for line in (suite_dir / "failures.jsonl").read_text().splitlines()
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["infrastructure_failures"] > 0
    assert summary["suites"][0]["model_failures"] == 0
    assert metrics["infrastructure_failures"] > 0
    assert metrics["model_failures"] == 0
    assert failures
    assert all(failure["failure_category"] == "infrastructure" for failure in failures)
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "environment_failed"


def test_needle_smoke_calibration_real_adapter_uses_responses_endpoint(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    run_id = "needle-smoke-real-calibration"
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "needle-smoke",
            "--manifest",
            str(REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "needle-smoke"
    for relative_path in [
        "needle-smoke/samples.jsonl",
        "needle-smoke/metrics.json",
        "needle-smoke/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
        "archive-manifest.json",
    ]:
        assert (result_dir / relative_path).is_file()
    assert [request["path"] for request in fake_responses_server.requests] == [
        "/v1/responses",
        "/v1/responses",
        "/v1/responses",
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert len(samples) == 3
    assert {sample["endpoint"] for sample in samples} == {fake_responses_server.url}
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    environment = json.loads((result_dir / "environment.json").read_text())
    run_record = json.loads((result_dir / "run.json").read_text())
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert environment["mode"] == "calibration"
    assert run_record["mode"] == "calibration"
    assert summary["mode"] == "calibration"
    assert summary["responses_base_url"] == fake_responses_server.url
    assert summary["conformance"] == {
        "claim": "none",
        "comparable_to_published": False,
    }
    assert summary["status"] == "pass"
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert set(archive_manifest["contract_artifacts"]) >= {
        "needle-smoke/samples.jsonl",
        "needle-smoke/metrics.json",
        "needle-smoke/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
    }


def test_needle_smoke_calibration_real_adapter_classifies_responses_failure(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    fake_responses_server.fail_responses()
    run_id = "needle-smoke-real-calibration-failure"
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "needle-smoke",
            "--manifest",
            str(REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "needle-smoke"
    assert (result_dir / "archive-manifest.json").is_file()
    environment = json.loads((result_dir / "environment.json").read_text())
    run_record = json.loads((result_dir / "run.json").read_text())
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert environment["mode"] == "calibration"
    assert run_record["mode"] == "calibration"
    assert summary["mode"] == "calibration"
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["infrastructure_failures"] > 0
    assert summary["suites"][0]["model_failures"] == 0
    assert metrics["infrastructure_failures"] > 0
    assert metrics["model_failures"] == 0
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "environment_failed"


@pytest.mark.parametrize("mode", ["smoke", "calibration"])
def test_ruler_single_suite_real_adapter_uses_responses_endpoint(
    tmp_path: Path,
    fake_responses_server: object,
    mode: str,
) -> None:
    manifest_path = _write_ruler_cache_and_manifest(tmp_path)
    run_id = f"ruler-real-{mode}"
    args = build_parser().parse_args(
        [
            mode,
            "--suite",
            "ruler",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "ruler"
    for relative_path in [
        "ruler/samples.jsonl",
        "ruler/metrics.json",
        "ruler/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "summary.json",
        "archive-manifest.json",
    ]:
        assert (result_dir / relative_path).is_file()
    assert [request["path"] for request in fake_responses_server.requests] == [
        "/v1/responses"
    ]
    request_payload = fake_responses_server.requests[0]["payload"]
    assert "ORCHID-7194" in request_payload["input"]
    assert "What is the deployment cleanup token?" in request_payload["input"]
    assert request_payload["model"] == "zai-org/GLM-5.2"
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert len(samples) == 1
    sample = samples[0]
    assert sample["endpoint"] == fake_responses_server.url
    assert sample["endpoint"] != "fixture"
    assert sample["profile"] == "long-context"
    assert sample["dataset_revision"] == "ruler@local-fixture"
    assert sample["harness_revision"] == "lm-evaluation-harness@fixture"
    assert sample["prompt_template"] == "ruler-v1"
    assert sample["prompt_template_sha256"] == hashlib.sha256(b"ruler-v1").hexdigest()
    assert sample["decoding_profile"] == {
        "temperature": 0,
        "top_p": 1,
        "max_output_tokens": 256,
        "glm_thinking": "disabled",
    }
    assert sample["execution_backend"] == "bwrap_rootfs"
    assert sample["latency_seconds"] >= 0
    assert sample["usage"] == {
        "input_tokens": 17,
        "output_tokens": 3,
        "total_tokens": 20,
    }
    assert sample["expected_answer"] == "ORCHID-7194"
    assert sample["parsed_answer"] == "ORCHID-7194"
    assert sample["extracted_answer"] == "ORCHID-7194"
    assert sample["dataset_sample_id"] == "ruler-local-0001"
    assert sample["passed"] is True
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    assert metrics["tasks_total"] == 1
    assert metrics["tasks_passed"] == 1
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 0
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["mode"] == mode
    assert summary["status"] == "pass"
    assert summary["responses_base_url"] == fake_responses_server.url
    assert summary["conformance"] == {
        "claim": "none",
        "comparable_to_published": False,
    }
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "pass"
    assert set(archive_manifest["contract_artifacts"]) >= {
        "ruler/samples.jsonl",
        "ruler/metrics.json",
        "ruler/failures.jsonl",
        "environment.json",
        "benchmark-manifest.json",
        "run.json",
        "evalrun-state.json",
        "summary.json",
    }
    state = json.loads((result_dir / "evalrun-state.json").read_text())
    assert state["campaign_materialization"]["status"] == "completed"
    assert state["trial_generation"]["ruler"]["status"] == "completed"
    assert state["grading"]["ruler"]["status"] == "completed"
    assert state["suite_summary"]["ruler"]["status"] == "pass"
    assert state["campaign_summary"]["status"] == "pass"


def test_ruler_single_suite_real_adapter_classifies_responses_failure(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    manifest_path = _write_ruler_cache_and_manifest(tmp_path)
    fake_responses_server.fail_responses()
    run_id = "ruler-real-adapter-failure"
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "ruler",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "ruler"
    assert (result_dir / "run.json").is_file()
    assert (result_dir / "archive-manifest.json").is_file()
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    failures = [
        json.loads(line)
        for line in (suite_dir / "failures.jsonl").read_text().splitlines()
    ]
    samples = [
        json.loads(line)
        for line in (suite_dir / "samples.jsonl").read_text().splitlines()
    ]
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["infrastructure_failures"] > 0
    assert summary["suites"][0]["model_failures"] == 0
    assert metrics["infrastructure_failures"] > 0
    assert metrics["model_failures"] == 0
    assert failures
    assert all(failure["failure_category"] == "infrastructure" for failure in failures)
    assert all(sample["endpoint"] != "fixture" for sample in samples)
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archive_manifest["summary_status"] == "environment_failed"


def test_ruler_single_suite_real_adapter_classifies_wrong_model_output(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    manifest_path = _write_ruler_cache_and_manifest(tmp_path)
    fake_responses_server.set_output_text("The answer is LAVENDER-0000.")
    run_id = "ruler-real-adapter-wrong-answer"
    args = build_parser().parse_args(
        [
            "calibration",
            "--suite",
            "ruler",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            run_id,
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 1

    result_dir = tmp_path / "results" / run_id
    suite_dir = result_dir / "ruler"
    summary = json.loads((result_dir / "summary.json").read_text())
    metrics = json.loads((suite_dir / "metrics.json").read_text())
    sample = json.loads((suite_dir / "samples.jsonl").read_text().splitlines()[0])
    assert summary["status"] == "fail"
    assert metrics["model_failures"] == 1
    assert metrics["infrastructure_failures"] == 0
    assert sample["failure_category"] == "model"
    assert sample["state"] == "wrong_answer"
    assert sample["expected_answer"] == "ORCHID-7194"
    assert sample["parsed_answer"] == "The answer is LAVENDER-0000."
    assert sample["endpoint"] == fake_responses_server.url


def test_ruler_single_suite_real_adapter_rejects_missing_cache_sample(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    manifest_path = _write_ruler_cache_and_manifest(tmp_path)
    shutil.rmtree(tmp_path / "benchmarks" / "datasets" / "ruler")
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "ruler",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "ruler-missing-cache",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="RULER responses run requires a materialized dataset cache sample",
    ):
        args.func(args)

    assert fake_responses_server.requests == []
    assert not (tmp_path / "results" / "ruler-missing-cache" / "ruler").exists()


def test_ruler_single_suite_real_adapter_rejects_stale_state_before_endpoint_call(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    manifest_path = _write_ruler_cache_and_manifest(tmp_path)
    result_dir = tmp_path / "results" / "ruler-stale-state"
    result_dir.mkdir(parents=True)
    (result_dir / "evalrun-state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "different-run",
                "mode": "smoke",
                "manifest_sha256": "different-manifest",
                "suite_ids": ["ruler"],
                "campaign_materialization": {"status": "running", "artifacts": []},
                "suite_preparation": {},
                "trial_generation": {},
                "grading": {},
                "suite_summary": {},
                "campaign_summary": {"status": "running", "artifacts": []},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "ruler",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "ruler-stale-state",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(glm52_benchmark_verifier.BenchmarkVerifierError, match="mismatch"):
        args.func(args)

    assert fake_responses_server.requests == []


def test_ruler_mixed_smoke_stays_on_fixture_path(
    tmp_path: Path,
    fake_responses_server: object,
) -> None:
    manifest_path = _write_ruler_cache_and_manifest(tmp_path)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "ruler",
            "--suite",
            "gsm8k",
            "--manifest",
            str(manifest_path),
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "ruler-mixed-fixture",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert args.func(args) == 0

    ruler_samples = [
        json.loads(line)
        for line in (
            tmp_path / "results" / "ruler-mixed-fixture" / "ruler" / "samples.jsonl"
        ).read_text().splitlines()
    ]
    assert fake_responses_server.requests == []
    assert ruler_samples
    assert {sample["endpoint"] for sample in ruler_samples} == {"fixture"}


def test_prepare_command_materializes_local_cache_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = "ghcr.io/harbor-framework/terminal-bench-2@sha256:" + ("e" * 64)
    source_root = tmp_path / "sources"
    dataset_source = source_root / "needle-dataset"
    harness_source = source_root / "needle-harness"
    dataset_source.mkdir(parents=True)
    harness_source.mkdir(parents=True)
    (dataset_source / "needle.json").write_text('{"needle": "answer"}\n')
    (harness_source / "oracle.txt").write_text("local oracle\n")
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    (
                        f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    + (
                        f"    container_image: {image}\n"
                        if suite_id == "terminal-bench-2"
                        else ""
                    )
                    + "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    )
                    for suite_id in [
                        "gsm8k",
                        "aime",
                        "humaneval",
                        "mbpp",
                        "terminal-bench-2",
                        "swe-bench-verified",
                        "ruler",
                    ]
                ],
                "  - id: needle-smoke",
                "    profile: fixture",
                "    dataset_revision: needle-smoke@rev",
                "    harness_revision: monarch-fixture@rev",
                "    prompt_template: needle-smoke-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_source}",
                "      sha256: dataset-fixture-sha",
                "    harness_source:",
                "      type: local_path",
                f"      path: {harness_source}",
                "      sha256: harness-fixture-sha",
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-cache-materialize",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    assert args.func(args) == 0

    prepare = json.loads(
        (
            tmp_path / "results" / "prepare-cache-materialize" / "prepare.json"
        ).read_text()
    )
    needle_record = next(
        record
        for record in prepare["cache_preflight"]
        if record["suite"] == "needle-smoke"
    )
    assert needle_record["status"] == "available"
    assert needle_record["dataset_source_type"] == "local_path"
    assert needle_record["dataset_source_sha256"] == "dataset-fixture-sha"
    assert needle_record["harness_source_type"] == "local_path"
    assert needle_record["harness_source_sha256"] == "harness-fixture-sha"
    assert (
        tmp_path
        / "run"
        / ".."
        / "benchmarks"
        / "datasets"
        / "needle-smoke"
        / "needle.json"
    ).resolve().read_text() == '{"needle": "answer"}\n'
    assert (
        tmp_path
        / "run"
        / ".."
        / "benchmarks"
        / "harnesses"
        / "needle-smoke"
        / "oracle.txt"
    ).resolve().read_text() == "local oracle\n"


def test_prepare_command_materializes_ruler_smoke_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_responses_server: object,
) -> None:
    source_root = tmp_path / "sources"
    dataset_source = source_root / "ruler-dataset"
    harness_source = source_root / "ruler-harness"
    dataset_source.mkdir(parents=True)
    harness_source.mkdir(parents=True)
    (dataset_source / "scripts" / "data" / "synthetic").mkdir(parents=True)
    (dataset_source / "scripts" / "synthetic.yaml").write_text("niah_single_1: {}\n")
    (harness_source / "README.md").write_text("local harness\n")
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: ruler",
                "    profile: long-context",
                "    dataset_revision: ruler@rev",
                "    harness_revision: lm-evaluation-harness@rev",
                "    prompt_template: ruler-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "      top_p: 1",
                "      max_output_tokens: 1024",
                "      glm_thinking: disabled",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_source}",
                "    harness_source:",
                "      type: local_path",
                f"      path: {harness_source}",
                "",
            ]
        )
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )

    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--suite",
            "ruler",
            "--run-id",
            "prepare-ruler-smoke-sample",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    assert args.func(args) == 0

    samples_path = tmp_path / "benchmarks" / "datasets" / "ruler" / "samples.jsonl"
    sample = json.loads(samples_path.read_text())
    assert sample["id"] == "ruler-smoke-niah-single-1"
    assert "deployment cleanup token" in sample["input"]
    assert sample["outputs"] == ["ORCHID-7194"]
    assert sample["source"] == "monarch-ruler-smoke-fixture"
    prepare = json.loads(
        (
            tmp_path / "results" / "prepare-ruler-smoke-sample" / "prepare.json"
        ).read_text()
    )
    ruler_record = next(
        record
        for record in prepare["cache_preflight"]
        if record["suite"] == "ruler"
    )
    assert ruler_record["status"] == "available"
    assert ruler_record["smoke_sample"] == str(samples_path)

    smoke_args = build_parser().parse_args(
        [
            "smoke",
            "--manifest",
            str(manifest_path),
            "--suite",
            "ruler",
            "--execution-backend",
            "bwrap_rootfs",
            "--responses-base-url",
            fake_responses_server.url,
            "--run-id",
            "ruler-smoke-after-prepare",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    assert smoke_args.func(smoke_args) == 0


def test_prepare_command_filters_selected_suites_before_image_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sources"
    dataset_source = source_root / "needle-dataset"
    harness_source = source_root / "needle-harness"
    dataset_source.mkdir(parents=True)
    harness_source.mkdir(parents=True)
    (dataset_source / "needle.json").write_text('{"needle": "answer"}\n')
    (harness_source / "oracle.txt").write_text("local oracle\n")
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: terminal-bench-2",
                "    profile: terminal-agent",
                "    dataset_revision: terminal-bench-2@dataset-rev",
                "    harness_revision: harbor@harness-rev",
                "    prompt_template: terminal-bench-2-v1",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0.2",
                "    metric: task_success",
                "  - id: needle-smoke",
                "    profile: fixture",
                "    dataset_revision: needle-smoke@rev",
                "    harness_revision: monarch-fixture@rev",
                "    prompt_template: needle-smoke-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: local_path",
                f"      path: {dataset_source}",
                "    harness_source:",
                "      type: local_path",
                f"      path: {harness_source}",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    "    harness_revision: fixture@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    "    execution_backend: bwrap_rootfs\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                    if suite_id not in {"terminal-bench-2", "needle-smoke"}
                ],
                "",
            ]
        )
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--suite",
            "needle-smoke",
            "--run-id",
            "prepare-selected-cache",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    assert args.func(args) == 0

    prepare = json.loads(
        (tmp_path / "results" / "prepare-selected-cache" / "prepare.json").read_text()
    )
    copied_manifest = json.loads(
        (
            tmp_path / "results" / "prepare-selected-cache" / "benchmark-manifest.json"
        ).read_text()
    )
    assert [suite["id"] for suite in copied_manifest["suites"]] == ["needle-smoke"]
    assert [record["suite"] for record in prepare["cache_preflight"]] == [
        "needle-smoke"
    ]
    assert [record["suite"] for record in prepare["image_preflight"]] == []


def test_prepare_command_records_swe_bench_smoke_image_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_revision = "4e6126978a16bdfebc6538db8f28cacc2c8b77dc"
    row_image = "ghcr.io/swe-bench/astropy__astropy-12907:latest"
    image_digest = "ghcr.io/swe-bench/astropy__astropy-12907@sha256:" + ("a" * 64)
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: swe-bench-verified",
                "    profile: terminal-agent",
                "    dataset_revision: SWE-bench/SWE-bench_Verified@"
                + source_revision,
                "    harness_revision: swebench@fixture-rev",
                "    prompt_template: swe-bench-verified-v1",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: resolved_instances",
                "    dataset_source:",
                "      dataset: SWE-bench/SWE-bench_Verified",
                f"      revision: {source_revision}",
                "    harness_source:",
                "      repo: swebench",
                "      revision: fixture-rev",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    "    harness_revision: fixture@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    "    execution_backend: bwrap_rootfs\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                    if suite_id != "swe-bench-verified"
                ],
                "",
            ]
        )
    )
    swe_config_path = tmp_path / "swe-bench-verified-smoke.yaml"
    swe_config_path.write_text(
        "\n".join(
            [
                "suite: swe-bench-verified",
                "dataset_source:",
                "  dataset: SWE-bench/SWE-bench_Verified",
                f"  revision: {source_revision}",
                "subset:",
                "  smoke_instances:",
                "    - astropy__astropy-12907",
                "",
            ]
        )
    )
    swe_lock_path = tmp_path / "swe-bench-verified.lock.yaml"
    swe_lock_path.write_text(
        "\n".join(
            [
                "suite: swe-bench-verified",
                "dataset_source:",
                "  dataset: SWE-bench/SWE-bench_Verified",
                f"  revision: {source_revision}",
                "official_images:",
                "  status: resolved",
                "  provider: swebench",
                "  per_instance_images:",
                "    - instance_id: astropy__astropy-12907",
                f"      row_image: {row_image}",
                f"      image_digest: {image_digest}",
                "",
            ]
        )
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "DEFAULT_HARBOR_SWEBENCH_SMOKE_CONFIG",
        swe_config_path,
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "DEFAULT_HARBOR_SWEBENCH_LOCK",
        swe_lock_path,
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "materialize_prepare_caches",
        lambda manifest, *, cache_root=None: [],
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "build_image_preflight",
        lambda manifest, tool_results, runtime="docker": [],
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "build_container_runtime_preflight",
        lambda manifest, runtime: [],
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--suite",
            "swe-bench-verified",
            "--run-id",
            "prepare-swebench-images",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    assert args.func(args) == 0

    prepare = json.loads(
        (tmp_path / "results" / "prepare-swebench-images" / "prepare.json").read_text()
    )
    assert prepare["swe_bench_smoke_image_preflight"] == [
        {
            "suite": "swe-bench-verified",
            "status": "pass",
            "instance_id": "astropy__astropy-12907",
            "row_image": row_image,
            "image_digest": image_digest,
            "provider_namespace": "swebench",
            "source_revision": source_revision,
        }
    ]


def test_prepare_command_records_current_swe_bench_smoke_image_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "materialize_prepare_caches",
        lambda manifest, *, cache_root=None: [],
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "build_container_runtime_preflight",
        lambda manifest, runtime: [],
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"),
            "--suite",
            "swe-bench-verified",
            "--run-id",
            "prepare-swebench-current",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    assert args.func(args) == 0

    prepare = json.loads(
        (tmp_path / "results" / "prepare-swebench-current" / "prepare.json").read_text()
    )
    assert prepare["image_preflight"] == []
    assert prepare["swe_bench_smoke_image_preflight"] == [
        {
            "suite": "swe-bench-verified",
            "status": "pass",
            "instance_id": "astropy__astropy-12907",
            "row_image": "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest",
            "image_digest": (
                "docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907"
                "@sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88"
            ),
            "provider_namespace": "swebench",
            "source_revision": SWEBENCH_VERIFIED_HF_DATASET_REVISION,
        }
    ]


def test_write_prepare_artifact_records_current_swe_bench_image_preflight(
    tmp_path: Path,
) -> None:
    manifest = load_yaml_object(
        REPO_ROOT / ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
    )
    selected_manifest = {
        **manifest,
        "suites": select_suites(manifest, ["swe-bench-verified"]),
    }
    config = load_yaml_object(
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
    )
    lock = load_yaml_object(
        REPO_ROOT
        / ".scratch/glm52-local-serving/harbor/datasets/swe-bench-verified.lock.yaml"
    )

    path = write_prepare_artifact(
        results_root=tmp_path / "results",
        run_id="prepare-swebench-current",
        manifest=selected_manifest,
        rootfs_path=tmp_path / "rootfs",
        endpoints_checked=False,
        swe_bench_smoke_image_results=resolve_swe_bench_smoke_image_metadata(
            config,
            lock,
        ),
    )

    payload = json.loads(path.read_text())
    assert payload["suites"] == ["swe-bench-verified"]
    assert payload["swe_bench_smoke_image_preflight"] == [
        {
            "suite": "swe-bench-verified",
            "status": "pass",
            "instance_id": "astropy__astropy-12907",
            "row_image": "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest",
            "image_digest": (
                "docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907"
                "@sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88"
            ),
            "provider_namespace": "swebench",
            "source_revision": SWEBENCH_VERIFIED_HF_DATASET_REVISION,
        }
    ]


def test_prepare_command_records_selected_git_source_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    dataset_revision = "dataset-rev"
    harness_revision = "harness-rev"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                "  - id: terminal-bench-2",
                "    profile: terminal-agent",
                "    dataset_revision: terminal-bench-2@rev",
                "    harness_revision: harbor@rev",
                "    prompt_template: terminal-bench-2-v1",
                "    execution_backend: harbor_local_docker",
                "    decoding_profile:",
                "      temperature: 0.2",
                "    metric: task_success",
                "  - id: ruler",
                "    profile: long-context",
                f"    dataset_revision: ruler@{dataset_revision}",
                f"    harness_revision: lm-evaluation-harness@{harness_revision}",
                "    prompt_template: ruler-v1",
                "    execution_backend: bwrap_rootfs",
                "    decoding_profile:",
                "      temperature: 0",
                "    metric: exact_match",
                "    dataset_source:",
                "      type: git",
                "      url: https://example.test/ruler.git",
                f"      revision: {dataset_revision}",
                "    harness_source:",
                "      type: git",
                "      url: https://example.test/lm-evaluation-harness.git",
                f"      revision: {harness_revision}",
                *[
                    f"  - id: {suite_id}\n"
                    "    profile: fixture\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    "    harness_revision: fixture@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    "    execution_backend: bwrap_rootfs\n"
                    "    decoding_profile:\n"
                    "      temperature: 0\n"
                    "    metric: exact_match"
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                    if suite_id not in {"terminal-bench-2", "ruler"}
                ],
                "",
            ]
        )
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "missing"},
    )

    def fake_materialize_prepare_caches(
        manifest: dict[str, object],
        *,
        cache_root: Path | None = None,
    ) -> list[dict[str, object]]:
        assert [suite["id"] for suite in manifest["suites"]] == ["ruler"]
        return [
            {
                "suite": "ruler",
                "status": "available",
                "dataset_cache": str(tmp_path / "benchmarks/datasets/ruler"),
                "dataset_cache_exists": True,
                "dataset_revision": f"ruler@{dataset_revision}",
                "dataset_source_type": "git",
                "dataset_source_revision": dataset_revision,
                "harness_cache": str(tmp_path / "benchmarks/harnesses/ruler"),
                "harness_cache_exists": True,
                "harness_revision": f"lm-evaluation-harness@{harness_revision}",
                "harness_source_type": "git",
                "harness_source_revision": harness_revision,
            }
        ]

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "materialize_prepare_caches",
        fake_materialize_prepare_caches,
    )
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--suite",
            "ruler",
            "--run-id",
            "prepare-selected-git",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    assert args.func(args) == 0

    result_dir = tmp_path / "results" / "prepare-selected-git"
    prepare = json.loads((result_dir / "prepare.json").read_text())
    copied_manifest = json.loads((result_dir / "benchmark-manifest.json").read_text())
    assert [suite["id"] for suite in copied_manifest["suites"]] == ["ruler"]
    assert prepare["cache_preflight"][0]["dataset_source_revision"] == dataset_revision
    assert prepare["cache_preflight"][0]["harness_source_revision"] == harness_revision


def test_prepare_command_records_container_runtime_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = "ghcr.io/harbor-framework/terminal-bench-2@sha256:" + ("c" * 64)
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "suites:",
                *[
                    (
                        f"  - id: {suite_id}\n"
                    f"    profile: {'terminal-agent' if suite_id == 'terminal-bench-2' else 'fixture'}\n"
                    f"    dataset_revision: {suite_id}@rev\n"
                    f"    harness_revision: {'harbor' if suite_id == 'terminal-bench-2' else 'fixture'}@rev\n"
                    f"    prompt_template: {suite_id}-v1\n"
                    f"    execution_backend: {'harbor_local_docker' if suite_id == 'terminal-bench-2' else 'bwrap_rootfs'}\n"
                    + (
                        f"    container_image: {image}\n"
                        if suite_id == "terminal-bench-2"
                        else ""
                    )
                    + "    decoding_profile:\n"
                    "      temperature: 0.2\n"
                    "    metric: exact_match"
                    )
                    for suite_id in REQUIRED_FIXTURE_SUITE_IDS
                ],
                "",
            ]
        )
    )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "check_local_tool",
        lambda name: {"name": name, "status": "ok", "path": f"/usr/bin/{name}"},
    )

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command[0] == "docker"
        if command[1] == "version":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"Client":{"Version":"27.0.0"},"Server":{"Version":"27.0.1"}}\n',
                stderr="",
            )
        if command[1] == "info":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"ID":"local-runtime","Driver":"overlay2"}\n',
                stderr="",
            )
        if command[1:3] == ["image", "inspect"]:
            assert command[3] == image
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "Id": "sha256:local-image-id",
                            "RepoDigests": [image],
                        }
                    ]
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)
    args = build_parser().parse_args(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "prepare-runtime",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
            "--skip-endpoints",
        ]
    )

    assert args.func(args) == 0

    prepare = json.loads(
        (tmp_path / "results" / "prepare-runtime" / "prepare.json").read_text()
    )
    assert prepare["container_runtime_preflight"] == [
        {
            "runtime": "docker",
            "required": True,
            "status": "ok",
            "version": {"Client": {"Version": "27.0.0"}, "Server": {"Version": "27.0.1"}},
            "info": {"ID": "local-runtime", "Driver": "overlay2"},
        }
    ]


def test_write_prepare_artifact_records_gold_path_preflight_results(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": suite_id,
                "profile": "fixture",
                "dataset_revision": "fixture",
                "harness_revision": "fixture",
                "prompt_template": f"{suite_id}-v1",
                "execution_backend": "bwrap_rootfs"
                if suite_id != "terminal-bench-2"
                else "harbor_local_docker",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
            for suite_id in REQUIRED_FIXTURE_SUITE_IDS
        ]
    }

    path = write_prepare_artifact(
        results_root=tmp_path / "results",
        run_id="prepare-gold-path",
        manifest=manifest,
        rootfs_path=tmp_path / "rootfs",
        endpoints_checked=False,
        gold_path_results=[
            {
                "suite": "humaneval",
                "check": "known-good-bad-fixtures",
                "status": "available",
                "execution_backend": "bwrap_rootfs",
            },
            {
                "suite": "terminal-bench-2",
                "check": "harbor-oracle",
                "status": "missing_prerequisite",
                "missing": ["harbor"],
                "execution_backend": "harbor_local_docker",
            },
        ],
    )

    payload = json.loads(path.read_text())
    assert payload["gold_path_preflight"] == [
        {
            "suite": "humaneval",
            "check": "known-good-bad-fixtures",
            "status": "available",
            "execution_backend": "bwrap_rootfs",
        },
        {
            "suite": "terminal-bench-2",
            "check": "harbor-oracle",
            "status": "missing_prerequisite",
            "missing": ["harbor"],
            "execution_backend": "harbor_local_docker",
        },
    ]


def test_write_prepare_artifact_records_cache_and_image_preflight_results(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": suite_id,
                "profile": "fixture",
                "dataset_revision": "fixture",
                "harness_revision": "fixture",
                "prompt_template": f"{suite_id}-v1",
                "execution_backend": "bwrap_rootfs"
                if suite_id != "terminal-bench-2"
                else "harbor_local_docker",
                "decoding_profile": {"temperature": 0},
                "metric": "exact_match",
            }
            for suite_id in REQUIRED_FIXTURE_SUITE_IDS
        ]
    }

    path = write_prepare_artifact(
        results_root=tmp_path / "results",
        run_id="prepare-caches-images",
        manifest=manifest,
        rootfs_path=tmp_path / "rootfs",
        endpoints_checked=False,
        cache_results=[
            {
                "suite": "humaneval",
                "dataset_revision": "fixture",
                "dataset_cache": ".scratch/glm52-local-serving/benchmarks/datasets/humaneval",
                "harness_revision": "fixture",
                "harness_cache": ".scratch/glm52-local-serving/benchmarks/harnesses/humaneval",
                "status": "planned",
            }
        ],
        image_results=[
            {
                "suite": "terminal-bench-2",
                "execution_backend": "harbor_local_docker",
                "status": "missing_prerequisite",
                "missing": ["harbor"],
            }
        ],
    )

    payload = json.loads(path.read_text())
    assert payload["cache_preflight"] == [
        {
            "suite": "humaneval",
            "dataset_revision": "fixture",
            "dataset_cache": ".scratch/glm52-local-serving/benchmarks/datasets/humaneval",
            "harness_revision": "fixture",
            "harness_cache": ".scratch/glm52-local-serving/benchmarks/harnesses/humaneval",
            "status": "planned",
        }
    ]
    assert payload["image_preflight"] == [
        {
            "suite": "terminal-bench-2",
            "execution_backend": "harbor_local_docker",
            "status": "missing_prerequisite",
            "missing": ["harbor"],
        }
    ]


def test_build_prepare_cache_and_image_preflight_from_manifest(tmp_path: Path) -> None:
    image = "ghcr.io/harbor-framework/terminal-bench-2@sha256:" + ("f" * 64)
    cache_root = tmp_path / "benchmarks"
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
            },
            {
                "id": "terminal-bench-2",
                "dataset_revision": "terminal-bench-2@rev",
                "harness_revision": "harbor@rev",
                "execution_backend": "harbor_local_docker",
                "container_image": image,
            },
        ]
    }
    tool_results = [
        {"name": "docker", "status": "ok", "path": "/usr/bin/docker"},
        {"name": "harbor", "status": "missing"},
    ]

    assert build_cache_preflight(manifest, cache_root=cache_root) == [
        {
            "suite": "humaneval",
            "dataset_revision": "openai/humaneval@rev",
            "dataset_cache": str(cache_root / "datasets" / "humaneval"),
            "dataset_cache_exists": False,
            "harness_revision": "evalplus@rev",
            "harness_cache": str(cache_root / "harnesses" / "humaneval"),
            "harness_cache_exists": False,
            "status": "planned",
        },
        {
            "suite": "terminal-bench-2",
            "dataset_revision": "terminal-bench-2@rev",
            "dataset_cache": str(cache_root / "datasets" / "terminal-bench-2"),
            "dataset_cache_exists": False,
            "harness_revision": "harbor@rev",
            "harness_cache": str(cache_root / "harnesses" / "terminal-bench-2"),
            "harness_cache_exists": False,
            "status": "planned",
        },
    ]
    assert build_image_preflight(manifest, tool_results) == [
        {
            "suite": "terminal-bench-2",
            "execution_backend": "harbor_local_docker",
            "image": image,
            "status": "missing_prerequisite",
            "missing": ["harbor"],
        }
    ]


def test_build_cache_preflight_records_available_materialized_caches(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "benchmarks"
    (cache_root / "datasets" / "humaneval").mkdir(parents=True)
    (cache_root / "harnesses" / "humaneval").mkdir(parents=True)
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
            },
            {
                "id": "terminal-bench-2",
                "dataset_revision": "terminal-bench-2@rev",
                "harness_revision": "harbor@rev",
                "execution_backend": "harbor_local_docker",
            },
        ]
    }

    assert build_cache_preflight(manifest, cache_root=cache_root) == [
        {
            "suite": "humaneval",
            "dataset_revision": "openai/humaneval@rev",
            "dataset_cache": str(cache_root / "datasets" / "humaneval"),
            "dataset_cache_exists": True,
            "harness_revision": "evalplus@rev",
            "harness_cache": str(cache_root / "harnesses" / "humaneval"),
            "harness_cache_exists": True,
            "status": "available",
        },
        {
            "suite": "terminal-bench-2",
            "dataset_revision": "terminal-bench-2@rev",
            "dataset_cache": str(cache_root / "datasets" / "terminal-bench-2"),
            "dataset_cache_exists": False,
            "harness_revision": "harbor@rev",
            "harness_cache": str(cache_root / "harnesses" / "terminal-bench-2"),
            "harness_cache_exists": False,
            "status": "planned",
        },
    ]


def test_materialize_prepare_caches_copies_local_sources(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    dataset_source = source_root / "humaneval-dataset"
    harness_source = source_root / "evalplus-harness"
    dataset_source.mkdir(parents=True)
    harness_source.mkdir(parents=True)
    (dataset_source / "problems.jsonl").write_text('{"task_id": "HumanEval/0"}\n')
    (harness_source / "README.md").write_text("evalplus fixture\n")
    cache_root = tmp_path / "benchmarks"
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "dataset_source": {
                    "type": "local_path",
                    "path": str(dataset_source),
                    "sha256": "dataset-source-fixture",
                },
                "harness_source": {
                    "type": "local_path",
                    "path": str(harness_source),
                    "sha256": "harness-source-fixture",
                },
            }
        ]
    }

    records = materialize_prepare_caches(manifest, cache_root=cache_root)

    assert records == [
        {
            "suite": "humaneval",
            "dataset_revision": "openai/humaneval@rev",
            "dataset_cache": str(cache_root / "datasets" / "humaneval"),
            "dataset_cache_exists": True,
            "dataset_source_type": "local_path",
            "dataset_source_sha256": "dataset-source-fixture",
            "harness_revision": "evalplus@rev",
            "harness_cache": str(cache_root / "harnesses" / "humaneval"),
            "harness_cache_exists": True,
            "harness_source_type": "local_path",
            "harness_source_sha256": "harness-source-fixture",
            "status": "available",
        }
    ]
    assert (cache_root / "datasets" / "humaneval" / "problems.jsonl").read_text() == (
        '{"task_id": "HumanEval/0"}\n'
    )
    assert (cache_root / "harnesses" / "humaneval" / "README.md").read_text() == (
        "evalplus fixture\n"
    )


def test_materialize_prepare_caches_clones_pinned_git_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "benchmarks"
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "bwrap_rootfs",
                "dataset_source": {
                    "type": "git",
                    "url": "https://example.test/humaneval.git",
                    "revision": "dataset-rev",
                },
                "harness_source": {
                    "type": "git",
                    "url": "https://example.test/evalplus.git",
                    "revision": "harness-rev",
                },
            }
        ]
    }
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        commands.append(command)
        if command[:3] == ["git", "clone", "--no-checkout"]:
            Path(command[-1]).mkdir(parents=True)
        elif command[:2] == ["git", "-C"] and command[3:5] == ["checkout", "--detach"]:
            (Path(command[2]) / "CHECKED_OUT").write_text(f"{command[5]}\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)

    records = materialize_prepare_caches(manifest, cache_root=cache_root)

    assert records == [
        {
            "suite": "humaneval",
            "dataset_revision": "openai/humaneval@rev",
            "dataset_cache": str(cache_root / "datasets" / "humaneval"),
            "dataset_cache_exists": True,
            "dataset_source_type": "git",
            "dataset_source_revision": "dataset-rev",
            "harness_revision": "evalplus@rev",
            "harness_cache": str(cache_root / "harnesses" / "humaneval"),
            "harness_cache_exists": True,
            "harness_source_type": "git",
            "harness_source_revision": "harness-rev",
            "status": "available",
        }
    ]
    assert commands == [
        [
            "git",
            "clone",
            "--no-checkout",
            "https://example.test/humaneval.git",
            str(cache_root / "datasets" / "humaneval"),
        ],
        [
            "git",
            "-C",
            str(cache_root / "datasets" / "humaneval"),
            "checkout",
            "--detach",
            "dataset-rev",
        ],
        [
            "git",
            "clone",
            "--no-checkout",
            "https://example.test/evalplus.git",
            str(cache_root / "harnesses" / "humaneval"),
        ],
        [
            "git",
            "-C",
            str(cache_root / "harnesses" / "humaneval"),
            "checkout",
            "--detach",
            "harness-rev",
        ],
    ]


def test_materialize_prepare_caches_extracts_http_archive_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_source = tmp_path / "source.tar.gz"
    archive_build = tmp_path / "archive-build"
    archive_build.mkdir()
    (archive_build / "problems.jsonl").write_text('{"task_id": "gsm8k-0"}\n')
    with tarfile.open(archive_source, "w:gz") as archive:
        archive.add(archive_build / "problems.jsonl", arcname="problems.jsonl")
    archive_sha256 = hashlib.sha256(archive_source.read_bytes()).hexdigest()
    cache_root = tmp_path / "benchmarks"
    manifest = {
        "suites": [
            {
                "id": "gsm8k",
                "dataset_revision": "openai/gsm8k@rev",
                "harness_revision": "fixture-harness@rev",
                "execution_backend": "bwrap_rootfs",
                "dataset_source": {
                    "type": "http_archive",
                    "url": "https://example.test/gsm8k.tar.gz",
                    "sha256": archive_sha256,
                },
                "harness_source": {
                    "type": "local_path",
                    "path": str(archive_build),
                    "sha256": "harness-fixture-sha",
                },
            }
        ]
    }
    downloads: list[tuple[str, str]] = []

    def fake_urlretrieve(url: str, filename: str) -> tuple[str, object | None]:
        downloads.append((url, filename))
        Path(filename).write_bytes(archive_source.read_bytes())
        return filename, None

    monkeypatch.setattr(
        glm52_benchmark_verifier.urllib.request,
        "urlretrieve",
        fake_urlretrieve,
    )

    records = materialize_prepare_caches(manifest, cache_root=cache_root)

    assert records == [
        {
            "suite": "gsm8k",
            "dataset_revision": "openai/gsm8k@rev",
            "dataset_cache": str(cache_root / "datasets" / "gsm8k"),
            "dataset_cache_exists": True,
            "dataset_source_type": "http_archive",
            "dataset_source_sha256": archive_sha256,
            "harness_revision": "fixture-harness@rev",
            "harness_cache": str(cache_root / "harnesses" / "gsm8k"),
            "harness_cache_exists": True,
            "harness_source_type": "local_path",
            "harness_source_sha256": "harness-fixture-sha",
            "status": "available",
        }
    ]
    assert downloads == [
        (
            "https://example.test/gsm8k.tar.gz",
            str(cache_root / "datasets" / "gsm8k.download"),
        )
    ]
    assert (cache_root / "datasets" / "gsm8k" / "problems.jsonl").read_text() == (
        '{"task_id": "gsm8k-0"}\n'
    )


def test_materialize_prepare_caches_downloads_huggingface_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "benchmarks"
    manifest = {
        "suites": [
            {
                "id": "swe-bench-verified",
                "dataset_revision": "SWE-bench/SWE-bench_Verified@dataset-rev",
                "harness_revision": "swebench@harness-rev",
                "execution_backend": "harbor_local_docker",
                "dataset_source": {
                    "type": "huggingface_or_swebench",
                    "dataset": "SWE-bench/SWE-bench_Verified",
                    "revision": "dataset-rev",
                },
                "harness_source": {
                    "type": "huggingface",
                    "repo_id": "SWE-bench/SWE-bench",
                    "revision": "harness-rev",
                },
            }
        ]
    }
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        destination = Path(command[command.index("--local-dir") + 1])
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("huggingface fixture\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", lambda name: "/usr/bin/hf")
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)

    records = materialize_prepare_caches(manifest, cache_root=cache_root)

    assert records == [
        {
            "suite": "swe-bench-verified",
            "dataset_revision": "SWE-bench/SWE-bench_Verified@dataset-rev",
            "dataset_cache": str(cache_root / "datasets" / "swe-bench-verified"),
            "dataset_cache_exists": True,
            "dataset_source_type": "huggingface_or_swebench",
            "dataset_source_revision": "dataset-rev",
            "harness_revision": "swebench@harness-rev",
            "harness_cache": str(cache_root / "harnesses" / "swe-bench-verified"),
            "harness_cache_exists": True,
            "harness_source_type": "huggingface",
            "harness_source_revision": "harness-rev",
            "status": "available",
        }
    ]
    assert commands == [
        [
            "hf",
            "download",
            "SWE-bench/SWE-bench_Verified",
            "--repo-type",
            "dataset",
            "--revision",
            "dataset-rev",
            "--local-dir",
            str(cache_root / "datasets" / "swe-bench-verified"),
        ],
        [
            "hf",
            "download",
            "SWE-bench/SWE-bench",
            "--repo-type",
            "model",
            "--revision",
            "harness-rev",
            "--local-dir",
            str(cache_root / "harnesses" / "swe-bench-verified"),
        ],
    ]


def test_materialize_prepare_caches_falls_back_to_legacy_huggingface_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/openai_humaneval@dataset-rev",
                "harness_revision": "evalplus@harness-rev",
                "execution_backend": "bwrap_rootfs",
                "dataset_source": {
                    "type": "huggingface",
                    "repo_id": "openai/openai_humaneval",
                    "repo_type": "dataset",
                    "revision": "dataset-rev",
                },
            }
        ]
    }
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        destination = Path(command[command.index("--local-dir") + 1])
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("legacy fixture\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        glm52_benchmark_verifier.shutil,
        "which",
        lambda name: None if name == "hf" else "/usr/bin/huggingface-cli",
    )
    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)

    records = materialize_prepare_caches(manifest, cache_root=tmp_path / "benchmarks")

    assert commands[0][0] == "huggingface-cli"
    assert commands[0][-2:] == ["--local-dir-use-symlinks", "False"]
    assert records[0]["dataset_cache_exists"] is True


def test_materialize_prepare_caches_reports_missing_huggingface_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/openai_humaneval@dataset-rev",
                "harness_revision": "evalplus@harness-rev",
                "execution_backend": "bwrap_rootfs",
                "dataset_source": {
                    "type": "huggingface",
                    "repo_id": "openai/openai_humaneval",
                    "repo_type": "dataset",
                    "revision": "dataset-rev",
                },
            }
        ]
    }

    def missing_huggingface_tool(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        missing_huggingface_tool,
    )
    monkeypatch.setattr(glm52_benchmark_verifier.shutil, "which", lambda name: None)

    with pytest.raises(
        glm52_benchmark_verifier.BenchmarkVerifierError,
        match="dataset_source huggingface download failed: executable not found",
    ):
        materialize_prepare_caches(manifest, cache_root=tmp_path / "benchmarks")


def test_build_image_preflight_records_declared_image_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = "ghcr.io/harbor-framework/terminal-bench-2@sha256:" + ("a" * 64)
    manifest = {
        "suites": [
            {
                "id": "terminal-bench-2",
                "dataset_revision": "terminal-bench-2@rev",
                "harness_revision": "harbor@rev",
                "execution_backend": "harbor_local_docker",
                "container_image": image,
            },
        ]
    }
    tool_results = [
        {"name": "docker", "status": "ok", "path": "/usr/bin/docker"},
        {"name": "harbor", "status": "ok", "path": "/usr/bin/harbor"},
    ]

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        assert command == [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            "json",
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                [
                    {
                        "Id": "sha256:local-image-id",
                        "RepoDigests": [
                            image,
                        ],
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)

    assert build_image_preflight(manifest, tool_results) == [
        {
            "suite": "terminal-bench-2",
            "execution_backend": "harbor_local_docker",
            "image": image,
            "runtime": "docker",
            "status": "ok",
            "image_id": "sha256:local-image-id",
            "repo_digest": image,
        }
    ]


def test_build_image_preflight_rejects_mutable_container_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "terminal-bench-2",
                "dataset_revision": "terminal-bench-2@rev",
                "harness_revision": "harbor@rev",
                "execution_backend": "harbor_local_docker",
                "container_image": "ghcr.io/harbor-framework/terminal-bench-2:smoke",
            },
        ]
    }
    tool_results = [
        {"name": "docker", "status": "ok", "path": "/usr/bin/docker"},
        {"name": "harbor", "status": "ok", "path": "/usr/bin/harbor"},
    ]

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("mutable image references must fail before image inspect")

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)

    assert build_image_preflight(manifest, tool_results) == [
        {
            "suite": "terminal-bench-2",
            "execution_backend": "harbor_local_docker",
            "image": "ghcr.io/harbor-framework/terminal-bench-2:smoke",
            "status": "invalid_container_image",
            "error": "container_image must be digest-pinned",
        }
    ]


def test_build_image_preflight_rejects_missing_container_image_before_tool_checks() -> None:
    manifest = {
        "suites": [
            {
                "id": "terminal-bench-2",
                "dataset_revision": "terminal-bench-2@rev",
                "harness_revision": "harbor@rev",
                "execution_backend": "harbor_local_docker",
            },
        ]
    }
    tool_results = [
        {"name": "docker", "status": "missing"},
        {"name": "harbor", "status": "missing"},
    ]

    assert build_image_preflight(manifest, tool_results) == [
        {
            "suite": "terminal-bench-2",
            "execution_backend": "harbor_local_docker",
            "status": "invalid_container_image",
            "error": "container_image must be declared",
        }
    ]


def test_build_image_preflight_defers_swebench_to_per_instance_images() -> None:
    manifest = {
        "suites": [
            {
                "id": "swe-bench-verified",
                "execution_backend": "harbor_local_docker",
            }
        ]
    }

    assert build_image_preflight(manifest, []) == []


def test_build_image_preflight_uses_selected_container_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = "ghcr.io/openai/humaneval@sha256:" + ("b" * 64)
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "dataset_revision": "openai/humaneval@rev",
                "harness_revision": "evalplus@rev",
                "execution_backend": "local_docker",
                "container_image": image,
            },
        ]
    }
    tool_results = [
        {"name": "docker", "status": "ok", "path": "/usr/bin/docker"},
    ]

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == [
            "podman",
            "image",
            "inspect",
            image,
            "--format",
            "json",
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                [
                    {
                        "Id": "sha256:podman-image-id",
                        "RepoDigests": [
                            image,
                        ],
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fake_run)

    assert build_image_preflight(manifest, tool_results, runtime="podman") == [
        {
            "suite": "humaneval",
            "execution_backend": "local_docker",
            "image": image,
            "runtime": "podman",
            "status": "ok",
            "image_id": "sha256:podman-image-id",
            "repo_digest": image,
        }
    ]


def test_resolve_swe_bench_smoke_image_metadata_blocks_missing_smoke_instances() -> None:
    config = {
        "suite": "swe-bench-verified",
        "dataset_source": {
            "dataset": "SWE-bench/SWE-bench_Verified",
            "revision": SWEBENCH_VERIFIED_HF_DATASET_REVISION,
        },
        "subset": {"smoke_instances": []},
    }
    lock = {
        "suite": "swe-bench-verified",
        "dataset_source": {
            "dataset": "SWE-bench/SWE-bench_Verified",
            "revision": SWEBENCH_VERIFIED_HF_DATASET_REVISION,
        },
        "official_images": {
            "status": "unresolved",
            "provider": "swebench",
            "per_instance_images": [],
        },
        "smoke_instances": [],
    }

    assert resolve_swe_bench_smoke_image_metadata(config, lock) == [
        {
            "suite": "swe-bench-verified",
            "status": "missing_prerequisite",
            "missing": ["smoke_instances"],
            "error": "SWE-bench Verified smoke_instances must select at least one instance",
            "provider_namespace": "swebench",
            "source_revision": SWEBENCH_VERIFIED_HF_DATASET_REVISION,
        }
    ]


def test_resolve_swe_bench_smoke_image_metadata_records_selected_digest_rows() -> None:
    source_revision = "4e6126978a16bdfebc6538db8f28cacc2c8b77dc"
    first_image = "ghcr.io/swe-bench/astropy__astropy-12907:latest"
    second_image = "ghcr.io/swe-bench/django__django-11099:latest"
    first_digest = "ghcr.io/swe-bench/astropy__astropy-12907@sha256:" + ("a" * 64)
    second_digest = "ghcr.io/swe-bench/django__django-11099@sha256:" + ("b" * 64)
    config = {
        "suite": "swe-bench-verified",
        "dataset_source": {
            "dataset": "SWE-bench/SWE-bench_Verified",
            "revision": source_revision,
        },
        "subset": {
            "smoke_instances": [
                "astropy__astropy-12907",
                "django__django-11099",
            ],
        },
    }
    lock = {
        "suite": "swe-bench-verified",
        "dataset_source": {
            "dataset": "SWE-bench/SWE-bench_Verified",
            "revision": source_revision,
        },
        "official_images": {
            "status": "resolved",
            "provider": "swebench",
            "per_instance_images": [
                {
                    "instance_id": "astropy__astropy-12907",
                    "row_image": first_image,
                    "image_digest": first_digest,
                },
                {
                    "instance_id": "django__django-11099",
                    "row_image": second_image,
                    "image_digest": second_digest,
                },
            ],
        },
    }

    assert resolve_swe_bench_smoke_image_metadata(config, lock) == [
        {
            "suite": "swe-bench-verified",
            "status": "pass",
            "instance_id": "astropy__astropy-12907",
            "row_image": first_image,
            "image_digest": first_digest,
            "provider_namespace": "swebench",
            "source_revision": source_revision,
        },
        {
            "suite": "swe-bench-verified",
            "status": "pass",
            "instance_id": "django__django-11099",
            "row_image": second_image,
            "image_digest": second_digest,
            "provider_namespace": "swebench",
            "source_revision": source_revision,
        },
    ]


def test_resolve_swe_bench_smoke_image_metadata_requires_exact_digest_ref() -> None:
    source_revision = "4e6126978a16bdfebc6538db8f28cacc2c8b77dc"
    config = {
        "suite": "swe-bench-verified",
        "dataset_source": {
            "dataset": "SWE-bench/SWE-bench_Verified",
            "revision": source_revision,
        },
        "subset": {"smoke_instances": ["astropy__astropy-12907"]},
    }
    lock = {
        "suite": "swe-bench-verified",
        "dataset_source": {
            "dataset": "SWE-bench/SWE-bench_Verified",
            "revision": source_revision,
        },
        "official_images": {
            "status": "resolved",
            "provider": "swebench",
            "per_instance_images": [
                {
                    "instance_id": "astropy__astropy-12907",
                    "row_image": "ghcr.io/swe-bench/astropy__astropy-12907:latest",
                    "image_digest": "ghcr.io/swe-bench/astropy__astropy-12907@sha256:"
                    + ("a" * 64)
                    + "/extra",
                },
            ],
        },
    }

    assert resolve_swe_bench_smoke_image_metadata(config, lock) == [
        {
            "suite": "swe-bench-verified",
            "status": "missing_prerequisite",
            "instance_id": "astropy__astropy-12907",
            "row_image": "ghcr.io/swe-bench/astropy__astropy-12907:latest",
            "missing": ["image_digest"],
            "error": "image digest must use repo@sha256:<64 hex>",
            "provider_namespace": "swebench",
            "source_revision": source_revision,
        }
    ]


def test_build_gold_path_preflight_classifies_missing_harbor() -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "execution_backend": "bwrap_rootfs",
            },
            {
                "id": "terminal-bench-2",
                "execution_backend": "harbor_local_docker",
            },
            {
                "id": "swe-bench-verified",
                "execution_backend": "harbor_local_docker",
            },
        ]
    }

    preflight = build_gold_path_preflight(
        manifest,
        [
            {"name": "bwrap", "status": "ok", "path": "/usr/bin/bwrap"},
            {"name": "docker", "status": "ok", "path": "/usr/bin/docker"},
            {"name": "harbor", "status": "missing"},
        ],
    )

    assert preflight == [
        {
            "suite": "humaneval",
            "check": "known-good-bad-fixtures",
            "status": "available",
            "execution_backend": "bwrap_rootfs",
        },
        {
            "suite": "swe-bench-verified",
            "check": "swe-bench-official-harness",
            "status": "missing_prerequisite",
            "execution_backend": "harbor_local_docker",
            "missing": ["harbor"],
        },
        {
            "suite": "terminal-bench-2",
            "check": "harbor-oracle",
            "status": "missing_prerequisite",
            "execution_backend": "harbor_local_docker",
            "missing": ["harbor"],
        },
    ]


def test_build_gold_path_preflight_runs_local_fixture_checks() -> None:
    manifest = {
        "suites": [
            {
                "id": "gsm8k",
                "execution_backend": "bwrap_rootfs",
            },
            {
                "id": "aime",
                "execution_backend": "bwrap_rootfs",
            },
            {
                "id": "needle-smoke",
                "execution_backend": "bwrap_rootfs",
            },
        ]
    }

    preflight = build_gold_path_preflight(
        manifest,
        [
            {"name": "bwrap", "status": "ok", "path": "/usr/bin/bwrap"},
        ],
    )

    assert preflight == [
        {
            "suite": "aime",
            "check": "answer-extraction-fixture",
            "status": "passed",
            "execution_backend": "bwrap_rootfs",
            "fixtures_total": 2,
            "fixtures_passed": 2,
        },
        {
            "suite": "gsm8k",
            "check": "answer-extraction-fixture",
            "status": "passed",
            "execution_backend": "bwrap_rootfs",
            "fixtures_total": 2,
            "fixtures_passed": 2,
        },
        {
            "suite": "needle-smoke",
            "check": "local-answer-fixture",
            "status": "passed",
            "execution_backend": "bwrap_rootfs",
            "fixtures_total": 3,
            "fixtures_passed": 3,
        },
    ]


def test_build_gold_path_preflight_does_not_require_bwrap_for_trusted_fixtures() -> None:
    manifest = {
        "suites": [
            {
                "id": "gsm8k",
                "execution_backend": "bwrap_rootfs",
            },
            {
                "id": "humaneval",
                "execution_backend": "bwrap_rootfs",
            },
        ]
    }

    preflight = build_gold_path_preflight(
        manifest,
        [{"name": "bwrap", "status": "missing"}],
    )

    assert preflight == [
        {
            "suite": "gsm8k",
            "check": "answer-extraction-fixture",
            "status": "passed",
            "execution_backend": "bwrap_rootfs",
            "fixtures_total": 2,
            "fixtures_passed": 2,
        },
        {
            "suite": "humaneval",
            "check": "known-good-bad-fixtures",
            "status": "missing_prerequisite",
            "execution_backend": "bwrap_rootfs",
            "missing": ["bwrap"],
        },
    ]


def test_write_bwrap_codegen_smoke_run_records_task_roots(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "fixture-human-eval",
                "harness_revision": "fixture-harness",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            },
            {
                "id": "mbpp",
                "profile": "coding-benchmark",
                "dataset_revision": "fixture-mbpp",
                "harness_revision": "fixture-harness",
                "prompt_template": "mbpp-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            },
        ]
    }

    summary_path = write_bwrap_codegen_smoke_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="code-bwrap-smoke",
        suite_ids=["humaneval", "mbpp"],
        manifest=manifest,
        task_results=[
            {
                "suite": "humaneval",
                "case_id": "HumanEval/0",
                "task_root": str(tmp_path / "run" / "bwrap" / "code-bwrap-smoke" / "humaneval-001"),
                "passed": True,
                "stdout": "PASS\n",
                "stderr": "",
            },
            {
                "suite": "mbpp",
                "case_id": "MBPP/0",
                "task_root": str(tmp_path / "run" / "bwrap" / "code-bwrap-smoke" / "mbpp-001"),
                "passed": True,
                "stdout": "PASS\n",
                "stderr": "",
            },
        ],
    )

    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "pass"
    assert {suite["suite"] for suite in summary["suites"]} == {"humaneval", "mbpp"}
    result_dir = summary_path.parent
    assert (result_dir / "run.json").is_file()
    assert (result_dir / "environment.json").is_file()
    assert (result_dir / "benchmark-manifest.json").is_file()
    assert (result_dir / "evalrun-state.json").is_file()
    run_record = json.loads((result_dir / "run.json").read_text())
    assert run_record["status"] == "completed"
    assert {suite["id"] for suite in run_record["suites"]} == {"humaneval", "mbpp"}
    state = json.loads((result_dir / "evalrun-state.json").read_text())
    assert state["campaign_materialization"]["status"] == "completed"
    assert set(state["suite_ids"]) == {"humaneval", "mbpp"}
    assert state["trial_generation"]["humaneval"]["status"] == "completed"
    assert state["trial_generation"]["mbpp"]["status"] == "completed"
    assert state["grading"]["humaneval"]["status"] == "completed"
    assert state["grading"]["mbpp"]["status"] == "completed"
    assert state["campaign_summary"]["status"] == "pass"
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert "run.json" in archive_manifest["contract_artifacts"]
    assert "environment.json" in archive_manifest["contract_artifacts"]
    assert "benchmark-manifest.json" in archive_manifest["contract_artifacts"]
    assert "evalrun-state.json" in archive_manifest["contract_artifacts"]
    cleanup = json.loads(
        (tmp_path / "run" / "cleanup-code-bwrap-smoke.json").read_text()
    )
    lock = json.loads((tmp_path / "run" / "benchmark-code-bwrap-smoke.lock").read_text())
    assert lock["run_id"] == "code-bwrap-smoke"
    assert lock["status"] == "completed"
    assert lock["completed_at"]
    assert lock["cleanup_state_path"] == str(
        tmp_path / "run" / "cleanup-code-bwrap-smoke.json"
    )
    assert cleanup["bwrap_tasks"] == [
        {
            "pid": None,
            "task_root": str(tmp_path / "run" / "bwrap" / "code-bwrap-smoke" / "humaneval-001"),
            "command_contains": "glm52_bwrap_task_runner",
        },
        {
            "pid": None,
            "task_root": str(tmp_path / "run" / "bwrap" / "code-bwrap-smoke" / "mbpp-001"),
            "command_contains": "glm52_bwrap_task_runner",
        },
    ]
    humaneval_sample = json.loads(
        (summary_path.parent / "humaneval" / "samples.jsonl").read_text()
    )
    assert humaneval_sample["execution_backend"] == "bwrap_rootfs"
    assert humaneval_sample["task_root"].endswith("humaneval-001")
    assert humaneval_sample["prompt_sha256"]
    assert humaneval_sample["endpoint"] == "fixture"
    assert humaneval_sample["decoding"] == {"temperature": 0.2}
    assert humaneval_sample["decoding_profile"] == {"temperature": 0.2}
    assert humaneval_sample["profile"] == "coding-benchmark"
    assert humaneval_sample["latency_seconds"] == 0.0
    assert humaneval_sample["usage"] == {}
    assert humaneval_sample["state"] == "passed"


def test_write_bwrap_codegen_smoke_run_separates_infrastructure_failures(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "fixture-human-eval",
                "harness_revision": "fixture-harness",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            },
        ]
    }

    summary_path = write_bwrap_codegen_smoke_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="code-bwrap-infra-failure",
        suite_ids=["humaneval"],
        manifest=manifest,
        task_results=[
            {
                "suite": "humaneval",
                "case_id": "HumanEval/0",
                "task_root": str(
                    tmp_path
                    / "run"
                    / "bwrap"
                    / "code-bwrap-infra-failure"
                    / "humaneval-001"
                ),
                "passed": False,
                "state": "environment_crashed",
                "stdout": "",
                "stderr": "bwrap exited before running tests",
            },
        ],
    )

    summary = json.loads(summary_path.read_text())
    metrics = json.loads((summary_path.parent / "humaneval" / "metrics.json").read_text())
    failure = json.loads(
        (summary_path.parent / "humaneval" / "failures.jsonl").read_text()
    )

    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["model_failures"] == 0
    assert summary["suites"][0]["infrastructure_failures"] == 1
    assert summary["suites"][0]["infrastructure_failure_denominator"] == 1
    assert summary["suites"][0]["infrastructure_failure_rate"] == 1.0
    assert metrics["model_failures"] == 0
    assert metrics["infrastructure_failures"] == 1
    assert metrics["infrastructure_failure_denominator"] == 1
    assert metrics["infrastructure_failure_rate"] == 1.0
    assert failure["state"] == "environment_crashed"
    assert failure["failure_category"] == "infrastructure"


def test_bwrap_codegen_smoke_command_writes_summary_for_runner_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)

    def fail_bwrap_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["scripts/run_glm52_bwrap_task_runner.sh"],
            returncode=2,
            stdout="",
            stderr="bwrap rootfs is not built\n",
        )

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fail_bwrap_runner)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "humaneval",
            "--manifest",
            str(manifest_path),
            "--pool",
            "code_sandbox",
            "--execution-backend",
            "bwrap_rootfs",
            "--run-id",
            "codegen-runner-failure",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    exit_code = args.func(args)

    summary_path = tmp_path / "results" / "codegen-runner-failure" / "summary.json"
    failure_path = tmp_path / "results" / "codegen-runner-failure" / "humaneval" / "failures.jsonl"
    summary = json.loads(summary_path.read_text())
    failure = json.loads(failure_path.read_text())
    assert exit_code == 2
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["model_failures"] == 0
    assert summary["suites"][0]["infrastructure_failures"] == 1
    assert failure["state"] == "environment_crashed"
    assert failure["failure_category"] == "infrastructure"
    assert "bwrap rootfs is not built" in failure["stderr"]


def test_bwrap_codegen_smoke_command_rejects_stale_state_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    result_dir = tmp_path / "results" / "codegen-stale-state"
    result_dir.mkdir(parents=True)
    (result_dir / "evalrun-state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "different-run",
                "mode": "smoke",
                "manifest_sha256": "different-manifest",
                "suite_ids": ["humaneval"],
                "campaign_materialization": {"status": "running", "artifacts": []},
                "suite_preparation": {},
                "trial_generation": {},
                "grading": {},
                "suite_summary": {},
                "campaign_summary": {"status": "running", "artifacts": []},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    def fail_if_runner_starts(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("bwrap runner started before EvalRun state validation")

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fail_if_runner_starts)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "humaneval",
            "--manifest",
            str(manifest_path),
            "--pool",
            "code_sandbox",
            "--execution-backend",
            "bwrap_rootfs",
            "--run-id",
            "codegen-stale-state",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(glm52_benchmark_verifier.BenchmarkVerifierError, match="mismatch"):
        args.func(args)


def test_bwrap_codegen_smoke_command_preserves_runner_latency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)

    def successful_bwrap_runner(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        task_root = tmp_path / "run" / "bwrap" / "codegen-runner-latency" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                }
            )
        )
        return subprocess.CompletedProcess(
            args=["scripts/run_glm52_bwrap_task_runner.sh"],
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "codegen-runner-latency",
                    "task_id": "humaneval-001",
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 1.234,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "humaneval",
            "--manifest",
            str(manifest_path),
            "--pool",
            "code_sandbox",
            "--execution-backend",
            "bwrap_rootfs",
            "--run-id",
            "codegen-runner-latency",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    exit_code = args.func(args)

    result_dir = tmp_path / "results" / "codegen-runner-latency"
    sample = json.loads((result_dir / "humaneval" / "samples.jsonl").read_text())
    assert exit_code == 0
    assert sample["latency_seconds"] == 1.234


def test_humaneval_responses_run_scores_completion_with_bwrap_fixture_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    completion_text = "def add(a, b):\n    return a + b\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-fixture",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert "--completion-text" in command
        assert command[command.index("--completion-text") + 1] == completion_text
        task_root = tmp_path / "run" / "bwrap" / "responses-fixture" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-fixture",
                    "task_id": "humaneval-001",
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_humaneval_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-fixture",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    summary = json.loads(summary_path.read_text())
    metrics = json.loads((result_dir / "humaneval" / "metrics.json").read_text())
    sample = json.loads((result_dir / "humaneval" / "samples.jsonl").read_text())
    archived = (
        result_dir / "humaneval" / "artifacts" / "humaneval-001-codegen-artifact.json"
    )

    assert summary["status"] == "pass"
    assert sample["endpoint"] == "http://127.0.0.1:8080/v1"
    assert sample["usage"] == {"input_tokens": 11, "output_tokens": 7}
    assert sample["completion_text"] == completion_text
    assert sample["generated_code"] == completion_text
    assert sample["benchmark_scoring"] == "fixture_harness"
    assert sample["pass_at_1"] is None
    assert sample["passed"] is True
    assert sample["state"] == "passed"
    assert sample["contract_artifacts"]["codegen_artifact"] == (
        "humaneval/artifacts/humaneval-001-codegen-artifact.json"
    )
    assert archived.is_file()
    assert json.loads(archived.read_text())["generated_code"] == completion_text
    assert metrics["benchmark_scoring"] == "fixture_harness"
    assert metrics["pass_at_1"] is None
    assert metrics["score"] == 1.0


def test_humaneval_responses_run_records_official_evalplus_handoff_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    completion_text = "def add(a, b):\n    return a + b\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-fixture",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == [sys.executable, "-m", "evalplus.evaluate"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="fake evalplus completed\n",
                stderr="",
            )
        task_root = tmp_path / "run" / "bwrap" / "responses-fixture" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-fixture",
                    "task_id": "humaneval-001",
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_humaneval_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-fixture",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    official_harness = json.loads(
        (result_dir / "humaneval" / "official-harness.json").read_text()
    )
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert official_harness == {
        "schema_version": 1,
        "suite": "humaneval",
        "official_harness": "evalplus",
        "status": "missing_prerequisite",
        "metric": "pass@1",
        "pass_at_1": None,
        "dataset_revision": "fixture-human-eval",
        "harness_revision": "fixture-harness",
        "prompt_template": "humaneval-v1",
        "decoding_profile": {"temperature": 0.2},
        "execution_backend": "bwrap_rootfs",
        "benchmark_scoring": "fixture_harness",
        "current_scoring": "fixture_harness",
        "reason": "evalplus package is not installed",
        "generated_code_artifact": (
            "humaneval/artifacts/humaneval-001-codegen-artifact.json"
        ),
        "conformance": {"claim": "none"},
        "prerequisite": {
            "type": "python_import",
            "name": "evalplus",
            "status": "missing",
        },
    }
    assert "humaneval/official-harness.json" in archive_manifest["contract_artifacts"]


def test_humaneval_responses_run_classifies_missing_evalplus_official_harness_prerequisite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    completion_text = "def add(a, b):\n    return a + b\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-fixture",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["-m", "evalplus.evaluate"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="official evalplus executed\n",
                stderr="",
            )
        task_root = tmp_path / "run" / "bwrap" / "responses-fixture" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-fixture",
                    "task_id": "humaneval-001",
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_humaneval_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-fixture",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    official_harness = json.loads(
        (result_dir / "humaneval" / "official-harness.json").read_text()
    )
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())

    assert official_harness["official_harness"] == "evalplus"
    assert official_harness["status"] == "missing_prerequisite"
    assert official_harness["metric"] == "pass@1"
    assert official_harness["pass_at_1"] is None
    assert official_harness["benchmark_scoring"] == "fixture_harness"
    assert official_harness["current_scoring"] == "fixture_harness"
    assert official_harness["generated_code_artifact"] == (
        "humaneval/artifacts/humaneval-001-codegen-artifact.json"
    )
    assert official_harness["conformance"] == {"claim": "none"}
    assert official_harness["prerequisite"] == {
        "type": "python_import",
        "name": "evalplus",
        "status": "missing",
    }
    assert official_harness["reason"] == "evalplus package is not installed"
    assert "humaneval/official-harness.json" in archive_manifest["contract_artifacts"]


def test_humaneval_responses_run_records_official_evalplus_attempt_when_importable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    completion_text = "def add(a, b):\n    return a + b\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-fixture",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["-m", "evalplus.evaluate"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="official evalplus executed\n",
                stderr="",
            )
        task_root = tmp_path / "run" / "bwrap" / "responses-fixture" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-fixture",
                    "task_id": "humaneval-001",
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_humaneval_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-fixture",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    official_harness = json.loads(
        (result_dir / "humaneval" / "official-harness.json").read_text()
    )
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    samples_path = (
        result_dir
        / "humaneval"
        / "artifacts"
        / "humaneval-001-codegen-artifact-evalplus-samples.jsonl"
    )

    assert official_harness["official_attempt_evidence"][
        "generated_code_artifact"
    ] == "humaneval/artifacts/humaneval-001-codegen-artifact.json"
    assert official_harness["official_attempt_evidence"]["samples_path"] == str(
        samples_path
    )
    assert official_harness["official_attempt_evidence"]["command"][2:] == [
        "evalplus.evaluate",
        "--dataset",
        "humaneval",
        "--samples",
        str(samples_path),
        "--base-only",
    ]
    assert (
        "humaneval/artifacts/humaneval-001-codegen-artifact.json"
        in archive_manifest["contract_artifacts"]
    )
    assert official_harness["status"] == "executed"
    assert official_harness["reason"] == "official EvalPlus runner executed"
    assert official_harness["pass_at_1"] is None
    assert official_harness["conformance"] == {"claim": "none"}
    assert samples_path.is_file()
    assert json.loads(samples_path.read_text()) == {
        "task_id": "HumanEval/0",
        "solution": completion_text,
    }
    assert (
        "humaneval/artifacts/humaneval-001-codegen-artifact-evalplus-samples.jsonl"
        in archive_manifest["contract_artifacts"]
    )
    assert "prerequisite" not in official_harness


def test_humaneval_responses_run_classifies_fixture_failure_as_model_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)
    completion_text = "def add(a, b):\n    return a - b\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-wrong-code",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert "--completion-text" in command
        assert command[command.index("--completion-text") + 1] == completion_text
        task_root = tmp_path / "run" / "bwrap" / "responses-wrong-code" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "passed": False,
                    "stdout": "",
                    "stderr": "AssertionError: -1 != 3\n",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-wrong-code",
                    "task_id": "humaneval-001",
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "passed": False,
                    "stdout": "",
                    "stderr": "AssertionError: -1 != 3\n",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_humaneval_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-wrong-code",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    summary = json.loads(summary_path.read_text())
    metrics = json.loads((result_dir / "humaneval" / "metrics.json").read_text())
    sample = json.loads((result_dir / "humaneval" / "samples.jsonl").read_text())

    assert summary["status"] == "fail"
    assert sample["passed"] is False
    assert sample["state"] == "task_failed"
    assert sample["failure_category"] == "model"
    assert sample["benchmark_scoring"] == "fixture_harness"
    assert sample["score"] == 0.0
    assert sample["pass_at_1"] is None
    assert sample["generated_code"] == completion_text
    assert metrics["model_failures"] == 1
    assert metrics["infrastructure_failures"] == 0
    assert metrics["score"] == 0.0
    assert metrics["benchmark_scoring"] == "fixture_harness"
    assert metrics["pass_at_1"] is None


def test_mbpp_responses_run_classifies_fixture_failure_as_model_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_mbpp_manifest(manifest_path)
    completion_text = "def remove_Occ(string, char):\n    return string\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-wrong-code",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 13, "output_tokens": 8},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert "--completion-text" in command
        assert command[command.index("--completion-text") + 1] == completion_text
        task_root = tmp_path / "run" / "bwrap" / "responses-wrong-code" / "mbpp-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "passed": False,
                    "stdout": "",
                    "stderr": "AssertionError: 'hello' != 'helo'\n",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-wrong-code",
                    "task_id": "mbpp-001",
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "passed": False,
                    "stdout": "",
                    "stderr": "AssertionError: 'hello' != 'helo'\n",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_mbpp_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-wrong-code",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    summary = json.loads(summary_path.read_text())
    metrics = json.loads((result_dir / "mbpp" / "metrics.json").read_text())
    sample = json.loads((result_dir / "mbpp" / "samples.jsonl").read_text())

    assert summary["status"] == "fail"
    assert sample["passed"] is False
    assert sample["state"] == "task_failed"
    assert sample["failure_category"] == "model"
    assert sample["benchmark_scoring"] == "fixture_harness"
    assert sample["score"] == 0.0
    assert sample["pass_at_1"] is None
    assert sample["generated_code"] == completion_text
    assert metrics["model_failures"] == 1
    assert metrics["infrastructure_failures"] == 0
    assert metrics["score"] == 0.0
    assert metrics["benchmark_scoring"] == "fixture_harness"
    assert metrics["pass_at_1"] is None


def test_mbpp_responses_run_records_official_evalplus_handoff_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_mbpp_manifest(manifest_path)
    completion_text = "def remove_Occ(string, char):\n    return string.replace(char, '', 1)\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-fixture",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 13, "output_tokens": 8},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == [sys.executable, "-m", "evalplus.evaluate"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="fake evalplus completed\n",
                stderr="",
            )
        task_root = tmp_path / "run" / "bwrap" / "responses-fixture" / "mbpp-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-fixture",
                    "task_id": "mbpp-001",
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_mbpp_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-fixture",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    official_harness = json.loads(
        (result_dir / "mbpp" / "official-harness.json").read_text()
    )
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert official_harness == {
        "schema_version": 1,
        "suite": "mbpp",
        "official_harness": "evalplus",
        "status": "missing_prerequisite",
        "metric": "pass@1",
        "pass_at_1": None,
        "dataset_revision": "fixture-mbpp",
        "harness_revision": "fixture-harness",
        "prompt_template": "mbpp-v1",
        "decoding_profile": {"temperature": 0.2},
        "execution_backend": "bwrap_rootfs",
        "benchmark_scoring": "fixture_harness",
        "current_scoring": "fixture_harness",
        "reason": "evalplus package is not installed",
        "generated_code_artifact": "mbpp/artifacts/mbpp-001-codegen-artifact.json",
        "conformance": {"claim": "none"},
        "prerequisite": {
            "type": "python_import",
            "name": "evalplus",
            "status": "missing",
        },
    }
    assert "mbpp/official-harness.json" in archive_manifest["contract_artifacts"]


def test_mbpp_responses_run_classifies_missing_evalplus_official_harness_prerequisite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_mbpp_manifest(manifest_path)
    completion_text = "def remove_Occ(string, char):\n    return string.replace(char, '', 1)\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-fixture",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 13, "output_tokens": 8},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["-m", "evalplus.evaluate"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="official evalplus executed\n",
                stderr="",
            )
        task_root = tmp_path / "run" / "bwrap" / "responses-fixture" / "mbpp-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-fixture",
                    "task_id": "mbpp-001",
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_mbpp_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-fixture",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    official_harness = json.loads(
        (result_dir / "mbpp" / "official-harness.json").read_text()
    )
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())

    assert official_harness["official_harness"] == "evalplus"
    assert official_harness["status"] == "missing_prerequisite"
    assert official_harness["metric"] == "pass@1"
    assert official_harness["pass_at_1"] is None
    assert official_harness["benchmark_scoring"] == "fixture_harness"
    assert official_harness["current_scoring"] == "fixture_harness"
    assert official_harness["generated_code_artifact"] == (
        "mbpp/artifacts/mbpp-001-codegen-artifact.json"
    )
    assert official_harness["conformance"] == {"claim": "none"}
    assert official_harness["prerequisite"] == {
        "type": "python_import",
        "name": "evalplus",
        "status": "missing",
    }
    assert official_harness["reason"] == "evalplus package is not installed"
    assert "mbpp/official-harness.json" in archive_manifest["contract_artifacts"]


def test_mbpp_responses_run_records_official_evalplus_attempt_when_importable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_mbpp_manifest(manifest_path)
    completion_text = "def remove_Occ(string, char):\n    return string.replace(char, '', 1)\n"

    def fake_responses_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "resp-fixture",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": completion_text}],
                }
            ],
            "usage": {"input_tokens": 13, "output_tokens": 8},
        }

    def successful_bwrap_runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["-m", "evalplus.evaluate"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="official evalplus executed\n",
                stderr="",
            )
        task_root = tmp_path / "run" / "bwrap" / "responses-fixture" / "mbpp-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        artifact_path = output_dir / "codegen-artifact.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "checkout_write": "denied",
                    "network": "denied",
                    "scoring": "fixture_harness",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "run_id": "responses-fixture",
                    "task_id": "mbpp-001",
                    "suite": "mbpp",
                    "case_id": "MBPP/0",
                    "task_root": str(task_root),
                    "artifact": str(artifact_path),
                    "duration_seconds": 0.5,
                    "stdout": "",
                    "stderr": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier,
        "_post_responses_request",
        fake_responses_request,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        successful_bwrap_runner,
    )
    summary_path = glm52_benchmark_verifier.write_mbpp_responses_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="responses-fixture",
        manifest=load_yaml_object(manifest_path),
        execution_backend="bwrap_rootfs",
        responses_base_url="http://127.0.0.1:8080/v1",
    )

    result_dir = summary_path.parent
    official_harness = json.loads(
        (result_dir / "mbpp" / "official-harness.json").read_text()
    )
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    samples_path = (
        result_dir
        / "mbpp"
        / "artifacts"
        / "mbpp-001-codegen-artifact-evalplus-samples.jsonl"
    )

    assert official_harness["official_attempt_evidence"][
        "generated_code_artifact"
    ] == "mbpp/artifacts/mbpp-001-codegen-artifact.json"
    assert official_harness["official_attempt_evidence"]["samples_path"] == str(
        samples_path
    )
    assert official_harness["official_attempt_evidence"]["command"][2:] == [
        "evalplus.evaluate",
        "--dataset",
        "mbpp",
        "--samples",
        str(samples_path),
        "--base-only",
    ]
    assert (
        "mbpp/artifacts/mbpp-001-codegen-artifact.json"
        in archive_manifest["contract_artifacts"]
    )
    assert official_harness["status"] == "executed"
    assert official_harness["reason"] == "official EvalPlus runner executed"
    assert official_harness["pass_at_1"] is None
    assert official_harness["conformance"] == {"claim": "none"}
    assert samples_path.is_file()
    assert json.loads(samples_path.read_text()) == {
        "task_id": "MBPP/0",
        "solution": completion_text,
    }
    assert (
        "mbpp/artifacts/mbpp-001-codegen-artifact-evalplus-samples.jsonl"
        in archive_manifest["contract_artifacts"]
    )
    assert "prerequisite" not in official_harness


def test_write_bwrap_codegen_smoke_run_archives_task_artifact(
    tmp_path: Path,
) -> None:
    manifest = {
        "suites": [
            {
                "id": "humaneval",
                "profile": "coding-benchmark",
                "dataset_revision": "fixture-human-eval",
                "harness_revision": "fixture-harness",
                "prompt_template": "humaneval-v1",
                "execution_backend": "bwrap_rootfs",
                "decoding_profile": {"temperature": 0.2},
                "metric": "pass@1",
            },
        ]
    }
    task_root = tmp_path / "run" / "bwrap" / "code-bwrap-artifact" / "humaneval-001"
    output_dir = task_root / "output"
    output_dir.mkdir(parents=True)
    task_artifact = output_dir / "codegen-artifact.json"
    task_artifact.write_text(
        json.dumps(
            {
                "suite": "humaneval",
                "case_id": "HumanEval/0",
                "passed": True,
                "stdout": "fixture passed\n",
                "stderr": "",
            }
        )
    )

    summary_path = write_bwrap_codegen_smoke_run(
        results_root=tmp_path / "results",
        run_root=tmp_path / "run",
        run_id="code-bwrap-artifact",
        suite_ids=["humaneval"],
        manifest=manifest,
        task_results=[
            {
                "suite": "humaneval",
                "case_id": "HumanEval/0",
                "task_root": str(task_root),
                "artifact_path": str(task_artifact),
                "passed": True,
                "stdout": "PASS\n",
                "stderr": "",
            },
        ],
    )

    result_dir = summary_path.parent
    archived_artifact = (
        result_dir / "humaneval" / "artifacts" / "humaneval-001-codegen-artifact.json"
    )
    sample = json.loads((result_dir / "humaneval" / "samples.jsonl").read_text())
    archive_manifest = json.loads((result_dir / "archive-manifest.json").read_text())
    assert archived_artifact.is_file()
    assert json.loads(archived_artifact.read_text())["passed"] is True
    assert sample["contract_artifacts"]["codegen_artifact"] == (
        "humaneval/artifacts/humaneval-001-codegen-artifact.json"
    )
    assert (
        "humaneval/artifacts/humaneval-001-codegen-artifact.json"
        in archive_manifest["contract_artifacts"]
    )


def test_bwrap_codegen_smoke_command_records_all_suites_after_runner_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_mbpp_manifest(manifest_path)

    def fail_bwrap_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["scripts/run_glm52_bwrap_task_runner.sh"],
            returncode=2,
            stdout="",
            stderr="bwrap rootfs is not built\n",
        )

    monkeypatch.setattr(glm52_benchmark_verifier.subprocess, "run", fail_bwrap_runner)
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "humaneval",
            "--suite",
            "mbpp",
            "--manifest",
            str(manifest_path),
            "--pool",
            "code_sandbox",
            "--execution-backend",
            "bwrap_rootfs",
            "--run-id",
            "codegen-two-suite-runner-failure",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    exit_code = args.func(args)

    result_dir = tmp_path / "results" / "codegen-two-suite-runner-failure"
    summary = json.loads((result_dir / "summary.json").read_text())
    humaneval_failure = json.loads((result_dir / "humaneval" / "failures.jsonl").read_text())
    mbpp_failure = json.loads((result_dir / "mbpp" / "failures.jsonl").read_text())
    assert exit_code == 2
    assert summary["status"] == "environment_failed"
    assert {suite["suite"] for suite in summary["suites"]} == {"humaneval", "mbpp"}
    assert all(suite["model_failures"] == 0 for suite in summary["suites"])
    assert all(suite["infrastructure_failures"] == 1 for suite in summary["suites"])
    assert humaneval_failure["state"] == "environment_crashed"
    assert mbpp_failure["state"] == "environment_crashed"
    assert "not run after earlier bwrap codegen failure" in mbpp_failure["stderr"]


def test_bwrap_codegen_smoke_command_writes_summary_for_malformed_runner_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "benchmark-manifest.yaml"
    _write_humaneval_manifest(manifest_path)

    def malformed_bwrap_runner(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["scripts/run_glm52_bwrap_task_runner.sh"],
            returncode=0,
            stdout="{not-json",
            stderr="",
        )

    monkeypatch.setattr(
        glm52_benchmark_verifier.subprocess,
        "run",
        malformed_bwrap_runner,
    )
    args = build_parser().parse_args(
        [
            "smoke",
            "--suite",
            "humaneval",
            "--manifest",
            str(manifest_path),
            "--pool",
            "code_sandbox",
            "--execution-backend",
            "bwrap_rootfs",
            "--run-id",
            "codegen-runner-malformed",
            "--results-root",
            str(tmp_path / "results"),
            "--run-root",
            str(tmp_path / "run"),
        ]
    )

    exit_code = args.func(args)

    summary_path = tmp_path / "results" / "codegen-runner-malformed" / "summary.json"
    failure_path = tmp_path / "results" / "codegen-runner-malformed" / "humaneval" / "failures.jsonl"
    summary = json.loads(summary_path.read_text())
    failure = json.loads(failure_path.read_text())
    assert exit_code == 2
    assert summary["status"] == "environment_failed"
    assert summary["suites"][0]["model_failures"] == 0
    assert summary["suites"][0]["infrastructure_failures"] == 1
    assert failure["state"] == "grader_failed"
    assert failure["failure_category"] == "infrastructure"
    assert "failed to parse bwrap codegen runner output" in failure["stderr"]
