from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Protocol

from ginkgo.local_run import LocalRunResult
from ginkgo.local_run import Qwen3SglangWorkload
from ginkgo.local_run import RuntimeBackedLocalRunAdapter
from ginkgo.local_run import SglangLocalRun


class ControlPlaneConfigError(RuntimeError):
    pass


class _LocalEndpoint:
    def __init__(self, method: Callable[..., Any]) -> None:
        self._method = method

    def __get__(self, instance: object, owner: type[object] | None = None) -> "_LocalEndpoint":
        del instance, owner
        return self


def _load_monarch_actor_symbols() -> tuple[type[object], Callable[[Callable[..., Any]], Any]]:
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            from monarch.actor import Actor as MonarchActor
            from monarch.actor import endpoint as monarch_endpoint
    except SystemExit:
        return object, _LocalEndpoint
    return MonarchActor, monarch_endpoint


Actor, endpoint = _load_monarch_actor_symbols()


@dataclass(frozen=True)
class ControlPlaneFailurePolicy:
    fail_fast: bool
    allow_fallback: bool
    teardown_requires_process_record: bool


@dataclass(frozen=True)
class ControlPlaneComponent:
    name: str
    kind: str
    declared_ref: str
    depends_on: list[str]
    upstream_ref: str | None
    artifacts: dict[str, str]


@dataclass(frozen=True)
class MonarchControlPlaneRun:
    schema_version: int
    run_id: str
    profile: str
    declared_config_ref: str
    local_environment_ref: str
    execution_mode: str
    components: list[ControlPlaneComponent]
    artifacts: dict[str, str]
    failure_policy: ControlPlaneFailurePolicy

    def component(self, name: str) -> ControlPlaneComponent:
        for component in self.components:
            if component.name == name:
                return component
        raise ControlPlaneConfigError(f"unknown component: {name}")


@dataclass(frozen=True)
class ControlPlaneRunResult:
    status: str
    completed_components: list[str]
    failed_component: str | None
    failed_phase: str | None
    error: str | None
    teardown_errors: list[dict[str, str]]
    state: dict[str, dict[str, str]]


class ControlPlaneAdapter(Protocol):
    def prepare(self, run: MonarchControlPlaneRun) -> dict[str, str]:
        ...

    def launch(self, component: ControlPlaneComponent, upstream_url: str | None) -> dict[str, str]:
        ...

    def probe(self, component: ControlPlaneComponent, component_state: dict[str, str]) -> dict[str, str]:
        ...

    def teardown(self, component: ControlPlaneComponent, component_state: dict[str, str]) -> dict[str, str]:
        ...

    def is_cancelled(self) -> bool:
        ...


class SglangLocalRunner(Protocol):
    def run(
        self,
        *,
        declared_spec: Path,
        local_environment: Path,
        run_id: str | None = None,
        port: int | None = None,
        output: Any | None = None,
    ) -> LocalRunResult:
        ...


