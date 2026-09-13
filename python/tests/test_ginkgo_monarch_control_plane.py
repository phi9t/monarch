from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from isolate_in_subprocess import isolate_in_subprocess

from ginkgo.control_plane import ControlPlaneConfigError
from ginkgo.control_plane import ControlPlaneCoordinator
from ginkgo.control_plane import GinkgoHostControlAdapter
from ginkgo.control_plane import GinkgoControlPlaneActor
from ginkgo.control_plane import Qwen3HostControlPlaneActor
from ginkgo.control_plane import control_plane_run_from_mapping
from ginkgo.control_plane import create_qwen3_host_control_adapter
from ginkgo.control_plane import resolve_component_ref
from ginkgo.control_plane import run_to_mapping
from ginkgo.local_run import LocalRunResult
from monarch.actor import this_host


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_PLANE_SCRIPT = REPO_ROOT / "ginkgo" / "scripts" / "run_qwen3_monarch_control_plane_smoke.py"
CONTROL_PLANE_VERIFIER = REPO_ROOT / "ginkgo" / "scripts" / "verify_qwen3_monarch_control_plane_smoke.py"


VALID_RUN = {
    "schema_version": 1,
    "run_id": "ginkgo-parent-001",
    "profile": "glm52",
    "declared_config_ref": "repo://ginkgo/configs/inference-glm52.yaml",
    "local_environment_ref": "local-env://glm52-serving.yaml",
    "execution_mode": "host-control adapter",
    "components": [
        {
            "name": "sglang_backend",
            "kind": "sglang",
            "declared_ref": "repo://ginkgo/configs/sglang-glm52.yaml",
            "depends_on": [],
            "artifacts": {
                "process_record": "run://sglang/process.yaml",
                "insula_plan": "run://sglang/insula/plan.yaml",
            },
        },
        {
            "name": "dynamo_frontend",
            "kind": "dynamo",
            "declared_ref": "repo://ginkgo/configs/inference-glm52.yaml#dynamo_frontend",
            "depends_on": ["sglang_backend"],
            "upstream_ref": "component://sglang_backend/openai_base_url",
            "artifacts": {
                "process_record": "run://dynamo/process.yaml",
                "insula_plan": "run://dynamo/insula/plan.yaml",
            },
        },
        {
            "name": "responses_adapter",
            "kind": "responses_adapter",
            "declared_ref": "repo://ginkgo/configs/inference-glm52.yaml#responses_adapter",
            "depends_on": ["dynamo_frontend"],
            "upstream_ref": "component://dynamo_frontend/openai_base_url",
            "artifacts": {
                "process_record": "run://responses/process.yaml",
                "insula_plan": "run://responses/insula/plan.yaml",
            },
        },
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


def test_control_plane_run_round_trips_and_preserves_component_order() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)

    assert [component.name for component in run.components] == [
        "sglang_backend",
        "dynamo_frontend",
        "responses_adapter",
    ]
    assert run.component("responses_adapter").upstream_ref == "component://dynamo_frontend/openai_base_url"
    assert run_to_mapping(run) == VALID_RUN


def test_control_plane_run_requires_no_fallback_policy() -> None:
    data = dict(VALID_RUN)
    data["failure_policy"] = {
        "fail_fast": True,
        "allow_fallback": True,
        "teardown_requires_process_record": True,
    }

    with pytest.raises(ControlPlaneConfigError, match="allow_fallback must be false"):
        control_plane_run_from_mapping(data)


def test_control_plane_run_rejects_out_of_order_dependencies() -> None:
    data = dict(VALID_RUN)
    data["components"] = list(reversed(VALID_RUN["components"]))

    with pytest.raises(ControlPlaneConfigError, match="dependency must appear before component"):
        control_plane_run_from_mapping(data)


def test_control_plane_run_rejects_unresolved_component_ref() -> None:
    data = dict(VALID_RUN)
    data["components"] = [
        dict(VALID_RUN["components"][0]),
        {
            **VALID_RUN["components"][1],
            "upstream_ref": "component://missing/openai_base_url",
        },
    ]

    with pytest.raises(ControlPlaneConfigError, match="component ref names unknown component"):
        control_plane_run_from_mapping(data)


def test_resolve_component_ref_reads_parent_run_state() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    state = {
        "sglang_backend": {"openai_base_url": "http://127.0.0.1:19000/v1"},
        "dynamo_frontend": {"openai_base_url": "http://127.0.0.1:19001/v1"},
    }

    assert (
        resolve_component_ref(run, "component://dynamo_frontend/openai_base_url", state)
        == "http://127.0.0.1:19001/v1"
    )


def test_resolve_component_ref_fails_loudly_for_missing_state_key() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)

    with pytest.raises(ControlPlaneConfigError, match="component state does not contain key"):
        resolve_component_ref(run, "component://sglang_backend/openai_base_url", {"sglang_backend": {}})


def test_coordinator_runs_prepare_launch_probe_in_dependency_order() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter()
    coordinator = ControlPlaneCoordinator(run=run, adapter=adapter)

    result = coordinator.run()

    assert result.status == "completed"
    assert result.completed_components == ["sglang_backend", "dynamo_frontend", "responses_adapter"]
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "launch:dynamo_frontend:upstream=http://127.0.0.1:19000/v1",
        "probe:dynamo_frontend",
        "launch:responses_adapter:upstream=http://127.0.0.1:19001/v1",
        "probe:responses_adapter",
    ]
    assert coordinator.status()["phase"] == "completed"


def test_coordinator_tears_down_launched_components_after_probe_failure() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter(fail_probe_for="dynamo_frontend")
    coordinator = ControlPlaneCoordinator(run=run, adapter=adapter)

    result = coordinator.run()

    assert result.status == "failed"
    assert result.failed_component == "dynamo_frontend"
    assert result.failed_phase == "probing:dynamo_frontend"
    assert result.error == "probe failed for dynamo_frontend"
    status = coordinator.status()
    assert status["phase"] == "failed"
    assert status["failed_phase"] == "probing:dynamo_frontend"
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "launch:dynamo_frontend:upstream=http://127.0.0.1:19000/v1",
        "probe:dynamo_frontend",
        "teardown:dynamo_frontend",
        "teardown:sglang_backend",
    ]
    assert coordinator.status()["phase"] == "failed"


def test_coordinator_preserves_primary_failure_when_teardown_fails() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter(
        fail_probe_for="dynamo_frontend",
        fail_teardown_for="sglang_backend",
    )
    coordinator = ControlPlaneCoordinator(run=run, adapter=adapter)

    result = coordinator.run()
    status = coordinator.status()

    assert result.status == "failed"
    assert result.failed_component == "dynamo_frontend"
    assert result.failed_phase == "probing:dynamo_frontend"
    assert result.error == "probe failed for dynamo_frontend"
    assert status["phase"] == "failed"
    assert status["failed_phase"] == "probing:dynamo_frontend"
    assert status["teardown_errors"] == [
        {
            "component": "sglang_backend",
            "error": "teardown failed for sglang_backend",
        }
    ]
    assert status["state"]["dynamo_frontend"]["closed"] == "true"
    assert "closed" not in status["state"]["sglang_backend"]
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "launch:dynamo_frontend:upstream=http://127.0.0.1:19000/v1",
        "probe:dynamo_frontend",
        "teardown:dynamo_frontend",
        "teardown:sglang_backend",
    ]


