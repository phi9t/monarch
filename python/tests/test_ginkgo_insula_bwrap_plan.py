from __future__ import annotations

from pathlib import Path

import pytest

from ginkgo.insula.bwrap_plan import build_bwrap_argv
from ginkgo.insula.bwrap_plan import emit_plan
from ginkgo.insula.bwrap_plan import validate_plan
from ginkgo.insula.artifacts import write_invocation_artifacts
from ginkgo.insula.executor import execute_invocation
from ginkgo.insula.local_environment import load_local_environment
from ginkgo.insula.materialize import materialize_invocation
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import invocation_spec_from_mapping
from test_ginkgo_insula_materialize import write_local_env
from test_ginkgo_insula_schema import VALID_INVOCATION


def materialized(tmp_path: Path):
    env = load_local_environment(write_local_env(tmp_path))
    spec = invocation_spec_from_mapping(VALID_INVOCATION)
    return materialize_invocation(
        spec=spec,
        local_environment=env,
        invocation_id="run-1",
        compatibility={"adapter": "unit-test"},
    )


def test_emit_plan_preserves_materialized_network_and_gpu(tmp_path: Path) -> None:
    env = load_local_environment(write_local_env(tmp_path))
    spec_data = {
        **VALID_INVOCATION,
        "network": "private",
        "gpu": "none",
    }
    spec = invocation_spec_from_mapping(spec_data)
    invocation = materialize_invocation(
        spec=spec,
        local_environment=env,
        invocation_id="run-private",
        compatibility={"adapter": "unit-test"},
    )

    plan = emit_plan(invocation)
    argv = build_bwrap_argv(invocation)

    assert plan.network == "private"
    assert plan.gpu == "none"
    assert "--share-net" not in argv


