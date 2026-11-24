# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "glm52_bwrap_task_runner.py"
)
spec = importlib.util.spec_from_file_location("glm52_bwrap_task_runner", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_bwrap_task_runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_bwrap_task_runner
spec.loader.exec_module(glm52_bwrap_task_runner)

TaskSpec = glm52_bwrap_task_runner.TaskSpec
build_bwrap_command = glm52_bwrap_task_runner.build_bwrap_command
prepare_task_root = glm52_bwrap_task_runner.prepare_task_root
record_bwrap_task = glm52_bwrap_task_runner.record_bwrap_task
run_codegen_smoke = glm52_bwrap_task_runner.run_codegen_smoke
validate_smoke_artifact = glm52_bwrap_task_runner.validate_smoke_artifact


def test_prepare_task_root_creates_isolated_layout(tmp_path: Path) -> None:
    source_input = tmp_path / "source-input"
    source_input.mkdir()
    (source_input / "prompt.txt").write_text("fix slugify\n")
    task_spec = TaskSpec(
        run_id="run-1",
        task_id="task-1",
        input_dir=source_input,
        timeout_seconds=30,
        network=False,
        gpu=False,
        command=["python", "-c", "print('ok')"],
        environment_allowlist=["GLM52_RESPONSES_BASE_URL"],
    )

    prepared = prepare_task_root(tmp_path / "run", task_spec)

    assert sorted(path.name for path in prepared.task_root.iterdir()) == [
        "input",
        "output",
        "task.json",
        "tmp",
        "work",
    ]
    assert (prepared.input_dir / "prompt.txt").read_text() == "fix slugify\n"
    task_payload = json.loads((prepared.task_root / "task.json").read_text())
    assert task_payload["run_id"] == "run-1"
    assert task_payload["task_id"] == "task-1"
    assert task_payload["network"] is False
    assert task_payload["gpu"] is False
    assert task_payload["input_dir"] == str(source_input)
    assert task_payload["task_input_dir"] == str(prepared.input_dir)
    assert task_payload["work_dir"] == str(prepared.work_dir)
    assert task_payload["output_dir"] == str(prepared.output_dir)
    assert task_payload["tmp_dir"] == str(prepared.tmp_dir)


def test_prepare_task_root_rejects_invalid_environment_allowlist(
    tmp_path: Path,
) -> None:
    task_spec = TaskSpec(
        run_id="run-1",
        task_id="task-1",
        input_dir=None,
        timeout_seconds=30,
        network=False,
        gpu=False,
        command=["python", "-c", "print('ok')"],
        environment_allowlist=["GLM52_RESPONSES_BASE_URL", "BAD-NAME"],
    )

    with pytest.raises(
        glm52_bwrap_task_runner.BwrapTaskError,
        match="environment_allowlist contains invalid variable name",
    ):
        prepare_task_root(tmp_path / "run", task_spec)

    assert not (tmp_path / "run" / "run-1" / "task-1" / "task.json").exists()


@pytest.mark.parametrize(
    ("run_id", "task_id"),
    [
        ("../escape", "task-1"),
        ("run-1", "../escape"),
        ("..", "task-1"),
        ("run-1", ".."),
        (".", "task-1"),
        ("run-1", "."),
    ],
)
def test_prepare_task_root_rejects_path_like_task_identifiers(
    tmp_path: Path,
    run_id: str,
    task_id: str,
) -> None:
    task_spec = TaskSpec(
        run_id=run_id,
        task_id=task_id,
        input_dir=None,
        timeout_seconds=30,
        network=False,
        gpu=False,
        command=["python", "-c", "print('ok')"],
        environment_allowlist=[],
    )

    with pytest.raises(
        glm52_bwrap_task_runner.BwrapTaskError,
        match="run_id and task_id must be simple identifiers",
    ):
        prepare_task_root(tmp_path / "run", task_spec)

    assert list(tmp_path.rglob("task.json")) == []


def test_bwrap_command_defaults_to_no_network_no_gpu_and_read_only_checkout(
    tmp_path: Path,
) -> None:
    task_spec = TaskSpec(
        run_id="run-1",
        task_id="task-1",
        input_dir=None,
        timeout_seconds=30,
        network=False,
        gpu=False,
        command=["python", "-c", "print('ok')"],
        environment_allowlist=[],
    )
    prepared = prepare_task_root(tmp_path / "run", task_spec)

    command = build_bwrap_command(
        repo_root=Path("/repo/monarch"),
        rootfs=Path("/repo/monarch/scripts/rootfs/rootfs"),
        prepared=prepared,
    )

    assert "--share-net" not in command
    assert "--dev-bind" not in command
    checkout_index = command.index("/workspace/monarch")
    assert command[checkout_index - 2 : checkout_index + 1] == [
        "--ro-bind",
        "/repo/monarch",
        "/workspace/monarch",
    ]
    assert command[command.index("--chdir") + 1] == "/tmp/glm52-task/work"
    assert command[-3:] == ["python", "-c", "print('ok')"]


def test_record_bwrap_task_appends_cleanup_ledger_entry(tmp_path: Path) -> None:
    cleanup_path = tmp_path / "cleanup.json"
    task_root = tmp_path / "run" / "task-1"

    record_bwrap_task(
        cleanup_path,
        run_id="run-1",
        pid=12345,
        task_root=task_root,
    )

    payload = json.loads(cleanup_path.read_text())
    assert payload["schema_version"] == 1
    assert payload["run_id"] == "run-1"
    assert payload["bwrap_tasks"] == [
        {
            "pid": 12345,
            "task_root": str(task_root),
            "command_contains": "glm52_bwrap_task_runner",
        }
    ]


def test_validate_smoke_artifact_requires_checkout_denial_and_no_network() -> None:
    validate_smoke_artifact(
        {
            "task_id": "task-1",
            "work_write": "pass",
            "output_write": "pass",
            "checkout_write": "denied",
            "network": "denied",
        }
    )


def test_codegen_smoke_summary_includes_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()

    def fake_run_task(**_kwargs: object) -> dict[str, object]:
        task_root = tmp_path / "bwrap" / "run-1" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "codegen-artifact.json").write_text(
            json.dumps(
                {
                    "checkout_write": "denied",
                    "network": "denied",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                        "scoring": "fixture_harness",
                }
            )
        )
        return {
            "task_root": str(task_root),
            "returncode": 0,
            "duration_seconds": 1.234,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(glm52_bwrap_task_runner, "run_task", fake_run_task)
    args = Namespace(
        repo_root=tmp_path,
        rootfs=rootfs,
        run_id="run-1",
        task_id="humaneval-001",
        suite="humaneval",
        case_id="HumanEval/0",
        cleanup_ledger=tmp_path / "cleanup.json",
        base_dir=tmp_path / "bwrap",
        timeout_seconds=30,
    )

    exit_code = run_codegen_smoke(args)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["duration_seconds"] == 1.234


def test_codegen_smoke_scores_supplied_completion_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    completion_text = "def add(a, b):\n    return a + b\n"

    def fake_run_task(**kwargs: object) -> dict[str, object]:
        spec = kwargs["spec"]
        input_dir = spec.input_dir
        assert input_dir is not None
        assert (input_dir / "completion.py").read_text() == completion_text
        task_root = tmp_path / "bwrap" / "run-1" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "codegen-artifact.json").write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "checkout_write": "denied",
                    "network": "denied",
                    "passed": True,
                    "stdout": "fixture passed\n",
                    "stderr": "",
                    "generated_code": completion_text,
                    "scoring": "fixture_harness",
                }
            )
        )
        return {
            "task_root": str(task_root),
            "returncode": 0,
            "duration_seconds": 0.25,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(glm52_bwrap_task_runner, "run_task", fake_run_task)
    args = Namespace(
        repo_root=tmp_path,
        rootfs=rootfs,
        run_id="run-1",
        task_id="humaneval-001",
        suite="humaneval",
        case_id="HumanEval/0",
        completion_text=completion_text,
        cleanup_ledger=tmp_path / "cleanup.json",
        base_dir=tmp_path / "bwrap",
        timeout_seconds=30,
    )

    exit_code = run_codegen_smoke(args)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["artifact"].endswith("codegen-artifact.json")


def test_codegen_smoke_reports_fixture_failure_as_scoreable_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()

    def fake_run_task(**_kwargs: object) -> dict[str, object]:
        task_root = tmp_path / "bwrap" / "run-1" / "humaneval-001"
        output_dir = task_root / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "codegen-artifact.json").write_text(
            json.dumps(
                {
                    "suite": "humaneval",
                    "case_id": "HumanEval/0",
                    "checkout_write": "denied",
                    "network": "denied",
                    "passed": False,
                    "stdout": "",
                    "stderr": "AssertionError: -1 != 3\n",
                    "generated_code": "def add(a, b):\n    return a - b\n",
                    "scoring": "fixture_harness",
                }
            )
        )
        return {
            "task_root": str(task_root),
            "returncode": 0,
            "duration_seconds": 0.25,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(glm52_bwrap_task_runner, "run_task", fake_run_task)
    args = Namespace(
        repo_root=tmp_path,
        rootfs=rootfs,
        run_id="run-1",
        task_id="humaneval-001",
        suite="humaneval",
        case_id="HumanEval/0",
        completion_text="def add(a, b):\n    return a - b\n",
        cleanup_ledger=tmp_path / "cleanup.json",
        base_dir=tmp_path / "bwrap",
        timeout_seconds=30,
    )

    exit_code = run_codegen_smoke(args)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["passed"] is False
