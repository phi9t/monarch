from __future__ import annotations

import importlib.util
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ginkgo.local_run import RuntimeBackedLocalRunAdapter
from ginkgo.local_run import SglangLocalRun
from ginkgo.local_run import Qwen3SglangWorkload


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "ginkgo" / "scripts" / "run_qwen3_sglang_smoke.py"

spec = importlib.util.spec_from_file_location("run_qwen3_sglang_smoke", SCRIPT_PATH)
assert spec is not None
assert spec.loader is not None
run_qwen3_sglang_smoke = importlib.util.module_from_spec(spec)
sys.modules["run_qwen3_sglang_smoke"] = run_qwen3_sglang_smoke
spec.loader.exec_module(run_qwen3_sglang_smoke)


@dataclass(frozen=True)
class DeclaredSpecForTest:
    run_group: str
    port_range_start: int
    port_range_end: int
    disallowed_ports: list[int]
    device: str = "cuda"
    cuda_visible_devices: str = "0"
    tensor_parallel_size: int = 1


@dataclass(frozen=True)
class MaterializedConfigForTest:
    run_id: str
    port: int
    run_dir: Path
    run_group: str = "ginkgo-smoke-qwen3-dense"
    device: str = "cuda"

    @property
    def service(self) -> dict[str, Any]:
        return {
            "bind_host": "127.0.0.1",
            "port": self.port,
            "base_url": f"http://127.0.0.1:{self.port}/v1",
            "expected_model_ids": ["Qwen/Qwen3-0.6B"],
        }

    @property
    def model(self) -> dict[str, Any]:
        return {
            "id": "Qwen/Qwen3-0.6B",
            "path": "Qwen/Qwen3-0.6B",
            "served_model_name": "Qwen/Qwen3-0.6B",
            "expected_model_ids": ["Qwen/Qwen3-0.6B"],
        }

    @property
    def probes(self) -> dict[str, Any]:
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
    def runtime(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "cuda_visible_devices": "0" if self.device == "cuda" else "",
            "tensor_parallel_size": 1,
        }

    @property
    def sandbox(self) -> dict[str, Any]:
        return {"gpu": "required" if self.device == "cuda" else "none"}


class FakeRuntime:
    class RuntimeConfigError(RuntimeError):
        pass

    def __init__(self, *, tmp_path: Path) -> None:
        self.calls: list[str] = []
        self.tmp_path = tmp_path
        self.validate_errors: list[Exception] = []
        self.last_device = "cuda"

    def load_declared_spec(self, path: Path) -> Any:
        self.calls.append(f"load_declared:{path.name}")
        return DeclaredSpecForTest(
            run_group="ginkgo-smoke-qwen3-dense",
            port_range_start=19000,
            port_range_end=19100,
            disallowed_ports=[8000, 8080, 18080],
        )

    def load_local_environment(self, path: Path) -> dict[str, str]:
        self.calls.append(f"load_local:{path.name}")
        return {"repo": str(self.tmp_path / "repo")}

    def materialize_runtime_config(
        self,
        *,
        declared: Any,
        local_environment: Any,
        run_id: str,
        port: int | None,
    ) -> Any:
        self.calls.append(f"materialize:{run_id}:{port}")
        assert port == 19007
        self.last_device = getattr(declared, "device", "cuda")
        return MaterializedConfigForTest(
            run_id=run_id,
            port=port,
            run_dir=self.tmp_path / "results" / run_id,
            device=self.last_device,
        )

    def with_stable_preparation_record_paths(
        self,
        config: Any,
        *,
        declared: Any,
        local_environment: Any,
    ) -> Any:
        self.calls.append("stable_preparation_paths")
        return config

    def write_materialized_config(self, config: Any, path: Path) -> None:
        self.calls.append("write_materialized")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("schema_version: 1\n")

    def validate_preparation_records(self, *, config: Any) -> None:
        self.calls.append("validate_preparation")
        if self.validate_errors:
            raise self.validate_errors.pop(0)
        return {
            "sglang_venv": {"run_id": "prepare-venv"},
            "model_cache": {
                "model_cache": {
                    "snapshot_path": "/cache/glm52/hf-home/snapshots/qwen3",
                    "missing_shard_count": 0,
                },
            },
        }

    def prepare_sglang_venv(self, *, declared_path: Path, local_environment_path: Path) -> dict[str, Any]:
        self.calls.append(f"prepare_venv:{declared_path.name}:{local_environment_path.name}")
        return {"run_id": "prepare-venv"}

    def prepare_model_cache(self, *, declared_path: Path, local_environment_path: Path) -> dict[str, Any]:
        self.calls.append(f"prepare_model:{declared_path.name}:{local_environment_path.name}")
        return {"run_id": "prepare-model"}

    def launch_runtime(self, config: Any, *, local_environment: Any) -> dict[str, Any]:
        self.calls.append("launch")
        run_dir = config.run_dir
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs" / "stderr.log").write_text("INFO sglang request prompt=Say OK. output=OK\n")
        (run_dir / "logs" / "stdout.log").write_text("server started\n")
        return {"status": "launch_passed", "run_id": config.run_id, "port": config.port, "pid": 1234}

    def load_materialized_config(self, path: Path) -> Any:
        self.calls.append("load_effective_materialized")
        return MaterializedConfigForTest(
            run_id=path.parent.name,
            port=19007,
            run_dir=path.parent,
            device=self.last_device,
        )

    def probe_models(self, config: Any) -> dict[str, Any]:
        self.calls.append("models")
        return {"models": ["Qwen/Qwen3-0.6B"], "payload": {"data": [{"id": "Qwen/Qwen3-0.6B"}]}}

    def probe_chat(self, config: Any) -> dict[str, Any]:
        self.calls.append("chat")
        return {
            "content": "OK",
            "payload": {
                "choices": [{"message": {"role": "assistant", "content": "OK"}}],
            },
        }

    def teardown_runtime(self, config: Any, *, local_environment: Any) -> dict[str, Any]:
        self.calls.append("teardown")
        return {"status": "teardown_passed", "run_id": config.run_id, "port": config.port}

    def wait_for_gpu_free_window(
        self,
        config: Any,
        *,
        timeout_seconds: int,
        stable_seconds: int = 0,
    ) -> dict[str, Any]:
        self.calls.append(f"gpu_wait:{timeout_seconds}:{stable_seconds}")
        return {
            "status": "free",
            "checked_gpus": [{"index": 0, "status": "free"}],
            "stable_seconds": stable_seconds,
        }