class GinkgoHostControlAdapter:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        sglang_runner: SglangLocalRunner,
    ) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
        self.sglang_runner = sglang_runner
        self._run: MonarchControlPlaneRun | None = None
        self._cancelled = False

    def prepare(self, run: MonarchControlPlaneRun) -> dict[str, str]:
        if run.execution_mode != "host-control adapter":
            raise ControlPlaneConfigError("GinkgoHostControlAdapter requires host-control adapter mode")
        self._run = run
        return {
            "run_id": run.run_id,
            "local_environment": str(self._resolve_local_environment_ref(run.local_environment_ref)),
        }

    def launch(self, component: ControlPlaneComponent, upstream_url: str | None) -> dict[str, str]:
        run = self._require_prepared()
        if component.kind != "sglang":
            raise ControlPlaneConfigError(f"unsupported host-control component kind: {component.kind}")
        if upstream_url is not None:
            raise ControlPlaneConfigError("sglang component must not receive upstream_url")

        component_run_id = f"{run.run_id}-{component.name}"
        result = self.sglang_runner.run(
            declared_spec=self._resolve_repo_ref(component.declared_ref),
            local_environment=self._resolve_local_environment_ref(run.local_environment_ref),
            run_id=component_run_id,
            port=None,
        )
        if result.status != "passed":
            raise ControlPlaneConfigError(f"sglang local run failed: {result.status}")
        state = {
            "status": result.status,
            "run_id": result.run_id,
            "port": str(result.port),
            "openai_base_url": f"http://127.0.0.1:{result.port}/v1",
            "generated_text": result.generated_text,
            "evidence_manifest": str(result.evidence_manifest),
        }
        if result.teardown_status is not None:
            state["teardown_status"] = result.teardown_status
        return state

    def probe(self, component: ControlPlaneComponent, component_state: dict[str, str]) -> dict[str, str]:
        if component.kind != "sglang":
            raise ControlPlaneConfigError(f"unsupported host-control component kind: {component.kind}")
        if component_state.get("status") != "passed":
            raise ControlPlaneConfigError(f"sglang component is not ready: {component.name}")
        evidence_manifest = component_state.get("evidence_manifest")
        if not evidence_manifest:
            raise ControlPlaneConfigError("sglang component state missing evidence_manifest")
        return {"ready": "true", "evidence_manifest": evidence_manifest}

    def teardown(self, component: ControlPlaneComponent, component_state: dict[str, str]) -> dict[str, str]:
        run_id = component_state.get("run_id")
        if not run_id:
            raise ControlPlaneConfigError(f"component state missing run_id for teardown: {component.name}")
        return {"closed": "true", "run_id": run_id}

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _require_prepared(self) -> MonarchControlPlaneRun:
        if self._run is None:
            raise ControlPlaneConfigError("host-control adapter must be prepared before launch")
        return self._run

    def _resolve_repo_ref(self, ref: str) -> Path:
        if "#" in ref:
            ref, fragment = ref.split("#", 1)
            if fragment:
                raise ControlPlaneConfigError(f"host-control adapter cannot launch config fragments: {fragment}")
        if not ref.startswith("repo://"):
            raise ControlPlaneConfigError(f"host-control adapter requires repo:// refs: {ref}")
        suffix = ref.removeprefix("repo://")
        if suffix.startswith("/") or ".." in Path(suffix).parts:
            raise ControlPlaneConfigError(f"unsafe repo ref: {ref}")
        return self.repo_root / suffix

    def _resolve_local_environment_ref(self, ref: str) -> Path:
        if not ref.startswith("local-env://"):
            raise ControlPlaneConfigError(f"host-control adapter requires local-env:// refs: {ref}")
        suffix = ref.removeprefix("local-env://")
        if suffix.startswith("/") or ".." in Path(suffix).parts:
            raise ControlPlaneConfigError(f"unsafe local environment ref: {ref}")
        return self.repo_root / "ginkgo" / "local-env" / suffix


def create_qwen3_host_control_adapter(
    *,
    repo_root: Path | None = None,
    runtime: Any | None = None,
) -> GinkgoHostControlAdapter:
    runtime_adapter = RuntimeBackedLocalRunAdapter(runtime) if runtime is not None else None
    return GinkgoHostControlAdapter(
        repo_root=repo_root,
        sglang_runner=SglangLocalRun(
            workload=Qwen3SglangWorkload(),
            runtime=runtime_adapter,
        ),
    )


