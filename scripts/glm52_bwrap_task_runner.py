#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BWRAP_BASE = Path(".scratch/glm52-local-serving/run/bwrap")
DEFAULT_CLEANUP_BASE = Path(".scratch/glm52-local-serving/run")
DEFAULT_ROOTFS = Path("scripts/rootfs/rootfs")
REPO_MOUNT = Path("/workspace/monarch")
TASK_MOUNT = Path("/tmp/glm52-task")
COMMAND_GUARD = "glm52_bwrap_task_runner"


class BwrapTaskError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskSpec:
    run_id: str
    task_id: str
    input_dir: Path | None
    timeout_seconds: int
    network: bool
    gpu: bool
    command: list[str]
    environment_allowlist: list[str]

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_dir"] = str(self.input_dir) if self.input_dir else None
        return payload


@dataclass(frozen=True)
class PreparedTask:
    spec: TaskSpec
    task_root: Path
    input_dir: Path
    work_dir: Path
    output_dir: Path
    tmp_dir: Path


def prepare_task_root(base_dir: Path, spec: TaskSpec) -> PreparedTask:
    if not spec.run_id or not spec.task_id:
        raise BwrapTaskError("run_id and task_id are required")
    _validate_task_identifier(spec.run_id)
    _validate_task_identifier(spec.task_id)
    if not spec.command:
        raise BwrapTaskError("task command is required")
    if spec.timeout_seconds <= 0:
        raise BwrapTaskError("timeout_seconds must be positive")
    _validate_environment_allowlist(spec.environment_allowlist)

    task_root = base_dir / spec.run_id / spec.task_id
    input_dir = task_root / "input"
    work_dir = task_root / "work"
    output_dir = task_root / "output"
    tmp_dir = task_root / "tmp"

    if task_root.exists():
        shutil.rmtree(task_root)
    for path in (input_dir, work_dir, output_dir, tmp_dir):
        path.mkdir(parents=True, exist_ok=True)

    if spec.input_dir is not None:
        if not spec.input_dir.is_dir():
            raise BwrapTaskError(f"input_dir is not a directory: {spec.input_dir}")
        _copy_tree_contents(spec.input_dir, input_dir)

    task_payload = spec.to_json()
    task_payload.update(
        {
            "task_input_dir": str(input_dir),
            "work_dir": str(work_dir),
            "output_dir": str(output_dir),
            "tmp_dir": str(tmp_dir),
        }
    )
    (task_root / "task.json").write_text(
        json.dumps(task_payload, indent=2, sort_keys=True) + "\n"
    )
    return PreparedTask(
        spec=spec,
        task_root=task_root,
        input_dir=input_dir,
        work_dir=work_dir,
        output_dir=output_dir,
        tmp_dir=tmp_dir,
    )


def _validate_task_identifier(identifier: str) -> None:
    if identifier in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", identifier):
        raise BwrapTaskError("run_id and task_id must be simple identifiers")


def _validate_environment_allowlist(environment_allowlist: list[str]) -> None:
    for name in environment_allowlist:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise BwrapTaskError(
                f"environment_allowlist contains invalid variable name: {name!r}"
            )


def _copy_tree_contents(source: Path, destination: Path) -> None:
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def build_bwrap_command(
    *,
    repo_root: Path,
    rootfs: Path,
    prepared: PreparedTask,
) -> list[str]:
    spec = prepared.spec
    command = [
        "bwrap",
        "--ro-bind",
        str(rootfs),
        "/",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--dev",
        "/dev",
        "--tmpfs",
        "/home",
        "--dir",
        "/home/monarch",
        "--tmpfs",
        str(TASK_MOUNT),
        "--dir",
        str(TASK_MOUNT),
        "--ro-bind",
        str(repo_root),
        str(REPO_MOUNT),
        "--ro-bind",
        str(prepared.input_dir),
        str(TASK_MOUNT / "input"),
        "--bind",
        str(prepared.work_dir),
        str(TASK_MOUNT / "work"),
        "--bind",
        str(prepared.output_dir),
        str(TASK_MOUNT / "output"),
        "--bind",
        str(prepared.tmp_dir),
        str(TASK_MOUNT / "tmp"),
        "--unshare-all",
        "--die-with-parent",
        "--clearenv",
        "--chdir",
        str(TASK_MOUNT / "work"),
        "--setenv",
        "HOME",
        "/home/monarch",
        "--setenv",
        "PATH",
        "/opt/cuda-synth/bin:/opt/cargo/bin:/usr/local/bin:/usr/bin:/bin",
        "--setenv",
        "PYTHONUNBUFFERED",
        "1",
        "--setenv",
        "GLM52_BWRAP_TASK_ROOT",
        str(TASK_MOUNT),
    ]
    if spec.network:
        command.append("--share-net")
        for host_file in (Path("/etc/resolv.conf"), Path("/etc/hosts")):
            if host_file.exists():
                command.extend(["--ro-bind", str(host_file), str(host_file)])
    if spec.gpu:
        command.extend(_gpu_binds())

    for name in spec.environment_allowlist:
        if name in os.environ:
            command.extend(["--setenv", name, os.environ[name]])

    command.extend(spec.command)
    return command


