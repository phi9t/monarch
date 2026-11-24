from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import invocation_spec_from_mapping
from ginkgo.insula.schema import invocation_spec_to_mapping
from ginkgo.insula.schema import load_invocation_spec
from ginkgo.insula.schema import write_invocation_spec


VALID_INVOCATION = {
    "schema_version": 1,
    "name": "qwen3-sglang",
    "rootfs_ref": "rootfs://monarch-default",
    "repo": {
        "name": "repo",
        "host": "repo://",
        "sandbox": "/workspace/monarch",
        "mode": "ro",
        "create": False,
        "required": True,
    },
    "binds": [
        {
            "name": "run",
            "host": "run://qwen3",
            "sandbox": "/run/glm52",
            "mode": "rw",
            "create": True,
            "required": True,
        }
    ],
    "environment": {
        "clear": True,
        "values": {"CUDA_VISIBLE_DEVICES": "0"},
        "inherit_allowlist": ["TERM"],
    },
    "command": {
        "cwd": "/workspace/monarch",
        "argv": ["python3", "-c", "print('ok')"],
    },
    "artifacts": {
        "root": "run://qwen3/insula",
        "stdout": "run://qwen3/logs/stdout.log",
        "stderr": "run://qwen3/logs/stderr.log",
        "plan": "run://qwen3/insula/plan.yaml",
        "result": "run://qwen3/insula/result.json",
    },
    "network": "share-net",
    "gpu": "nvidia-if-present",
    "die_with_parent": True,
    "unshare_all": True,
}


def test_invocation_spec_round_trips(tmp_path: Path) -> None:
    spec = invocation_spec_from_mapping(VALID_INVOCATION)
    path = tmp_path / "insula.yaml"

    write_invocation_spec(spec, path)
    loaded = load_invocation_spec(path)

    assert invocation_spec_to_mapping(loaded) == invocation_spec_to_mapping(spec)


def test_invocation_spec_rejects_unknown_fields() -> None:
    data = dict(VALID_INVOCATION)
    data["unexpected"] = True

    with pytest.raises(InsulaConfigError, match="unknown field"):
        invocation_spec_from_mapping(data)


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("repo", "host"), "/data02/repo", "portable host paths must use logical refs"),
        (("repo", "sandbox"), "workspace/monarch", "sandbox path must be absolute"),
        (("command", "argv"), [], "command.argv must be non-empty"),
        (("environment", "clear"), False, "environment.clear must be true"),
        (("binds", 0, "mode"), "maybe", "bind mode must be one of"),
        (("rootfs_ref",), "repo://rootfs", "rootfs_ref must use rootfs://"),
        (
            ("artifacts", "root"),
            "/tmp/insula",
            "portable host paths must use logical refs",
        ),
    ],
)
def test_invocation_spec_rejects_invalid_values(
    path: tuple[object, ...], value: object, match: str
) -> None:
    data = yaml.safe_load(yaml.safe_dump(VALID_INVOCATION))
    cursor = data
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value

    with pytest.raises(InsulaConfigError, match=match):
        invocation_spec_from_mapping(data)
