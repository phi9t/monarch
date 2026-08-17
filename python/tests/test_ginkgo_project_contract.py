from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


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
    "configs/smoke-qwen3-dense.yaml",
    "configs/smoke-qwen3-moe.yaml",
    "local-env/template.yaml",
    "schemas/sglang-runtime.md",
    "schemas/inference-runtime.md",
    "schemas/sandbox-runtime.md",
    "profiles/sandbox-only.yaml",
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
    "scripts/run_qwen3_sglang_smoke.py",
    "scripts/run_qwen3_sglang_smoke.sh",
]


ABSOLUTE_HOST_PATH = re.compile(r"(?<![A-Za-z0-9_])/(data\\d+|home/[^<\\s]+|Users)/")


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
        if path.suffix not in {".md", ".py", ".yaml"}:
            continue
        text = re.sub(r"<[^>\n]*>", "<placeholder>", path.read_text())
        if ABSOLUTE_HOST_PATH.search(text):
            offenders.append(relative)

    assert offenders == []


def test_ginkgo_configs_use_owned_custom_ports_and_disable_fallback() -> None:
    for relative in [
        "configs/sglang-glm52.yaml",
        "configs/inference-glm52.yaml",
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


def test_ginkgo_sglang_configs_parse_with_runtime_schema() -> None:
    for relative in [
        "configs/sglang-glm52.yaml",
        "configs/smoke-qwen3-dense.yaml",
        "configs/smoke-qwen3-moe.yaml",
    ]:
        spec = glm52_sglang_runtime.load_declared_spec(GINKGO_ROOT / relative)

        assert spec.fail_fast is True
        assert spec.allow_fallback is False
        assert spec.port_policy.mode == "strict_run_owned_range"
        assert {8000, 8080, 18080}.issubset(set(spec.port_policy.disallowed_ports))
        assert spec.sandbox.kind == "bwrap_rootfs"


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
