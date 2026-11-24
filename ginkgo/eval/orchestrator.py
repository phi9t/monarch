from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EVALRUN_STATE_FILE = "evalrun-state.json"


class EvalRunStateError(RuntimeError):
    """Raised when EvalRun state cannot be resumed safely."""

    pass


@dataclass(frozen=True)
class CampaignMaterializationState:
    """State for campaign-level manifest and environment materialization."""

    status: str
    artifacts: list[str]


@dataclass(frozen=True)
class SuitePreparationState:
    """State for suite-local preparation artifacts."""

    status: str
    artifacts: list[str]


@dataclass(frozen=True)
class TrialGenerationState:
    """State for suite trial generation artifacts."""

    status: str
    artifacts: list[str]
    trials_total: int


@dataclass(frozen=True)
class GradingState:
    """State for suite grading artifacts."""

    status: str
    artifacts: list[str]
    trials_graded: int


@dataclass(frozen=True)
class SuiteSummaryState:
    """State for suite summary artifacts and terminal suite status."""

    status: str
    artifacts: list[str]


@dataclass(frozen=True)
class CampaignSummaryState:
    """State for campaign summary artifacts and terminal campaign status."""

    status: str
    artifacts: list[str]


@dataclass(frozen=True)
class EvalRunState:
    """File-backed state for one local EvalRun result directory."""

    schema_version: int
    run_id: str
    mode: str
    manifest_sha256: str
    suite_ids: list[str]
    campaign_materialization: CampaignMaterializationState
    suite_preparation: dict[str, SuitePreparationState]
    trial_generation: dict[str, TrialGenerationState]
    grading: dict[str, GradingState]
    suite_summary: dict[str, SuiteSummaryState]
    campaign_summary: CampaignSummaryState


def begin_campaign_materialization(
    *,
    result_dir: Path,
    run_id: str,
    manifest_sha256: str,
    mode: str,
    suite_ids: list[str],
) -> EvalRunState:
    """Create a running EvalRun state before writing campaign artifacts."""

    payload = {
        "schema_version": 1,
        "run_id": _require_non_empty_str(run_id, "run_id"),
        "mode": _require_non_empty_str(mode, "mode"),
        "manifest_sha256": _require_non_empty_str(
            manifest_sha256, "manifest_sha256"
        ),
        "suite_ids": _suite_id_list(suite_ids),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "campaign_materialization": {
            "status": "running",
            "artifacts": [],
        },
        "suite_preparation": {},
        "trial_generation": {},
        "grading": {},
        "suite_summary": {},
        "campaign_summary": {
            "status": "running",
            "artifacts": [],
        },
    }
    _write_state_payload(result_dir, payload)
    return _state_from_payload(payload, result_dir / EVALRUN_STATE_FILE)


def complete_campaign_materialization(
    *,
    result_dir: Path,
    artifacts: list[str],
) -> EvalRunState:
    """Mark campaign materialization complete after its artifacts are durable."""

    payload = _read_state_payload(result_dir)
    payload["campaign_materialization"] = {
        "status": "completed",
        "artifacts": _artifact_list(artifacts),
    }
    _touch(payload)
    _write_state_payload(result_dir, payload)
    return _state_from_payload(payload, result_dir / EVALRUN_STATE_FILE)


def begin_suite_preparation(*, result_dir: Path, suite_id: str) -> EvalRunState:
    """Record that suite preparation has started."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="suite_preparation",
        suite_id=suite_id,
        value={"status": "running", "artifacts": []},
    )


def complete_suite_preparation(
    *,
    result_dir: Path,
    suite_id: str,
    artifacts: list[str],
) -> EvalRunState:
    """Mark suite preparation complete after its artifacts are durable."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="suite_preparation",
        suite_id=suite_id,
        value={"status": "completed", "artifacts": _artifact_list(artifacts)},
    )