def test_coordinator_cancellation_tears_down_existing_components_before_next_launch() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter(cancel_after_probe="sglang_backend")
    coordinator = ControlPlaneCoordinator(run=run, adapter=adapter)

    result = coordinator.run()

    assert result.status == "cancelled"
    assert result.completed_components == ["sglang_backend"]
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "teardown:sglang_backend",
    ]
    assert coordinator.status()["phase"] == "cancelled"


def test_host_control_adapter_launches_sglang_with_resolved_local_runner_paths(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    runner = FakeSglangLocalRunner(
        LocalRunResult(
            status="passed",
            run_id="ginkgo-parent-001-sglang_backend",
            port=19017,
            generated_text="hello from qwen",
            evidence_manifest=repo_root / "results" / "evidence.json",
            teardown_status="teardown_passed",
        )
    )
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = GinkgoHostControlAdapter(repo_root=repo_root, sglang_runner=runner)

    assert adapter.prepare(run) == {
        "run_id": "ginkgo-parent-001",
        "local_environment": str(repo_root / "ginkgo" / "local-env" / "glm52-serving.yaml"),
    }
    state = adapter.launch(run.component("sglang_backend"), upstream_url=None)

    assert runner.calls == [
        {
            "declared_spec": repo_root / "ginkgo" / "configs" / "sglang-glm52.yaml",
            "local_environment": repo_root / "ginkgo" / "local-env" / "glm52-serving.yaml",
            "run_id": "ginkgo-parent-001-sglang_backend",
            "port": None,
        }
    ]
    assert state == {
        "status": "passed",
        "run_id": "ginkgo-parent-001-sglang_backend",
        "port": "19017",
        "openai_base_url": "http://127.0.0.1:19017/v1",
        "generated_text": "hello from qwen",
        "evidence_manifest": str(repo_root / "results" / "evidence.json"),
        "teardown_status": "teardown_passed",
    }
    assert adapter.probe(run.component("sglang_backend"), state) == {
        "ready": "true",
        "evidence_manifest": str(repo_root / "results" / "evidence.json"),
    }
    assert adapter.teardown(run.component("sglang_backend"), state) == {
        "closed": "true",
        "run_id": "ginkgo-parent-001-sglang_backend",
    }


def test_host_control_adapter_rejects_upstream_for_sglang_component(tmp_path) -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = GinkgoHostControlAdapter(
        repo_root=tmp_path,
        sglang_runner=FakeSglangLocalRunner(
            LocalRunResult(
                status="passed",
                run_id="unused",
                port=19017,
                generated_text="unused",
                evidence_manifest=tmp_path / "unused.json",
                teardown_status="teardown_passed",
            )
        ),
    )
    adapter.prepare(run)

    with pytest.raises(ControlPlaneConfigError, match="sglang component must not receive upstream_url"):
        adapter.launch(run.component("sglang_backend"), upstream_url="http://127.0.0.1:19000/v1")


def test_host_control_adapter_rejects_non_sglang_component_until_contract_exists(tmp_path) -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = GinkgoHostControlAdapter(
        repo_root=tmp_path,
        sglang_runner=FakeSglangLocalRunner(
            LocalRunResult(
                status="passed",
                run_id="unused",
                port=19017,
                generated_text="unused",
                evidence_manifest=tmp_path / "unused.json",
                teardown_status="teardown_passed",
            )
        ),
    )
    adapter.prepare(run)

    with pytest.raises(ControlPlaneConfigError, match="unsupported host-control component kind: dynamo"):
        adapter.launch(run.component("dynamo_frontend"), upstream_url="http://127.0.0.1:19017/v1")


def test_host_control_adapter_requires_explicit_sglang_runner(tmp_path) -> None:
    with pytest.raises(TypeError, match="sglang_runner"):
        GinkgoHostControlAdapter(repo_root=tmp_path)


def test_create_qwen3_host_control_adapter_runs_coordinator_through_local_run_stack(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    run = control_plane_run_from_mapping(
        {
            **VALID_RUN,
            "run_id": "qwen3-actor-smoke",
            "profile": "serving-smoke-cpu",
            "declared_config_ref": "repo://ginkgo/configs/smoke-qwen3-cpu.yaml",
            "local_environment_ref": "local-env://qwen3-sglang.yaml",
            "components": [
                {
                    **VALID_RUN["components"][0],
                    "declared_ref": "repo://ginkgo/configs/smoke-qwen3-cpu.yaml",
                }
            ],
        }
    )
    adapter = create_qwen3_host_control_adapter(repo_root=tmp_path, runtime=runtime)

    result = ControlPlaneCoordinator(run=run, adapter=adapter).run()

    assert result.status == "completed"
    assert result.completed_components == ["sglang_backend"]
    assert result.state["sglang_backend"]["openai_base_url"] == "http://127.0.0.1:19007/v1"
    assert result.state["sglang_backend"]["generated_text"] == "OK"
    assert result.state["sglang_backend"]["ready"] == "true"
    assert result.state["sglang_backend"]["teardown_status"] == "teardown_passed"
    assert result.state["sglang_backend"]["evidence_manifest"].endswith("qwen3-sglang-smoke-evidence.json")
    assert runtime.calls == [
        "load_declared:smoke-qwen3-cpu.yaml",
        "load_local:qwen3-sglang.yaml",
        "materialize:qwen3-actor-smoke-sglang_backend:None",
        "stable_preparation_paths",
        "write_materialized",
        "validate_preparation",
        "launch",
        "load_effective_materialized",
        "models",
        "chat",
        "teardown",
    ]


def test_control_plane_host_control_import_does_not_require_monarch_rootfs() -> None:
    env = dict(os.environ)
    env.pop("MONARCH_IN_ROOTFS", None)
    env.pop("MONARCH_ROOTFS_RECIPE_SHA256", None)
    env["PYTHONPATH"] = str(REPO_ROOT)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from ginkgo.control_plane import ControlPlaneCoordinator, "
                "GinkgoHostControlAdapter; "
                "print(ControlPlaneCoordinator.__name__, GinkgoHostControlAdapter.__name__)"
            ),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ControlPlaneCoordinator GinkgoHostControlAdapter"


def test_qwen3_monarch_control_plane_smoke_script_runs_actor_with_fake_runtime(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    runtime = FakeRuntime(tmp_path=tmp_path)
    manifest_path = tmp_path / "results" / "parent-manifest.json"

    result = module.run_smoke(
        declared_spec=tmp_path / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml",
        local_environment=tmp_path / "ginkgo" / "local-env" / "qwen3-sglang.yaml",
        repo_root=tmp_path,
        run_id="qwen3-actor-smoke",
        manifest_path=manifest_path,
        runtime=runtime,
    )

    assert result["manifest"] == str(manifest_path)
    assert result["status"]["phase"] == "probe:sglang_backend"
    assert result["status"]["completed_components"] == ["sglang_backend"]
    assert result["launch"]["openai_base_url"] == "http://127.0.0.1:19007/v1"
    assert result["probe"]["ready"] == "true"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "passed"
    assert manifest["execution_mode"] == "monarch-actor-control"
    assert manifest["run_id"] == "qwen3-actor-smoke"
    assert manifest["profile"] == "serving-smoke-cpu"
    assert manifest["evidence_boundary"] == "fake_runtime_contract"
    assert manifest["declared_config_ref"] == "repo://ginkgo/configs/smoke-qwen3-cpu.yaml"
    assert manifest["local_environment_ref"] == "local-env://qwen3-sglang.yaml"
    assert manifest["components"]["sglang_backend"]["openai_base_url"] == "http://127.0.0.1:19007/v1"
    assert manifest["components"]["sglang_backend"]["ready"] == "true"
    assert manifest["components"]["sglang_backend"]["teardown_status"] == "teardown_passed"
    assert manifest["actor_status"]["status"] == "passed"
    assert runtime.calls == [
        "load_declared:smoke-qwen3-cpu.yaml",
        "load_local:qwen3-sglang.yaml",
        "materialize:qwen3-actor-smoke-sglang_backend:None",
        "stable_preparation_paths",
        "write_materialized",
        "validate_preparation",
        "launch",
        "load_effective_materialized",
        "models",
        "chat",
        "teardown",
    ]


def test_qwen3_monarch_control_plane_smoke_verifies_manifest_when_requested(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    runtime = FakeRuntime(tmp_path=tmp_path)
    manifest_path = tmp_path / "results" / "parent-manifest.json"
    calls: list[dict[str, object]] = []

    def fake_verify(path: Path, **kwargs: object) -> dict[str, object]:
        calls.append({"path": path, **kwargs})
        return {
            "status": "passed",
            "run_id": "qwen3-actor-smoke",
            "component": "sglang_backend",
        }

    result = module.run_smoke(
        declared_spec=tmp_path / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml",
        local_environment=tmp_path / "ginkgo" / "local-env" / "qwen3-sglang.yaml",
        repo_root=tmp_path,
        run_id="qwen3-actor-smoke",
        manifest_path=manifest_path,
        runtime=runtime,
        verify_artifact=True,
        artifact_verifier=fake_verify,
    )

    assert result["artifact_verification"] == {
        "status": "passed",
        "run_id": "qwen3-actor-smoke",
        "component": "sglang_backend",
    }
    assert calls == [
        {
            "path": manifest_path,
            "expected_execution_mode": "monarch-actor-control",
            "expected_evidence_boundary": "fake_runtime_contract",
            "expected_generated_text": "OK",
            "expected_child_device": "cpu",
        }
    ]


def test_qwen3_monarch_control_plane_smoke_fails_when_artifact_verification_fails(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    verifier = load_control_plane_verifier_script()
    runtime = FakeRuntime(tmp_path=tmp_path)
    manifest_path = tmp_path / "results" / "parent-manifest.json"

    def fake_verify(path: Path, **kwargs: object) -> dict[str, object]:
        del path, kwargs
        raise verifier.VerificationError("artifact drift")

    with pytest.raises(verifier.VerificationError, match="artifact drift"):
        module.run_smoke(
            declared_spec=tmp_path / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml",
            local_environment=tmp_path / "ginkgo" / "local-env" / "qwen3-sglang.yaml",
            repo_root=tmp_path,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
            runtime=runtime,
            verify_artifact=True,
            artifact_verifier=fake_verify,
        )

    assert json.loads(manifest_path.read_text())["status"] == "passed"


def test_qwen3_monarch_control_plane_smoke_writes_failure_manifest(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    runtime = FakeRuntime(tmp_path=tmp_path)
    manifest_path = tmp_path / "results" / "failed-parent-manifest.json"

    def fail_chat(config: object) -> dict[str, object]:
        del config
        runtime.calls.append("chat")
        raise RuntimeError("chat probe failed")

    runtime.probe_chat = fail_chat  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="chat probe failed"):
        module.run_smoke(
            declared_spec=tmp_path / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml",
            local_environment=tmp_path / "ginkgo" / "local-env" / "qwen3-sglang.yaml",
            repo_root=tmp_path,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
            runtime=runtime,
        )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "failed"
    assert manifest["execution_mode"] == "monarch-actor-control"
    assert manifest["run_id"] == "qwen3-actor-smoke"
    assert manifest["evidence_boundary"] == "fake_runtime_contract"
    assert manifest["failure"] == {
        "exception_type": "RuntimeError",
        "failed_component": "sglang_backend",
        "message": "chat probe failed",
        "phase": "launch:sglang_backend",
        "teardown_errors": [],
        "terminal_phase": "failed",
    }
    assert manifest["actor_status"]["status"] == "failed"
    assert manifest["actor_status"]["phase"] == "failed"
    assert manifest["actor_status"]["failed_phase"] == "launch:sglang_backend"
    assert manifest["actor_status"]["state"]["parent"]["run_id"] == "qwen3-actor-smoke"
    assert runtime.calls[-1] == "teardown"


def test_qwen3_monarch_control_plane_smoke_live_delegates_to_host_child(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    repo_root = tmp_path
    declared_spec = repo_root / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml"
    local_environment = repo_root / "ginkgo" / "local-env" / "qwen3-sglang.yaml"
    manifest_path = tmp_path / "results" / "parent-manifest.json"
    child_manifest = (
        repo_root
        / "glm52-serving-results"
        / "qwen3-actor-smoke-sglang_backend"
        / "qwen3-sglang-smoke-evidence.json"
    )
    write_qwen3_child_manifest(child_manifest, generated_text="hello from child")
    calls: list[list[str]] = []

    def fake_child_runner(argv: list[str], *, env: dict[str, str]) -> object:
        calls.append(argv)
        assert env["GINKGO_QWEN3_CHILD_EVIDENCE_MANIFEST"] == str(child_manifest)
        return subprocess.CompletedProcess(argv, 0, stdout="child ok\n", stderr="")

    result = module.run_smoke(
        declared_spec=declared_spec,
        local_environment=local_environment,
        repo_root=repo_root,
        run_id="qwen3-actor-smoke",
        manifest_path=manifest_path,
        child_runner=fake_child_runner,
        child_port_probe=closed_port_probe,
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "passed"
    assert manifest["execution_mode"] == "host-control adapter"
    assert manifest["run_id"] == "qwen3-actor-smoke"
    assert manifest["evidence_boundary"] == "live_qwen3_host_child_smoke"
    assert manifest["components"]["sglang_backend"] == {
        "evidence_manifest": str(child_manifest),
        "generated_text": "hello from child",
        "openai_base_url": "http://127.0.0.1:19007/v1",
        "port": "19007",
        "ready": "true",
        "run_id": "qwen3-actor-smoke-sglang_backend",
        "status": "passed",
        "teardown_status": "teardown_passed",
    }
    assert result["launch"]["teardown_status"] == "teardown_passed"
    assert result["status"]["phase"] == "host_child_completed"
    assert calls == [
        [
            str(repo_root / "ginkgo" / "scripts" / "run_qwen3_sglang_inference_in_bwrap_rootfs.sh"),
            "--declared-spec",
            str(declared_spec),
            "--local-environment",
            str(local_environment),
            "--run-id",
            "qwen3-actor-smoke-sglang_backend",
        ]
    ]


def test_qwen3_monarch_control_plane_smoke_live_rejects_open_child_port(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    repo_root = tmp_path
    declared_spec = repo_root / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml"
    local_environment = repo_root / "ginkgo" / "local-env" / "qwen3-sglang.yaml"
    manifest_path = tmp_path / "results" / "failed-parent-manifest.json"
    child_manifest = (
        repo_root
        / "glm52-serving-results"
        / "qwen3-actor-smoke-sglang_backend"
        / "qwen3-sglang-smoke-evidence.json"
    )
    write_qwen3_child_manifest(child_manifest, generated_text="hello from child")

    def fake_child_runner(argv: list[str], *, env: dict[str, str]) -> object:
        del env
        return subprocess.CompletedProcess(argv, 0, stdout="child ok\n", stderr="")

    def open_port(host: str, port: int, timeout_seconds: float) -> int:
        assert host == "127.0.0.1"
        assert port == 19007
        assert timeout_seconds == 1.0
        return 0

    with pytest.raises(module.ChildRunError, match="serving port is still open after teardown"):
        module.run_smoke(
            declared_spec=declared_spec,
            local_environment=local_environment,
            repo_root=repo_root,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
            child_runner=fake_child_runner,
            child_port_probe=open_port,
        )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "failed"
    assert manifest["execution_mode"] == "host-control adapter"
    assert manifest["failure"]["phase"] == "host_child_failed"
    assert "serving port is still open after teardown" in manifest["failure"]["message"]


def test_qwen3_monarch_control_plane_smoke_live_requires_child_summary_fields(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    repo_root = tmp_path
    declared_spec = repo_root / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml"
    local_environment = repo_root / "ginkgo" / "local-env" / "qwen3-sglang.yaml"
    manifest_path = tmp_path / "results" / "parent-manifest.json"
    child_manifest = (
        repo_root
        / "glm52-serving-results"
        / "qwen3-actor-smoke-sglang_backend"
        / "qwen3-sglang-smoke-evidence.json"
    )
    child_manifest.parent.mkdir(parents=True)
    child_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": "qwen3-actor-smoke-sglang_backend",
                "port": 19007,
                "response": {"generated_text": "nested-only output"},
            }
        )
        + "\n"
    )

    def fake_child_runner(argv: list[str], *, env: dict[str, str]) -> object:
        del env
        return subprocess.CompletedProcess(argv, 0, stdout="child ok\n", stderr="")

    with pytest.raises(module.ChildRunError, match="child artifact verification failed"):
        module.run_smoke(
            declared_spec=declared_spec,
            local_environment=local_environment,
            repo_root=repo_root,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
            child_runner=fake_child_runner,
            child_port_probe=closed_port_probe,
        )


def test_qwen3_monarch_control_plane_smoke_live_rejects_child_manifest_that_fails_verifier(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    repo_root = tmp_path
    declared_spec = repo_root / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml"
    local_environment = repo_root / "ginkgo" / "local-env" / "qwen3-sglang.yaml"
    manifest_path = tmp_path / "results" / "failed-parent-manifest.json"
    child_manifest = (
        repo_root
        / "glm52-serving-results"
        / "qwen3-actor-smoke-sglang_backend"
        / "qwen3-sglang-smoke-evidence.json"
    )
    child_manifest.parent.mkdir(parents=True)
    child_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": "qwen3-actor-smoke-sglang_backend",
                "port": 19007,
                "openai_base_url": "http://127.0.0.1:19007/v1",
                "generated_text": "nested-only output",
                "teardown_status": "teardown_passed",
                "response": {"generated_text": "nested-only output"},
            }
        )
        + "\n"
    )

    def fake_child_runner(argv: list[str], *, env: dict[str, str]) -> object:
        del env
        return subprocess.CompletedProcess(argv, 0, stdout="child ok\n", stderr="")

    with pytest.raises(module.ChildRunError, match="child artifact verification failed"):
        module.run_smoke(
            declared_spec=declared_spec,
            local_environment=local_environment,
            repo_root=repo_root,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
            child_runner=fake_child_runner,
            child_port_probe=closed_port_probe,
        )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "failed"
    assert manifest["execution_mode"] == "host-control adapter"
    assert manifest["failure"]["phase"] == "host_child_failed"
    assert "child artifact verification failed" in manifest["failure"]["message"]


def test_qwen3_monarch_control_plane_smoke_live_requires_child_manifest(tmp_path) -> None:
    module = load_control_plane_smoke_script()
    manifest_path = tmp_path / "results" / "failed-parent-manifest.json"

    def fake_child_runner(argv: list[str], *, env: dict[str, str]) -> object:
        del env
        return subprocess.CompletedProcess(argv, 0, stdout="child ok\n", stderr="")

    with pytest.raises(module.ChildRunError, match="host child evidence manifest missing"):
        module.run_smoke(
            declared_spec=tmp_path / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml",
            local_environment=tmp_path / "ginkgo" / "local-env" / "qwen3-sglang.yaml",
            repo_root=tmp_path,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
            child_runner=fake_child_runner,
            child_port_probe=closed_port_probe,
        )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "failed"
    assert manifest["execution_mode"] == "host-control adapter"
    assert manifest["failure"]["phase"] == "host_child_failed"
    assert manifest["failure"]["exception_type"] == "ChildRunError"
    assert "host child evidence manifest missing" in manifest["failure"]["message"]
    assert manifest["execution_domain"] == {
        "monarch_import_domain": "requires_rootfs",
        "ginkgo_child_domain": "host_control_child_process",
        "supported": True,
    }


def test_qwen3_monarch_control_plane_smoke_live_rejects_default_child_from_rootfs(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_control_plane_smoke_script()
    manifest_path = tmp_path / "results" / "failed-parent-manifest.json"
    monkeypatch.setenv("MONARCH_IN_ROOTFS", "1")

    with pytest.raises(module.ExecutionDomainError, match="host child mode must run from the host"):
        module.run_smoke(
            declared_spec=tmp_path / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml",
            local_environment=tmp_path / "ginkgo" / "local-env" / "qwen3-sglang.yaml",
            repo_root=tmp_path,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
        )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "failed"
    assert manifest["execution_mode"] == "host-control adapter"
    assert manifest["failure"]["phase"] == "host_child_domain_preflight"
    assert manifest["failure"]["exception_type"] == "ExecutionDomainError"


def test_qwen3_monarch_control_plane_smoke_cli_selects_in_process_actor_mode() -> None:
    module = load_control_plane_smoke_script()

    args = module.build_parser().parse_args(["--mode", "in-process-actor"])

    assert args.mode == "in-process-actor"


def test_qwen3_monarch_control_plane_smoke_cli_parses_expected_child_device() -> None:
    module = load_control_plane_smoke_script()

    args = module.build_parser().parse_args(["--expected-child-device", "cuda"])

    assert args.expected_child_device == "cuda"


def test_qwen3_monarch_control_plane_in_process_actor_mode_preflights_rootfs_paths(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_control_plane_smoke_script()
    repo_root = tmp_path
    declared_spec = repo_root / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml"
    local_environment = repo_root / "ginkgo" / "local-env" / "qwen3-sglang.yaml"
    manifest_path = tmp_path / "results" / "failed-parent-manifest.json"
    _write_local_environment(
        local_environment,
        repo="/data02/home/philip.yang/workspace/monarch",
        cache="/data02/home/philip.yang/workspace/monarch/.scratch/glm52-local-serving/cache/ginkgo",
        temp="/data02/home/philip.yang/workspace/monarch/.scratch/glm52-local-serving/tmp/ginkgo",
        rootfs="/data02/home/philip.yang/workspace/monarch/scripts/rootfs/rootfs",
    )
    monkeypatch.setenv("MONARCH_IN_ROOTFS", "1")

    with pytest.raises(module.ExecutionDomainError, match="not reachable from in-process actor namespace"):
        module.run_smoke(
            declared_spec=declared_spec,
            local_environment=local_environment,
            repo_root=repo_root,
            run_id="qwen3-actor-smoke",
            manifest_path=manifest_path,
            mode="in-process-actor",
        )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "failed"
    assert manifest["execution_mode"] == "monarch-actor-control"
    assert manifest["evidence_boundary"] == "live_qwen3_in_process_actor_smoke"
    assert manifest["local_environment_ref"] == "local-env://.generated/qwen3-actor-smoke/in-process-actor.yaml"
    assert manifest["execution_domain"]["local_environment"] == str(
        repo_root / "ginkgo" / "local-env" / ".generated" / "qwen3-actor-smoke" / "in-process-actor.yaml"
    )
    assert manifest["failure"]["phase"] == "actor_domain_preflight"
    assert manifest["failure"]["exception_type"] == "ExecutionDomainError"


def test_qwen3_monarch_control_plane_in_process_actor_mode_projects_local_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_control_plane_smoke_script()
    repo_root = tmp_path
    host_local_environment = repo_root / "ginkgo" / "local-env" / "qwen3-sglang.yaml"
    _write_local_environment(
        host_local_environment,
        repo="/data02/home/philip.yang/workspace/monarch",
        cache="/data02/home/philip.yang/workspace/monarch/.scratch/glm52-local-serving/cache/ginkgo",
        temp="/data02/home/philip.yang/workspace/monarch/.scratch/glm52-local-serving/tmp/ginkgo",
        rootfs="/data02/home/philip.yang/workspace/monarch/scripts/rootfs/rootfs",
    )
    monkeypatch.setenv("MONARCH_IN_ROOTFS", "1")
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    projected_path, projected_ref = module._materialize_in_process_actor_local_environment(
        repo_root=repo_root,
        local_environment=host_local_environment,
        run_id="qwen3-actor-smoke",
    )

    assert projected_ref == "local-env://.generated/qwen3-actor-smoke/in-process-actor.yaml"
    assert projected_path == repo_root / "ginkgo" / "local-env" / ".generated" / "qwen3-actor-smoke" / "in-process-actor.yaml"
    projected = yaml.safe_load(projected_path.read_text())
    assert projected == {
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


def test_qwen3_monarch_control_plane_in_process_actor_mode_requires_nested_bwrap(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_control_plane_smoke_script()
    repo_root = tmp_path
    local_environment = repo_root / "ginkgo" / "local-env" / ".generated" / "qwen3-actor-smoke" / "in-process-actor.yaml"
    _write_local_environment(
        local_environment,
        repo=str(repo_root),
        cache=str(repo_root / ".scratch" / "glm52-local-serving" / "cache" / "ginkgo"),
        temp=str(repo_root / ".scratch" / "glm52-local-serving" / "tmp" / "ginkgo"),
        rootfs=str(repo_root / "scripts" / "rootfs" / "rootfs"),
    )
    for path in (
        repo_root / ".scratch" / "glm52-local-serving" / "cache" / "ginkgo",
        repo_root / ".scratch" / "glm52-local-serving" / "tmp" / "ginkgo",
        repo_root / "scripts" / "rootfs" / "rootfs",
    ):
        path.mkdir(parents=True)
    monkeypatch.setenv("MONARCH_IN_ROOTFS", "1")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    with pytest.raises(module.ExecutionDomainError, match="requires bwrap in the actor namespace"):
        module._preflight_in_process_actor_domain(local_environment=local_environment)


def test_qwen3_monarch_control_plane_verifier_accepts_passed_in_process_actor_manifest(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        port=19007,
        generated_text="Sure!",
    )

    result = verifier.verify_manifest(
        manifest_path,
        expected_execution_mode="monarch-actor-control",
        expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
        expected_generated_text="Sure!",
        check_port_closed=False,
    )

    assert result == {
        "status": "passed",
        "run_id": "qwen3-actor-smoke",
        "component": "sglang_backend",
        "child_run_id": "qwen3-actor-smoke-sglang_backend",
        "port": 19007,
        "generated_text": "Sure!",
        "teardown_status": "teardown_passed",
        "evidence_boundary": "live_qwen3_in_process_actor_smoke",
        "child_evidence_boundary": "live_qwen3_sglang_smoke",
        "child_model_id": "Qwen/Qwen3-0.6B",
        "child_device": "cpu",
        "execution_mode": "monarch-actor-control",
    }


def test_qwen3_monarch_control_plane_verifier_rejects_wrong_execution_mode(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="host-control adapter",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        port=19007,
        generated_text="Sure!",
    )

    with pytest.raises(verifier.VerificationError, match="execution_mode mismatch"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            check_port_closed=False,
        )


def test_qwen3_monarch_control_plane_verifier_rejects_missing_child_manifest(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        port=19007,
        generated_text="Sure!",
    )
    child_path = tmp_path / "glm52-serving-results" / "qwen3-actor-smoke-sglang_backend" / "qwen3-sglang-smoke-evidence.json"
    child_path.unlink()

    with pytest.raises(verifier.VerificationError, match="child artifact verification failed"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            check_port_closed=False,
        )


def test_qwen3_monarch_control_plane_verifier_rejects_child_boundary_mismatch(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        child_evidence_boundary="fixture_child_smoke",
        port=19007,
        generated_text="Sure!",
    )

    with pytest.raises(verifier.VerificationError, match="child artifact verification failed"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            check_port_closed=False,
        )


def test_qwen3_monarch_control_plane_verifier_rejects_child_model_mismatch(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        child_model_id="Other/Model",
        port=19007,
        generated_text="Sure!",
    )

    with pytest.raises(verifier.VerificationError, match="child artifact verification failed"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            check_port_closed=False,
        )


def test_qwen3_monarch_control_plane_verifier_rejects_child_device_mismatch(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        child_device="cuda",
        port=19007,
        generated_text="Sure!",
    )

    with pytest.raises(verifier.VerificationError, match="child artifact verification failed"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            check_port_closed=False,
        )


def test_qwen3_monarch_control_plane_verifier_cli_rejects_child_device_mismatch(tmp_path: Path) -> None:
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        child_device="cuda",
        port=19007,
        generated_text="Sure!",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(CONTROL_PLANE_VERIFIER),
            str(manifest_path),
            "--expected-execution-mode",
            "monarch-actor-control",
            "--expected-evidence-boundary",
            "live_qwen3_in_process_actor_smoke",
            "--expected-child-device",
            "cpu",
            "--skip-port-closed-check",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "child artifact verification failed" in completed.stderr
    assert "device mismatch" in completed.stderr


def test_qwen3_monarch_control_plane_verifier_rejects_malformed_child_response(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        port=19007,
        generated_text="Sure!",
    )
    child_path = tmp_path / "glm52-serving-results" / "qwen3-actor-smoke-sglang_backend" / "qwen3-sglang-smoke-evidence.json"
    child = json.loads(child_path.read_text())
    child["response"].pop("payload")
    child_path.write_text(json.dumps(child, indent=2, sort_keys=True) + "\n")

    with pytest.raises(verifier.VerificationError, match="child artifact verification failed"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            check_port_closed=False,
        )


def test_qwen3_monarch_control_plane_verifier_rejects_missing_teardown_status(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        port=19007,
        generated_text="Sure!",
        teardown_status=None,
    )

    with pytest.raises(verifier.VerificationError, match="component teardown_status must be teardown_passed"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            check_port_closed=False,
        )


def test_qwen3_monarch_control_plane_verifier_rejects_open_port(tmp_path: Path) -> None:
    verifier = load_control_plane_verifier_script()
    manifest_path = write_control_plane_evidence_pair(
        tmp_path,
        run_id="qwen3-actor-smoke",
        execution_mode="monarch-actor-control",
        evidence_boundary="live_qwen3_in_process_actor_smoke",
        port=19007,
        generated_text="Sure!",
    )

    def open_port(host: str, port: int, timeout_seconds: float) -> int:
        assert host == "127.0.0.1"
        assert port == 19007
        assert timeout_seconds == 1.0
        return 0

    with pytest.raises(verifier.VerificationError, match="serving port is still open after teardown"):
        verifier.verify_manifest(
            manifest_path,
            expected_execution_mode="monarch-actor-control",
            expected_evidence_boundary="live_qwen3_in_process_actor_smoke",
            port_probe=open_port,
        )


async def test_qwen3_host_control_actor_constructs_adapter_from_repo_root_and_runtime(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    run = qwen3_cpu_control_run()
    actor = Qwen3HostControlPlaneActor(run, tmp_path, runtime)

    assert await _call_actor_endpoint(actor, "prepare") == {
        "run_id": "qwen3-actor-smoke",
        "local_environment": str(tmp_path / "ginkgo" / "local-env" / "qwen3-sglang.yaml"),
    }
    launch_state = await _call_actor_endpoint(actor, "launch", "sglang_backend")
    assert launch_state["openai_base_url"] == "http://127.0.0.1:19007/v1"
    assert launch_state["generated_text"] == "OK"
    assert launch_state["teardown_status"] == "teardown_passed"
    assert await _call_actor_endpoint(actor, "probe", "sglang_backend") == {
        "ready": "true",
        "evidence_manifest": launch_state["evidence_manifest"],
    }

    status = await _call_actor_endpoint(actor, "status")

    assert status["phase"] == "probe:sglang_backend"
    assert status["completed_components"] == ["sglang_backend"]
    assert runtime.calls[-3:] == ["models", "chat", "teardown"]


def test_actor_exposes_control_plane_endpoint_shape() -> None:
    endpoint_names = {
        "prepare",
        "launch",
        "probe",
        "teardown",
        "status",
        "cancel",
    }

    for name in endpoint_names:
        assert hasattr(getattr(GinkgoControlPlaneActor, name), "_method")


async def test_actor_endpoints_delegate_to_adapter_and_preserve_state() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter()
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    assert await _call_actor_endpoint(actor, "prepare") == {"manifest": "run://parent/manifest.json"}
    assert await _call_actor_endpoint(actor, "launch", "sglang_backend") == {
        "openai_base_url": "http://127.0.0.1:19000/v1"
    }
    assert await _call_actor_endpoint(actor, "probe", "sglang_backend") == {"ready": "true"}
    assert await _call_actor_endpoint(actor, "launch", "dynamo_frontend") == {
        "openai_base_url": "http://127.0.0.1:19001/v1"
    }
    assert await _call_actor_endpoint(actor, "teardown", "dynamo_frontend") == {"closed": "true"}

    status = await _call_actor_endpoint(actor, "status")

    assert status["phase"] == "teardown:dynamo_frontend"
    assert status["state"]["sglang_backend"]["ready"] == "true"
    assert status["state"]["dynamo_frontend"]["closed"] == "true"
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "launch:dynamo_frontend:upstream=http://127.0.0.1:19000/v1",
        "teardown:dynamo_frontend",
    ]


async def test_actor_records_launch_failure_in_status() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter(fail_launch_for="dynamo_frontend")
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    await _call_actor_endpoint(actor, "prepare")
    await _call_actor_endpoint(actor, "launch", "sglang_backend")
    await _call_actor_endpoint(actor, "probe", "sglang_backend")

    with pytest.raises(RuntimeError, match="launch failed for dynamo_frontend"):
        await _call_actor_endpoint(actor, "launch", "dynamo_frontend")

    status = await _call_actor_endpoint(actor, "status")

    assert status["phase"] == "failed"
    assert status["failed_component"] == "dynamo_frontend"
    assert status["failed_phase"] == "launch:dynamo_frontend"
    assert status["error"] == "launch failed for dynamo_frontend"
    assert status["state"]["sglang_backend"]["ready"] == "true"
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "launch:dynamo_frontend:upstream=http://127.0.0.1:19000/v1",
        "teardown:sglang_backend",
    ]


async def test_actor_records_probe_failure_in_status() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter(fail_probe_for="dynamo_frontend")
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    await _call_actor_endpoint(actor, "prepare")
    await _call_actor_endpoint(actor, "launch", "sglang_backend")
    await _call_actor_endpoint(actor, "probe", "sglang_backend")
    await _call_actor_endpoint(actor, "launch", "dynamo_frontend")

    with pytest.raises(RuntimeError, match="probe failed for dynamo_frontend"):
        await _call_actor_endpoint(actor, "probe", "dynamo_frontend")

    status = await _call_actor_endpoint(actor, "status")

    assert status["phase"] == "failed"
    assert status["failed_component"] == "dynamo_frontend"
    assert status["failed_phase"] == "probe:dynamo_frontend"
    assert status["error"] == "probe failed for dynamo_frontend"
    assert status["state"]["dynamo_frontend"]["openai_base_url"] == "http://127.0.0.1:19001/v1"
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "launch:dynamo_frontend:upstream=http://127.0.0.1:19000/v1",
        "probe:dynamo_frontend",
        "teardown:dynamo_frontend",
        "teardown:sglang_backend",
    ]


async def test_actor_preserves_primary_failure_when_teardown_fails() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter(
        fail_probe_for="dynamo_frontend",
        fail_teardown_for="sglang_backend",
    )
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    await _call_actor_endpoint(actor, "prepare")
    await _call_actor_endpoint(actor, "launch", "sglang_backend")
    await _call_actor_endpoint(actor, "probe", "sglang_backend")
    await _call_actor_endpoint(actor, "launch", "dynamo_frontend")

    with pytest.raises(RuntimeError, match="probe failed for dynamo_frontend"):
        await _call_actor_endpoint(actor, "probe", "dynamo_frontend")

    status = await _call_actor_endpoint(actor, "status")

    assert status["phase"] == "failed"
    assert status["failed_component"] == "dynamo_frontend"
    assert status["failed_phase"] == "probe:dynamo_frontend"
    assert status["error"] == "probe failed for dynamo_frontend"
    assert status["teardown_errors"] == [
        {
            "component": "sglang_backend",
            "error": "teardown failed for sglang_backend",
        }
    ]
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "probe:sglang_backend",
        "launch:dynamo_frontend:upstream=http://127.0.0.1:19000/v1",
        "probe:dynamo_frontend",
        "teardown:dynamo_frontend",
        "teardown:sglang_backend",
    ]


async def test_actor_launch_requires_completed_dependencies() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter()
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    await _call_actor_endpoint(actor, "prepare")
    await _call_actor_endpoint(actor, "launch", "sglang_backend")

    with pytest.raises(ControlPlaneConfigError, match="dependency not completed"):
        await _call_actor_endpoint(actor, "launch", "dynamo_frontend")

    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
    ]


async def test_actor_launch_rejects_already_launched_component() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter()
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    await _call_actor_endpoint(actor, "prepare")
    await _call_actor_endpoint(actor, "launch", "sglang_backend")

    with pytest.raises(ControlPlaneConfigError, match="component already launched"):
        await _call_actor_endpoint(actor, "launch", "sglang_backend")

    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
    ]


async def test_actor_lifecycle_endpoints_require_prepare_first() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter()
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    for endpoint_name in ("launch", "probe", "teardown"):
        with pytest.raises(ControlPlaneConfigError, match="must be prepared before lifecycle endpoints"):
            await _call_actor_endpoint(actor, endpoint_name, "sglang_backend")

    assert adapter.events == []


async def test_actor_teardown_requires_launched_component() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter()
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    await _call_actor_endpoint(actor, "prepare")

    with pytest.raises(ControlPlaneConfigError, match="component has not launched"):
        await _call_actor_endpoint(actor, "teardown", "sglang_backend")

    assert adapter.events == ["prepare:ginkgo-parent-001"]


async def test_actor_cancel_endpoint_tears_down_launched_components() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    adapter = FakeControlPlaneAdapter()
    actor = GinkgoControlPlaneActor(run=run, adapter=adapter)

    await _call_actor_endpoint(actor, "prepare")
    await _call_actor_endpoint(actor, "launch", "sglang_backend")

    assert await _call_actor_endpoint(actor, "cancel") == {"status": "cancelled"}
    assert await _call_actor_endpoint(actor, "status") == {
        "phase": "cancelled",
        "completed_components": [],
        "failed_component": None,
        "failed_phase": None,
        "teardown_errors": [],
        "error": None,
        "state": {
            "parent": {"manifest": "run://parent/manifest.json"},
            "sglang_backend": {
                "closed": "true",
                "openai_base_url": "http://127.0.0.1:19000/v1",
            },
        },
    }
    assert adapter.events == [
        "prepare:ginkgo-parent-001",
        "launch:sglang_backend:upstream=None",
        "teardown:sglang_backend",
    ]


@isolate_in_subprocess
def test_actor_runs_through_local_proc_mesh_with_fake_adapter() -> None:
    run = control_plane_run_from_mapping(VALID_RUN)
    proc = this_host().spawn_procs(per_host={"processes": 1})
    actor = proc.spawn("ginkgo_control_plane", GinkgoControlPlaneActor, run, FakeControlPlaneAdapter())

    try:
        assert actor.prepare.call_one().get() == {"manifest": "run://parent/manifest.json"}
        assert actor.launch.call_one("sglang_backend").get() == {
            "openai_base_url": "http://127.0.0.1:19000/v1"
        }
        assert actor.probe.call_one("sglang_backend").get() == {"ready": "true"}
        assert actor.launch.call_one("dynamo_frontend").get() == {
            "openai_base_url": "http://127.0.0.1:19001/v1"
        }
        assert actor.cancel.call_one().get() == {"status": "cancelled"}
        status = actor.status.call_one().get()
    finally:
        proc.stop().get()

    assert status["phase"] == "cancelled"
    assert status["state"]["sglang_backend"]["ready"] == "true"
    assert status["state"]["dynamo_frontend"]["openai_base_url"] == "http://127.0.0.1:19001/v1"


async def _call_actor_endpoint(actor: object, name: str, *args: object) -> object:
    endpoint_property = getattr(type(actor), name)
    return await endpoint_property._method(actor, *args)


def load_control_plane_smoke_script() -> object:
    spec = importlib.util.spec_from_file_location("run_qwen3_monarch_control_plane_smoke", CONTROL_PLANE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_qwen3_monarch_control_plane_smoke"] = module
    spec.loader.exec_module(module)
    return module


def load_control_plane_verifier_script() -> object:
    spec = importlib.util.spec_from_file_location("verify_qwen3_monarch_control_plane_smoke", CONTROL_PLANE_VERIFIER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_qwen3_monarch_control_plane_smoke"] = module
    spec.loader.exec_module(module)
    return module


def qwen3_cpu_control_run() -> object:
    return control_plane_run_from_mapping(
        {
            **VALID_RUN,
            "run_id": "qwen3-actor-smoke",
            "profile": "serving-smoke-cpu",
            "declared_config_ref": "repo://ginkgo/configs/smoke-qwen3-cpu.yaml",
            "local_environment_ref": "local-env://qwen3-sglang.yaml",
            "components": [
                {
                    **VALID_RUN["components"][0],
                    "declared_ref": "repo://ginkgo/configs/smoke-qwen3-cpu.yaml",
                }
            ],
        }
    )


def write_control_plane_evidence_pair(
    tmp_path: Path,
    *,
    run_id: str,
    execution_mode: str,
    evidence_boundary: str,
    child_evidence_boundary: str = "live_qwen3_sglang_smoke",
    child_model_id: str = "Qwen/Qwen3-0.6B",
    child_device: str = "cpu",
    port: int,
    generated_text: str,
    teardown_status: str | None = "teardown_passed",
) -> Path:
    child_run_id = f"{run_id}-sglang_backend"
    results_dir = tmp_path / "glm52-serving-results"
    parent_path = results_dir / run_id / "monarch-control-plane-manifest.json"
    child_path = results_dir / child_run_id / "qwen3-sglang-smoke-evidence.json"
    child_path.parent.mkdir(parents=True)
    child: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "run_id": child_run_id,
        "evidence_boundary": child_evidence_boundary,
        "workload": "qwen3",
        "device": child_device,
        "model_id": child_model_id,
        "served_model_name": child_model_id,
        "expected_model_ids": [child_model_id],
        "port": port,
        "openai_base_url": f"http://127.0.0.1:{port}/v1",
        "generated_text": generated_text,
        "request": {
            "url": f"http://127.0.0.1:{port}/v1/chat/completions",
            "payload": {"model": child_model_id},
        },
        "response": {
            "generated_text": generated_text,
            "payload": {"choices": [{"message": {"content": generated_text}}]},
        },
        "models": {
            "models": [child_model_id],
            "payload": {"data": [{"id": child_model_id}]},
        },
    }
    if teardown_status is not None:
        child["teardown_status"] = teardown_status
        child["teardown"] = {"status": teardown_status, "run_id": child_run_id, "port": port}
    child_path.write_text(json.dumps(child, indent=2, sort_keys=True) + "\n")

    component: dict[str, object] = {
        "status": "passed",
        "run_id": child_run_id,
        "port": str(port),
        "openai_base_url": f"http://127.0.0.1:{port}/v1",
        "generated_text": generated_text,
        "ready": "true",
        "evidence_manifest": str(child_path),
    }
    if teardown_status is not None:
        component["teardown_status"] = teardown_status
    parent_path.parent.mkdir(parents=True)
    parent_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": run_id,
                "profile": "serving-smoke-cpu",
                "execution_mode": execution_mode,
                "evidence_boundary": evidence_boundary,
                "components": {"sglang_backend": component},
                "actor_status": {
                    "status": "passed",
                    "phase": "probe:sglang_backend",
                    "completed_components": ["sglang_backend"],
                    "teardown_errors": [],
                    "state": {"sglang_backend": component},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return parent_path


def write_qwen3_child_manifest(
    path: Path,
    *,
    run_id: str = "qwen3-actor-smoke-sglang_backend",
    port: int = 19007,
    generated_text: str,
    device: str = "cpu",
    model_id: str = "Qwen/Qwen3-0.6B",
) -> None:
    path.parent.mkdir(parents=True)
    base_url = f"http://127.0.0.1:{port}/v1"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": run_id,
                "workload": "qwen3",
                "evidence_boundary": "live_qwen3_sglang_smoke",
                "device": device,
                "model_id": model_id,
                "served_model_name": model_id,
                "expected_model_ids": [model_id],
                "port": port,
                "openai_base_url": base_url,
                "generated_text": generated_text,
                "teardown_status": "teardown_passed",
                "request": {
                    "url": f"{base_url}/chat/completions",
                    "payload": {"model": model_id},
                },
                "response": {
                    "generated_text": generated_text,
                    "payload": {"choices": [{"message": {"content": generated_text}}]},
                },
                "models": {
                    "models": [model_id],
                    "payload": {"data": [{"id": model_id}]},
                },
                "teardown": {"status": "teardown_passed"},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def closed_port_probe(host: str, port: int, timeout_seconds: float) -> int:
    del host, port, timeout_seconds
    return 111


def _write_local_environment(path: Path, *, repo: str, cache: str, temp: str, rootfs: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "roots:",
                f"  repo: {repo}",
                f"  cache: {cache}",
                f"  temp: {temp}",
                "rootfs:",
                f"  monarch-default: {rootfs}",
                "",
            ]
        )
    )


class FakeControlPlaneAdapter:
    def __init__(
        self,
        *,
        fail_launch_for: str | None = None,
        fail_probe_for: str | None = None,
        fail_teardown_for: str | None = None,
        cancel_after_probe: str | None = None,
    ) -> None:
        self.fail_launch_for = fail_launch_for
        self.fail_probe_for = fail_probe_for
        self.fail_teardown_for = fail_teardown_for
        self.cancel_after_probe = cancel_after_probe
        self.events: list[str] = []
        self.cancelled = False

    def prepare(self, run: object) -> dict[str, str]:
        self.events.append(f"prepare:{run.run_id}")
        return {"manifest": "run://parent/manifest.json"}

    def launch(self, component: object, upstream_url: str | None) -> dict[str, str]:
        self.events.append(f"launch:{component.name}:upstream={upstream_url}")
        if component.name == self.fail_launch_for:
            raise RuntimeError(f"launch failed for {component.name}")
        if component.name == "sglang_backend":
            return {"openai_base_url": "http://127.0.0.1:19000/v1"}
        if component.name == "dynamo_frontend":
            return {"openai_base_url": "http://127.0.0.1:19001/v1"}
        if component.name == "responses_adapter":
            return {"openai_base_url": "http://127.0.0.1:19002/v1"}
        raise AssertionError(f"unexpected component: {component.name}")

    def probe(self, component: object, component_state: dict[str, str]) -> dict[str, str]:
        del component_state
        self.events.append(f"probe:{component.name}")
        if component.name == self.fail_probe_for:
            raise RuntimeError(f"probe failed for {component.name}")
        if component.name == self.cancel_after_probe:
            self.cancelled = True
        return {"ready": "true"}

    def teardown(self, component: object, component_state: dict[str, str]) -> dict[str, str]:
        del component_state
        self.events.append(f"teardown:{component.name}")
        if component.name == self.fail_teardown_for:
            raise RuntimeError(f"teardown failed for {component.name}")
        return {"closed": "true"}

    def is_cancelled(self) -> bool:
        return self.cancelled


class FakeSglangLocalRunner:
    def __init__(self, result: LocalRunResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        *,
        declared_spec: object,
        local_environment: object,
        run_id: str | None = None,
        port: int | None = None,
        output: object | None = None,
    ) -> LocalRunResult:
        del output
        self.calls.append(
            {
                "declared_spec": declared_spec,
                "local_environment": local_environment,
                "run_id": run_id,
                "port": port,
            }
        )
        return self.result


class FakeRuntime:
    class RuntimeConfigError(RuntimeError):
        pass

    def __init__(self, *, tmp_path: Path) -> None:
        self.calls: list[str] = []
        self.tmp_path = tmp_path
        self.last_device = "cpu"

    def load_declared_spec(self, path: Path) -> object:
        self.calls.append(f"load_declared:{path.name}")
        return DeclaredSpecForControlPlaneTest(
            run_group="ginkgo-smoke-qwen3-cpu",
            port_range_start=19000,
            port_range_end=19100,
            disallowed_ports=[8000, 8080, 18080],
            device="cpu",
            cuda_visible_devices="",
            tensor_parallel_size=1,
        )

    def load_local_environment(self, path: Path) -> dict[str, str]:
        self.calls.append(f"load_local:{path.name}")
        return {"repo": str(self.tmp_path)}

    def materialize_runtime_config(
        self,
        *,
        declared: object,
        local_environment: object,
        run_id: str,
        port: int | None,
    ) -> object:
        del local_environment
        self.calls.append(f"materialize:{run_id}:{port}")
        self.last_device = getattr(declared, "device", "cpu")
        return MaterializedConfigForControlPlaneTest(
            run_id=run_id,
            port=port or 19007,
            run_dir=self.tmp_path / "results" / run_id,
            device=self.last_device,
        )

    def with_stable_preparation_record_paths(
        self,
        config: object,
        *,
        declared: object,
        local_environment: object,
    ) -> object:
        del declared, local_environment
        self.calls.append("stable_preparation_paths")
        return config

    def write_materialized_config(self, config: object, path: Path) -> None:
        del config
        self.calls.append("write_materialized")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("schema_version: 1\n")

    def validate_preparation_records(self, *, config: object) -> None:
        del config
        self.calls.append("validate_preparation")

    def launch_runtime(self, config: object, *, local_environment: object) -> dict[str, object]:
        del local_environment
        self.calls.append("launch")
        run_dir = config.run_dir
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs" / "stderr.log").write_text("INFO output=OK\n")
        (run_dir / "logs" / "stdout.log").write_text("server started\n")
        return {"status": "launch_passed", "run_id": config.run_id, "port": config.port}

    def load_materialized_config(self, path: Path) -> object:
        self.calls.append("load_effective_materialized")
        return MaterializedConfigForControlPlaneTest(
            run_id=path.parent.name,
            port=19007,
            run_dir=path.parent,
            device=self.last_device,
        )

    def probe_models(self, config: object) -> dict[str, object]:
        del config
        self.calls.append("models")
        return {"models": ["Qwen/Qwen3-0.6B"]}

    def probe_chat(self, config: object) -> dict[str, object]:
        del config
        self.calls.append("chat")
        return {"content": "OK", "payload": {"choices": [{"message": {"content": "OK"}}]}}

    def teardown_runtime(self, config: object, *, local_environment: object) -> dict[str, object]:
        del local_environment
        self.calls.append("teardown")
        return {"status": "teardown_passed", "run_id": config.run_id, "port": config.port}


class DeclaredSpecForControlPlaneTest:
    def __init__(
        self,
        *,
        run_group: str,
        port_range_start: int,
        port_range_end: int,
        disallowed_ports: list[int],
        device: str,
        cuda_visible_devices: str,
        tensor_parallel_size: int,
    ) -> None:
        self.run_group = run_group
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end
        self.disallowed_ports = disallowed_ports
        self.device = device
        self.cuda_visible_devices = cuda_visible_devices
        self.tensor_parallel_size = tensor_parallel_size


class MaterializedConfigForControlPlaneTest:
    def __init__(self, *, run_id: str, port: int, run_dir: Path, device: str) -> None:
        self.run_id = run_id
        self.port = port
        self.run_dir = run_dir
        self.run_group = "ginkgo-smoke-qwen3-cpu"
        self.device = device

    @property
    def service(self) -> dict[str, object]:
        return {
            "bind_host": "127.0.0.1",
            "port": self.port,
            "base_url": f"http://127.0.0.1:{self.port}/v1",
            "expected_model_ids": ["Qwen/Qwen3-0.6B"],
        }

    @property
    def model(self) -> dict[str, object]:
        return {
            "id": "Qwen/Qwen3-0.6B",
            "path": "Qwen/Qwen3-0.6B",
            "served_model_name": "Qwen/Qwen3-0.6B",
            "expected_model_ids": ["Qwen/Qwen3-0.6B"],
        }

    @property
    def probes(self) -> dict[str, object]:
        return {
            "models_url": f"http://127.0.0.1:{self.port}/v1/models",
            "chat_url": f"http://127.0.0.1:{self.port}/v1/chat/completions",
            "chat_payload": {
                "model": "Qwen/Qwen3-0.6B",
                "messages": [{"role": "user", "content": "Say OK."}],
                "max_tokens": 2,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        }

    @property
    def runtime(self) -> dict[str, object]:
        return {
            "device": self.device,
            "cuda_visible_devices": "0" if self.device == "cuda" else "",
            "tensor_parallel_size": 1,
        }

    @property
    def sandbox(self) -> dict[str, object]:
        return {"gpu": "required" if self.device == "cuda" else "none"}
