from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import InsulaLocalEnvironment


_LOCAL_ENVIRONMENT_FIELDS = {
    "schema_version",
    "repo",
    "rootfs",
    "cache",
    "temp",
    "run",
    "results",
    "shared_memory",
    "gpu",
}


def load_local_environment(path: Path) -> InsulaLocalEnvironment:
    with path.open() as f:
        data = yaml.safe_load(f)
    return local_environment_from_mapping(data)


def local_environment_from_mapping(data: object) -> InsulaLocalEnvironment:
    mapping = _require_mapping(data, "local environment")
    _reject_unknown_fields(mapping, _LOCAL_ENVIRONMENT_FIELDS, "local environment")
    if mapping["schema_version"] != 1:
        raise InsulaConfigError("local environment.schema_version must be 1")

    rootfs = _string_mapping(mapping["rootfs"], "rootfs")
    for name, path in rootfs.items():
        _require_absolute_path(path, f"rootfs.{name}")

    repo = _require_str(mapping["repo"], "repo")
    cache = _require_str(mapping["cache"], "cache")
    temp = _require_str(mapping["temp"], "temp")
    run = _require_str(mapping["run"], "run")
    results = _require_str(mapping["results"], "results")
    for field, path in (
        ("repo", repo),
        ("cache", cache),
        ("temp", temp),
        ("run", run),
        ("results", results),
    ):
        _require_absolute_path(path, field)

    shared_memory = _string_mapping(mapping["shared_memory"], "shared_memory")
    if "host_path" in shared_memory:
        _require_absolute_path(shared_memory["host_path"], "shared_memory.host_path")
    if shared_memory.get("sandbox_path") not in {None, "/dev/shm"}:
        raise InsulaConfigError("shared_memory.sandbox_path must be /dev/shm")

    return InsulaLocalEnvironment(
        schema_version=1,
        repo=repo,
        rootfs=rootfs,
        cache=cache,
        temp=temp,
        run=run,
        results=results,
        shared_memory=shared_memory,
        gpu=_string_mapping(mapping["gpu"], "gpu"),
    )


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


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise InsulaConfigError(f"{field} must be a string")
    return value


def _string_mapping(value: object, field: str) -> dict[str, str]:
    mapping = _require_mapping(value, field)
    for key, item in mapping.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise InsulaConfigError(f"{field} must map strings to strings")
    return dict(mapping)


def _require_absolute_path(path: str, field: str) -> None:
    if not Path(path).is_absolute():
        raise InsulaConfigError(f"{field} must be an absolute path")
