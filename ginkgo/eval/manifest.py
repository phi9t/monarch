from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Literal
from typing import TypeVar
from typing import cast

import yaml


class CampaignManifestError(RuntimeError):
    """Raised when a campaign manifest is malformed or unsupported."""

    pass


ExecutionMode = Literal["machine_local"]
EndpointRole = Literal[
    "model_under_test",
    "judge",
    "reader",
    "controller",
    "embedding",
    "tool_service",
]
EndpointProtocol = Literal[
    "openai_responses",
    "openai_chat_completions",
    "openai_embeddings",
]
ExecutionBackend = Literal[
    "bwrap_rootfs",
    "scripts_run",
    "local_docker",
    "harbor_local_docker",
    "host_subprocess",
]

T = TypeVar("T")
LiteralT = TypeVar("LiteralT", bound=str)


@dataclass(frozen=True)
class Campaign:
    """Top-level campaign identity and local execution target."""

    id: str
    execution_mode: ExecutionMode
    artifact_root: str


@dataclass(frozen=True)
class ModelUnderTest:
    """Reference from campaign policy to the endpoint under evaluation."""

    endpoint_ref: str
    required_serving_summary_ref: str


@dataclass(frozen=True)
class Endpoint:
    """OpenAI-compatible endpoint declaration used by campaign suites."""

    id: str
    role: EndpointRole
    protocol: EndpointProtocol
    base_url_ref: str
    model: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CampaignDefaults:
    """Default pilot and full-run controls shared by suites."""

    pilot: dict[str, Any]
    full: dict[str, Any]


@dataclass(frozen=True)
class Suite:
    """Benchmark suite declaration plus additive campaign metadata."""

    id: str
    profile: str
    dataset_revision: str
    harness_revision: str
    prompt_template: str
    execution_backend: ExecutionBackend
    decoding_profile: dict[str, Any]
    metric: str
    family: str | None
    adapter: str | None
    evidence_class: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CampaignManifest:
    """Validated machine-local GLM52 agentic benchmark campaign manifest."""

    schema_version: int
    campaign: Campaign
    model_under_test: ModelUnderTest
    endpoints: list[Endpoint]
    defaults: CampaignDefaults
    suites: list[Suite]


_TOP_LEVEL_FIELDS = {
    "schema_version",
    "campaign",
    "model_under_test",
    "endpoints",
    "defaults",
    "suites",
}
_CAMPAIGN_FIELDS = {"id", "execution_mode", "artifact_root"}
_MODEL_UNDER_TEST_FIELDS = {"endpoint_ref", "required_serving_summary_ref"}
_ENDPOINT_FIELDS = {"id", "role", "protocol", "base_url_ref", "model"}
_DEFAULTS_FIELDS = {"pilot", "full"}
_REQUIRED_SUITE_FIELDS = {
    "id",
    "profile",
    "dataset_revision",
    "harness_revision",
    "prompt_template",
    "execution_backend",
    "decoding_profile",
    "metric",
}
_OPTIONAL_CAMPAIGN_SUITE_FIELDS = {
    "family",
    "adapter",
    "evidence_class",
}
_EXECUTION_MODES: set[ExecutionMode] = {"machine_local"}
_ENDPOINT_ROLES: set[EndpointRole] = {
    "model_under_test",
    "judge",
    "reader",
    "controller",
    "embedding",
    "tool_service",
}
_ENDPOINT_PROTOCOLS: set[EndpointProtocol] = {
    "openai_responses",
    "openai_chat_completions",
    "openai_embeddings",
}
_EXECUTION_BACKENDS: set[ExecutionBackend] = {
    "bwrap_rootfs",
    "scripts_run",
    "local_docker",
    "harbor_local_docker",
    "host_subprocess",
}


def load_campaign_manifest(path: Path) -> CampaignManifest:
    """Load and validate a campaign manifest from a YAML file."""

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return campaign_manifest_from_mapping(data)