def test_build_bwrap_argv_contains_rootfs_mounts_env_and_command(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    argv = build_bwrap_argv(invocation)

    assert argv[0] == "bwrap"
    assert argv[:3] == ["bwrap", "--ro-bind", invocation.rootfs_path]
    assert "/" in argv
    assert "--proc" in argv
    assert _ro_bind_sandboxes(argv)["/sys"] == "/sys"
    assert "--tmpfs" in argv
    assert "--dev" in argv
    assert "--dir" in argv
    assert "--unshare-all" in argv
    assert "--share-net" in argv
    assert "--die-with-parent" in argv
    assert "--clearenv" in argv
    assert "--chdir" in argv
    assert "/workspace/monarch" in argv
    assert "--ro-bind" in argv
    assert invocation.repo_root in argv
    assert "--bind" in argv
    assert str(tmp_path / "run" / "qwen3") in argv
    assert "--setenv" in argv
    assert "CUDA_VISIBLE_DEVICES" in argv
    assert "--" in argv
    assert argv[-3:] == ["python3", "-c", "print('ok')"]


def test_build_bwrap_argv_creates_writable_bind_sandbox_destinations(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    argv = build_bwrap_argv(invocation)

    bind_index = argv.index("--bind")
    assert argv[bind_index + 2] == "/run/glm52"
    assert _option_value_pairs(argv, "--tmpfs")["/run"] < bind_index
    assert _option_value_pairs(argv, "--dir")["/run/glm52"] < bind_index


def test_build_bwrap_argv_creates_nested_writable_bind_parents(tmp_path: Path) -> None:
    env = load_local_environment(write_local_env(tmp_path))
    spec_data = {
        **VALID_INVOCATION,
        "binds": [
            {
                "name": "cache",
                "host": "cache://qwen3-cpu",
                "sandbox": "/cache/glm52",
                "mode": "rw",
                "create": True,
                "required": True,
            }
        ],
    }
    invocation = materialize_invocation(
        spec=invocation_spec_from_mapping(spec_data),
        local_environment=env,
        invocation_id="run-cache",
        compatibility={"adapter": "unit-test"},
    )

    argv = build_bwrap_argv(invocation)

    bind_index = argv.index("--bind")
    assert argv[bind_index + 2] == "/cache/glm52"
    assert _option_value_pairs(argv, "--tmpfs")["/cache"] < bind_index
    assert _option_value_pairs(argv, "--dir")["/cache/glm52"] < bind_index


def test_emit_and_validate_plan(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    plan = emit_plan(invocation)
    result = validate_plan(invocation, plan)

    assert result["status"] == "passed"
    assert plan.schema_version == invocation.schema_version
    assert plan.invocation_id == "run-1"
    assert plan.rootfs_path == invocation.rootfs_path
    assert plan.recipe_sha256 == invocation.rootfs_recipe_sha256
    assert plan.cwd == "/workspace/monarch"
    assert plan.network == "share-net"
    assert plan.gpu == "nvidia-if-present"
    assert plan.env == {"CUDA_VISIBLE_DEVICES": "0"}
    assert plan.command_argv == ["python3", "-c", "print('ok')"]
    assert {mount["sandbox"] for mount in plan.mounts} >= {
        "/",
        "/sys",
        "/workspace/monarch",
        "/run/glm52",
    }


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("rootfs_path", "/different/rootfs", "rootfs path mismatch"),
        ("recipe_sha256", "different-recipe", "recipe sha256 mismatch"),
        ("cwd", "/tmp", "cwd mismatch"),
        ("env", {"CUDA_VISIBLE_DEVICES": "1"}, "env mismatch"),
        ("command_argv", ["python3", "-c", "print('bad')"], "command argv mismatch"),
        ("bwrap_argv_sha256", "0" * 64, "bwrap argv digest mismatch"),
    ],
)
def test_validate_plan_rejects_drift(
    tmp_path: Path, field: str, value: object, match: str
) -> None:
    invocation = materialized(tmp_path)
    plan = emit_plan(invocation)
    drifted = plan.__class__(**{**plan.__dict__, field: value})

    with pytest.raises(InsulaConfigError, match=match):
        validate_plan(invocation, drifted)


def test_validate_plan_rejects_mount_drift(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    plan = emit_plan(invocation)
    drifted_mounts = [
        {**mount, "mode": "rw"} if mount["sandbox"] == "/" else mount
        for mount in plan.mounts
    ]
    drifted = plan.__class__(**{**plan.__dict__, "mounts": drifted_mounts})

    with pytest.raises(InsulaConfigError, match="mount mismatch for /"):
        validate_plan(invocation, drifted)


def test_write_invocation_artifacts(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)
    paths = write_invocation_artifacts(invocation)

    assert Path(paths["materialized"]).is_file()
    assert Path(paths["argv"]).is_file()
    assert Path(paths["env"]).is_file()
    assert Path(paths["plan"]).is_file()
    assert Path(paths["validation"]).is_file()
    assert Path(paths["stdout"]).is_file()
    assert Path(paths["stderr"]).is_file()


def test_execute_invocation_with_fake_runner_writes_result(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)

    def fake_run(argv, *, stdout, stderr, env):
        stdout.write(b"ok\n")
        return 0

    result = execute_invocation(invocation, run=fake_run)

    assert result.status == "passed"
    assert result.returncode == 0
    assert Path(result.stdout_path).read_text() == "ok\n"
    assert Path(result.stderr_path).is_file()
    assert Path(invocation.artifacts["result"]).is_file()


def test_execute_invocation_marks_nonzero_fake_runner_failed(tmp_path: Path) -> None:
    invocation = materialized(tmp_path)

    def fake_run(argv, *, stdout, stderr, env):
        stderr.write(b"bad\n")
        return 19

    result = execute_invocation(invocation, run=fake_run)

    assert result.status == "failed"
    assert result.returncode == 19
    assert Path(result.stderr_path).read_text() == "bad\n"


def _option_value_pairs(argv: list[str], option: str) -> dict[str, int]:
    return {
        argv[index + 1]: index
        for index, arg in enumerate(argv[:-1])
        if arg == option
    }


def _ro_bind_sandboxes(argv: list[str]) -> dict[str, str]:
    return {
        argv[index + 2]: argv[index + 1]
        for index, arg in enumerate(argv[:-2])
        if arg == "--ro-bind"
    }