class ControlPlaneCoordinator:
    def __init__(self, *, run: MonarchControlPlaneRun, adapter: ControlPlaneAdapter) -> None:
        self.control_run = run
        self.adapter = adapter
        self._phase = "initialized"
        self._state: dict[str, dict[str, str]] = {}
        self._launched: list[ControlPlaneComponent] = []
        self._completed: list[str] = []
        self._failed_component: str | None = None
        self._error: str | None = None
        self._failed_phase: str | None = None
        self._teardown_errors: list[dict[str, str]] = []

    def run(self) -> ControlPlaneRunResult:
        self._phase = "preparing"
        try:
            self._state["parent"] = self.adapter.prepare(self.control_run)
            for component in self.control_run.components:
                if self.adapter.is_cancelled():
                    return self._cancelled_result()
                upstream_url = self._upstream_url(component)
                self._phase = f"launching:{component.name}"
                component_state = self.adapter.launch(component, upstream_url)
                self._state[component.name] = dict(component_state)
                self._launched.append(component)
                self._phase = f"probing:{component.name}"
                probe_state = self.adapter.probe(component, self._state[component.name])
                self._state[component.name].update(probe_state)
                self._completed.append(component.name)
                if self.adapter.is_cancelled():
                    return self._cancelled_result()
            self._phase = "completed"
            return self._result("completed")
        except Exception as error:
            self._failed_component = _phase_component(self._phase)
            self._failed_phase = self._phase
            self._error = str(error)
            self._phase = "failed"
            self._teardown_launched()
            return self._result("failed")

    def status(self) -> dict[str, object]:
        return {
            "phase": self._phase,
            "completed_components": list(self._completed),
            "failed_component": self._failed_component,
            "failed_phase": self._failed_phase,
            "error": self._error,
            "teardown_errors": list(self._teardown_errors),
            "state": _copy_state(self._state),
        }

    def _upstream_url(self, component: ControlPlaneComponent) -> str | None:
        if component.upstream_ref is None:
            return None
        return resolve_component_ref(self.control_run, component.upstream_ref, self._state)

    def _cancelled_result(self) -> ControlPlaneRunResult:
        self._phase = "cancelled"
        self._teardown_launched()
        return self._result("cancelled")

    def _teardown_launched(self) -> None:
        for component in reversed(self._launched):
            try:
                component_state = self._state.get(component.name, {})
                teardown_state = self.adapter.teardown(component, component_state)
                component_state.update(teardown_state)
            except Exception as error:
                self._teardown_errors.append(
                    {
                        "component": component.name,
                        "error": str(error),
                    }
                )

    def _result(self, status: str) -> ControlPlaneRunResult:
        return ControlPlaneRunResult(
            status=status,
            completed_components=list(self._completed),
            failed_component=self._failed_component,
            failed_phase=self._failed_phase,
            error=self._error,
            teardown_errors=list(self._teardown_errors),
            state=_copy_state(self._state),
        )


class GinkgoControlPlaneActor(Actor):
    def __init__(self, run: MonarchControlPlaneRun, adapter: ControlPlaneAdapter) -> None:
        self.control_run = run
        self.adapter = adapter
        self._phase = "initialized"
        self._state: dict[str, dict[str, str]] = {}
        self._launched: list[ControlPlaneComponent] = []
        self._completed: list[str] = []
        self._failed_component: str | None = None
        self._error: str | None = None
        self._failed_phase: str | None = None
        self._teardown_errors: list[dict[str, str]] = []

    @endpoint
    async def prepare(self) -> dict[str, str]:
        self._phase = "preparing"
        self._state["parent"] = dict(self.adapter.prepare(self.control_run))
        return dict(self._state["parent"])

    @endpoint
    async def launch(self, component_name: str) -> dict[str, str]:
        self._require_prepared()
        component = self.control_run.component(component_name)
        if component.name in self._state:
            raise ControlPlaneConfigError(f"component already launched: {component.name}")
        self._require_completed_dependencies(component)
        upstream_url = self._upstream_url(component)
        self._phase = f"launch:{component.name}"
        try:
            self._state[component.name] = dict(self.adapter.launch(component, upstream_url))
            if component not in self._launched:
                self._launched.append(component)
            return dict(self._state[component.name])
        except Exception as error:
            self._record_failure(component, error)
            self._teardown_launched()
            raise

    @endpoint
    async def probe(self, component_name: str) -> dict[str, str]:
        self._require_prepared()
        component = self.control_run.component(component_name)
        self._phase = f"probe:{component.name}"
        component_state = self._state.get(component.name)
        if component_state is None:
            raise ControlPlaneConfigError(f"component has not launched: {component.name}")
        try:
            probe_state = dict(self.adapter.probe(component, component_state))
            component_state.update(probe_state)
            if component.name not in self._completed:
                self._completed.append(component.name)
            return probe_state
        except Exception as error:
            self._record_failure(component, error)
            self._teardown_launched()
            raise

    @endpoint
    async def teardown(self, component_name: str) -> dict[str, str]:
        self._require_prepared()
        component = self.control_run.component(component_name)
        component_state = self._state.get(component.name)
        if component_state is None:
            raise ControlPlaneConfigError(f"component has not launched: {component.name}")
        self._phase = f"teardown:{component.name}"
        teardown_state = dict(self.adapter.teardown(component, component_state))
        component_state.update(teardown_state)
        return teardown_state

    @endpoint
    async def status(self) -> dict[str, object]:
        return self._status()

    @endpoint
    async def cancel(self) -> dict[str, str]:
        self._phase = "cancelled"
        self._teardown_launched()
        return {"status": "cancelled"}

    def _upstream_url(self, component: ControlPlaneComponent) -> str | None:
        if component.upstream_ref is None:
            return None
        return resolve_component_ref(self.control_run, component.upstream_ref, self._state)

    def _require_prepared(self) -> None:
        if "parent" not in self._state:
            raise ControlPlaneConfigError("actor must be prepared before lifecycle endpoints")

    def _require_completed_dependencies(self, component: ControlPlaneComponent) -> None:
        for dependency in component.depends_on:
            if dependency not in self._completed:
                raise ControlPlaneConfigError(
                    f"dependency not completed for component {component.name}: {dependency}"
                )

    def _status(self) -> dict[str, object]:
        return {
            "phase": self._phase,
            "completed_components": list(self._completed),
            "failed_component": self._failed_component,
            "failed_phase": self._failed_phase,
            "teardown_errors": list(self._teardown_errors),
            "error": self._error,
            "state": _copy_state(self._state),
        }

    def _record_failure(self, component: ControlPlaneComponent, error: Exception) -> None:
        self._failed_component = component.name
        self._error = str(error)
        self._failed_phase = self._phase
        self._phase = "failed"

    def _teardown_launched(self) -> None:
        for component in reversed(self._launched):
            try:
                component_state = self._state.get(component.name, {})
                teardown_state = self.adapter.teardown(component, component_state)
                component_state.update(teardown_state)
            except Exception as error:
                self._teardown_errors.append(
                    {
                        "component": component.name,
                        "error": str(error),
                    }
                )


