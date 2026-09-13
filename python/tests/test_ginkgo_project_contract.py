from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
GINKGO_ROOT = REPO_ROOT / "ginkgo"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


glm52_sglang_runtime = load_script_module(
    "glm52_sglang_runtime",
    REPO_ROOT / "scripts" / "glm52_sglang_runtime.py",
)
glm52_inference_runtime = load_script_module(
    "glm52_inference_runtime",
    REPO_ROOT / "scripts" / "glm52_inference_runtime.py",
)


EXPECTED_FILES = [
    "README.md",
    "configs/sglang-glm52.yaml",
    "configs/inference-glm52.yaml",
    "configs/smoke-qwen3-cpu.yaml",
    "configs/smoke-qwen3-dense.yaml",
    "configs/smoke-qwen3-moe.yaml",
    "local-env/template.yaml",
    "schemas/sglang-runtime.md",
    "schemas/inference-runtime.md",
    "schemas/sandbox-runtime.md",
    "schemas/monarch-control-plane.md",
    "profiles/sandbox-only.yaml",
    "profiles/serving-smoke-cpu.yaml",
    "profiles/cuda-kernel.yaml",
    "profiles/serving-smoke-dense.yaml",
    "profiles/serving-smoke-moe.yaml",
    "profiles/glm52.yaml",
    "manifests/dependency-contract.yaml",
    "manifests/optimized-kernels.yaml",
    "manifests/model-cache-contract.yaml",
    "docs/operator-workflow.md",
    "docs/verification-ladder.md",
    "docs/evidence-boundary.md",
    "__init__.py",
    "control_plane.py",
    "local_run.py",
    "scripts/run_qwen3_monarch_control_plane_smoke.py",
    "scripts/run_qwen3_sglang_smoke.py",
    "scripts/run_qwen3_sglang_smoke.sh",
    "scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh",
]


ABSOLUTE_HOST_PATH = re.compile(r"(?<![A-Za-z0-9_])/(data\d+|home/(?!monarch\b)[^<\s]+|Users)/")


def test_ginkgo_project_contract_files_exist() -> None:
    missing = [path for path in EXPECTED_FILES if not (GINKGO_ROOT / path).is_file()]

    assert missing == []