def campaign_manifest_from_mapping(data: object) -> CampaignManifest:
    """Validate a decoded campaign manifest mapping."""

    mapping = _require_mapping(data, "campaign manifest")
    _reject_unknown_fields(mapping, _TOP_LEVEL_FIELDS, "campaign manifest")
    _require_schema_version(mapping["schema_version"], "campaign manifest")

    endpoints = _endpoints_from_sequence(mapping["endpoints"])
    endpoint_ids = {endpoint.id for endpoint in endpoints}
    model_under_test = _model_under_test_from_mapping(mapping["model_under_test"])
    if model_under_test.endpoint_ref not in endpoint_ids:
        raise CampaignManifestError(
            "model_under_test.endpoint_ref must reference a declared endpoint"
        )

    return CampaignManifest(
        schema_version=1,
        campaign=_campaign_from_mapping(mapping["campaign"]),
        model_under_test=model_under_test,
        endpoints=endpoints,
        defaults=_defaults_from_mapping(mapping["defaults"]),
        suites=_suites_from_sequence(mapping["suites"]),
    )


def _campaign_from_mapping(data: object) -> Campaign:
    mapping = _require_mapping(data, "campaign")
    _reject_unknown_fields(mapping, _CAMPAIGN_FIELDS, "campaign")
    return Campaign(
        id=_require_non_empty_str(mapping["id"], "campaign.id"),
        execution_mode=_require_literal(
            mapping["execution_mode"], _EXECUTION_MODES, "campaign.execution_mode"
        ),
        artifact_root=_require_non_empty_str(
            mapping["artifact_root"], "campaign.artifact_root"
        ),
    )


def _model_under_test_from_mapping(data: object) -> ModelUnderTest:
    mapping = _require_mapping(data, "model_under_test")
    _reject_unknown_fields(
        mapping, _MODEL_UNDER_TEST_FIELDS, "model_under_test"
    )
    return ModelUnderTest(
        endpoint_ref=_require_non_empty_str(
            mapping["endpoint_ref"], "model_under_test.endpoint_ref"
        ),
        required_serving_summary_ref=_require_non_empty_str(
            mapping["required_serving_summary_ref"],
            "model_under_test.required_serving_summary_ref",
        ),
    )


def _endpoints_from_sequence(value: object) -> list[Endpoint]:
    return _identified_items_from_sequence(
        value,
        "endpoints",
        _endpoint_from_mapping,
        lambda endpoint: endpoint.id,
        "endpoint",
    )


def _endpoint_from_mapping(data: object, field: str) -> Endpoint:
    mapping = _require_mapping(data, field)
    missing = sorted(_ENDPOINT_FIELDS - set(mapping))
    if missing:
        raise CampaignManifestError(f"{field} missing field: {missing[0]}")
    endpoint_id = _require_non_empty_str(mapping["id"], f"{field}.id")
    role = _require_literal(
        mapping["role"],
        _ENDPOINT_ROLES,
        f"endpoint {endpoint_id} role",
    )
    protocol = _require_literal(
        mapping["protocol"],
        _ENDPOINT_PROTOCOLS,
        f"endpoint {endpoint_id} protocol",
    )
    metadata = {
        key: value for key, value in mapping.items() if key not in _ENDPOINT_FIELDS
    }
    return Endpoint(
        id=endpoint_id,
        role=role,
        protocol=protocol,
        base_url_ref=_require_non_empty_str(
            mapping["base_url_ref"], f"endpoint {endpoint_id} base_url_ref"
        ),
        model=_require_non_empty_str(
            mapping["model"], f"endpoint {endpoint_id} model"
        ),
        metadata=metadata,
    )


def _defaults_from_mapping(data: object) -> CampaignDefaults:
    mapping = _require_mapping(data, "defaults")
    _reject_unknown_fields(mapping, _DEFAULTS_FIELDS, "defaults")
    return CampaignDefaults(
        pilot=_require_mapping(mapping["pilot"], "defaults.pilot"),
        full=_require_mapping(mapping["full"], "defaults.full"),
    )