def _gpu_binds() -> list[str]:
    binds: list[str] = []
    for dev in sorted(Path("/dev").glob("nvidia*")):
        binds.extend(["--dev-bind", str(dev), str(dev)])
    return binds


def record_bwrap_task(
    cleanup_path: Path,
    *,
    run_id: str,
    pid: int,
    task_root: Path,
) -> None:
    if cleanup_path.exists():
        payload = json.loads(cleanup_path.read_text())
        if not isinstance(payload, dict):
            raise BwrapTaskError(f"cleanup ledger must be an object: {cleanup_path}")
    else:
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "processes": [],
            "bwrap_tasks": [],
            "containers": [],
            "temp_dirs": [],
            "ports": [],
        }
    payload.setdefault("schema_version", 1)
    payload.setdefault("run_id", run_id)
    payload.setdefault("processes", [])
    payload.setdefault("bwrap_tasks", [])
    payload.setdefault("containers", [])
    payload.setdefault("temp_dirs", [])
    payload.setdefault("ports", [])
    payload["bwrap_tasks"].append(
        {
            "pid": pid,
            "task_root": str(task_root),
            "command_contains": COMMAND_GUARD,
        }
    )
    cleanup_path.parent.mkdir(parents=True, exist_ok=True)
    cleanup_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def run_task(
    *,
    repo_root: Path,
    rootfs: Path,
    base_dir: Path,
    cleanup_path: Path,
    spec: TaskSpec,
) -> dict[str, Any]:
    prepared = prepare_task_root(base_dir, spec)
    command = build_bwrap_command(repo_root=repo_root, rootfs=rootfs, prepared=prepared)
    started_at = time.time()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    record_bwrap_task(
        cleanup_path,
        run_id=spec.run_id,
        pid=process.pid,
        task_root=prepared.task_root,
    )
    try:
        stdout, stderr = process.communicate(timeout=spec.timeout_seconds)
        timed_out = False
    except subprocess.TimeoutExpired:
        process.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        timed_out = True

    result = {
        "run_id": spec.run_id,
        "task_id": spec.task_id,
        "task_root": str(prepared.task_root),
        "returncode": process.returncode,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - started_at, 3),
        "stdout": stdout,
        "stderr": stderr,
    }
    (prepared.output_dir / "task-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


def validate_smoke_artifact(payload: dict[str, Any]) -> None:
    required = {
        "work_write": "pass",
        "output_write": "pass",
        "checkout_write": "denied",
        "network": "denied",
    }
    for key, expected in required.items():
        if payload.get(key) != expected:
            raise BwrapTaskError(
                f"smoke artifact field {key!r} expected {expected!r}, got {payload.get(key)!r}"
            )


def make_smoke_input(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "smoke_payload.py").write_text(
        textwrap.dedent(
            f"""\
            import json
            import socket
            from pathlib import Path

            task_root = Path(__import__("os").environ["GLM52_BWRAP_TASK_ROOT"])
            result = {{"task_id": "{input_dir.parent.name}"}}

            (task_root / "work" / "work.txt").write_text("ok\\n")
            result["work_write"] = "pass"

            (task_root / "output" / "output.txt").write_text("ok\\n")
            result["output_write"] = "pass"

            try:
                Path("/workspace/monarch/.glm52-bwrap-checkout-write").write_text("bad\\n")
            except OSError:
                result["checkout_write"] = "denied"
            else:
                result["checkout_write"] = "allowed"

            try:
                socket.create_connection(("1.1.1.1", 53), timeout=1).close()
            except OSError:
                result["network"] = "denied"
            else:
                result["network"] = "allowed"

            (task_root / "output" / "smoke-artifact.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\\n"
            )
            """
        )
    )


def make_codegen_input(
    input_dir: Path,
    *,
    suite: str,
    case_id: str,
    completion_text: str | None = None,
) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    generated_code = completion_text if completion_text is not None else _default_completion(suite)
    (input_dir / "completion.py").write_text(generated_code)
    (input_dir / "codegen_payload.py").write_text(
        textwrap.dedent(
            f"""\
            import json
            import socket
            import subprocess
            import sys
            from pathlib import Path

            task_root = Path(__import__("os").environ["GLM52_BWRAP_TASK_ROOT"])
            work = task_root / "work"
            output = task_root / "output"
            solution = work / "solution.py"
            test_file = work / "test_solution.py"

            solution.write_text((task_root / "input" / "completion.py").read_text())
            test_file.write_text({json.dumps(_fixture_test_source(suite, case_id))})
            completed = subprocess.run(
                [sys.executable, str(test_file.name)],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=10,
            )

            try:
                Path("/workspace/monarch/.glm52-codegen-checkout-write").write_text("bad\\n")
            except OSError:
                checkout_write = "denied"
            else:
                checkout_write = "allowed"

            try:
                socket.create_connection(("1.1.1.1", 53), timeout=1).close()
            except OSError:
                network = "denied"
            else:
                network = "allowed"

            artifact = {{
                "suite": "{suite}",
                "case_id": "{case_id}",
                "passed": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "generated_code": solution.read_text(),
                "checkout_write": checkout_write,
                "network": network,
                "scoring": "fixture_harness",
            }}
            (output / "codegen-artifact.json").write_text(
                json.dumps(artifact, indent=2, sort_keys=True) + "\\n"
            )
            """
        )
    )


def _default_completion(suite: str) -> str:
    if suite == "mbpp":
        return "def remove_Occ(string, char):\n    return string.replace(char, '', 1)\n"
    return "def add(a, b):\n    return a + b\n"


def _fixture_test_source(suite: str, case_id: str) -> str:
    if suite == "humaneval" and case_id == "HumanEval/0":
        return textwrap.dedent(
            """\
            from solution import add

            import unittest


            class SolutionTest(unittest.TestCase):
                def test_add(self):
                    self.assertEqual(add(1, 2), 3)
                    self.assertEqual(add(-4, 9), 5)


            if __name__ == '__main__':
                unittest.main()
            """
        )
    if suite == "mbpp" and case_id == "MBPP/0":
        return textwrap.dedent(
            """\
            from solution import remove_Occ

            import unittest


            class SolutionTest(unittest.TestCase):
                def test_remove_first_occurrence(self):
                    self.assertEqual(remove_Occ("hello", "l"), "helo")
                    self.assertEqual(remove_Occ("aaaa", "a"), "aaa")
                    self.assertEqual(remove_Occ("abc", "z"), "abc")


            if __name__ == '__main__':
                unittest.main()
            """
        )
    raise BwrapTaskError(f"unsupported codegen fixture case: {suite} {case_id}")


def run_smoke(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    rootfs = Path(args.rootfs).resolve()
    if not rootfs.is_dir():
        raise BwrapTaskError(f"rootfs is not built: {rootfs}")

    smoke_input = DEFAULT_CLEANUP_BASE / "tmp" / args.run_id / args.task_id / "source-input"
    make_smoke_input(smoke_input)
    cleanup_path = Path(args.cleanup_ledger)
    spec = TaskSpec(
        run_id=args.run_id,
        task_id=args.task_id,
        input_dir=smoke_input,
        timeout_seconds=args.timeout_seconds,
        network=False,
        gpu=False,
        command=["python3", str(TASK_MOUNT / "input" / "smoke_payload.py")],
        environment_allowlist=[],
    )
    result = run_task(
        repo_root=repo_root,
        rootfs=rootfs,
        base_dir=Path(args.base_dir),
        cleanup_path=cleanup_path,
        spec=spec,
    )
    artifact_path = Path(result["task_root"]) / "output" / "smoke-artifact.json"
    if result["returncode"] != 0:
        raise BwrapTaskError(f"bwrap smoke task failed: {result['stderr']}")
    artifact = json.loads(artifact_path.read_text())
    validate_smoke_artifact(artifact)
    summary = {
        "status": "pass",
        "run_id": args.run_id,
        "task_id": args.task_id,
        "artifact": str(artifact_path),
        "cleanup_ledger": str(cleanup_path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def run_codegen_smoke(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    rootfs = Path(args.rootfs).resolve()
    if not rootfs.is_dir():
        raise BwrapTaskError(f"rootfs is not built: {rootfs}")

    source_input = DEFAULT_CLEANUP_BASE / "tmp" / args.run_id / args.task_id / "source-input"
    make_codegen_input(
        source_input,
        suite=args.suite,
        case_id=args.case_id,
        completion_text=getattr(args, "completion_text", None),
    )
    cleanup_path = Path(args.cleanup_ledger)
    spec = TaskSpec(
        run_id=args.run_id,
        task_id=args.task_id,
        input_dir=source_input,
        timeout_seconds=args.timeout_seconds,
        network=False,
        gpu=False,
        command=["python3", str(TASK_MOUNT / "input" / "codegen_payload.py")],
        environment_allowlist=[],
    )
    result = run_task(
        repo_root=repo_root,
        rootfs=rootfs,
        base_dir=Path(args.base_dir),
        cleanup_path=cleanup_path,
        spec=spec,
    )
    artifact_path = Path(result["task_root"]) / "output" / "codegen-artifact.json"
    if result["returncode"] != 0:
        raise BwrapTaskError(f"bwrap codegen smoke task failed: {result['stderr']}")
    artifact = json.loads(artifact_path.read_text())
    if artifact.get("checkout_write") != "denied":
        raise BwrapTaskError("bwrap codegen smoke allowed checkout write")
    if artifact.get("network") != "denied":
        raise BwrapTaskError("bwrap codegen smoke allowed network access")
    if artifact.get("scoring") != "fixture_harness":
        raise BwrapTaskError("bwrap codegen smoke used an unexpected scoring harness")
    summary = {
        "status": "pass",
        "run_id": args.run_id,
        "task_id": args.task_id,
        "suite": args.suite,
        "case_id": args.case_id,
        "task_root": result["task_root"],
        "artifact": str(artifact_path),
        "passed": artifact.get("passed") is True,
        "cleanup_ledger": str(cleanup_path),
        "duration_seconds": result["duration_seconds"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run GLM-5.2 benchmark tasks in a strict bwrap rootfs sandbox."
    )
    subparsers = parser.add_subparsers(required=True)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--run-id", required=True)
    smoke.add_argument("--task-id", default="task-001")
    smoke.add_argument("--base-dir", type=Path, default=DEFAULT_BWRAP_BASE)
    smoke.add_argument("--cleanup-ledger", type=Path)
    smoke.add_argument("--repo-root", type=Path, default=Path.cwd())
    smoke.add_argument("--rootfs", type=Path, default=DEFAULT_ROOTFS)
    smoke.add_argument("--timeout-seconds", type=int, default=30)
    smoke.set_defaults(func=run_smoke)

    codegen = subparsers.add_parser("codegen-smoke")
    codegen.add_argument("--run-id", required=True)
    codegen.add_argument("--task-id", required=True)
    codegen.add_argument("--suite", required=True)
    codegen.add_argument("--case-id", required=True)
    codegen.add_argument("--completion-text")
    codegen.add_argument("--base-dir", type=Path, default=DEFAULT_BWRAP_BASE)
    codegen.add_argument("--cleanup-ledger", type=Path)
    codegen.add_argument("--repo-root", type=Path, default=Path.cwd())
    codegen.add_argument("--rootfs", type=Path, default=DEFAULT_ROOTFS)
    codegen.add_argument("--timeout-seconds", type=int, default=30)
    codegen.set_defaults(func=run_codegen_smoke)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "cleanup_ledger", None) is None:
        args.cleanup_ledger = DEFAULT_CLEANUP_BASE / f"cleanup-{args.run_id}.json"
    try:
        return args.func(args)
    except BwrapTaskError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
