import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_CONFIG = REPO_ROOT / "scripts" / "rootfs" / "rootfs_sandbox_config.py"

spec = importlib.util.spec_from_file_location("rootfs_sandbox_config", SANDBOX_CONFIG)
assert spec is not None and spec.loader is not None
sandbox = importlib.util.module_from_spec(spec)
sys.modules["rootfs_sandbox_config"] = sandbox
spec.loader.exec_module(sandbox)

RECIPE = "a" * 64


def test_materialized_sandbox_plan_maps_external_cache_and_target(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    rootfs = tmp_path / "rootfs"
    cache_root = tmp_path / "cache"
    repo_root.mkdir()
    rootfs.mkdir()
    cache_root.mkdir()

    plan = sandbox.materialize_sandbox_plan(
        rootfs=rootfs,
        repo_root=repo_root,
        recipe_sha256=RECIPE,
        cache_root=cache_root,
        cwd="/workspace/monarch",
        repo_projection_mode="rw",
        inner_argv=["python", "-c", "print(1)"],
    )

    mounts = {mount.sandbox_path: mount for mount in plan.mounts}
    assert mounts["/workspace/monarch/scripts/rootfs/cache"].host_path == cache_root
    assert mounts[f"/workspace/monarch/target/bwrap/{RECIPE}"].host_path == (
        cache_root / "target" / "bwrap" / RECIPE
    )
    assert plan.host_layout.cache_root == cache_root
    assert plan.sandbox_layout.cache_root == "/workspace/monarch/scripts/rootfs/cache"
    assert plan.env["CARGO_TARGET_DIR"] == f"/workspace/monarch/target/bwrap/{RECIPE}"


def test_materialized_sandbox_plan_rejects_relative_host_paths(tmp_path: Path) -> None:
    with pytest.raises(sandbox.SandboxConfigError, match="rootfs must be absolute"):
        sandbox.materialize_sandbox_plan(
            rootfs=Path("relative-rootfs"),
            repo_root=tmp_path,
            recipe_sha256=RECIPE,
            cache_root=tmp_path / "cache",
            cwd="/workspace/monarch",
            repo_projection_mode="rw",
            inner_argv=["python"],
        )


def test_materialized_sandbox_plan_rejects_cache_inside_rootfs(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()

    with pytest.raises(sandbox.SandboxConfigError, match="cache_root must not live inside rootfs"):
        sandbox.materialize_sandbox_plan(
            rootfs=rootfs,
            repo_root=tmp_path / "repo",
            recipe_sha256=RECIPE,
            cache_root=rootfs / "cache",
            cwd="/workspace/monarch",
            repo_projection_mode="rw",
            inner_argv=["python"],
        )


def test_bwrap_argv_round_trips_against_materialized_schema(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    rootfs = tmp_path / "rootfs"
    cache_root = tmp_path / "cache"
    repo_root.mkdir()
    rootfs.mkdir()
    cache_root.mkdir()

    plan = sandbox.materialize_sandbox_plan(
        rootfs=rootfs,
        repo_root=repo_root,
        recipe_sha256=RECIPE,
        cache_root=cache_root,
        cwd="/workspace/monarch",
        repo_projection_mode="ro",
        inner_argv=["/bin/bash", "-lc", "true"],
        extra_env={"TERM": "xterm-256color"},
    )

    argv = sandbox.bwrap_argv_from_plan(plan)

    sandbox.validate_bwrap_argv_matches_plan(plan, argv)
    assert argv[0] == "bwrap"
    assert "--ro-bind" in argv
    assert "TERM" in argv


def test_bwrap_argv_validation_rejects_wrong_host_mount(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    rootfs = tmp_path / "rootfs"
    cache_root = tmp_path / "cache"
    repo_root.mkdir()
    rootfs.mkdir()
    cache_root.mkdir()
    plan = sandbox.materialize_sandbox_plan(
        rootfs=rootfs,
        repo_root=repo_root,
        recipe_sha256=RECIPE,
        cache_root=cache_root,
        cwd="/workspace/monarch",
        repo_projection_mode="rw",
        inner_argv=["python"],
    )
    argv = sandbox.bwrap_argv_from_plan(plan)
    wrong_index = argv.index(str(cache_root))
    argv[wrong_index] = str(tmp_path / "wrong-cache")

    with pytest.raises(sandbox.SandboxConfigError, match="mount mismatch"):
        sandbox.validate_bwrap_argv_matches_plan(plan, argv)


@pytest.mark.parametrize(
    "argv, message",
    [
        (["bwrap", "--bind", "/host"], "--bind requires host and sandbox paths"),
        (["bwrap", "--setenv", "NAME"], "--setenv requires a name and value"),
        (["bwrap", "--chdir"], "--chdir requires a path"),
        (["bwrap", "--tmpfs"], "--tmpfs requires a path"),
    ],
)
def test_parse_bwrap_argv_rejects_truncated_options(
    argv: list[str],
    message: str,
) -> None:
    with pytest.raises(sandbox.SandboxConfigError, match=message):
        sandbox.parse_bwrap_argv(argv)