def test_qwen3_sglang_smoke_launches_observes_and_tears_down(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    output = io.StringIO()
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    result = run_qwen3_sglang_smoke.run_smoke(
        declared_spec=declared,
        local_environment=local_env,
        run_id="qwen3-smoke-test",
        port=19007,
        runtime=runtime,
        output=output,
    )

    assert runtime.calls == [
        "load_declared:smoke-qwen3-dense.yaml",
        "load_local:local-env.yaml",
        "materialize:qwen3-smoke-test:19007",
        "stable_preparation_paths",
        "write_materialized",
        "validate_preparation",
        "launch",
        "load_effective_materialized",
        "models",
        "chat",
        "teardown",
    ]
    assert result["status"] == "passed"
    assert result["generated_text"] == "OK"
    assert result["port"] == 19007
    assert result["evidence_manifest"].is_file()

    text = output.getvalue()
    assert "[ginkgo] stage=load_declared" in text
    assert "[ginkgo] stage=materialize" in text
    assert "[ginkgo] stage=launch_sglang" in text
    assert "[ginkgo] stage=inference_request" in text
    assert "[ginkgo] stage=teardown" in text
    assert "========== SGLANG STDERR TAIL ==========" in text
    assert "INFO sglang request prompt=Say OK. output=OK" in text
    assert "========== MODEL OUTPUT ==========" in text
    assert "\nOK\n" in text

    manifest = json.loads(result["evidence_manifest"].read_text())
    assert manifest["status"] == "passed"
    assert manifest["evidence_boundary"] == "live_qwen3_sglang_smoke"
    assert manifest["model_id"] == "Qwen/Qwen3-0.6B"
    assert manifest["served_model_name"] == "Qwen/Qwen3-0.6B"
    assert manifest["expected_model_ids"] == ["Qwen/Qwen3-0.6B"]
    assert [event["stage"] for event in manifest["control_plane"]] == [
        "load_declared",
        "load_local_environment",
        "materialize",
        "write_materialized_config",
        "validate_preparation_records",
        "launch_sglang",
        "models_probe",
        "inference_request",
        "teardown",
        "write_evidence_manifest",
    ]
    assert manifest["request"]["url"] == "http://127.0.0.1:19007/v1/chat/completions"
    assert manifest["request"]["payload"]["model"] == "Qwen/Qwen3-0.6B"
    assert manifest["generated_text"] == "OK"
    assert manifest["openai_base_url"] == "http://127.0.0.1:19007/v1"
    assert manifest["teardown_status"] == "teardown_passed"
    assert manifest["response"]["generated_text"] == "OK"
    assert manifest["models"]["models"] == ["Qwen/Qwen3-0.6B"]
    assert manifest["logs"]["stderr_tail"].endswith("output=OK\n")
    assert manifest["teardown"]["status"] == "teardown_passed"


def test_qwen3_sglang_smoke_waits_for_gpu_free_window_before_launch(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    result = run_qwen3_sglang_smoke.run_smoke(
        declared_spec=declared,
        local_environment=local_env,
        run_id="qwen3-smoke-test",
        port=19007,
        runtime=runtime,
        wait_for_gpu_free_seconds=60,
        gpu_free_stable_seconds=6,
    )

    assert result["status"] == "passed"
    assert runtime.calls.index("gpu_wait:60:6") < runtime.calls.index("launch")
    manifest = json.loads(result["evidence_manifest"].read_text())
    assert manifest["gpu_wait"] == {
        "status": "free",
        "checked_gpus": [{"index": 0, "status": "free"}],
        "stable_seconds": 6,
    }


def test_qwen3_sglang_smoke_records_failed_gpu_wait_before_launch(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)

    class OccupiedGpuError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("GPU-free wait timed out after 1s")
            self.blocked_gpus = [
                {
                    "index": 0,
                    "uuid": "GPU-busy",
                    "pid": 1234,
                    "process_name": "VLLM::Worker_TP0_EP0",
                    "used_memory": "160200",
                }
            ]

    def wait_for_gpu_free_window(config: Any, *, timeout_seconds: int, stable_seconds: int = 0) -> dict[str, Any]:
        runtime.calls.append(f"gpu_wait:{timeout_seconds}:{stable_seconds}")
        raise OccupiedGpuError()

    runtime.wait_for_gpu_free_window = wait_for_gpu_free_window  # type: ignore[method-assign]
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    with pytest.raises(OccupiedGpuError):
        run_qwen3_sglang_smoke.run_smoke(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=19007,
            runtime=runtime,
            wait_for_gpu_free_seconds=1,
        )

    assert "launch" not in runtime.calls
    manifest = json.loads((tmp_path / "results" / "qwen3-smoke-test" / "qwen3-sglang-smoke-evidence.json").read_text())
    assert manifest["gpu_wait"] == {
        "status": "failed",
        "error": "GPU-free wait timed out after 1s",
        "blocked_gpus": [
            {
                "index": 0,
                "uuid": "GPU-busy",
                "pid": 1234,
                "process_name": "VLLM::Worker_TP0_EP0",
                "used_memory": "160200",
            }
        ],
    }
    assert manifest["launch"] is None
    assert manifest["failure"]["stage"] == "wait_for_gpu_free"


def test_qwen3_sglang_smoke_auto_prepares_missing_stable_records(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    runtime.validate_errors.append(
        FakeRuntime.RuntimeConfigError(
            "missing SGLang venv preparation record: /repo/glm52-serving-results/prepare-venv/sglang-venv.json"
        )
    )
    output = io.StringIO()
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    result = run_qwen3_sglang_smoke.run_smoke(
        declared_spec=declared,
        local_environment=local_env,
        run_id="qwen3-smoke-test",
        port=19007,
        runtime=runtime,
        output=output,
    )

    assert result["status"] == "passed"
    assert runtime.calls == [
        "load_declared:smoke-qwen3-dense.yaml",
        "load_local:local-env.yaml",
        "materialize:qwen3-smoke-test:19007",
        "stable_preparation_paths",
        "write_materialized",
        "validate_preparation",
        "prepare_venv:smoke-qwen3-dense.yaml:local-env.yaml",
        "prepare_model:smoke-qwen3-dense.yaml:local-env.yaml",
        "validate_preparation",
        "launch",
        "load_effective_materialized",
        "models",
        "chat",
        "teardown",
    ]

    text = output.getvalue()
    assert "[ginkgo] stage=prepare_sglang_venv run_id=prepare-venv" in text
    assert "[ginkgo] stage=prepare_model_cache run_id=prepare-model" in text
    manifest = json.loads(result["evidence_manifest"].read_text())
    assert "prepare_sglang_venv" in [event["stage"] for event in manifest["control_plane"]]
    assert "prepare_model_cache" in [event["stage"] for event in manifest["control_plane"]]


def test_qwen3_sglang_smoke_failure_manifest_includes_blocked_gpus(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)

    class OccupiedGpuError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("visible GPU 0 is already occupied")
            self.blocked_gpus = [
                {
                    "index": 0,
                    "uuid": "GPU-busy",
                    "pid": 1234,
                    "process_name": "VLLM::Worker_TP0_EP0",
                    "used_memory": "160200",
                }
            ]

    def launch_runtime(config: Any, *, local_environment: Any) -> dict[str, Any]:
        runtime.calls.append("launch")
        raise OccupiedGpuError()

    runtime.launch_runtime = launch_runtime  # type: ignore[method-assign]
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    with pytest.raises(OccupiedGpuError):
        run_qwen3_sglang_smoke.run_smoke(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=19007,
            runtime=runtime,
        )

    manifest = json.loads((tmp_path / "results" / "qwen3-smoke-test" / "qwen3-sglang-smoke-evidence.json").read_text())
    assert manifest["failure"]["exception_type"] == "OccupiedGpuError"
    assert manifest["failure"]["blocked_gpus"] == [
        {
            "index": 0,
            "uuid": "GPU-busy",
            "pid": 1234,
            "process_name": "VLLM::Worker_TP0_EP0",
            "used_memory": "160200",
        }
    ]


def test_qwen3_sglang_smoke_refreshes_stale_rootfs_preparation_records(tmp_path: Path) -> None:
    for error_message in [
        "SGLang preparation record rootfs recipe digest mismatch",
        "sglang_venv_record preparation record bwrap plan digest mismatch",
        "model_cache_record preparation bwrap plan env mismatch: HF_HOME",
        "mount host path mismatch: /cache/glm52",
        "SGLang venv preparation record package contract mismatch",
        "SGLang venv preparation record missing CPU platform proof",
        "SGLang venv preparation record missing utils.is_cpu proof",
        "SGLang venv preparation record missing rotary CPU proof",
        "SGLang venv preparation record reports CUDA rotary mode for CPU route",
    ]:
        runtime = FakeRuntime(tmp_path=tmp_path)
        runtime.validate_errors.append(FakeRuntime.RuntimeConfigError(error_message))
        declared = tmp_path / "smoke-qwen3-dense.yaml"
        declared.write_text("placeholder: true\n")
        local_env = tmp_path / "local-env.yaml"
        local_env.write_text("placeholder: true\n")

        result = run_qwen3_sglang_smoke.run_smoke(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=19007,
            runtime=runtime,
        )

        assert result["status"] == "passed"
        assert "prepare_venv:smoke-qwen3-dense.yaml:local-env.yaml" in runtime.calls
        assert "prepare_model:smoke-qwen3-dense.yaml:local-env.yaml" in runtime.calls


def test_qwen3_sglang_smoke_does_not_repair_malformed_preparation_records(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    runtime.validate_errors.append(FakeRuntime.RuntimeConfigError("malformed preparation record: /repo/prepare-venv.json"))
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    with pytest.raises(FakeRuntime.RuntimeConfigError, match="malformed preparation record"):
        run_qwen3_sglang_smoke.run_smoke(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=19007,
            runtime=runtime,
        )

    assert "prepare_venv:smoke-qwen3-dense.yaml:local-env.yaml" not in runtime.calls
    assert "prepare_model:smoke-qwen3-dense.yaml:local-env.yaml" not in runtime.calls


def test_qwen3_sglang_smoke_rejects_default_fallback_ports(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    with pytest.raises(run_qwen3_sglang_smoke.SmokeError, match="disallowed serving port"):
        run_qwen3_sglang_smoke.run_smoke(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=8000,
            runtime=runtime,
        )


def test_qwen3_sglang_smoke_accepts_cpu_declared_spec(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)

    def load_declared_spec(path: Path) -> Any:
        runtime.calls.append(f"load_declared:{path.name}")
        return DeclaredSpecForTest(
            run_group="ginkgo-smoke-qwen3-cpu",
            port_range_start=19000,
            port_range_end=19100,
            disallowed_ports=[8000, 8080, 18080],
            device="cpu",
            cuda_visible_devices="",
            tensor_parallel_size=1,
        )

    runtime.load_declared_spec = load_declared_spec  # type: ignore[method-assign]
    declared = tmp_path / "smoke-qwen3-cpu.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    result = run_qwen3_sglang_smoke.run_smoke(
        declared_spec=declared,
        local_environment=local_env,
        run_id="qwen3-cpu-smoke-test",
        port=19007,
        runtime=runtime,
    )

    assert result["status"] == "passed"
    manifest = json.loads(result["evidence_manifest"].read_text())
    assert manifest["metadata"]["device"] == "cpu"


def test_human_wrapper_exposes_cpu_device_route() -> None:
    wrapper = REPO_ROOT / "ginkgo" / "scripts" / "run_qwen3_sglang_inference_in_bwrap_rootfs.sh"
    text = wrapper.read_text()

    assert "smoke-qwen3-cpu.yaml" in text
    assert "--device" in text
    assert "device=cpu" in text


@pytest.mark.parametrize(
    ("cuda_visible_devices", "tensor_parallel_size", "match"),
    [
        ("0,1", 1, "Qwen3 SGLang smoke must use exactly one visible GPU"),
        ("0", 2, "Qwen3 SGLang smoke tensor_parallel_size must be 1"),
    ],
)
def test_qwen3_sglang_smoke_rejects_multi_gpu_declared_specs(
    tmp_path: Path,
    cuda_visible_devices: str,
    tensor_parallel_size: int,
    match: str,
) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)

    def load_declared_spec(path: Path) -> Any:
        runtime.calls.append(f"load_declared:{path.name}")
        return DeclaredSpecForTest(
            run_group="ginkgo-smoke-qwen3-dense",
            port_range_start=19000,
            port_range_end=19100,
            disallowed_ports=[8000, 8080, 18080],
            cuda_visible_devices=cuda_visible_devices,
            tensor_parallel_size=tensor_parallel_size,
        )

    runtime.load_declared_spec = load_declared_spec  # type: ignore[method-assign]
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    with pytest.raises(run_qwen3_sglang_smoke.SmokeError, match=match):
        run_qwen3_sglang_smoke.run_smoke(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=19007,
            runtime=runtime,
        )

    assert runtime.calls == ["load_declared:smoke-qwen3-dense.yaml"]


def test_qwen3_sglang_smoke_tears_down_after_chat_failure(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    output = io.StringIO()

    def fail_chat(config: Any) -> dict[str, Any]:
        runtime.calls.append("chat")
        raise RuntimeError("chat failed")

    runtime.probe_chat = fail_chat  # type: ignore[method-assign]
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    with pytest.raises(RuntimeError, match="chat failed"):
        run_qwen3_sglang_smoke.run_smoke(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=19007,
            runtime=runtime,
            output=output,
        )

    assert runtime.calls[-1] == "teardown"
    assert "[ginkgo] stage=teardown" in output.getvalue()


def test_ginkgo_local_run_writes_failure_manifest_for_probe_failure(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)
    output = io.StringIO()

    def fail_chat(config: Any) -> dict[str, Any]:
        runtime.calls.append("chat")
        raise RuntimeError("chat failed")

    runtime.probe_chat = fail_chat  # type: ignore[method-assign]
    declared = tmp_path / "smoke-qwen3-dense.yaml"
    declared.write_text("placeholder: true\n")
    local_env = tmp_path / "local-env.yaml"
    local_env.write_text("placeholder: true\n")

    local_run = SglangLocalRun(
        workload=Qwen3SglangWorkload(),
        runtime=RuntimeBackedLocalRunAdapter(runtime),
    )

    with pytest.raises(RuntimeError, match="chat failed"):
        local_run.run(
            declared_spec=declared,
            local_environment=local_env,
            run_id="qwen3-smoke-test",
            port=19007,
            output=output,
        )

    failure_manifest = tmp_path / "results" / "qwen3-smoke-test" / "qwen3-sglang-smoke-evidence.json"
    manifest = json.loads(failure_manifest.read_text())
    assert manifest["status"] == "failed"
    assert manifest["failure"]["stage"] == "inference_request"
    assert manifest["failure"]["exception_type"] == "RuntimeError"
    assert manifest["failure"]["message"] == "chat failed"
    assert manifest["run_id"] == "qwen3-smoke-test"
    assert manifest["port"] == 19007
    assert manifest["logs"]["stderr_tail"].endswith("output=OK\n")
    assert manifest["teardown"]["status"] == "teardown_passed"

    text = output.getvalue()
    assert "========== GINKGO FAILURE ==========" in text
    assert "stage=inference_request" in text
    assert "chat failed" in text