class Qwen3HostControlPlaneActor(GinkgoControlPlaneActor):
    def __init__(
        self,
        run: MonarchControlPlaneRun,
        repo_root: Path | str | None = None,
        runtime: Any | None = None,
    ) -> None:
        root = Path(repo_root) if repo_root is not None else None
        super().__init__(
            run,
            create_qwen3_host_control_adapter(repo_root=root, runtime=runtime),
        )


_RUN_FIELDS = {
    "schema_version",
    "run_id",
    "profile",
    "declared_config_ref",
    "local_environment_ref",
    "execution_mode",
    "components",
    "artifacts",
    "failure_policy",
}
_COMPONENT_FIELDS = {
    "name",
    "kind",
    "declared_ref",
    "depends_on",
    "upstream_ref",
    "artifacts",
}
_REQUIRED_COMPONENT_FIELDS = _COMPONENT_FIELDS - {"upstream_ref"}
_FAILURE_POLICY_FIELDS = {
    "fail_fast",
    "allow_fallback",
    "teardown_requires_process_record",
}
_EXECUTION_MODES = {"host-control adapter", "monarch-actor-control"}
_COMPONENT_KINDS = {"sglang", "dynamo", "responses_adapter", "benchmark", "eval"}
_PORTABLE_REF_PREFIXES = ("repo://", "run://", "results://")
_LOCAL_ENVIRONMENT_REF_PREFIXES = ("local-env://",)
_COMPONENT_REF_PREFIX = "component://"


def control_plane_run_from_mapping(data: object) -> MonarchControlPlaneRun:
    mapping = _require_mapping(data, "control plane run")
    _reject_unknown_fields(mapping, _RUN_FIELDS, "control plane run")
    _require_schema_version(mapping["schema_version"], "control plane run")

    components = _components_from_sequence(mapping["components"])
    _validate_component_graph(components)
    run = MonarchControlPlaneRun(
        schema_version=1,
        run_id=_require_non_empty_str(mapping["run_id"], "run_id"),
        profile=_require_non_empty_str(mapping["profile"], "profile"),
        declared_config_ref=_require_portable_ref(mapping["declared_config_ref"], "declared_config_ref"),
        local_environment_ref=_require_local_environment_ref(
            mapping["local_environment_ref"],
            "local_environment_ref",
        ),
        execution_mode=_require_one_of(mapping["execution_mode"], _EXECUTION_MODES, "execution_mode"),
        components=components,
        artifacts=_portable_ref_mapping(mapping["artifacts"], "artifacts"),
        failure_policy=_failure_policy_from_mapping(mapping["failure_policy"]),
    )
    _validate_component_refs(run)
    return run


