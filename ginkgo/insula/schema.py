from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class InsulaConfigError(RuntimeError):
    pass


class InsulaExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class InsulaLocalEnvironment:
    schema_version: int
    repo: str
    rootfs: dict[str, str]
    cache: str
    temp: str
    run: str
    results: str
    shared_memory: dict[str, str]
    gpu: dict[str, str]


@dataclass(frozen=True)
class InsulaBindSpec:
    name: str
    host: str
    sandbox: str
    mode: str
    create: bool
    required: bool


@dataclass(frozen=True)
class InsulaEnvironmentSpec:
    clear: bool
    values: dict[str, str]
    inherit_allowlist: list[str]


@dataclass(frozen=True)
class InsulaCommandSpec:
    cwd: str
    argv: list[str]


@dataclass(frozen=True)
class InsulaInvocationSpec:
    schema_version: int
    name: str
    rootfs_ref: str
    repo: InsulaBindSpec
    binds: list[InsulaBindSpec]
    environment: InsulaEnvironmentSpec
    command: InsulaCommandSpec
    artifacts: dict[str, str]
    network: str
    gpu: str
    die_with_parent: bool
    unshare_all: bool


@dataclass(frozen=True)
class MaterializedInsulaInvocation:
    schema_version: int
    invocation_id: str
    name: str
    repo_root: str
    rootfs_path: str
    rootfs_recipe_sha256: str
    cache_root: str
    command: InsulaCommandSpec
    binds: list[InsulaBindSpec]
    environment: dict[str, str]
    bwrap_argv: list[str]
    artifacts: dict[str, str]
    compatibility: dict[str, str]


@dataclass(frozen=True)
class InsulaPlan:
    schema_version: int
    invocation_id: str
    rootfs_path: str
    recipe_sha256: str
    cwd: str
    network: str
    gpu: str
    mounts: list[dict[str, str]]
    env: dict[str, str]
    command_argv: list[str]
    bwrap_argv_sha256: str


@dataclass(frozen=True)
class InsulaExecutionResult:
    schema_version: int
    invocation_id: str
    status: str
    returncode: int
    started_at: str
    completed_at: str
    stdout_path: str
    stderr_path: str
    materialized_path: str
    plan_path: str
    validation_path: str


_INVOCATION_FIELDS = {
    "schema_version",
    "name",
    "rootfs_ref",
    "repo",
    "binds",
    "environment",
    "command",
    "artifacts",
    "network",
    "gpu",
    "die_with_parent",
    "unshare_all",
}
_BIND_FIELDS = {"name", "host", "sandbox", "mode", "create", "required"}
_ENVIRONMENT_FIELDS = {"clear", "values", "inherit_allowlist"}
_COMMAND_FIELDS = {"cwd", "argv"}
_PORTABLE_REF_PREFIXES = ("repo://", "cache://", "temp://", "run://", "results://", "rootfs://")
_BIND_MODES = {"ro", "rw", "dev"}
_NETWORK_MODES = {"share-net", "private"}
_GPU_MODES = {"none", "nvidia-if-present", "nvidia-required"}


def load_invocation_spec(path: Path) -> InsulaInvocationSpec:
    with path.open() as f:
        data = yaml.safe_load(f)
    return invocation_spec_from_mapping(data)


def write_invocation_spec(spec: InsulaInvocationSpec, path: Path) -> None:
    with path.open("w") as f:
        yaml.safe_dump(invocation_spec_to_mapping(spec), f, sort_keys=False)


def invocation_spec_from_mapping(data: object) -> InsulaInvocationSpec:
    mapping = _require_mapping(data, "invocation spec")
    _reject_unknown_fields(mapping, _INVOCATION_FIELDS, "invocation spec")
    _require_schema_version(mapping["schema_version"], "invocation spec")

    rootfs_ref = _require_str(mapping["rootfs_ref"], "rootfs_ref")
    if not rootfs_ref.startswith("rootfs://"):
        raise InsulaConfigError("rootfs_ref must use rootfs://")

    return InsulaInvocationSpec(
        schema_version=1,
        name=_require_non_empty_str(mapping["name"], "name"),
        rootfs_ref=rootfs_ref,
        repo=_bind_spec_from_mapping(mapping["repo"], "repo"),
        binds=_bind_specs_from_sequence(mapping["binds"], "binds"),
        environment=_environment_spec_from_mapping(mapping["environment"]),
        command=_command_spec_from_mapping(mapping["command"]),
        artifacts=_portable_ref_mapping(mapping["artifacts"], "artifacts"),
        network=_require_one_of(mapping["network"], _NETWORK_MODES, "network"),
        gpu=_require_one_of(mapping["gpu"], _GPU_MODES, "gpu"),
        die_with_parent=_require_bool(mapping["die_with_parent"], "die_with_parent"),
        unshare_all=_require_bool(mapping["unshare_all"], "unshare_all"),
    )


def invocation_spec_to_mapping(spec: InsulaInvocationSpec) -> dict[str, object]:
    return {
        "schema_version": spec.schema_version,
        "name": spec.name,
        "rootfs_ref": spec.rootfs_ref,
        "repo": bind_spec_to_mapping(spec.repo),
        "binds": [bind_spec_to_mapping(bind) for bind in spec.binds],
        "environment": environment_spec_to_mapping(spec.environment),
        "command": command_spec_to_mapping(spec.command),
        "artifacts": dict(spec.artifacts),
        "network": spec.network,
        "gpu": spec.gpu,
        "die_with_parent": spec.die_with_parent,
        "unshare_all": spec.unshare_all,
    }


