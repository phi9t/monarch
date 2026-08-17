from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


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


@dataclass(frozen=True)
class MaterializedConfigForTest:
    run_id: str
    port: int
    run_dir: Path
    run_group: str = "ginkgo-smoke-qwen3-dense"

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
            "chat_url": f"http://127.0.0.1:{self.port}/v1/chat/completions",
            "chat_payload": {
                "model": "Qwen/Qwen3-0.6B",
                "messages": [{"role": "user", "content": "Say OK."}],
                "max_tokens": 2,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        }


class FakeRuntime:
    def __init__(self, *, tmp_path: Path) -> None:
        self.calls: list[str] = []
        self.tmp_path = tmp_path

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
        return MaterializedConfigForTest(
            run_id=run_id,
            port=port,
            run_dir=self.tmp_path / "results" / run_id,
        )

    def write_materialized_config(self, config: Any, path: Path) -> None:
        self.calls.append("write_materialized")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("schema_version: 1\n")

    def validate_preparation_records(self, *, config: Any) -> None:
        self.calls.append("validate_preparation")

    def launch_runtime(self, config: Any, *, local_environment: Any) -> dict[str, Any]:
        self.calls.append("launch")
        run_dir = config.run_dir
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs" / "stderr.log").write_text("INFO sglang request prompt=Say OK. output=OK\n")
        (run_dir / "logs" / "stdout.log").write_text("server started\n")
        return {"status": "launch_passed", "run_id": config.run_id, "port": config.port, "pid": 1234}

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


def test_qwen3_sglang_smoke_launches_observes_and_tears_down(tmp_path: Path) -> None:
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
    )

    assert runtime.calls == [
        "load_declared:smoke-qwen3-dense.yaml",
        "load_local:local-env.yaml",
        "materialize:qwen3-smoke-test:19007",
        "write_materialized",
        "validate_preparation",
        "launch",
        "models",
        "chat",
        "teardown",
    ]
    assert result["status"] == "passed"
    assert result["generated_text"] == "OK"
    assert result["port"] == 19007
    assert result["evidence_manifest"].is_file()

    manifest = json.loads(result["evidence_manifest"].read_text())
    assert manifest["status"] == "passed"
    assert manifest["request"]["url"] == "http://127.0.0.1:19007/v1/chat/completions"
    assert manifest["request"]["payload"]["model"] == "Qwen/Qwen3-0.6B"
    assert manifest["response"]["generated_text"] == "OK"
    assert manifest["models"]["models"] == ["Qwen/Qwen3-0.6B"]
    assert manifest["logs"]["stderr_tail"].endswith("output=OK\n")
    assert manifest["teardown"]["status"] == "teardown_passed"


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


def test_qwen3_sglang_smoke_tears_down_after_chat_failure(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path=tmp_path)

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
        )

    assert runtime.calls[-1] == "teardown"