def run_to_mapping(run: MonarchControlPlaneRun) -> dict[str, object]:
    return {
        "schema_version": run.schema_version,
        "run_id": run.run_id,
        "profile": run.profile,
        "declared_config_ref": run.declared_config_ref,
        "local_environment_ref": run.local_environment_ref,
        "execution_mode": run.execution_mode,
        "components": [component_to_mapping(component) for component in run.components],
        "artifacts": dict(run.artifacts),
        "failure_policy": failure_policy_to_mapping(run.failure_policy),
    }


def component_to_mapping(component: ControlPlaneComponent) -> dict[str, object]:
    mapping: dict[str, object] = {
        "name": component.name,
        "kind": component.kind,
        "declared_ref": component.declared_ref,
        "depends_on": list(component.depends_on),
        "artifacts": dict(component.artifacts),
    }
    if component.upstream_ref is not None:
        mapping["upstream_ref"] = component.upstream_ref
    return mapping


def failure_policy_to_mapping(policy: ControlPlaneFailurePolicy) -> dict[str, object]:
    return {
        "fail_fast": policy.fail_fast,
        "allow_fallback": policy.allow_fallback,
        "teardown_requires_process_record": policy.teardown_requires_process_record,
    }


def resolve_component_ref(
    run: MonarchControlPlaneRun,
    ref: str,
    state: dict[str, dict[str, str]],
) -> str:
    component_name, key = _split_component_ref(ref)
    run.component(component_name)
    component_state = state.get(component_name)
    if component_state is None:
        raise ControlPlaneConfigError(f"component state missing for ref: {ref}")
    try:
        return component_state[key]
    except KeyError as error:
        raise ControlPlaneConfigError(f"component state does not contain key: {ref}") from error


def _components_from_sequence(value: object) -> list[ControlPlaneComponent]:
    if not isinstance(value, list):
        raise ControlPlaneConfigError("components must be a list")
    if not value:
        raise ControlPlaneConfigError("components must be non-empty")
    return [_component_from_mapping(item, f"components[{index}]") for index, item in enumerate(value)]


def _component_from_mapping(data: object, field: str) -> ControlPlaneComponent:
    mapping = _require_mapping(data, field)
    _reject_unknown_fields(mapping, _COMPONENT_FIELDS, field, required=_REQUIRED_COMPONENT_FIELDS)
    upstream_ref = mapping.get("upstream_ref")
    if upstream_ref is not None:
        upstream_ref = _require_component_ref(upstream_ref, f"{field}.upstream_ref")
    return ControlPlaneComponent(
        name=_require_non_empty_str(mapping["name"], f"{field}.name"),
        kind=_require_one_of(mapping["kind"], _COMPONENT_KINDS, f"{field}.kind"),
        declared_ref=_require_portable_ref(mapping["declared_ref"], f"{field}.declared_ref"),
        depends_on=_string_list(mapping["depends_on"], f"{field}.depends_on"),
        upstream_ref=upstream_ref,
        artifacts=_portable_ref_mapping(mapping["artifacts"], f"{field}.artifacts"),
    )


def _failure_policy_from_mapping(data: object) -> ControlPlaneFailurePolicy:
    mapping = _require_mapping(data, "failure_policy")
    _reject_unknown_fields(mapping, _FAILURE_POLICY_FIELDS, "failure_policy")
    policy = ControlPlaneFailurePolicy(
        fail_fast=_require_bool(mapping["fail_fast"], "failure_policy.fail_fast"),
        allow_fallback=_require_bool(mapping["allow_fallback"], "failure_policy.allow_fallback"),
        teardown_requires_process_record=_require_bool(
            mapping["teardown_requires_process_record"],
            "failure_policy.teardown_requires_process_record",
        ),
    )
    if not policy.fail_fast:
        raise ControlPlaneConfigError("fail_fast must be true")
    if policy.allow_fallback:
        raise ControlPlaneConfigError("allow_fallback must be false")
    if not policy.teardown_requires_process_record:
        raise ControlPlaneConfigError("teardown_requires_process_record must be true")
    return policy


