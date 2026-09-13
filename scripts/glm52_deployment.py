# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STATE = Path(".scratch/glm52-local-serving/run/deployment.json")
DEFAULT_SELECTOR = "app.kubernetes.io/part-of=glm52-codex"


class DeploymentError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessStatus:
    pid: int | None
    state: str
    detail: str


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise DeploymentError(f"manifest not found: {path}") from error
    except json.JSONDecodeError as error:
        raise DeploymentError(f"invalid manifest JSON: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise DeploymentError(f"manifest must be a JSON object: {path}")
    return payload


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def manifest_components(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    components = manifest.get("components", [])
    if not isinstance(components, list):
        raise DeploymentError("manifest components must be a list")
    typed_components = []
    for component in components:
        if not isinstance(component, dict):
            raise DeploymentError(f"manifest component must be an object: {component!r}")
        typed_components.append(component)
    return typed_components


def manifest_bwrap_tasks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = manifest.get("bwrap_tasks", [])
    if not isinstance(tasks, list):
        raise DeploymentError("manifest bwrap_tasks must be a list")
    typed_tasks = []
    for task in tasks:
        if not isinstance(task, dict):
            raise DeploymentError(f"bwrap task must be an object: {task!r}")
        typed_tasks.append(task)
    return typed_tasks


def manifest_temp_dirs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    temp_dirs = manifest.get("temp_dirs", [])
    if not isinstance(temp_dirs, list):
        raise DeploymentError("manifest temp_dirs must be a list")
    typed_temp_dirs = []
    for temp_dir in temp_dirs:
        if not isinstance(temp_dir, dict):
            raise DeploymentError(f"temp_dir must be an object: {temp_dir!r}")
        typed_temp_dirs.append(temp_dir)
    return typed_temp_dirs


def manifest_containers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    containers = manifest.get("containers", [])
    if not isinstance(containers, list):
        raise DeploymentError("manifest containers must be a list")
    typed_containers = []
    for container in containers:
        if not isinstance(container, dict):
            raise DeploymentError(f"container must be an object: {container!r}")
        typed_containers.append(container)
    return typed_containers


def manifest_ports(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    ports = manifest.get("ports", [])
    if not isinstance(ports, list):
        raise DeploymentError("manifest ports must be a list")
    typed_ports = []
    for port in ports:
        if not isinstance(port, dict):
            raise DeploymentError(f"port must be an object: {port!r}")
        typed_ports.append(port)
    return typed_ports


def process_cmdline(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError:
        return None
    except PermissionError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()


def process_status(pidfile: Path, expected_command: str | None) -> ProcessStatus:
    try:
        raw_pid = pidfile.read_text().strip()
    except FileNotFoundError:
        return ProcessStatus(None, "absent", "pidfile is absent")
    try:
        pid = int(raw_pid)
    except ValueError:
        return ProcessStatus(None, "invalid", f"pidfile does not contain an integer: {raw_pid!r}")

    cmdline = process_cmdline(pid)
    if cmdline is None:
        return ProcessStatus(pid, "stale", "process is not running")
    if expected_command and expected_command not in cmdline:
        return ProcessStatus(pid, "mismatch", f"process command does not match: {cmdline}")
    return ProcessStatus(pid, "running", cmdline or "process is running")


def cleanup_process(component: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    name = str(component.get("name") or "process")
    pidfile_value = component.get("pidfile")
    if not isinstance(pidfile_value, str):
        raise DeploymentError(f"process component {name} is missing pidfile")
    expected_command = component.get("expected_command")
    if expected_command is not None and not isinstance(expected_command, str):
        raise DeploymentError(f"process component {name} has non-string expected_command")

    pidfile = Path(pidfile_value)
    status = process_status(pidfile, expected_command)
    result: dict[str, Any] = {
        "name": name,
        "kind": "process",
        "pid": status.pid,
        "status": status.state,
        "detail": status.detail,
    }
    if status.state in {"absent", "stale"}:
        if status.state == "stale" and not dry_run:
            pidfile.unlink(missing_ok=True)
        result["cleanup"] = "already-clean"
        return result
    if status.state != "running":
        result["cleanup"] = "manual-review"
        return result

    if dry_run:
        result["cleanup"] = "would-kill"
        return result

    assert status.pid is not None
    os.kill(status.pid, signal.SIGTERM)
    pidfile.unlink(missing_ok=True)
    result["cleanup"] = "killed"
    return result


def kubectl_delete(args: list[str], *, dry_run: bool) -> dict[str, Any]:
    command = ["kubectl", "delete", *args, "--ignore-not-found=true"]
    if dry_run:
        return {"command": command, "returncode": None, "stdout": "", "stderr": "", "cleanup": "would-run"}
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "cleanup": "deleted" if completed.returncode == 0 else "failed",
    }


def cleanup_kubernetes_manifest(component: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    name = str(component.get("name") or "kubernetes-manifest")
    path = component.get("path")
    namespace = component.get("namespace")
    if not isinstance(path, str):
        raise DeploymentError(f"kubernetes-manifest component {name} is missing path")
    args = ["-f", path]
    if isinstance(namespace, str) and namespace:
        args.extend(["-n", namespace])
    result = kubectl_delete(args, dry_run=dry_run)
    return {"name": name, "kind": "kubernetes-manifest", **result}


def cleanup_namespace(component: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    name = component.get("name") or component.get("namespace")
    if not isinstance(name, str) or not name:
        raise DeploymentError("namespace component is missing name")
    result = kubectl_delete(["namespace", name], dry_run=dry_run)
    return {"name": name, "kind": "namespace", **result}


def cleanup_secret(component: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    name = component.get("name")
    namespace = component.get("namespace")
    if not isinstance(name, str) or not name:
        raise DeploymentError("secret component is missing name")
    args = ["secret", name]
    if isinstance(namespace, str) and namespace:
        args.extend(["-n", namespace])
    result = kubectl_delete(args, dry_run=dry_run)
    return {"name": name, "kind": "secret", **result}


def cleanup_component(component: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    kind = component.get("kind")
    if kind == "process":
        return cleanup_process(component, dry_run=dry_run)
    if kind == "kubernetes-manifest":
        return cleanup_kubernetes_manifest(component, dry_run=dry_run)
    if kind == "namespace":
        return cleanup_namespace(component, dry_run=dry_run)
    if kind == "secret":
        return cleanup_secret(component, dry_run=dry_run)
    name = str(component.get("name") or kind or "unknown")
    return {
        "name": name,
        "kind": kind,
        "status": "external",
        "cleanup": "skipped",
        "detail": "component kind is external or unsupported",
    }


def bwrap_task_status(task: dict[str, Any]) -> dict[str, Any]:
    task_root_value = task.get("task_root")
    if not isinstance(task_root_value, str):
        raise DeploymentError("bwrap task is missing task_root")
    pid = task.get("pid")
    if pid is not None and not isinstance(pid, int):
        raise DeploymentError("bwrap task pid must be an integer or null")
    result = {
        "task_root": task_root_value,
        "status": "recorded",
        "exists": Path(task_root_value).exists(),
        "pid": pid,
    }
    if pid is not None:
        expected = task.get("command_contains")
        if expected is not None and not isinstance(expected, str):
            raise DeploymentError("bwrap task command_contains must be a string")
        status = process_status_from_pid(pid, expected)
        result["process_status"] = status.state
        result["detail"] = status.detail
    return result


def process_status_from_pid(pid: int, expected_command: str | None) -> ProcessStatus:
    cmdline = process_cmdline(pid)
    if cmdline is None:
        return ProcessStatus(pid, "stale", "process is not running")
    if expected_command and expected_command not in cmdline:
        return ProcessStatus(pid, "mismatch", f"process command does not match: {cmdline}")
    return ProcessStatus(pid, "running", cmdline or "process is running")


def cleanup_bwrap_task(task: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    status = bwrap_task_status(task)
    result = {
        "kind": "bwrap_task",
        "task_root": status["task_root"],
        "pid": status["pid"],
    }
    pid = status["pid"]
    if pid is not None:
        process_state = status.get("process_status")
        if process_state == "mismatch":
            result["status"] = "mismatch"
            result["cleanup"] = "manual-review"
            result["detail"] = status.get("detail")
            return result
        if process_state == "running":
            if dry_run:
                result["cleanup"] = "would-kill-and-remove"
                return result
            os.kill(pid, signal.SIGTERM)

    if dry_run:
        result["cleanup"] = "would-remove"
        return result
    shutil.rmtree(status["task_root"], ignore_errors=True)
    result["cleanup"] = "removed"
    return result


def cleanup_temp_dir(temp_dir: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    path_value = temp_dir.get("path")
    if not isinstance(path_value, str):
        raise DeploymentError("temp_dir is missing path")
    purpose = temp_dir.get("purpose")
    if purpose is not None and not isinstance(purpose, str):
        raise DeploymentError("temp_dir purpose must be a string")

    path = Path(path_value)
    exists = path.exists()
    result = {
        "kind": "temp_dir",
        "path": path_value,
        "purpose": purpose,
        "exists": exists,
    }
    if not exists:
        result["cleanup"] = "already-clean"
        return result
    if dry_run:
        result["cleanup"] = "would-remove"
        return result
    shutil.rmtree(path, ignore_errors=True)
    result["cleanup"] = "removed"
    return result


def container_status(container: dict[str, Any]) -> dict[str, Any]:
    container_id = container.get("id")
    name = container.get("name")
    runtime = container.get("runtime", "docker")
    purpose = container.get("purpose")
    if container_id is not None and not isinstance(container_id, str):
        raise DeploymentError("container id must be a string")
    if name is not None and not isinstance(name, str):
        raise DeploymentError("container name must be a string")
    if not container_id and not name:
        raise DeploymentError("container is missing id or name")
    if not isinstance(runtime, str) or not runtime:
        raise DeploymentError("container runtime must be a non-empty string")
    if purpose is not None and not isinstance(purpose, str):
        raise DeploymentError("container purpose must be a string")
    result = {
        "id": container_id,
        "name": name,
        "runtime": runtime,
        "purpose": purpose,
        "status": "recorded",
    }
    return {key: value for key, value in result.items() if value is not None}


def cleanup_container(container: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    status = container_status(container)
    result = {
        "kind": "container",
        **status,
    }
    result.pop("status", None)
    if dry_run:
        result["cleanup"] = "would-remove"
        return result

    result["cleanup"] = "manual-review"
    result["detail"] = "container ownership must be confirmed before cleanup"
    return result


def port_status(port: dict[str, Any]) -> dict[str, Any]:
    port_value = port.get("port")
    protocol = port.get("protocol", "tcp")
    purpose = port.get("purpose")
    if not isinstance(port_value, int):
        raise DeploymentError("port entry is missing integer port")
    if port_value <= 0 or port_value > 65535:
        raise DeploymentError("port entry must be between 1 and 65535")
    if not isinstance(protocol, str) or not protocol:
        raise DeploymentError("port protocol must be a non-empty string")
    if purpose is not None and not isinstance(purpose, str):
        raise DeploymentError("port purpose must be a string")
    result = {
        "port": port_value,
        "protocol": protocol,
        "purpose": purpose,
        "status": "recorded",
    }
    return {key: value for key, value in result.items() if value is not None}


def cleanup_port(port: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    status = port_status(port)
    result = {
        "kind": "port",
        **status,
        "cleanup": "manual-review",
        "detail": "port ownership must be confirmed before cleanup",
    }
    result.pop("status", None)
    return result


def manifest_status(manifest: dict[str, Any]) -> dict[str, Any]:
    if "bwrap_tasks" in manifest:
        return {
            "run_id": manifest.get("run_id"),
            "bwrap_tasks": [bwrap_task_status(task) for task in manifest_bwrap_tasks(manifest)],
            "containers": [container_status(container) for container in manifest_containers(manifest)],
            "ports": [port_status(port) for port in manifest_ports(manifest)],
        }

    components = []
    for component in manifest_components(manifest):
        kind = component.get("kind")
        if kind == "process":
            pidfile = component.get("pidfile")
            if not isinstance(pidfile, str):
                raise DeploymentError(f"process component {component.get('name')} is missing pidfile")
            expected_command = component.get("expected_command")
            if expected_command is not None and not isinstance(expected_command, str):
                raise DeploymentError(f"process component {component.get('name')} has non-string expected_command")
            status = process_status(Path(pidfile), expected_command)
            components.append(
                {
                    "name": component.get("name"),
                    "kind": kind,
                    "pid": status.pid,
                    "status": status.state,
                    "detail": status.detail,
                }
            )
        else:
            components.append(
                {
                    "name": component.get("name"),
                    "kind": kind,
                    "status": "recorded",
                }
            )
    return {
        "deployment_id": manifest.get("deployment_id"),
        "namespace": manifest.get("namespace"),
        "components": components,
    }


def cleanup_manifest(manifest: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    if "bwrap_tasks" in manifest:
        results = []
        for port in reversed(manifest_ports(manifest)):
            results.append(cleanup_port(port, dry_run=dry_run))
        for container in reversed(manifest_containers(manifest)):
            results.append(cleanup_container(container, dry_run=dry_run))
        for task in reversed(manifest_bwrap_tasks(manifest)):
            results.append(cleanup_bwrap_task(task, dry_run=dry_run))
        for temp_dir in reversed(manifest_temp_dirs(manifest)):
            results.append(cleanup_temp_dir(temp_dir, dry_run=dry_run))
        manual = [
            result
            for result in results
            if result.get("cleanup") == "manual-review"
            and not (dry_run and result.get("kind") == "port")
        ]
        return {
            "run_id": manifest.get("run_id"),
            "dry_run": dry_run,
            "status": "fail" if manual else "clean",
            "results": results,
        }

    results = []
    # Reverse order mirrors shell trap teardown: newest owned resource first.
    for component in reversed(manifest_components(manifest)):
        results.append(cleanup_component(component, dry_run=dry_run))
    failed = [result for result in results if result.get("cleanup") == "failed"]
    manual = [result for result in results if result.get("cleanup") == "manual-review"]
    return {
        "deployment_id": manifest.get("deployment_id"),
        "dry_run": dry_run,
        "status": "fail" if failed or manual else "clean",
        "results": results,
    }


def cleanup_selector(namespace: str, selector: str, *, dry_run: bool) -> dict[str, Any]:
    result = kubectl_delete(
        ["all,job,pvc,secret,configmap", "-l", selector, "-n", namespace],
        dry_run=dry_run,
    )
    return {
        "namespace": namespace,
        "selector": selector,
        "dry_run": dry_run,
        **result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage GLM-5.2 deployment manifests and crash cleanup."
    )
    subparsers = parser.add_subparsers(required=True)

    init_parser = subparsers.add_parser("init-state")
    init_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    init_parser.add_argument("--deployment-id", required=True)
    init_parser.add_argument("--namespace", default="glm")
    init_parser.add_argument("--mode", choices=["namespace-scoped", "label-scoped"], default="namespace-scoped")
    init_parser.set_defaults(func=_cmd_init_state)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    status_parser.set_defaults(func=_cmd_status)

    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--state", type=Path)
    cleanup_parser.add_argument("--namespace")
    cleanup_parser.add_argument("--selector", default=DEFAULT_SELECTOR)
    cleanup_parser.add_argument("--dry-run", action="store_true")
    cleanup_parser.set_defaults(func=_cmd_cleanup)
    return parser


def _cmd_init_state(args: argparse.Namespace) -> int:
    manifest = {
        "deployment_id": args.deployment_id,
        "namespace": args.namespace,
        "mode": args.mode,
        "components": [],
    }
    write_manifest(args.state, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.state)
    print(json.dumps(manifest_status(manifest), indent=2, sort_keys=True))
    return 0


def _cmd_cleanup(args: argparse.Namespace) -> int:
    if args.state is not None:
        result = cleanup_manifest(load_manifest(args.state), dry_run=args.dry_run)
    else:
        if not args.namespace:
            raise DeploymentError("cleanup requires --state or --namespace")
        result = cleanup_selector(args.namespace, args.selector, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {None, "clean"} and result.get("cleanup") != "failed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DeploymentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