def _suites_from_sequence(value: object) -> list[Suite]:
    return _identified_items_from_sequence(
        value,
        "suites",
        _suite_from_mapping,
        lambda suite: suite.id,
        "suite",
    )


def _suite_from_mapping(data: object, field: str) -> Suite:
    mapping = _require_mapping(data, field)
    suite_id = _require_non_empty_str(mapping.get("id"), f"{field}.id")
    missing = sorted(key for key in _REQUIRED_SUITE_FIELDS if key not in mapping)
    if missing:
        raise CampaignManifestError(
            f"suite {suite_id} missing fields: {', '.join(missing)}"
        )
    execution_backend = _require_literal(
        mapping["execution_backend"],
        _EXECUTION_BACKENDS,
        f"suite {suite_id} execution_backend",
    )
    metadata = {
        key: value
        for key, value in mapping.items()
        if key not in _REQUIRED_SUITE_FIELDS
        and key not in _OPTIONAL_CAMPAIGN_SUITE_FIELDS
    }
    return Suite(
        id=suite_id,
        profile=_require_non_empty_str(
            mapping["profile"], f"suite {suite_id} profile"
        ),
        dataset_revision=_require_non_empty_str(
            mapping["dataset_revision"], f"suite {suite_id} dataset_revision"
        ),
        harness_revision=_require_non_empty_str(
            mapping["harness_revision"], f"suite {suite_id} harness_revision"
        ),
        prompt_template=_require_non_empty_str(
            mapping["prompt_template"], f"suite {suite_id} prompt_template"
        ),
        execution_backend=execution_backend,
        decoding_profile=_require_mapping(
            mapping["decoding_profile"], f"suite {suite_id} decoding_profile"
        ),
        metric=_require_non_empty_str(
            mapping["metric"], f"suite {suite_id} metric"
        ),
        family=_optional_str(mapping.get("family"), f"suite {suite_id} family"),
        adapter=_optional_str(mapping.get("adapter"), f"suite {suite_id} adapter"),
        evidence_class=_optional_str(
            mapping.get("evidence_class"), f"suite {suite_id} evidence_class"
        ),
        metadata=metadata,
    )


def _identified_items_from_sequence(
    value: object,
    field: str,
    parse: Callable[[object, str], T],
    item_id: Callable[[T], str],
    item_name: str,
) -> list[T]:
    if not isinstance(value, list):
        raise CampaignManifestError(f"{field} must be a list")
    items = [parse(item, f"{field}[{index}]") for index, item in enumerate(value)]
    seen: set[str] = set()
    for item in items:
        identifier = item_id(item)
        if identifier in seen:
            raise CampaignManifestError(f"duplicate {item_name} id: {identifier}")
        seen.add(identifier)
    return items


def _require_mapping(data: object, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CampaignManifestError(f"{field} must be a mapping")
    return data


def _reject_unknown_fields(
    mapping: dict[str, object], allowed: set[str], field: str
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise CampaignManifestError(f"unknown field in {field}: {unknown[0]}")
    missing = sorted(allowed - set(mapping))
    if missing:
        raise CampaignManifestError(f"missing field in {field}: {missing[0]}")


def _require_schema_version(value: object, field: str) -> None:
    if value != 1:
        raise CampaignManifestError(f"{field}.schema_version must be 1")


def _require_non_empty_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise CampaignManifestError(f"{field} must be a string")
    if value == "":
        raise CampaignManifestError(f"{field} must be non-empty")
    return value


def _optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_str(value, field)


def _require_literal(value: object, allowed: set[LiteralT], field: str) -> LiteralT:
    text = _require_non_empty_str(value, field)
    if text not in allowed:
        raise CampaignManifestError(f"{field} must be one of {sorted(allowed)}")
    return cast(LiteralT, text)
