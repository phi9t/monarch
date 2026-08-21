from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ginkgo.eval.orchestrator import EvalRunStateError
from ginkgo.eval.orchestrator import begin_campaign_materialization
from ginkgo.eval.orchestrator import begin_campaign_summary
from ginkgo.eval.orchestrator import begin_grading
from ginkgo.eval.orchestrator import begin_suite_preparation
from ginkgo.eval.orchestrator import begin_suite_summary
from ginkgo.eval.orchestrator import begin_trial_generation
from ginkgo.eval.orchestrator import complete_campaign_materialization
from ginkgo.eval.orchestrator import complete_campaign_summary
from ginkgo.eval.orchestrator import complete_grading
from ginkgo.eval.orchestrator import complete_suite_preparation
from ginkgo.eval.orchestrator import complete_suite_summary
from ginkgo.eval.orchestrator import complete_trial_generation
from ginkgo.eval.orchestrator import resume_eval_run_state
from ginkgo.eval.manifest import CampaignManifestError
from ginkgo.eval.manifest import campaign_manifest_from_mapping
from ginkgo.eval.manifest import campaign_manifest_sha256
from ginkgo.eval.manifest import load_campaign_manifest


VALID_CAMPAIGN_MANIFEST = {
    "schema_version": 1,
    "campaign": {
        "id": "glm52-agentic-benchmarks-v1",
        "execution_mode": "machine_local",
        "artifact_root": "glm52-benchmark-results",
    },
    "model_under_test": {
        "endpoint_ref": "glm52-responses-local",
        "required_serving_summary_ref": "results://20260821T000000Z/summary.json",
    },
    "endpoints": [
        {
            "id": "glm52-responses-local",
            "role": "model_under_test",
            "protocol": "openai_responses",
            "base_url_ref": "component://responses_adapter/openai_base_url",
            "model": "zai-org/GLM-5.2",
        }
    ],
    "defaults": {
        "pilot": {
            "tasks": 5,
            "trials": 1,
            "concurrency": 1,
        },
        "full": {
            "retries": 1,
            "timeout_seconds": 7200,
        },
    },
    "suites": [
        {
            "id": "gsm8k",
            "profile": "math-reasoning-thinking-disabled",
            "dataset_revision": "openai/gsm8k@740312add88f781978c0658806c59bc2815b9866",
            "harness_revision": "lm-evaluation-harness@8a07e1110d060de48cfc7a9a7987b7659060b60b",
            "prompt_template": "gsm8k-v1",
            "execution_backend": "bwrap_rootfs",
            "metric": "exact_match",
            "decoding_profile": {
                "temperature": 0,
                "top_p": 1,
                "max_output_tokens": 2048,
                "glm_thinking": "disabled",
            },
            "dataset_source": {
                "type": "huggingface",
                "repo_id": "openai/gsm8k",
                "repo_type": "dataset",
                "revision": "740312add88f781978c0658806c59bc2815b9866",
            },
            "harness_source": {
                "type": "git",
                "url": "https://github.com/EleutherAI/lm-evaluation-harness.git",
                "revision": "8a07e1110d060de48cfc7a9a7987b7659060b60b",
            },
            "family": "static_eval",
            "adapter": "static_eval",
            "evidence_class": "pilot",
            "scoring": {"mode": "deterministic_exact_match"},
        }
    ],
}


def _manifest_with(path: tuple[object, ...], value: object) -> dict[str, object]:
    data = yaml.safe_load(yaml.safe_dump(VALID_CAMPAIGN_MANIFEST))
    cursor = data
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    return data