def test_ginkgo_portable_files_do_not_encode_absolute_host_paths() -> None:
    offenders: list[str] = []
    for path in sorted(GINKGO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(GINKGO_ROOT).as_posix()
        if "__pycache__" in path.parts:
            continue
        if relative.startswith("local-env/") and relative != "local-env/template.yaml":
            continue
        if path.suffix not in {".md", ".py", ".yaml"}:
            continue
        text = re.sub(r"<[^>\n]*>", "<placeholder>", path.read_text())
        if ABSOLUTE_HOST_PATH.search(text):
            offenders.append(relative)

    assert offenders == []


def test_ginkgo_generated_local_env_files_are_run_artifacts() -> None:
    generated_path = "ginkgo/local-env/.generated/example-run/in-process-actor.yaml"

    result = subprocess.run(
        ["git", "check-ignore", "--quiet", generated_path],
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_ginkgo_configs_use_owned_custom_ports_and_disable_fallback() -> None:
    for relative in [
        "configs/sglang-glm52.yaml",
        "configs/inference-glm52.yaml",
        "configs/smoke-qwen3-cpu.yaml",
        "configs/smoke-qwen3-dense.yaml",
        "configs/smoke-qwen3-moe.yaml",
    ]:
        text = (GINKGO_ROOT / relative).read_text()
        assert "allow_fallback: false" in text
        assert "strict_run_owned_range" in text
        assert "disallowed_ports: [8000, 8080, 18080]" in text
        assert "range_start: 19000" in text


def test_ginkgo_docs_define_smoke_evidence_boundary() -> None:
    text = (GINKGO_ROOT / "docs" / "evidence-boundary.md").read_text()

    assert "Qwen3 smoke" in text
    assert "not GLM-5.2 completion evidence" in text
    assert "Only the GLM profile can produce GLM-5.2 completion evidence" in text
    assert "Blocker Evidence" in text
    assert "gpu_wait.status: failed" in text
    assert "failure.blocked_gpus" in text
    assert "do not prove\nSGLang startup" in text


def test_ginkgo_operator_docs_define_no_fallback_gpu_wait() -> None:
    operator_text = (GINKGO_ROOT / "docs" / "operator-workflow.md").read_text()
    ladder_text = (GINKGO_ROOT / "docs" / "verification-ladder.md").read_text()

    assert "--wait-for-gpu-free-seconds" in operator_text
    assert "--gpu-free-stable-seconds" in operator_text
    assert "The wait is no-fallback" in operator_text
    assert "only the device declared by the\n   materialized config" in operator_text
    assert "does not choose another GPU" in operator_text
    assert "does not switch to CPU" in operator_text
    assert "gpu_wait" in operator_text
    assert "failure.blocked_gpus" in operator_text
    assert "gpu_wait" in ladder_text
    assert "blocked_gpus" in ladder_text
    assert "instead\n   of selecting a different GPU or switching device class" in ladder_text


def test_ginkgo_dependency_contract_requires_nested_bwrap_rootfs_tool() -> None:
    dependency_contract = yaml.safe_load((GINKGO_ROOT / "manifests" / "dependency-contract.yaml").read_text())

    assert "bwrap" in dependency_contract["rootfs_tools"]["required"]


def test_ginkgo_sglang_configs_parse_with_runtime_schema() -> None:
    for relative in [
        "configs/sglang-glm52.yaml",
        "configs/smoke-qwen3-cpu.yaml",
        "configs/smoke-qwen3-dense.yaml",
        "configs/smoke-qwen3-moe.yaml",
    ]:
        spec = glm52_sglang_runtime.load_declared_spec(GINKGO_ROOT / relative)

        assert spec.fail_fast is True
        assert spec.allow_fallback is False
        assert spec.port_policy.mode == "strict_run_owned_range"
        assert {8000, 8080, 18080}.issubset(set(spec.port_policy.disallowed_ports))
        assert spec.sandbox.kind == "bwrap_rootfs"


def test_ginkgo_cpu_serving_profile_is_first_class_and_gpu_free() -> None:
    profile_text = (GINKGO_ROOT / "profiles" / "serving-smoke-cpu.yaml").read_text()

    assert "profile: serving-smoke-cpu" in profile_text
    assert "requires_gpu: false" in profile_text
    assert "launches_serving_process: true" in profile_text
    assert "declared_config: repo://ginkgo/configs/smoke-qwen3-cpu.yaml" in profile_text
    assert "sglang_launch_probe_teardown" in profile_text
    assert "gpu" not in [
        line.strip()
        for line in profile_text.splitlines()
        if line.strip().startswith("- ")
    ]


def test_ginkgo_monarch_control_plane_schema_defines_orchestrator_contract() -> None:
    text = (GINKGO_ROOT / "schemas" / "monarch-control-plane.md").read_text()

    assert "MonarchControlPlaneRun" in text
    assert "Actor" in text
    assert "endpoint" in text
    assert "Insula" in text
    assert "ProcessRecord" in text
    assert "No fallback" in text
    assert "host-control adapter" in text
    assert "expected_child_device: cpu" in text
    assert "Host-child parent success is gated by the standalone Qwen3 SGLang verifier" in text
    assert "closed-port proof" in text
    assert "--verify-artifact` then performs an\nadditional parent-manifest audit" in text


def test_ginkgo_inference_config_parses_with_runtime_schema() -> None:
    spec = glm52_inference_runtime.load_declared_inference_spec(
        GINKGO_ROOT / "configs" / "inference-glm52.yaml"
    )

    assert spec.fail_fast is True
    assert spec.allow_fallback is False
    assert spec.ports.mode == "strict_run_owned_range"
    assert spec.components["sglang_backend"]["declared_ref"] == "repo://ginkgo/configs/sglang-glm52.yaml"
    assert spec.components["dynamo_frontend"]["upstream_ref"] == "component://sglang_backend/openai_base_url"
    assert spec.components["responses_adapter"]["upstream_ref"] == "component://dynamo_frontend/openai_base_url"


def test_qwen3_sglang_shell_wrapper_is_thin_and_executable() -> None:
    wrapper = GINKGO_ROOT / "scripts" / "run_qwen3_sglang_smoke.sh"
    text = wrapper.read_text()

    assert wrapper.stat().st_mode & 0o111
    assert "exec \"${PYTHON:-python}\"" in text
    assert "run_qwen3_sglang_smoke.py" in text
    assert "8000" not in text
    assert "8080" not in text
    assert "18080" not in text


def test_qwen3_monarch_control_plane_smoke_script_is_executable() -> None:
    script = GINKGO_ROOT / "scripts" / "run_qwen3_monarch_control_plane_smoke.py"
    text = script.read_text()

    assert script.stat().st_mode & 0o111
    assert "Qwen3HostControlPlaneActor" in text
    assert "control_plane_run_from_mapping" in text
    assert 'REPO_ROOT / "python"' in text
    assert "--manifest-path" in text
    assert "--expected-child-device" in text
    assert 'DEFAULT_EXPECTED_CHILD_DEVICE = "cpu"' in text
    assert "8000" not in text
    assert "8080" not in text
    assert "18080" not in text


def test_ginkgo_operator_workflow_pins_monarch_child_device() -> None:
    text = (GINKGO_ROOT / "docs" / "operator-workflow.md").read_text()

    assert "--expected-child-device cpu" in text
    assert "--expected-child-device cuda" in text
    assert "host-child parent pass is gated\n   by the standalone Qwen3 child verifier" in text
    assert "closed serving port" in text
    assert "`--verify-artifact`\n   then verifies the saved parent and child artifacts" in text
    assert "must not reuse CPU artifact\n   proof" in text


def test_qwen3_sglang_rootfs_operator_script_is_host_control_and_delegates() -> None:
    wrapper = GINKGO_ROOT / "scripts" / "run_qwen3_sglang_inference_in_bwrap_rootfs.sh"
    text = wrapper.read_text()

    assert wrapper.stat().st_mode & 0o111
    assert "materialize_default_local_environment" in text
    assert "run_qwen3_sglang_smoke.py" in text
    assert "ginkgo/local-env/qwen3-sglang.yaml" in text
    assert "exec \"${PYTHON:-python}\"" in text
    assert "host-control script" in text
    assert "bwrap command" in text
    assert "--wait-for-gpu-free-seconds" in text
    assert "--gpu-free-stable-seconds" in text
    assert "wait_for_gpu_free_seconds=${WAIT_FOR_GPU_FREE_SECONDS}" in text
    assert "gpu_free_stable_seconds=${GPU_FREE_STABLE_SECONDS}" in text
    assert "exec \"${REPO_ROOT}/scripts/run\"" not in text
    assert "MONARCH_ROOTFS" in text
    assert "8000" not in text
    assert "8080" not in text
    assert "18080" not in text
