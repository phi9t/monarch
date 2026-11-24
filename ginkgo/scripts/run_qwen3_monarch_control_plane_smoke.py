#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from typing import Callable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_PYTHON = REPO_ROOT / "python"
for import_root in (REPO_ROOT, REPO_PYTHON):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


from ginkgo.scripts import verify_qwen3_sglang_smoke


DEFAULT_DECLARED_SPEC = REPO_ROOT / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml"
DEFAULT_LOCAL_ENVIRONMENT = REPO_ROOT / "ginkgo" / "local-env" / "qwen3-sglang.yaml"
HOST_CHILD_MODE = "host-child"
IN_PROCESS_ACTOR_MODE = "in-process-actor"
DEFAULT_EXPECTED_CHILD_DEVICE = "cpu"


class ExecutionDomainError(RuntimeError):
    pass


class ChildRunError(RuntimeError):
    pass


ArtifactVerifier = Callable[..., dict[str, Any]]
PortProbe = Callable[[str, int, float], int]


def run_smoke(
    *,
    declared_spec: Path = DEFAULT_DECLARED_SPEC,
    local_environment: Path = DEFAULT_LOCAL_ENVIRONMENT,
    repo_root: Path = REPO_ROOT,
    run_id: str = "qwen3-monarch-control-plane-smoke",
    manifest_path: Path | None = None,
    mode: str = HOST_CHILD_MODE,
    runtime: Any | None = None,
    child_runner: Callable[..., object] | None = None,
    verify_artifact: bool = False,
    artifact_verifier: ArtifactVerifier | None = None,
    child_port_probe: PortProbe | None = None,
    expected_generated_text: str | None = None,
    expected_child_device: str = DEFAULT_EXPECTED_CHILD_DEVICE,
) -> dict[str, Any]:
    if mode not in {HOST_CHILD_MODE, IN_PROCESS_ACTOR_MODE}:
        raise ValueError(f"unknown Qwen3 control-plane smoke mode: {mode}")
    manifest_path = manifest_path or repo_root / "glm52-serving-results" / run_id / "monarch-control-plane-manifest.json"
    declared_config_ref = _repo_ref(repo_root, declared_spec)
    local_environment_ref = _local_environment_ref(repo_root, local_environment)
    if mode == HOST_CHILD_MODE and runtime is None:
        try:
            result = _run_host_child_smoke(
                repo_root=repo_root,
                declared_spec=declared_spec,
                local_environment=local_environment,
                run_id=run_id,
                child_runner=child_runner,
                expected_child_device=expected_child_device,
                port_probe=child_port_probe,
            )
        except Exception as error:
            failed_phase = "host_child_domain_preflight" if isinstance(error, ExecutionDomainError) else "host_child_failed"
            _write_manifest(
                manifest_path,
                _failure_manifest(
                    run_id=run_id,
                    declared_config_ref=declared_config_ref,
                    local_environment_ref=local_environment_ref,
                    actor_status={
                        "phase": failed_phase,
                        "completed_components": [],
                        "failed_component": None if failed_phase == "host_child_domain_preflight" else "sglang_backend",
                        "error": str(error),
                        "state": {},
                    },
                    fake_runtime=False,
                    error=error,
                    execution_domain=_host_child_execution_domain(),
                ),
            )
            raise
        _write_manifest(
            manifest_path,
            _parent_manifest(
                run_id=run_id,
                declared_config_ref=declared_config_ref,
                local_environment_ref=local_environment_ref,
                result=result,
                fake_runtime=False,
                execution_domain=_host_child_execution_domain(),
                execution_mode="host-control adapter",
            ),
        )
        return _result_with_optional_artifact_verification(
            result={**result, "manifest": str(manifest_path)},
            manifest_path=manifest_path,
            mode=mode,
            fake_runtime=False,
            verify_artifact=verify_artifact,
            artifact_verifier=artifact_verifier,
            expected_generated_text=expected_generated_text,
            expected_child_device=expected_child_device,
        )

    from ginkgo.control_plane import Qwen3HostControlPlaneActor
    from ginkgo.control_plane import control_plane_run_from_mapping

    actor_local_environment = local_environment
    actor_local_environment_ref = local_environment_ref
    if mode == IN_PROCESS_ACTOR_MODE and runtime is None:
        actor_local_environment, actor_local_environment_ref = _materialize_in_process_actor_local_environment(
            repo_root=repo_root,
            local_environment=local_environment,
            run_id=run_id,
        )
    execution_domain = _actor_execution_domain(local_environment=actor_local_environment)
    if runtime is None:
        try:
            _preflight_in_process_actor_domain(local_environment=actor_local_environment)
        except Exception as error:
            _write_manifest(
                manifest_path,
                _failure_manifest(
                    run_id=run_id,
                    declared_config_ref=declared_config_ref,
                    local_environment_ref=actor_local_environment_ref,
                    actor_status={
                        "phase": "actor_domain_preflight",
                        "completed_components": [],
                        "failed_component": None,
                        "error": str(error),
                        "state": {},
                    },
                    fake_runtime=False,
                    error=error,
                    execution_domain=execution_domain,
                    execution_mode="monarch-actor-control",
                ),
            )
            raise

    run = control_plane_run_from_mapping(
        {
            "schema_version": 1,
            "run_id": run_id,
            "profile": "serving-smoke-cpu",
            "declared_config_ref": declared_config_ref,
            "local_environment_ref": actor_local_environment_ref,
            "execution_mode": "host-control adapter",
            "components": [
                {
                    "name": "sglang_backend",
                    "kind": "sglang",
                    "declared_ref": declared_config_ref,
                    "depends_on": [],
                    "artifacts": {
                        "process_record": "run://sglang/process.yaml",
                        "insula_plan": "run://sglang/insula/plan.yaml",
                    },
                }
            ],
            "artifacts": {
                "manifest": "run://parent/manifest.json",
                "events": "run://parent/events.jsonl",
            },
            "failure_policy": {
                "fail_fast": True,
                "allow_fallback": False,
                "teardown_requires_process_record": True,
            },
        }
    )
    actor = Qwen3HostControlPlaneActor(run, repo_root, runtime)
    try:
        result = asyncio.run(_run_actor_smoke(actor))
    except Exception as error:
        manifest = _failure_manifest(
            run_id=run_id,
            declared_config_ref=declared_config_ref,
            local_environment_ref=actor_local_environment_ref,
            actor_status=asyncio.run(_actor_status(actor)),
            fake_runtime=runtime is not None,
            error=error,
            execution_domain=None if runtime is not None else execution_domain,
            execution_mode="monarch-actor-control",
        )
        _write_manifest(manifest_path, manifest)
        raise
    _write_manifest(
        manifest_path,
        _parent_manifest(
            run_id=run_id,
            declared_config_ref=declared_config_ref,
            local_environment_ref=actor_local_environment_ref,
            result=result,
            fake_runtime=runtime is not None,
            execution_domain=None if runtime is not None else execution_domain,
            execution_mode="monarch-actor-control",
        ),
    )
    return _result_with_optional_artifact_verification(
        result={**result, "manifest": str(manifest_path)},
        manifest_path=manifest_path,
        mode=IN_PROCESS_ACTOR_MODE,
        fake_runtime=runtime is not None,
        verify_artifact=verify_artifact,
        artifact_verifier=artifact_verifier,
        expected_generated_text=expected_generated_text,
        expected_child_device=expected_child_device,
    )