def test_campaign_manifest_accepts_additive_suite_metadata(tmp_path: Path) -> None:
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump(VALID_CAMPAIGN_MANIFEST), encoding="utf-8")

    manifest = load_campaign_manifest(path)

    assert manifest.campaign.id == "glm52-agentic-benchmarks-v1"
    assert manifest.campaign.execution_mode == "machine_local"
    assert manifest.model_under_test.endpoint_ref == "glm52-responses-local"
    assert manifest.endpoints[0].base_url_ref == (
        "component://responses_adapter/openai_base_url"
    )
    assert manifest.suites[0].execution_backend == "bwrap_rootfs"
    assert manifest.suites[0].family == "static_eval"
    assert manifest.suites[0].adapter == "static_eval"
    assert manifest.suites[0].evidence_class == "pilot"
    assert manifest.suites[0].metadata["scoring"] == {
        "mode": "deterministic_exact_match"
    }


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (
            ("campaign", "execution_mode"),
            "kubernetes",
            "campaign.execution_mode must be one of",
        ),
        (
            ("endpoints", 0, "role"),
            "oracle",
            "endpoint glm52-responses-local role must be one of",
        ),
        (
            ("endpoints", 0, "protocol"),
            "raw_http",
            "endpoint glm52-responses-local protocol must be one of",
        ),
    ],
)
def test_campaign_manifest_rejects_unsupported_modes(
    path: tuple[object, ...], value: object, match: str
) -> None:
    data = _manifest_with(path, value)

    with pytest.raises(CampaignManifestError, match=match):
        campaign_manifest_from_mapping(data)


def test_campaign_manifest_preserves_required_existing_suite_fields() -> None:
    suite = yaml.safe_load(yaml.safe_dump(VALID_CAMPAIGN_MANIFEST["suites"][0]))
    del suite["execution_backend"]
    data = _manifest_with(("suites",), [suite])

    with pytest.raises(
        CampaignManifestError,
        match="suite gsm8k missing fields: execution_backend",
    ):
        campaign_manifest_from_mapping(data)


def test_campaign_manifest_rejects_unknown_model_endpoint_ref() -> None:
    data = _manifest_with(("model_under_test", "endpoint_ref"), "missing-endpoint")

    with pytest.raises(
        CampaignManifestError,
        match="model_under_test.endpoint_ref must reference a declared endpoint",
    ):
        campaign_manifest_from_mapping(data)


def test_campaign_manifest_sha256_uses_materialized_json_contract() -> None:
    first = {"b": 2, "a": {"d": 4, "c": 3}}
    second = {"a": {"c": 3, "d": 4}, "b": 2}

    assert campaign_manifest_sha256(first) == campaign_manifest_sha256(second)


