from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ginkgo.insula import cli
from ginkgo.insula.bwrap_plan import emit_plan
from ginkgo.insula.cli import build_parser
from ginkgo.insula.cli import run_insula_from_args
from ginkgo.insula.compatibility import EnterRootfsCompatArgs
from ginkgo.insula.compatibility import enter_rootfs_compat
from ginkgo.insula.local_environment import load_local_environment
from ginkgo.insula.materialize import materialize_invocation
from ginkgo.insula.rootfs_lifecycle import prepare_rootfs
from ginkgo.insula.schema import invocation_spec_from_mapping
from test_ginkgo_insula_materialize import write_local_env
from test_ginkgo_insula_schema import VALID_INVOCATION


def test_cli_exposes_required_commands() -> None:
    parser = build_parser()
    subcommands = parser._subparsers._group_actions[0].choices

    assert "run" in subcommands
    assert "emit-plan" in subcommands
    assert "monarch-run" in subcommands
    assert "enter-rootfs-compat" in subcommands


def test_prepare_rootfs_accepts_existing_rootfs_with_contract(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    contract = rootfs / "etc" / "monarch-rootfs-contract"
    contract.parent.mkdir(parents=True)
    contract.write_text("MONARCH_ROOTFS_RECIPE_SHA256=" + "0" * 64 + "\n")
    (rootfs / "bin").mkdir()
    (rootfs / "bin" / "bash").write_text("#!/bin/sh\n")
    (rootfs / "bin" / "bash").chmod(0o755)

    evidence = prepare_rootfs(
        rootfs=rootfs, expected_recipe=None, build=False, verify=False
    )

    assert evidence["status"] == "ready"
    assert evidence["rootfs"] == str(rootfs)
    assert evidence["recipe_sha256"] == "0" * 64


def test_emit_plan_cli_writes_materialized_plan(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    env_path = write_local_env(tmp_path)
    output_path = tmp_path / "plan.yaml"
    spec_path.write_text(yaml.safe_dump(VALID_INVOCATION))

    code = run_insula_from_args(
        [
            "emit-plan",
            "--spec",
            str(spec_path),
            "--local-environment",
            str(env_path),
            "--invocation-id",
            "run-cli",
            "--output",
            str(output_path),
        ]
    )

    assert code == 0
    data = yaml.safe_load(output_path.read_text())
    assert data["invocation_id"] == "run-cli"
    assert data["cwd"] == "/workspace/monarch"
    assert data["command_argv"] == ["python3", "-c", "print('ok')"]


def test_run_cli_executes_with_fake_runner(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    env_path = write_local_env(tmp_path)
    spec_path.write_text(yaml.safe_dump(VALID_INVOCATION))

    def fake_run(argv, *, stdout, stderr, env):
        stdout.write(b"ran\n")
        return 0

    code = run_insula_from_args(
        [
            "run",
            "--spec",
            str(spec_path),
            "--local-environment",
            str(env_path),
            "--invocation-id",
            "run-cli",
        ],
        run=fake_run,
    )

    assert code == 0
    assert (tmp_path / "run" / "qwen3" / "logs" / "stdout.log").read_text() == "ran\n"
    assert (tmp_path / "run" / "qwen3" / "insula" / "result.json").is_file()


def test_monarch_run_cli_delegates_to_compatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_monarch_run(payload: list[str]) -> int:
        calls.append(payload)
        return 17

    monkeypatch.setattr(cli, "monarch_run", fake_monarch_run)

    assert run_insula_from_args(["monarch-run", "--", "python3", "-c", "print(1)"]) == 17
    assert calls == [["--", "python3", "-c", "print(1)"]]


def test_enter_rootfs_compat_emits_plan_without_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rootfs = tmp_path / "rootfs"
    (rootfs / "bin").mkdir(parents=True)
    (rootfs / "bin" / "bash").write_text("#!/bin/sh\n")
    (rootfs / "etc").mkdir()
    (rootfs / "etc" / "monarch-rootfs-contract").write_text(
        "MONARCH_ROOTFS_RECIPE_SHA256=" + "1" * 64 + "\n"
    )
    plan_path = tmp_path / "plan.yaml"

    monkeypatch.setenv("MONARCH_ROOTFS_EMIT_PLAN_ONLY", "1")
    monkeypatch.setattr("ginkgo.insula.compatibility._preflight_host", lambda: None)
    monkeypatch.setattr("ginkgo.insula.compatibility._recipe_sha256", lambda: "1" * 64)
    monkeypatch.setattr("ginkgo.insula.compatibility._verify_rootfs", lambda _rootfs: None)

    code = enter_rootfs_compat(
        EnterRootfsCompatArgs(
            rootfs=rootfs,
            chdir="docs",
            repo_readonly=True,
            emit_plan=plan_path,
            bind_rw=(),
            payload=("python3", "-c", "print('ok')"),
        )
    )

    assert code == 0
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["rootfs"] == str(rootfs)
    assert plan["cwd"] == "/workspace/monarch/docs"
    assert plan["repo_projection_mode"] == "ro"
    assert plan["inner_argv"] == ["python3", "-c", "print('ok')"]
    assert plan["insula"]["invocation_id"] == "monarch-rootfs-compat"
    assert plan["insula"]["recipe_sha256"] == "1" * 64
    assert len(plan["insula"]["bwrap_argv_sha256"]) == 64
    assert plan["outer_argv"][0] == "bwrap"
    assert "--clearenv" in plan["outer_argv"]
    assert "--" in plan["outer_argv"]
    assert plan["outer_argv"][-3:] == ["python3", "-c", "print('ok')"]


def test_emit_plan_cli_matches_direct_plan(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    env_path = write_local_env(tmp_path)
    output_path = tmp_path / "plan.yaml"
    spec_path.write_text(yaml.safe_dump(VALID_INVOCATION))

    run_insula_from_args(
        [
            "emit-plan",
            "--spec",
            str(spec_path),
            "--local-environment",
            str(env_path),
            "--invocation-id",
            "run-cli",
            "--output",
            str(output_path),
        ]
    )

    data = yaml.safe_load(output_path.read_text())
    invocation = materialize_invocation(
        spec=invocation_spec_from_mapping(VALID_INVOCATION),
        local_environment=load_local_environment(env_path),
        invocation_id="run-cli",
        compatibility={"adapter": "cli"},
    )
    assert data["bwrap_argv_sha256"] == emit_plan(invocation).bwrap_argv_sha256
