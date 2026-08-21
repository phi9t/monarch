from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ginkgo.eval.manifest import CampaignManifestError
from ginkgo.eval.manifest import campaign_manifest_from_mapping
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
