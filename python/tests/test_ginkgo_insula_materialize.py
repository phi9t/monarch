from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ginkgo.insula.local_environment import load_local_environment
from ginkgo.insula.materialize import materialize_invocation
from ginkgo.insula.refs import resolve_path_ref
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import invocation_spec_from_mapping
from test_ginkgo_insula_schema import VALID_INVOCATION


def write_local_env(tmp_path: Path) -> Path:
    data = {
        "schema_version": 1,
        "repo": str(tmp_path / "repo"),
        "rootfs": {"monarch-default": str(tmp_path / "rootfs")},
        "cache": str(tmp_path / "cache"),
        "temp": str(tmp_path / "temp"),
        "run": str(tmp_path / "run"),
        "results": str(tmp_path / "results"),
        "shared_memory": {
            "mode": "host_path",
            "host_path": str(tmp_path / "shm"),
            "sandbox_path": "/dev/shm",
        },
        "gpu": {"mode": "nvidia", "devices": "0"},
    }
    path = tmp_path / "local-env.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_local_environment_resolves_refs(tmp_path: Path) -> None:
    env = load_local_environment(write_local_env(tmp_path))

    assert resolve_path_ref(env, "repo://ginkgo") == str(tmp_path / "repo" / "ginkgo")
    assert resolve_path_ref(env, "repo:///ginkgo") == str(tmp_path / "repo" / "ginkgo")
    assert resolve_path_ref(env, "cache://qwen3") == str(tmp_path / "cache" / "qwen3")
    assert resolve_path_ref(env, "temp://run-a") == str(tmp_path / "temp" / "run-a")
    assert resolve_path_ref(env, "run://run-a/logs") == str(tmp_path / "run" / "run-a" / "logs")
    assert resolve_path_ref(env, "results://run-a") == str(tmp_path / "results" / "run-a")
    assert resolve_path_ref(env, "rootfs://monarch-default") == str(tmp_path / "rootfs")


def test_local_environment_rejects_relative_paths(tmp_path: Path) -> None:
    path = write_local_env(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["cache"] = "relative-cache"
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InsulaConfigError, match="cache must be an absolute path"):
        load_local_environment(path)


def test_local_environment_rejects_invalid_shared_memory(tmp_path: Path) -> None:
    path = write_local_env(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["shared_memory"]["host_path"] = "relative-shm"
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InsulaConfigError, match="shared_memory.host_path must be an absolute path"):
        load_local_environment(path)

    data["shared_memory"]["host_path"] = str(tmp_path / "shm")
    data["shared_memory"]["sandbox_path"] = "/tmp/shm"
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InsulaConfigError, match="shared_memory.sandbox_path must be /dev/shm"):
        load_local_environment(path)


def test_resolve_path_ref_rejects_unknown_ref(tmp_path: Path) -> None:
    env = load_local_environment(write_local_env(tmp_path))

    with pytest.raises(InsulaConfigError, match="unsupported path ref"):
        resolve_path_ref(env, "unknown://x")


def test_materialize_invocation_resolves_all_host_paths(tmp_path: Path) -> None:
    local_env = load_local_environment(write_local_env(tmp_path))
    spec = invocation_spec_from_mapping(VALID_INVOCATION)

    materialized = materialize_invocation(
        spec=spec,
        local_environment=local_env,
        invocation_id="run-1",
        compatibility={"adapter": "unit-test"},
    )

    assert materialized.invocation_id == "run-1"
    assert materialized.rootfs_path == str(tmp_path / "rootfs")
    assert materialized.repo_root == str(tmp_path / "repo")
    assert materialized.cache_root == str(tmp_path / "cache")
    assert materialized.command.cwd == "/workspace/monarch"
    assert materialized.command.argv == ["python3", "-c", "print('ok')"]
    assert materialized.binds[0].host == str(tmp_path / "repo")
    assert materialized.binds[1].host == str(tmp_path / "run" / "qwen3")
    assert materialized.artifacts["stdout"] == str(
        tmp_path / "run" / "qwen3" / "logs" / "stdout.log"
    )
    assert materialized.compatibility["adapter"] == "unit-test"
    assert not _contains_ref(materialized.rootfs_path)
    assert not any(_contains_ref(bind.host) for bind in materialized.binds)
    assert not any(_contains_ref(path) for path in materialized.artifacts.values())


def _contains_ref(value: str) -> bool:
    return "://" in value