def begin_trial_generation(
    *,
    result_dir: Path,
    suite_id: str,
    trials_total: int,
) -> EvalRunState:
    """Record that suite trial generation has started."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="trial_generation",
        suite_id=suite_id,
        value={
            "status": "running",
            "artifacts": [],
            "trials_total": _non_negative_int(trials_total, "trials_total"),
        },
    )


def complete_trial_generation(
    *,
    result_dir: Path,
    suite_id: str,
    artifacts: list[str],
    trials_total: int,
) -> EvalRunState:
    """Mark trial generation complete after samples are durable."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="trial_generation",
        suite_id=suite_id,
        value={
            "status": "completed",
            "artifacts": _artifact_list(artifacts),
            "trials_total": _non_negative_int(trials_total, "trials_total"),
        },
    )


def begin_grading(*, result_dir: Path, suite_id: str) -> EvalRunState:
    """Record that suite grading has started."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="grading",
        suite_id=suite_id,
        value={"status": "running", "artifacts": [], "trials_graded": 0},
    )


def complete_grading(
    *,
    result_dir: Path,
    suite_id: str,
    artifacts: list[str],
    trials_graded: int,
) -> EvalRunState:
    """Mark grading complete after metrics are durable."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="grading",
        suite_id=suite_id,
        value={
            "status": "completed",
            "artifacts": _artifact_list(artifacts),
            "trials_graded": _non_negative_int(trials_graded, "trials_graded"),
        },
    )