def test_evalrun_state_records_artifact_bearing_transitions(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "run"

    begin_campaign_materialization(
        result_dir=result_dir,
        run_id="agentic-pilot-001",
        manifest_sha256="manifest-a",
        mode="pilot",
        suite_ids=["gsm8k"],
    )
    complete_campaign_materialization(
        result_dir=result_dir,
        artifacts=["benchmark-manifest.json", "environment.json"],
    )
    materialized = resume_eval_run_state(
        result_dir=result_dir,
        manifest_sha256="manifest-a",
    )
    assert materialized.campaign_materialization.status == "completed"
    assert materialized.suite_preparation == {}

    begin_suite_preparation(result_dir=result_dir, suite_id="gsm8k")
    complete_suite_preparation(
        result_dir=result_dir,
        suite_id="gsm8k",
        artifacts=["gsm8k/prepare.json"],
    )
    begin_trial_generation(result_dir=result_dir, suite_id="gsm8k", trials_total=5)
    complete_trial_generation(
        result_dir=result_dir,
        suite_id="gsm8k",
        artifacts=["gsm8k/samples.jsonl"],
        trials_total=5,
    )
    begin_grading(result_dir=result_dir, suite_id="gsm8k")
    complete_grading(
        result_dir=result_dir,
        suite_id="gsm8k",
        artifacts=["gsm8k/metrics.json"],
        trials_graded=5,
    )
    begin_suite_summary(result_dir=result_dir, suite_id="gsm8k")
    complete_suite_summary(
        result_dir=result_dir,
        suite_id="gsm8k",
        artifacts=["gsm8k/summary.json"],
        status="passed",
    )
    begin_campaign_summary(result_dir=result_dir)
    complete_campaign_summary(
        result_dir=result_dir,
        artifacts=["summary.json", "run.json"],
        status="passed",
    )

    state = resume_eval_run_state(result_dir=result_dir, manifest_sha256="manifest-a")
    assert state.manifest_sha256 == "manifest-a"
    assert state.campaign_materialization.status == "completed"
    assert state.suite_preparation["gsm8k"].status == "completed"
    assert state.trial_generation["gsm8k"].trials_total == 5
    assert state.grading["gsm8k"].trials_graded == 5
    assert state.suite_summary["gsm8k"].status == "passed"
    assert state.campaign_summary.status == "passed"

    raw_state = (result_dir / "evalrun-state.json").read_text(encoding="utf-8")
    assert raw_state.endswith("\n")
    assert '"campaign_materialization"' in raw_state


def test_evalrun_state_rejects_resume_when_manifest_hash_changes(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "run"
    begin_campaign_materialization(
        result_dir=result_dir,
        run_id="agentic-pilot-001",
        manifest_sha256="manifest-a",
        mode="pilot",
        suite_ids=["gsm8k"],
    )

    with pytest.raises(EvalRunStateError, match="manifest_sha256 mismatch"):
        resume_eval_run_state(result_dir=result_dir, manifest_sha256="manifest-b")


def test_evalrun_state_rejects_resume_when_identity_changes(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "run"
    begin_campaign_materialization(
        result_dir=result_dir,
        run_id="agentic-pilot-001",
        manifest_sha256="manifest-a",
        mode="smoke",
        suite_ids=["gsm8k"],
    )

    with pytest.raises(EvalRunStateError, match="run_id mismatch"):
        resume_eval_run_state(
            result_dir=result_dir,
            manifest_sha256="manifest-a",
            run_id="different-run",
        )
    with pytest.raises(EvalRunStateError, match="mode mismatch"):
        resume_eval_run_state(
            result_dir=result_dir,
            manifest_sha256="manifest-a",
            mode="calibration",
        )
    with pytest.raises(EvalRunStateError, match="suite_ids mismatch"):
        resume_eval_run_state(
            result_dir=result_dir,
            manifest_sha256="manifest-a",
            suite_ids=["aime"],
        )


def test_evalrun_state_resume_accepts_same_suite_set_in_different_order(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "run"
    begin_campaign_materialization(
        result_dir=result_dir,
        run_id="agentic-pilot-001",
        manifest_sha256="manifest-a",
        mode="smoke",
        suite_ids=["humaneval", "mbpp"],
    )

    state = resume_eval_run_state(
        result_dir=result_dir,
        manifest_sha256="manifest-a",
        suite_ids=["mbpp", "humaneval"],
    )

    assert state.suite_ids == ["humaneval", "mbpp"]


def test_evalrun_state_rejects_duplicate_suite_ids(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "run"
    with pytest.raises(EvalRunStateError, match="suite_ids must not contain duplicates"):
        begin_campaign_materialization(
            result_dir=result_dir,
            run_id="agentic-pilot-001",
            manifest_sha256="manifest-a",
            mode="smoke",
            suite_ids=["humaneval", "humaneval"],
        )

    begin_campaign_materialization(
        result_dir=result_dir,
        run_id="agentic-pilot-001",
        manifest_sha256="manifest-a",
        mode="smoke",
        suite_ids=["humaneval"],
    )
    state_path = result_dir / "evalrun-state.json"
    payload = json.loads(state_path.read_text())
    payload["suite_ids"] = ["humaneval", "humaneval"]
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with pytest.raises(EvalRunStateError, match="suite_ids must not contain duplicates"):
        resume_eval_run_state(result_dir=result_dir, manifest_sha256="manifest-a")


def test_evalrun_state_rejects_duplicate_current_suite_ids(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "run"
    begin_campaign_materialization(
        result_dir=result_dir,
        run_id="agentic-pilot-001",
        manifest_sha256="manifest-a",
        mode="smoke",
        suite_ids=["humaneval"],
    )

    with pytest.raises(EvalRunStateError, match="suite_ids must not contain duplicates"):
        resume_eval_run_state(
            result_dir=result_dir,
            manifest_sha256="manifest-a",
            suite_ids=["humaneval", "humaneval"],
        )


@pytest.mark.parametrize(
    ("contents", "match"),
    [
        (None, "invalid_artifact: missing evalrun state"),
        ("not json", "invalid_artifact: malformed evalrun state"),
        ("[]", "invalid_artifact: evalrun state must be a mapping"),
    ],
)
def test_evalrun_state_treats_missing_or_malformed_state_as_invalid_artifact(
    tmp_path: Path, contents: str | None, match: str
) -> None:
    result_dir = tmp_path / "run"
    result_dir.mkdir()
    if contents is not None:
        (result_dir / "evalrun-state.json").write_text(contents, encoding="utf-8")

    with pytest.raises(EvalRunStateError, match=match):
        resume_eval_run_state(result_dir=result_dir, manifest_sha256="manifest-a")
