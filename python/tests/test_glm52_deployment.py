# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import importlib.util
import subprocess
import sys
from pathlib import Path

HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "glm52_deployment.py"
spec = importlib.util.spec_from_file_location("glm52_deployment", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_deployment = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_deployment
spec.loader.exec_module(glm52_deployment)

cleanup_manifest = glm52_deployment.cleanup_manifest
cleanup_process = glm52_deployment.cleanup_process
cleanup_selector = glm52_deployment.cleanup_selector
manifest_status = glm52_deployment.manifest_status
write_manifest = glm52_deployment.write_manifest


def test_manifest_status_reports_stale_process(tmp_path: Path) -> None:
    pidfile = tmp_path / "stale.pid"
    pidfile.write_text("999999999")
    manifest = {
        "deployment_id": "test",
        "namespace": "glm",
        "components": [
            {
                "kind": "process",
                "name": "port-forward",
                "pidfile": str(pidfile),
                "expected_command": "kubectl port-forward",
            }
        ],
    }

    status = manifest_status(manifest)

    assert status["components"] == [
        {
            "name": "port-forward",
            "kind": "process",
            "pid": 999999999,
            "status": "stale",
            "detail": "process is not running",
        }
    ]


def test_cleanup_process_removes_stale_pidfile(tmp_path: Path) -> None:
    pidfile = tmp_path / "stale.pid"
    pidfile.write_text("999999999")

    result = cleanup_process(
        {
            "kind": "process",
            "name": "port-forward",
            "pidfile": str(pidfile),
            "expected_command": "kubectl port-forward",
        },
        dry_run=False,
    )

    assert result["cleanup"] == "already-clean"
    assert not pidfile.exists()


def test_cleanup_process_refuses_mismatched_command(tmp_path: Path) -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        pidfile = tmp_path / "python.pid"
        pidfile.write_text(str(process.pid))

        result = cleanup_process(
            {
                "kind": "process",
                "name": "port-forward",
                "pidfile": str(pidfile),
                "expected_command": "kubectl port-forward",
            },
            dry_run=False,
        )

        assert result["cleanup"] == "manual-review"
        assert result["status"] == "mismatch"
        assert pidfile.exists()
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_cleanup_manifest_runs_in_reverse_order_dry_run(tmp_path: Path) -> None:
    manifest = {
        "deployment_id": "test",
        "namespace": "glm",
        "components": [
            {"kind": "namespace", "name": "glm"},
            {
                "kind": "kubernetes-manifest",
                "name": "dynamo",
                "path": "deploy.yaml",
                "namespace": "glm",
            },
        ],
    }

    result = cleanup_manifest(manifest, dry_run=True)

    assert result["status"] == "clean"
    assert [item["name"] for item in result["results"]] == ["dynamo", "glm"]
    assert result["results"][0]["command"] == [
        "kubectl",
        "delete",
        "-f",
        "deploy.yaml",
        "-n",
        "glm",
        "--ignore-not-found=true",
    ]


def test_cleanup_selector_dry_run() -> None:
    result = cleanup_selector(
        "glm",
        "app.kubernetes.io/part-of=glm52-codex",
        dry_run=True,
    )

    assert result["cleanup"] == "would-run"
    assert result["command"] == [
        "kubectl",
        "delete",
        "all,job,pvc,secret,configmap",
        "-l",
        "app.kubernetes.io/part-of=glm52-codex",
        "-n",
        "glm",
        "--ignore-not-found=true",
    ]


def test_write_manifest_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "state" / "deployment.json"

    write_manifest(path, {"deployment_id": "test", "components": []})

    assert '"deployment_id": "test"' in path.read_text()


def test_deployment_state_fixture_supports_status_and_dry_run() -> None:
    manifest = glm52_deployment.load_manifest(
        Path(".scratch/glm52-local-serving/run/deployment.json")
    )

    status = manifest_status(manifest)
    cleanup = cleanup_manifest(manifest, dry_run=True)

    assert status["deployment_id"] == "glm52-local-serving-fixture"
    assert status["namespace"] == "glm52-local"
    assert [component["name"] for component in status["components"]] == [
        "responses-adapter",
        "dynamo-sglang",
    ]
    assert [result["name"] for result in cleanup["results"]] == [
        "dynamo-sglang",
        "responses-adapter",
    ]
    assert cleanup["status"] == "clean"
    assert all(result["cleanup"] == "already-clean" for result in cleanup["results"])


def test_cleanup_ledger_status_and_dry_run_for_bwrap_task(tmp_path: Path) -> None:
    task_root = tmp_path / "bwrap" / "run-1" / "task-1"
    task_root.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "run_id": "run-1",
        "bwrap_tasks": [
            {
                "pid": None,
                "task_root": str(task_root),
                "command_contains": "glm52_bwrap_task_runner",
            }
        ],
        "processes": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }

    status = manifest_status(manifest)
    cleanup = cleanup_manifest(manifest, dry_run=True)

    assert status["run_id"] == "run-1"
    assert status["bwrap_tasks"] == [
        {
            "task_root": str(task_root),
            "status": "recorded",
            "exists": True,
            "pid": None,
        }
    ]
    assert cleanup["status"] == "clean"
    assert cleanup["results"] == [
        {
            "kind": "bwrap_task",
            "task_root": str(task_root),
            "pid": None,
            "cleanup": "would-remove",
        }
    ]
    assert task_root.exists()