def begin_suite_summary(*, result_dir: Path, suite_id: str) -> EvalRunState:
    """Record that suite summary materialization has started."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="suite_summary",
        suite_id=suite_id,
        value={"status": "running", "artifacts": []},
    )


def complete_suite_summary(
    *,
    result_dir: Path,
    suite_id: str,
    artifacts: list[str],
    status: str,
) -> EvalRunState:
    """Mark a suite summary complete after its summary artifacts are durable."""

    return _set_suite_transition(
        result_dir=result_dir,
        collection="suite_summary",
        suite_id=suite_id,
        value={"status": status, "artifacts": _artifact_list(artifacts)},
    )


def begin_campaign_summary(*, result_dir: Path) -> EvalRunState:
    """Record that campaign summary materialization has started."""

    payload = _read_state_payload(result_dir)
    payload["campaign_summary"] = {"status": "running", "artifacts": []}
    _touch(payload)
    _write_state_payload(result_dir, payload)
    return _state_from_payload(payload, result_dir / EVALRUN_STATE_FILE)


def complete_campaign_summary(
    *,
    result_dir: Path,
    artifacts: list[str],
    status: str,
) -> EvalRunState:
    """Mark the campaign summary complete after terminal artifacts are durable."""

    payload = _read_state_payload(result_dir)
    payload["campaign_summary"] = {
        "status": status,
        "artifacts": _artifact_list(artifacts),
    }
    _touch(payload)
    _write_state_payload(result_dir, payload)
    return _state_from_payload(payload, result_dir / EVALRUN_STATE_FILE)


def resume_eval_run_state(
    *,
    result_dir: Path,
    manifest_sha256: str,
    run_id: str | None = None,
    mode: str | None = None,
    suite_ids: list[str] | None = None,
) -> EvalRunState:
    """Load EvalRun state and reject unsafe resume attempts."""

    payload = _read_state_payload(result_dir)
    stored_manifest_sha256 = payload.get("manifest_sha256")
    if stored_manifest_sha256 != manifest_sha256:
        raise EvalRunStateError(
            "manifest_sha256 mismatch: "
            f"stored {stored_manifest_sha256!r}, current {manifest_sha256!r}"
        )
    state = _state_from_payload(payload, result_dir / EVALRUN_STATE_FILE)
    if run_id is not None and state.run_id != run_id:
        raise EvalRunStateError(
            f"run_id mismatch: stored {state.run_id!r}, current {run_id!r}"
        )
    if mode is not None and state.mode != mode:
        raise EvalRunStateError(
            f"mode mismatch: stored {state.mode!r}, current {mode!r}"
        )
    if suite_ids is not None and set(state.suite_ids) != set(_suite_id_list(suite_ids)):
        raise EvalRunStateError(
            f"suite_ids mismatch: stored {state.suite_ids!r}, current {suite_ids!r}"
        )
    return state


def has_eval_run_state(*, result_dir: Path) -> bool:
    """Return whether an EvalRun state artifact exists."""

    return (result_dir / EVALRUN_STATE_FILE).exists()


def _set_suite_transition(
    *,
    result_dir: Path,
    collection: str,
    suite_id: str,
    value: dict[str, Any],
) -> EvalRunState:
    payload = _read_state_payload(result_dir)
    transitions = payload.get(collection)
    if not isinstance(transitions, dict):
        raise EvalRunStateError(f"invalid_artifact: {collection} must be a mapping")
    transitions[_require_non_empty_str(suite_id, "suite_id")] = value
    _touch(payload)
    _write_state_payload(result_dir, payload)
    return _state_from_payload(payload, result_dir / EVALRUN_STATE_FILE)


def _read_state_payload(result_dir: Path) -> dict[str, Any]:
    path = result_dir / EVALRUN_STATE_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvalRunStateError("invalid_artifact: missing evalrun state") from error
    except json.JSONDecodeError as error:
        raise EvalRunStateError("invalid_artifact: malformed evalrun state") from error
    if not isinstance(payload, dict):
        raise EvalRunStateError("invalid_artifact: evalrun state must be a mapping")
    return payload


def _write_state_payload(result_dir: Path, payload: dict[str, Any]) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    path = result_dir / EVALRUN_STATE_FILE
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _state_from_payload(payload: dict[str, Any], path: Path) -> EvalRunState:
    try:
        schema_version = payload["schema_version"]
        run_id = payload["run_id"]
        mode = payload["mode"]
        manifest_sha256 = payload["manifest_sha256"]
        suite_ids = payload["suite_ids"]
    except KeyError as error:
        raise EvalRunStateError(
            f"invalid_artifact: evalrun state missing field {error.args[0]}"
        ) from error
    if schema_version != 1:
        raise EvalRunStateError(
            "invalid_artifact: evalrun state schema_version must be 1"
        )
    if not isinstance(run_id, str) or not run_id:
        raise EvalRunStateError("invalid_artifact: run_id must be a non-empty string")
    if not isinstance(mode, str) or not mode:
        raise EvalRunStateError("invalid_artifact: mode must be a non-empty string")
    if not isinstance(manifest_sha256, str) or not manifest_sha256:
        raise EvalRunStateError(
            "invalid_artifact: manifest_sha256 must be a non-empty string"
        )
    if not isinstance(suite_ids, list) or not all(
        isinstance(suite_id, str) and suite_id for suite_id in suite_ids
    ):
        raise EvalRunStateError(
            "invalid_artifact: suite_ids must be a list of non-empty strings"
        )
    if len(set(suite_ids)) != len(suite_ids):
        raise EvalRunStateError("invalid_artifact: suite_ids must not contain duplicates")
    return EvalRunState(
        schema_version=1,
        run_id=run_id,
        mode=mode,
        manifest_sha256=manifest_sha256,
        suite_ids=suite_ids,
        campaign_materialization=_campaign_materialization_state(
            payload, path
        ),
        suite_preparation=_suite_state_mapping(
            payload, "suite_preparation", SuitePreparationState
        ),
        trial_generation=_suite_state_mapping(
            payload, "trial_generation", TrialGenerationState
        ),
        grading=_suite_state_mapping(payload, "grading", GradingState),
        suite_summary=_suite_state_mapping(
            payload, "suite_summary", SuiteSummaryState
        ),
        campaign_summary=_campaign_summary_state(payload, path),
    )


def _campaign_materialization_state(
    payload: dict[str, Any], path: Path
) -> CampaignMaterializationState:
    value = _mapping_field(payload, "campaign_materialization", path)
    return CampaignMaterializationState(
        status=_transition_status(
            value.get("status"),
            "campaign_materialization.status",
        ),
        artifacts=_artifact_list(value.get("artifacts", [])),
    )


def _campaign_summary_state(
    payload: dict[str, Any], path: Path
) -> CampaignSummaryState:
    value = _mapping_field(payload, "campaign_summary", path)
    return CampaignSummaryState(
        status=_transition_status(value.get("status"), "campaign_summary.status"),
        artifacts=_artifact_list(value.get("artifacts", [])),
    )


def _suite_state_mapping(
    payload: dict[str, Any],
    field: str,
    state_type: type[
        SuitePreparationState
        | TrialGenerationState
        | GradingState
        | SuiteSummaryState
    ],
) -> dict[str, Any]:
    raw = payload.get(field)
    if not isinstance(raw, dict):
        raise EvalRunStateError(f"invalid_artifact: {field} must be a mapping")
    return {
        suite_id: _suite_state(field, suite_id, value, state_type)
        for suite_id, value in raw.items()
    }


def _suite_state(
    field: str,
    suite_id: object,
    value: object,
    state_type: type[
        SuitePreparationState
        | TrialGenerationState
        | GradingState
        | SuiteSummaryState
    ],
) -> SuitePreparationState | TrialGenerationState | GradingState | SuiteSummaryState:
    if not isinstance(suite_id, str) or not suite_id:
        raise EvalRunStateError(
            f"invalid_artifact: {field} suite id must be non-empty"
        )
    if not isinstance(value, dict):
        raise EvalRunStateError(
            f"invalid_artifact: {field}.{suite_id} must be a mapping"
        )
    status = _transition_status(value.get("status"), f"{field}.{suite_id}.status")
    artifacts = _artifact_list(value.get("artifacts", []))
    if state_type is TrialGenerationState:
        return TrialGenerationState(
            status=status,
            artifacts=artifacts,
            trials_total=_non_negative_int(
                value.get("trials_total"), f"{field}.{suite_id}.trials_total"
            ),
        )
    if state_type is GradingState:
        return GradingState(
            status=status,
            artifacts=artifacts,
            trials_graded=_non_negative_int(
                value.get("trials_graded"), f"{field}.{suite_id}.trials_graded"
            ),
        )
    if state_type is SuitePreparationState:
        return SuitePreparationState(status=status, artifacts=artifacts)
    if state_type is SuiteSummaryState:
        return SuiteSummaryState(status=status, artifacts=artifacts)
    raise AssertionError(f"unsupported state type: {state_type}")


def _mapping_field(payload: dict[str, Any], field: str, path: Path) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise EvalRunStateError(
            f"invalid_artifact: {path} field {field} must be a mapping"
        )
    return value


def _artifact_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(artifact, str) and artifact for artifact in value
    ):
        raise EvalRunStateError(
            "invalid_artifact: artifacts must be a list of non-empty strings"
        )
    return value


def _transition_status(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvalRunStateError(f"invalid_artifact: {field} has invalid status")
    return value


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvalRunStateError(
            f"invalid_artifact: {field} must be a non-negative int"
        )
    return value


def _require_non_empty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvalRunStateError(f"{field} must be a non-empty string")
    return value


def _suite_id_list(suite_ids: list[str]) -> list[str]:
    result = [_require_non_empty_str(suite_id, "suite_id") for suite_id in suite_ids]
    if len(set(result)) != len(result):
        raise EvalRunStateError("invalid_artifact: suite_ids must not contain duplicates")
    return result


def _touch(payload: dict[str, Any]) -> None:
    payload["updated_at"] = _utc_now()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