def _validate_component_graph(components: list[ControlPlaneComponent]) -> None:
    seen: set[str] = set()
    for component in components:
        if component.name in seen:
            raise ControlPlaneConfigError(f"duplicate component: {component.name}")
        for dependency in component.depends_on:
            if dependency not in seen:
                raise ControlPlaneConfigError("dependency must appear before component")
        seen.add(component.name)


def _validate_component_refs(run: MonarchControlPlaneRun) -> None:
    names = {component.name for component in run.components}
    for component in run.components:
        if component.upstream_ref is None:
            continue
        upstream_name, _ = _split_component_ref(component.upstream_ref)
        if upstream_name not in names:
            raise ControlPlaneConfigError("component ref names unknown component")
        if upstream_name not in component.depends_on:
            raise ControlPlaneConfigError("component ref must name a declared dependency")


def _split_component_ref(ref: str) -> tuple[str, str]:
    ref = _require_component_ref(ref, "component ref")
    suffix = ref[len(_COMPONENT_REF_PREFIX) :]
    try:
        component_name, key = suffix.split("/", 1)
    except ValueError as error:
        raise ControlPlaneConfigError(f"component ref must include component and key: {ref}") from error
    if not component_name or not key:
        raise ControlPlaneConfigError(f"component ref must include component and key: {ref}")
    return component_name, key


def _require_mapping(data: object, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ControlPlaneConfigError(f"{field} must be a mapping")
    return data


def _reject_unknown_fields(
    mapping: dict[str, object],
    allowed: set[str],
    field: str,
    *,
    required: set[str] | None = None,
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ControlPlaneConfigError(f"unknown field in {field}: {unknown[0]}")
    required = required or allowed
    missing = sorted(required - set(mapping))
    if missing:
        raise ControlPlaneConfigError(f"missing field in {field}: {missing[0]}")


def _require_schema_version(value: object, field: str) -> None:
    if value != 1:
        raise ControlPlaneConfigError(f"{field}.schema_version must be 1")


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ControlPlaneConfigError(f"{field} must be a string")
    return value


def _require_non_empty_str(value: object, field: str) -> str:
    text = _require_str(value, field)
    if text == "":
        raise ControlPlaneConfigError(f"{field} must be non-empty")
    return text


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ControlPlaneConfigError(f"{field} must be a boolean")
    return value


def _require_one_of(value: object, allowed: set[str], field: str) -> str:
    text = _require_non_empty_str(value, field)
    if text not in allowed:
        raise ControlPlaneConfigError(f"{field} must be one of {sorted(allowed)}")
    return text


def _require_portable_ref(value: object, field: str) -> str:
    ref = _require_non_empty_str(value, field)
    if not ref.startswith(_PORTABLE_REF_PREFIXES):
        raise ControlPlaneConfigError(f"{field} must use a portable ref")
    return ref


def _require_local_environment_ref(value: object, field: str) -> str:
    ref = _require_non_empty_str(value, field)
    if not ref.startswith(_LOCAL_ENVIRONMENT_REF_PREFIXES):
        raise ControlPlaneConfigError(f"{field} must use local-env://")
    return ref


def _require_component_ref(value: object, field: str) -> str:
    ref = _require_non_empty_str(value, field)
    if not ref.startswith(_COMPONENT_REF_PREFIX):
        raise ControlPlaneConfigError(f"{field} must use component://")
    return ref


def _portable_ref_mapping(value: object, field: str) -> dict[str, str]:
    mapping = _string_mapping(value, field)
    for key, item in mapping.items():
        _require_portable_ref(item, f"{field}.{key}")
    return mapping


def _string_mapping(value: object, field: str) -> dict[str, str]:
    mapping = _require_mapping(value, field)
    for key, item in mapping.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ControlPlaneConfigError(f"{field} must map strings to strings")
    return dict(mapping)


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ControlPlaneConfigError(f"{field} must be a list")
    for item in value:
        if not isinstance(item, str) or item == "":
            raise ControlPlaneConfigError(f"{field} must contain non-empty strings")
    return list(value)


def _phase_component(phase: str) -> str | None:
    if ":" not in phase:
        return None
    return phase.split(":", 1)[1]


def _copy_state(state: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {name: dict(values) for name, values in state.items()}