def test_cleanup_ledger_removes_bwrap_task_root(tmp_path: Path) -> None:
    task_root = tmp_path / "bwrap" / "run-1" / "task-1"
    task_root.mkdir(parents=True)
    (task_root / "output.json").write_text("{}\n")
    manifest = {
        "schema_version": 1,
        "run_id": "run-1",
        "bwrap_tasks": [
            {
                "pid": None,
                "task_root": str(task_root),
                "command_contains": "glm52_bwrap_task_runner",
            }
        ],
        "processes": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }

    cleanup = cleanup_manifest(manifest, dry_run=False)

    assert cleanup["status"] == "clean"
    assert cleanup["results"] == [
        {
            "kind": "bwrap_task",
            "task_root": str(task_root),
            "pid": None,
            "cleanup": "removed",
        }
    ]
    assert not task_root.exists()


def test_cleanup_ledger_removes_temp_dirs(tmp_path: Path) -> None:
    temp_dir = tmp_path / "results" / "run-1" / "harbor-raw"
    temp_dir.mkdir(parents=True)
    (temp_dir / "partial.log").write_text("harbor failed\n")
    manifest = {
        "schema_version": 1,
        "run_id": "run-1",
        "bwrap_tasks": [],
        "processes": [],
        "containers": [],
        "temp_dirs": [
            {
                "path": str(temp_dir),
                "purpose": "harbor_raw_output",
            }
        ],
        "ports": [],
    }

    dry_run = cleanup_manifest(manifest, dry_run=True)
    cleanup = cleanup_manifest(manifest, dry_run=False)

    assert dry_run["status"] == "clean"
    assert dry_run["results"] == [
        {
            "kind": "temp_dir",
            "path": str(temp_dir),
            "purpose": "harbor_raw_output",
            "exists": True,
            "cleanup": "would-remove",
        }
    ]
    assert cleanup["status"] == "clean"
    assert cleanup["results"] == [
        {
            "kind": "temp_dir",
            "path": str(temp_dir),
            "purpose": "harbor_raw_output",
            "exists": True,
            "cleanup": "removed",
        }
    ]
    assert not temp_dir.exists()


def test_cleanup_ledger_reports_containers_and_ports_in_dry_run() -> None:
    manifest = {
        "schema_version": 1,
        "run_id": "run-1",
        "bwrap_tasks": [],
        "processes": [],
        "containers": [
            {
                "id": "container-123",
                "name": "harbor-task",
                "runtime": "docker",
                "purpose": "terminal-bench-2",
            }
        ],
        "temp_dirs": [],
        "ports": [
            {
                "port": 8080,
                "protocol": "tcp",
                "purpose": "responses-adapter",
            }
        ],
    }

    status = manifest_status(manifest)
    cleanup = cleanup_manifest(manifest, dry_run=True)

    assert status["run_id"] == "run-1"
    assert status["containers"] == [
        {
            "id": "container-123",
            "name": "harbor-task",
            "runtime": "docker",
            "purpose": "terminal-bench-2",
            "status": "recorded",
        }
    ]
    assert status["ports"] == [
        {
            "port": 8080,
            "protocol": "tcp",
            "purpose": "responses-adapter",
            "status": "recorded",
        }
    ]
    assert cleanup["status"] == "clean"
    assert cleanup["results"] == [
        {
            "kind": "port",
            "port": 8080,
            "protocol": "tcp",
            "purpose": "responses-adapter",
            "cleanup": "manual-review",
            "detail": "port ownership must be confirmed before cleanup",
        },
        {
            "kind": "container",
            "id": "container-123",
            "name": "harbor-task",
            "runtime": "docker",
            "purpose": "terminal-bench-2",
            "cleanup": "would-remove",
        },
    ]