async def _run_actor_smoke(actor: Any) -> dict[str, Any]:
    actor_type = type(actor)
    prepare = await actor_type.prepare._method(actor)
    launch = await actor_type.launch._method(actor, "sglang_backend")
    probe = await actor_type.probe._method(actor, "sglang_backend")
    status = await actor_type.status._method(actor)
    return {
        "prepare": prepare,
        "launch": launch,
        "probe": probe,
        "status": status,
    }


async def _actor_status(actor: Any) -> dict[str, Any]:
    return await type(actor).status._method(actor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Ginkgo Qwen3 Monarch control-plane smoke")
    parser.add_argument("--declared-spec", type=Path, default=DEFAULT_DECLARED_SPEC)
    parser.add_argument("--local-environment", type=Path, default=DEFAULT_LOCAL_ENVIRONMENT)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--run-id", default="qwen3-monarch-control-plane-smoke")
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument(
        "--verify-artifact",
        action="store_true",
        help="verify the saved parent and child artifacts before returning success",
    )
    parser.add_argument(
        "--expected-generated-text",
        help="optional generated text expected by artifact verification",
    )
    parser.add_argument(
        "--expected-child-device",
        choices=("cpu", "cuda"),
        default=DEFAULT_EXPECTED_CHILD_DEVICE,
        help="child Qwen3 SGLang device expected by artifact verification",
    )
    parser.add_argument(
        "--mode",
        choices=(HOST_CHILD_MODE, IN_PROCESS_ACTOR_MODE),
        default=HOST_CHILD_MODE,
        help=(
            "host-child runs the existing host-owned child wrapper; "
            "in-process-actor runs the actor adapter in the current namespace after preflight"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_smoke(
        declared_spec=args.declared_spec,
        local_environment=args.local_environment,
        repo_root=args.repo_root,
        run_id=args.run_id,
        manifest_path=args.manifest_path,
        mode=args.mode,
        verify_artifact=args.verify_artifact,
        expected_generated_text=args.expected_generated_text,
        expected_child_device=args.expected_child_device,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _parent_manifest(
    *,
    run_id: str,
    declared_config_ref: str,
    local_environment_ref: str,
    result: dict[str, Any],
    fake_runtime: bool,
    execution_domain: dict[str, Any] | None = None,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    status = dict(result["status"])
    launch = result["launch"]
    probe = result["probe"]
    manifest_status = "passed" if status["phase"] in {"probe:sglang_backend", "host_child_completed"} else "failed"
    status.setdefault("status", manifest_status)
    manifest = {
        "schema_version": 1,
        "status": manifest_status,
        "run_id": run_id,
        "profile": "serving-smoke-cpu",
        "execution_mode": execution_mode or _manifest_execution_mode(execution_domain=execution_domain),
        "declared_config_ref": declared_config_ref,
        "local_environment_ref": local_environment_ref,
        "evidence_boundary": _evidence_boundary(fake_runtime=fake_runtime, execution_domain=execution_domain),
        "components": {
            "sglang_backend": {
                **launch,
                **probe,
            }
        },
        "actor_status": status,
    }
    if execution_domain is not None:
        manifest["execution_domain"] = execution_domain
    return manifest


def _failure_manifest(
    *,
    run_id: str,
    declared_config_ref: str,
    local_environment_ref: str,
    actor_status: dict[str, Any],
    fake_runtime: bool,
    error: Exception,
    execution_domain: dict[str, Any] | None = None,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    actor_status = dict(actor_status)
    actor_status.setdefault("status", "failed")
    manifest = {
        "schema_version": 1,
        "status": "failed",
        "run_id": run_id,
        "profile": "serving-smoke-cpu",
        "execution_mode": execution_mode or _manifest_execution_mode(execution_domain=execution_domain),
        "declared_config_ref": declared_config_ref,
        "local_environment_ref": local_environment_ref,
        "evidence_boundary": _evidence_boundary(fake_runtime=fake_runtime, execution_domain=execution_domain),
        "components": actor_status.get("state", {}),
        "actor_status": actor_status,
        "failure": {
            "phase": str(actor_status.get("failed_phase") or actor_status.get("phase", "unknown")),
            "terminal_phase": str(actor_status.get("phase", "unknown")),
            "failed_component": actor_status.get("failed_component"),
            "teardown_errors": list(actor_status.get("teardown_errors", [])),
            "exception_type": type(error).__name__,
            "message": str(error),
        },
    }
    if execution_domain is not None:
        manifest["execution_domain"] = execution_domain
    return manifest


def _host_child_execution_domain() -> dict[str, object]:
    return {
        "monarch_import_domain": "requires_rootfs",
        "ginkgo_child_domain": "host_control_child_process",
        "supported": True,
    }


def _actor_execution_domain(*, local_environment: Path) -> dict[str, object]:
    return {
        "monarch_import_domain": "current_process",
        "ginkgo_child_domain": "in_process_actor_adapter",
        "local_environment": str(local_environment),
        "supported": os.environ.get("MONARCH_IN_ROOTFS") == "1",
    }


def _evidence_boundary(*, fake_runtime: bool, execution_domain: dict[str, Any] | None) -> str:
    if fake_runtime:
        return "fake_runtime_contract"
    if execution_domain and execution_domain.get("ginkgo_child_domain") == "in_process_actor_adapter":
        return "live_qwen3_in_process_actor_smoke"
    return "live_qwen3_host_child_smoke"


def _manifest_execution_mode(*, execution_domain: dict[str, Any] | None) -> str:
    if execution_domain and execution_domain.get("ginkgo_child_domain") == "in_process_actor_adapter":
        return "monarch-actor-control"
    return "host-control adapter"


def _result_with_optional_artifact_verification(
    *,
    result: dict[str, Any],
    manifest_path: Path,
    mode: str,
    fake_runtime: bool,
    verify_artifact: bool,
    artifact_verifier: ArtifactVerifier | None,
    expected_generated_text: str | None,
    expected_child_device: str,
) -> dict[str, Any]:
    if not verify_artifact:
        return result
    verifier = artifact_verifier or _load_artifact_verifier()
    verification = verifier(
        manifest_path,
        expected_execution_mode=_expected_execution_mode_for_mode(mode),
        expected_evidence_boundary=_expected_evidence_boundary_for_mode(mode, fake_runtime=fake_runtime),
        expected_generated_text=expected_generated_text or _generated_text_from_result(result),
        expected_child_device=expected_child_device,
    )
    return {**result, "artifact_verification": verification}


def _load_artifact_verifier() -> ArtifactVerifier:
    from ginkgo.scripts.verify_qwen3_monarch_control_plane_smoke import verify_manifest

    return verify_manifest


def _expected_execution_mode_for_mode(mode: str) -> str:
    if mode == IN_PROCESS_ACTOR_MODE:
        return "monarch-actor-control"
    return "host-control adapter"


def _expected_evidence_boundary_for_mode(mode: str, *, fake_runtime: bool) -> str:
    if fake_runtime:
        return "fake_runtime_contract"
    if mode == IN_PROCESS_ACTOR_MODE:
        return "live_qwen3_in_process_actor_smoke"
    return "live_qwen3_host_child_smoke"


def _generated_text_from_result(result: dict[str, Any]) -> str | None:
    launch = result.get("launch")
    if not isinstance(launch, dict):
        return None
    generated_text = launch.get("generated_text")
    if isinstance(generated_text, str) and generated_text != "":
        return generated_text
    return None


def _preflight_in_process_actor_domain(*, local_environment: Path) -> None:
    if os.environ.get("MONARCH_IN_ROOTFS") != "1":
        raise ExecutionDomainError("in-process actor mode must run inside scripts/run rootfs")
    payload = _load_yaml_mapping(local_environment, "local environment")
    roots = _require_mapping(payload.get("roots"), "local_environment.roots")
    rootfs = _require_mapping(payload.get("rootfs"), "local_environment.rootfs")
    paths: list[tuple[str, Path, bool]] = [
        ("local_environment.roots.repo", Path(_require_str(roots.get("repo"), "local_environment.roots.repo")), True),
        ("local_environment.roots.cache", Path(_require_str(roots.get("cache"), "local_environment.roots.cache")), True),
        ("local_environment.roots.temp", Path(_require_str(roots.get("temp"), "local_environment.roots.temp")), True),
    ]
    for name, value in rootfs.items():
        paths.append((f"local_environment.rootfs.{name}", Path(_require_str(value, f"local_environment.rootfs.{name}")), False))
    for field, path, require_writable in paths:
        if not path.exists():
            raise ExecutionDomainError(f"{field} is not reachable from in-process actor namespace: {path}")
        if require_writable and not os.access(path, os.W_OK):
            raise ExecutionDomainError(f"{field} is not writable from in-process actor namespace: {path}")
    if shutil.which("bwrap") is None:
        raise ExecutionDomainError("in-process actor mode requires bwrap in the actor namespace")


def _materialize_in_process_actor_local_environment(
    *,
    repo_root: Path,
    local_environment: Path,
    run_id: str,
) -> tuple[Path, str]:
    if os.environ.get("MONARCH_IN_ROOTFS") != "1":
        raise ExecutionDomainError("in-process actor mode must run inside scripts/run rootfs")
    _load_yaml_mapping(local_environment, "local environment")
    generated_relative = Path("ginkgo") / "local-env" / ".generated" / run_id / "in-process-actor.yaml"
    generated_path = repo_root / generated_relative
    projected = {
        "schema_version": 1,
        "roots": {
            "repo": str(repo_root),
            "cache": str(repo_root / ".scratch" / "glm52-local-serving" / "cache" / "ginkgo"),
            "temp": str(repo_root / ".scratch" / "glm52-local-serving" / "tmp" / "ginkgo"),
        },
        "rootfs": {
            "monarch-default": str(repo_root / "scripts" / "rootfs" / "rootfs"),
        },
    }
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text(yaml.safe_dump(projected, sort_keys=False))
    return generated_path, f"local-env://.generated/{run_id}/in-process-actor.yaml"


def _load_yaml_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open() as handle:
            value = yaml.safe_load(handle)
    except OSError as error:
        raise ExecutionDomainError(f"{label} cannot be read: {path}") from error
    if not isinstance(value, dict):
        raise ExecutionDomainError(f"{label} must be a mapping: {path}")
    return value


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutionDomainError(f"{field} must be a mapping")
    return value


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ExecutionDomainError(f"{field} must be a non-empty string")
    return value


def _run_host_child_smoke(
    *,
    repo_root: Path,
    declared_spec: Path,
    local_environment: Path,
    run_id: str,
    child_runner: Callable[..., object] | None,
    expected_child_device: str,
    port_probe: PortProbe | None,
) -> dict[str, Any]:
    if child_runner is None and os.environ.get("MONARCH_IN_ROOTFS") == "1":
        raise ExecutionDomainError(
            "host child mode must run from the host: invoke this live smoke with host Python, "
            "not scripts/run, so the child can own host absolute paths before entering Insula"
        )
    child_run_id = f"{run_id}-sglang_backend"
    evidence_manifest = repo_root / "glm52-serving-results" / child_run_id / "qwen3-sglang-smoke-evidence.json"
    argv = [
        str(repo_root / "ginkgo" / "scripts" / "run_qwen3_sglang_inference_in_bwrap_rootfs.sh"),
        "--declared-spec",
        str(declared_spec),
        "--local-environment",
        str(local_environment),
        "--run-id",
        child_run_id,
    ]
    env = dict(os.environ)
    env["GINKGO_QWEN3_CHILD_EVIDENCE_MANIFEST"] = str(evidence_manifest)
    runner = child_runner or _subprocess_child_runner
    completed = runner(argv, env=env)
    returncode = _returncode(completed)
    if returncode != 0:
        stderr = getattr(completed, "stderr", "")
        raise ChildRunError(f"host child qwen3 smoke failed: returncode={returncode}; stderr={stderr}")
    _verify_host_child_manifest(
        evidence_manifest,
        expected_child_device=expected_child_device,
        port_probe=port_probe,
    )
    child = _load_child_manifest(evidence_manifest)
    launch = _launch_state_from_child_manifest(child, evidence_manifest)
    return {
        "prepare": {
            "run_id": run_id,
            "local_environment": str(local_environment),
            "child_command": " ".join(argv),
        },
        "launch": launch,
        "probe": {
            "ready": "true",
            "evidence_manifest": str(evidence_manifest),
        },
        "status": {
            "phase": "host_child_completed",
            "completed_components": ["sglang_backend"],
            "failed_component": None,
            "error": None,
            "state": {"sglang_backend": launch},
        },
    }


def _subprocess_child_runner(argv: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=False, capture_output=True, env=env, text=True)


def _returncode(result: object) -> int:
    returncode = getattr(result, "returncode", None)
    if isinstance(returncode, int):
        return returncode
    if isinstance(result, int):
        return result
    raise ChildRunError("host child runner must return an int or object with integer returncode")


def _verify_host_child_manifest(
    path: Path,
    *,
    expected_child_device: str,
    port_probe: PortProbe | None,
) -> None:
    if not path.exists():
        raise ChildRunError(f"host child evidence manifest missing: {path}")
    try:
        verify_qwen3_sglang_smoke.verify_manifest(
            path,
            expected_device=expected_child_device,
            check_port_closed=True,
            port_probe=port_probe,
        )
    except verify_qwen3_sglang_smoke.VerificationError as error:
        raise ChildRunError(f"child artifact verification failed: {error}") from error


def _load_child_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except OSError as error:
        raise ChildRunError(f"host child evidence manifest missing: {path}") from error
    except json.JSONDecodeError as error:
        raise ChildRunError(f"host child evidence manifest is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ChildRunError(f"host child evidence manifest must be a JSON object: {path}")
    if payload.get("status") != "passed":
        raise ChildRunError(f"host child evidence manifest did not pass: {path}")
    return payload


def _launch_state_from_child_manifest(child: dict[str, Any], evidence_manifest: Path) -> dict[str, str]:
    port = child.get("port")
    if not isinstance(port, int):
        raise ChildRunError("host child evidence manifest missing integer port")
    run_id = child.get("run_id")
    if not isinstance(run_id, str) or run_id == "":
        raise ChildRunError("host child evidence manifest missing run_id")
    generated_text = child.get("generated_text")
    if not isinstance(generated_text, str) or generated_text == "":
        raise ChildRunError("host child evidence manifest missing generated_text")
    openai_base_url = child.get("openai_base_url")
    expected_base_url = f"http://127.0.0.1:{port}/v1"
    if openai_base_url != expected_base_url:
        raise ChildRunError("host child evidence manifest openai_base_url does not match port")
    teardown_status = child.get("teardown_status")
    if teardown_status != "teardown_passed":
        raise ChildRunError("host child evidence manifest missing teardown_passed status")
    return {
        "status": "passed",
        "run_id": run_id,
        "port": str(port),
        "openai_base_url": openai_base_url,
        "generated_text": generated_text,
        "teardown_status": teardown_status,
        "evidence_manifest": str(evidence_manifest),
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _repo_ref(repo_root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError as error:
        raise ValueError(f"path must be under repo root: {path}") from error
    return f"repo://{relative.as_posix()}"


def _local_environment_ref(repo_root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to((repo_root / "ginkgo" / "local-env").resolve())
    except ValueError as error:
        raise ValueError(f"local environment must be under ginkgo/local-env: {path}") from error
    return f"local-env://{relative.as_posix()}"


if __name__ == "__main__":
    raise SystemExit(main())