def bind_spec_to_mapping(spec: InsulaBindSpec) -> dict[str, object]:
    return {
        "name": spec.name,
        "host": spec.host,
        "sandbox": spec.sandbox,
        "mode": spec.mode,
        "create": spec.create,
        "required": spec.required,
    }


def environment_spec_to_mapping(spec: InsulaEnvironmentSpec) -> dict[str, object]:
    return {
        "clear": spec.clear,
        "values": dict(spec.values),
        "inherit_allowlist": list(spec.inherit_allowlist),
    }


def command_spec_to_mapping(spec: InsulaCommandSpec) -> dict[str, object]:
    return {
        "cwd": spec.cwd,
        "argv": list(spec.argv),
    }


def _bind_specs_from_sequence(value: object, field: str) -> list[InsulaBindSpec]:
    if not isinstance(value, list):
        raise InsulaConfigError(f"{field} must be a list")
    return [_bind_spec_from_mapping(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _bind_spec_from_mapping(data: object, field: str) -> InsulaBindSpec:
    mapping = _require_mapping(data, field)
    _reject_unknown_fields(mapping, _BIND_FIELDS, field)
    host = _require_str(mapping["host"], f"{field}.host")
    if not host.startswith(_PORTABLE_REF_PREFIXES):
        raise InsulaConfigError("portable host paths must use logical refs")

    sandbox = _require_str(mapping["sandbox"], f"{field}.sandbox")
    _require_absolute_sandbox_path(sandbox)

    mode = _require_str(mapping["mode"], f"{field}.mode")
    if mode not in _BIND_MODES:
        raise InsulaConfigError(f"bind mode must be one of {sorted(_BIND_MODES)}")

    return InsulaBindSpec(
        name=_require_non_empty_str(mapping["name"], f"{field}.name"),
        host=host,
        sandbox=sandbox,
        mode=mode,
        create=_require_bool(mapping["create"], f"{field}.create"),
        required=_require_bool(mapping["required"], f"{field}.required"),
    )


def _environment_spec_from_mapping(data: object) -> InsulaEnvironmentSpec:
    mapping = _require_mapping(data, "environment")
    _reject_unknown_fields(mapping, _ENVIRONMENT_FIELDS, "environment")
    clear = _require_bool(mapping["clear"], "environment.clear")
    if not clear:
        raise InsulaConfigError("environment.clear must be true")
    return InsulaEnvironmentSpec(
        clear=clear,
        values=_string_mapping(mapping["values"], "environment.values"),
        inherit_allowlist=_string_list(mapping["inherit_allowlist"], "environment.inherit_allowlist"),
    )


def _command_spec_from_mapping(data: object) -> InsulaCommandSpec:
    mapping = _require_mapping(data, "command")
    _reject_unknown_fields(mapping, _COMMAND_FIELDS, "command")
    cwd = _require_str(mapping["cwd"], "command.cwd")
    _require_absolute_sandbox_path(cwd)
    argv = _string_list(mapping["argv"], "command.argv")
    if not argv:
        raise InsulaConfigError("command.argv must be non-empty")
    return InsulaCommandSpec(cwd=cwd, argv=argv)


def _require_mapping(data: object, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise InsulaConfigError(f"{field} must be a mapping")
    return data


def _reject_unknown_fields(mapping: dict[str, object], allowed: set[str], field: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise InsulaConfigError(f"unknown field in {field}: {unknown[0]}")
    missing = sorted(allowed - set(mapping))
    if missing:
        raise InsulaConfigError(f"missing field in {field}: {missing[0]}")


def _require_schema_version(value: object, field: str) -> None:
    if value != 1:
        raise InsulaConfigError(f"{field}.schema_version must be 1")


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise InsulaConfigError(f"{field} must be a string")
    return value


def _require_non_empty_str(value: object, field: str) -> str:
    text = _require_str(value, field)
    if text == "":
        raise InsulaConfigError(f"{field} must be non-empty")
    return text


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise InsulaConfigError(f"{field} must be a boolean")
    return value


def _require_one_of(value: object, allowed: set[str], field: str) -> str:
    text = _require_str(value, field)
    if text not in allowed:
        raise InsulaConfigError(f"{field} must be one of {sorted(allowed)}")
    return text


def _require_absolute_sandbox_path(path: str) -> None:
    if not path.startswith("/"):
        raise InsulaConfigError("sandbox path must be absolute")


def _string_mapping(value: object, field: str) -> dict[str, str]:
    mapping = _require_mapping(value, field)
    for key, item in mapping.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise InsulaConfigError(f"{field} must map strings to strings")
    return dict(mapping)


def _portable_ref_mapping(value: object, field: str) -> dict[str, str]:
    mapping = _string_mapping(value, field)
    for item in mapping.values():
        if not item.startswith(_PORTABLE_REF_PREFIXES):
            raise InsulaConfigError("portable host paths must use logical refs")
    return mapping


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise InsulaConfigError(f"{field} must be a list")
    for item in value:
        if not isinstance(item, str) or item == "":
            raise InsulaConfigError(f"{field} must contain non-empty strings")
    return list(value)
