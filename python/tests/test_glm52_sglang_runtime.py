#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "glm52_sglang_runtime.py"
REPO_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("glm52_sglang_runtime", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_sglang_runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_sglang_runtime
spec.loader.exec_module(glm52_sglang_runtime)

OFFLOADER_PATCH_PATH = Path(__file__).resolve().parents[2] / "scripts" / "glm52_sglang_offloader_patch.py"
offloader_patch_spec = importlib.util.spec_from_file_location("glm52_sglang_offloader_patch", OFFLOADER_PATCH_PATH)
assert offloader_patch_spec is not None
assert offloader_patch_spec.loader is not None
glm52_sglang_offloader_patch = importlib.util.module_from_spec(offloader_patch_spec)
sys.modules[offloader_patch_spec.name] = glm52_sglang_offloader_patch
offloader_patch_spec.loader.exec_module(glm52_sglang_offloader_patch)

DeclaredSglangLaunchSpec = glm52_sglang_runtime.DeclaredSglangLaunchSpec
RuntimeConfigError = glm52_sglang_runtime.RuntimeConfigError
RuntimeLaunchError = glm52_sglang_runtime.RuntimeLaunchError
MaterializedSglangRuntimeConfig = glm52_sglang_runtime.MaterializedSglangRuntimeConfig
load_declared_spec = glm52_sglang_runtime.load_declared_spec
load_local_environment = glm52_sglang_runtime.load_local_environment
load_materialized_config = glm52_sglang_runtime.load_materialized_config
load_yaml_mapping = glm52_sglang_runtime.load_yaml_mapping
main = glm52_sglang_runtime.main
materialize_runtime_config = glm52_sglang_runtime.materialize_runtime_config
parse_models_response = glm52_sglang_runtime.parse_models_response
prepare_model_cache = glm52_sglang_runtime.prepare_model_cache
prepare_sglang_venv = glm52_sglang_runtime.prepare_sglang_venv
validate_materialized_config = glm52_sglang_runtime.validate_materialized_config
validate_preparation_records = glm52_sglang_runtime.validate_preparation_records
validate_resolved_rootfs_plan = glm52_sglang_runtime.validate_resolved_rootfs_plan
validate_sglang_rootfs_overlay = glm52_sglang_runtime.validate_sglang_rootfs_overlay
validate_sglang_help = glm52_sglang_runtime.validate_sglang_help
should_teardown_after_failure = glm52_sglang_runtime.should_teardown_after_failure
validate_model_snapshot = glm52_sglang_runtime.validate_model_snapshot
write_materialized_config = glm52_sglang_runtime.write_materialized_config


def test_glm52_sglang_runtime_script_help_runs_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(HELPER_PATH), "--help"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout


def write_spec(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


VALID_DECLARED = """\
schema_version: 1
run_group: glm52-sglang-local
fail_fast: true
allow_fallback: false
port_policy:
  mode: strict_run_owned_range
  bind_host: 127.0.0.1
  range_start: 19000
  range_end: 19100
  disallowed_ports: [8000, 8080, 18080]
model:
  id: zai-org/GLM-5.2
  path: zai-org/GLM-5.2
  served_model_name: zai-org/GLM-5.2
  expected_model_ids: [zai-org/GLM-5.2]
runtime:
  kind: sglang_openai
  device: cuda
  cuda_visible_devices: "0,1,2,3,4,5,6,7"
  tensor_parallel_size: 8
  dtype: bfloat16
  context_length: 262144
  kv_cache_dtype: fp8_e4m3
  mem_fraction_static: 0.72
  max_total_tokens: 32768
  max_running_requests: 1
  cpu_offload_gb: 16
  extra_args: []
sandbox:
  kind: bwrap_rootfs
  rootfs_ref: rootfs://monarch-default
  cwd: /workspace/monarch
  network: host_loopback_required
  gpu: required
  sglang:
    venv_path: /cache/glm52/venvs/sglang
    hf_home: /cache/glm52/hf-home
    cache: /cache/glm52/sglang
    telemetry_root: /workspace/monarch/.scratch/glm52-local-serving/run
observability:
  debug_mode: false
  leave_running_on_failure: false
  log_level: info
  crash_dump_folder: /run/glm52/crash-dumps
  telemetry:
    local_artifacts: true
    remote_export: false
local_paths:
  results_root: repo://glm52-serving-results
  scratch_root: repo://.scratch/glm52-local-serving
  cache_root: cache://glm52-local-serving
  temp_root: temp://glm52-local-serving
probes:
  startup_timeout_seconds: 900
  chat_timeout_seconds: 120
  models_required: true
  chat_required: true
  prompt: Say OK.
  max_new_tokens: 1
  throughput_max_new_tokens: 128
  chat_template_kwargs:
    enable_thinking: false
repeatability:
  cycles: 3
"""

VALID_DECLARED_WITH_OVERLAY = VALID_DECLARED

CPU_DECLARED = VALID_DECLARED.replace(
    "run_group: glm52-sglang-local",
    "run_group: qwen3-sglang-cpu",
).replace(
    "model:\n  id: zai-org/GLM-5.2\n  path: zai-org/GLM-5.2\n  served_model_name: zai-org/GLM-5.2\n  expected_model_ids: [zai-org/GLM-5.2]",
    "model:\n  id: Qwen/Qwen3-0.6B\n  path: Qwen/Qwen3-0.6B\n  served_model_name: Qwen/Qwen3-0.6B\n  expected_model_ids: [Qwen/Qwen3-0.6B]",
).replace(
    '  device: cuda\n  cuda_visible_devices: "0,1,2,3,4,5,6,7"\n  tensor_parallel_size: 8\n  dtype: bfloat16\n  context_length: 262144\n  kv_cache_dtype: fp8_e4m3\n  mem_fraction_static: 0.72\n  max_total_tokens: 32768\n  max_running_requests: 1\n  cpu_offload_gb: 16',
    '  device: cpu\n  cuda_visible_devices: ""\n  tensor_parallel_size: 1\n  dtype: float32\n  context_length: 2048\n  kv_cache_dtype: auto\n  mem_fraction_static: 0.40\n  max_total_tokens: 512\n  max_running_requests: 1\n  cpu_offload_gb: 0',
).replace("  gpu: required", "  gpu: none")

VALID_LOCAL_ENV = """\
schema_version: 1
roots:
  repo: /repo/monarch
  cache: /repo/monarch/.scratch/glm52-local-serving/cache
  temp: /repo/monarch/.scratch/glm52-local-serving/tmp
rootfs:
  monarch-default: /repo/monarch/scripts/rootfs/rootfs
"""


def write_local_environment(tmp_path: Path) -> Path:
    return write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )


def materialized_config_for_test(tmp_path: Path, *, port: int):
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY))
    local_env = load_local_environment(write_local_environment(tmp_path))
    return materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=port,
    )


def test_load_yaml_mapping_rejects_non_mapping_documents(tmp_path: Path) -> None:
    path = write_spec(tmp_path / "list.yaml", "- one\n")

    with pytest.raises(RuntimeConfigError, match="must be a mapping"):
        load_yaml_mapping(path)


def test_locked_dependency_sync_env_targets_sglang_venv() -> None:
    # The sandbox launch env pins UV_PROJECT_ENVIRONMENT to the read-only
    # .venv-rootfs. The locked dependency sync must override it so uv installs
    # the glm52-runtime group into the SGLang venv rather than failing on the
    # read-only repo mount.
    env = glm52_sglang_runtime._locked_dependency_sync_env("/cache/glm52/venvs/sglang")

    assert env["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
    assert env["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"


def test_load_declared_spec_accepts_complete_spec(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))

    assert isinstance(declared, DeclaredSglangLaunchSpec)
    assert declared.run_group == "glm52-sglang-local"
    assert declared.fail_fast is True
    assert declared.allow_fallback is False
    assert declared.port_policy.mode == "strict_run_owned_range"
    assert declared.port_policy.range_start == 19000
    assert {8000, 8080, 18080}.issubset(set(declared.port_policy.disallowed_ports))
    assert declared.model.served_model_name == "zai-org/GLM-5.2"
    assert declared.model.served_model_name in declared.model.expected_model_ids
    assert declared.runtime.kind == "sglang_openai"
    assert declared.runtime.device == "cuda"
    assert declared.runtime.context_length == 262144
    assert declared.runtime.kv_cache_dtype == "fp8_e4m3"
    assert declared.runtime.mem_fraction_static == 0.72
    assert declared.runtime.max_total_tokens == 32768
    assert declared.runtime.max_running_requests == 1
    assert declared.runtime.cpu_offload_gb == 16
    assert declared.sandbox.kind == "bwrap_rootfs"
    assert declared.sandbox.sglang.venv_path == "/cache/glm52/venvs/sglang"
    assert declared.sandbox.sglang.hf_home == "/cache/glm52/hf-home"
    assert declared.sandbox.sglang.sglang_cache == "/cache/glm52/sglang"
    assert declared.sandbox.sglang.telemetry_root == "/workspace/monarch/.scratch/glm52-local-serving/run"
    assert declared.observability.debug_mode is False
    assert declared.observability.leave_running_on_failure is False
    assert declared.observability.crash_dump_folder == "/run/glm52/crash-dumps"
    assert declared.local_paths.results_root == "repo://glm52-serving-results"
    assert declared.repeatability.cycles == 3


@pytest.mark.parametrize(
    ("needle", "replacement", "match"),
    [
        ("fail_fast: true", "fail_fast: false", "fail_fast must be true"),
        ("allow_fallback: false", "allow_fallback: true", "allow_fallback must be false"),
        ("  id: zai-org/GLM-5.2\n", "", "model.id is required"),
        ("  path: zai-org/GLM-5.2\n", "", "model.path is required"),
        ("  served_model_name: zai-org/GLM-5.2\n", "", "model.served_model_name is required"),
        (
            "expected_model_ids: [zai-org/GLM-5.2]",
            "expected_model_ids: []",
            "expected_model_ids must include served_model_name",
        ),
        ("mode: strict_run_owned_range", "mode: best_effort", "port_policy.mode must be strict_run_owned_range"),
        (
            "disallowed_ports: [8000, 8080, 18080]",
            "disallowed_ports: [8080]",
            "disallowed_ports must include",
        ),
        ("kind: sglang_openai", "kind: other_openai", "runtime.kind must be sglang_openai"),
        ("kind: bwrap_rootfs", "kind: host", "sandbox.kind must be bwrap_rootfs"),
        (
            "    venv_path: /cache/glm52/venvs/sglang\n",
            "",
            "sandbox.sglang.venv_path is required",
        ),
        ("  debug_mode: false\n", "", "observability.debug_mode is required"),
        (
            "  leave_running_on_failure: false\n",
            "",
            "observability.leave_running_on_failure is required",
        ),
        (
            "  crash_dump_folder: /run/glm52/crash-dumps\n",
            "  crash_dump_folder: /tmp/crash-dumps\n",
            "observability.crash_dump_folder must be under /run/glm52/",
        ),
        (
            "  leave_running_on_failure: false\n",
            "  leave_running_on_failure: true\n",
            "leave_running_on_failure requires debug_mode",
        ),
        (
            "results_root: repo://glm52-serving-results",
            "results_root: /tmp/glm52",
            "must use logical path refs",
        ),
        ("  mem_fraction_static: 0.72\n", "  mem_fraction_static: 1.5\n", "runtime.mem_fraction_static must be between 0 and 1"),
        ("  max_total_tokens: 32768\n", "  max_total_tokens: 0\n", "runtime.max_total_tokens must be positive"),
        ("  max_running_requests: 1\n", "  max_running_requests: 0\n", "runtime.max_running_requests must be positive"),
        ("  cpu_offload_gb: 16\n", "  cpu_offload_gb: -1\n", "runtime.cpu_offload_gb must be non-negative"),
    ],
)
def test_load_declared_spec_rejects_invalid_policy(
    tmp_path: Path,
    needle: str,
    replacement: str,
    match: str,
) -> None:
    invalid = VALID_DECLARED.replace(needle, replacement)

    with pytest.raises(RuntimeConfigError, match=match):
        load_declared_spec(write_spec(tmp_path / "declared.yaml", invalid))


@pytest.mark.parametrize(
    ("declared_text", "match"),
    [
        (VALID_DECLARED.replace("  device: cuda\n", "  device: tpu\n"), "runtime.device must be cpu or cuda"),
        (
            VALID_DECLARED.replace(
                '  device: cuda\n  cuda_visible_devices: "0,1,2,3,4,5,6,7"\n',
                '  device: cuda\n  cuda_visible_devices: ""\n',
            ),
            "runtime.cuda_visible_devices is required for cuda",
        ),
        (
            VALID_DECLARED.replace(
                '  device: cuda\n  cuda_visible_devices: "0,1,2,3,4,5,6,7"\n',
                '  device: cpu\n  cuda_visible_devices: "0"\n',
            ).replace("  gpu: required", "  gpu: none"),
            "runtime.cuda_visible_devices must be empty for cpu",
        ),
        (
            VALID_DECLARED.replace(
                '  device: cuda\n  cuda_visible_devices: "0,1,2,3,4,5,6,7"',
                '  device: cpu\n  cuda_visible_devices: ""',
            ),
            "sandbox.gpu must be none for cpu",
        ),
    ],
)
def test_load_declared_spec_rejects_device_policy_mismatches(
    tmp_path: Path,
    declared_text: str,
    match: str,
) -> None:
    with pytest.raises(RuntimeConfigError, match=match):
        load_declared_spec(write_spec(tmp_path / "declared.yaml", declared_text))


def test_load_declared_spec_rejects_unknown_fields(tmp_path: Path) -> None:
    invalid = VALID_DECLARED + "surprise: true\n"

    with pytest.raises(RuntimeConfigError, match="unknown field"):
        load_declared_spec(write_spec(tmp_path / "declared.yaml", invalid))


def test_materialized_config_contains_sglang_rootfs_overlay(tmp_path: Path) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_env_path = write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV)

    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_env_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="overlay-test",
        port=19017,
    )

    assert config.sandbox["sglang"]["venv_path"] == "/cache/glm52/venvs/sglang"
    assert config.sandbox["sglang"]["hf_home"] == "/cache/glm52/hf-home"
    assert config.sandbox["sglang"]["cache"] == "/cache/glm52/sglang"
    assert config.launch["env"]["HF_HOME"] == "/cache/glm52/hf-home"
    assert config.launch["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"


def test_cpu_declared_config_materializes_cpu_only_sglang_launch(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", CPU_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="qwen3-sglang-cpu-001",
        port=19017,
    )

    inner = config.launch["inner_argv"]
    outer = glm52_sglang_runtime._resolved_outer_argv(config)
    insula = glm52_sglang_runtime.build_insula_invocation_spec(config)

    assert declared.runtime.device == "cpu"
    assert config.runtime["device"] == "cpu"
    assert config.runtime["cuda_visible_devices"] == ""
    assert config.sandbox["gpu"] == "none"
    assert "CUDA_VISIBLE_DEVICES" not in config.launch["env"]
    assert "CUDA_VISIBLE_DEVICES" not in config.sandbox["env"]
    assert config.launch["env"]["SGLANG_USE_CPU_ENGINE"] == "1"
    assert config.sandbox["env"]["SGLANG_USE_CPU_ENGINE"] == "1"
    assert inner[inner.index("--device") + 1] == "cpu"
    assert inner[inner.index("--tp") + 1] == "1"
    assert outer[outer.index("--device") + 1] == "cpu"
    assert insula.gpu == "none"
    assert "CUDA_VISIBLE_DEVICES" not in insula.environment.values
    assert insula.environment.values["SGLANG_USE_CPU_ENGINE"] == "1"


def test_cpu_rootfs_runtime_binds_driver_libs_without_gpu_devices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", CPU_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="qwen3-sglang-cpu-001",
        port=19017,
    )

    class FakePath:
        def __init__(self, value: object) -> None:
            self._path = Path(value)

        def glob(self, pattern: str):
            text = str(self._path)
            if text == "/usr/lib/x86_64-linux-gnu" and pattern == "libcuda.so*":
                return [FakePath("/usr/lib/x86_64-linux-gnu/libcuda.so.1")]
            if text == "/usr/lib/x86_64-linux-gnu" and pattern == "libnvidia-*.so*":
                return [FakePath("/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1")]
            if text == "/dev" and pattern == "nvidia*":
                return [FakePath("/dev/nvidia0")]
            return []

        @property
        def name(self) -> str:
            return self._path.name

        def exists(self) -> bool:
            return False

        def is_file(self) -> bool:
            return False

        def __truediv__(self, other: object):
            return FakePath(self._path / str(other))

        def __fspath__(self) -> str:
            return str(self._path)

        def __str__(self) -> str:
            return str(self._path)

        def __lt__(self, other: object) -> bool:
            return str(self) < str(other)

    monkeypatch.setattr(glm52_sglang_runtime, "Path", FakePath)

    binds, env = glm52_sglang_runtime._rootfs_runtime_binds_and_env(config)

    bind_by_name = {bind.name: bind for bind in binds}
    assert "nvidia-lib-libcuda-so-1" in bind_by_name
    assert "nvidia-lib-libnvidia-ml-so-1" in bind_by_name
    assert bind_by_name["nvidia-lib-libcuda-so-1"].mode == "ro"
    assert env["LD_LIBRARY_PATH"].startswith("/run/nvidia-host:")
    assert env["LIBRARY_PATH"].startswith("/run/nvidia-host:")
    assert all(not bind.name.startswith("dev-nvidia") for bind in binds)
    assert "nvidia-smi" not in bind_by_name
    assert "NVIDIA_VISIBLE_DEVICES" not in env


def test_cpu_rootfs_runtime_reprojects_driver_libs_from_outer_rootfs_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", CPU_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="qwen3-sglang-cpu-001",
        port=19017,
    )

    class FakePath:
        def __init__(self, value: object) -> None:
            self._path = Path(value)

        def glob(self, pattern: str):
            text = str(self._path)
            if text == "/usr/lib/x86_64-linux-gnu":
                return []
            if text == "/run/nvidia-host" and pattern == "libcuda.so*":
                return [FakePath("/run/nvidia-host/libcuda.so.1")]
            if text == "/run/nvidia-host" and pattern == "libnvidia-*.so*":
                return [FakePath("/run/nvidia-host/libnvidia-ml.so.1")]
            if text == "/dev" and pattern == "nvidia*":
                return [FakePath("/dev/nvidia0")]
            return []

        @property
        def name(self) -> str:
            return self._path.name

        def exists(self) -> bool:
            return False

        def is_file(self) -> bool:
            return False

        def __truediv__(self, other: object):
            return FakePath(self._path / str(other))

        def __fspath__(self) -> str:
            return str(self._path)

        def __str__(self) -> str:
            return str(self._path)

        def __lt__(self, other: object) -> bool:
            return str(self) < str(other)

    monkeypatch.setattr(glm52_sglang_runtime, "Path", FakePath)

    binds, env = glm52_sglang_runtime._rootfs_runtime_binds_and_env(config)

    bind_by_name = {bind.name: bind for bind in binds}
    assert bind_by_name["nvidia-lib-libcuda-so-1"].host == "host:///run/nvidia-host/libcuda.so.1"
    assert bind_by_name["nvidia-lib-libcuda-so-1"].sandbox == "/run/nvidia-host/libcuda.so.1"
    assert bind_by_name["nvidia-lib-libnvidia-ml-so-1"].host == "host:///run/nvidia-host/libnvidia-ml.so.1"
    assert env["LD_LIBRARY_PATH"].startswith("/run/nvidia-host:")
    assert all(not bind.name.startswith("dev-nvidia") for bind in binds)
    assert "NVIDIA_VISIBLE_DEVICES" not in env


def test_cuda_rootfs_runtime_projects_only_visible_gpu_devices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared_text = VALID_DECLARED.replace(
        '  cuda_visible_devices: "0,1,2,3,4,5,6,7"\n  tensor_parallel_size: 8\n',
        '  cuda_visible_devices: "0"\n  tensor_parallel_size: 1\n',
    )
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", declared_text))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="qwen3-sglang-cuda-001",
        port=19017,
    )

    class FakePath:
        def __init__(self, value: object) -> None:
            self._path = Path(value)

        def glob(self, pattern: str):
            text = str(self._path)
            if text == "/usr/lib/x86_64-linux-gnu" and pattern == "libcuda.so*":
                return [FakePath("/usr/lib/x86_64-linux-gnu/libcuda.so.1")]
            if text == "/usr/lib/x86_64-linux-gnu" and pattern == "libnvidia-*.so*":
                return [FakePath("/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1")]
            if text == "/dev" and pattern == "nvidia*":
                return [
                    FakePath("/dev/nvidia0"),
                    FakePath("/dev/nvidia1"),
                    FakePath("/dev/nvidia2"),
                    FakePath("/dev/nvidia3"),
                    FakePath("/dev/nvidia4"),
                    FakePath("/dev/nvidia5"),
                    FakePath("/dev/nvidia6"),
                    FakePath("/dev/nvidia7"),
                    FakePath("/dev/nvidiactl"),
                    FakePath("/dev/nvidia-uvm"),
                    FakePath("/dev/nvidia-uvm-tools"),
                    FakePath("/dev/nvidia-modeset"),
                    FakePath("/dev/nvidia-caps"),
                ]
            return []

        @property
        def name(self) -> str:
            return self._path.name

        def exists(self) -> bool:
            return True

        def is_file(self) -> bool:
            return str(self._path) == "/usr/bin/nvidia-smi"

        def __truediv__(self, other: object):
            return FakePath(self._path / str(other))

        def __fspath__(self) -> str:
            return str(self._path)

        def __str__(self) -> str:
            return str(self._path)

        def __lt__(self, other: object) -> bool:
            return str(self) < str(other)

    monkeypatch.setattr(glm52_sglang_runtime, "Path", FakePath)

    binds, env = glm52_sglang_runtime._rootfs_runtime_binds_and_env(config)

    dev_sandboxes = {bind.sandbox for bind in binds if bind.mode == "dev"}
    assert {
        "/dev/nvidia0",
        "/dev/nvidiactl",
        "/dev/nvidia-uvm",
        "/dev/nvidia-uvm-tools",
        "/dev/nvidia-modeset",
        "/dev/nvidia-caps",
    }.issubset(dev_sandboxes)
    assert "/dev/nvidia1" not in dev_sandboxes
    assert "/dev/nvidia2" not in dev_sandboxes
    assert "/dev/nvidia7" not in dev_sandboxes
    assert env["NVIDIA_VISIBLE_DEVICES"] == "0"


def test_checked_in_cpu_qwen3_config_materializes_cpu_only(tmp_path: Path) -> None:
    declared_path = Path(__file__).resolve().parents[2] / "ginkgo" / "configs" / "smoke-qwen3-cpu.yaml"
    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="qwen3-sglang-cpu-001",
        port=19017,
    )

    assert config.run_group == "ginkgo-smoke-qwen3-cpu"
    assert config.runtime["device"] == "cpu"
    assert config.sandbox["gpu"] == "none"
    assert "CUDA_VISIBLE_DEVICES" not in config.launch["env"]


def test_declared_example_contains_sglang_rootfs_overlay(tmp_path: Path) -> None:
    declared_path = Path(__file__).resolve().parents[2] / ".scratch" / "glm52-local-serving" / "config" / "sglang-local.yaml"
    local_env_path = write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV)

    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_env_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="overlay-test",
        port=19017,
    )

    assert config.sandbox["sglang"] == {
        "venv_path": "/cache/glm52/venvs/sglang",
        "python": "/cache/glm52/venvs/sglang/bin/python",
        "hf_home": "/cache/glm52/hf-home",
        "cache": "/cache/glm52/sglang",
        "telemetry_root": "/workspace/monarch/.scratch/glm52-local-serving/run",
    }


def test_materialized_config_owns_sglang_crash_dump_folder(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="crash-dump-test",
        port=19017,
    )

    assert config.observability["crash_dump_folder"] == "/run/glm52/crash-dumps"
    assert glm52_sglang_runtime._argv_value(config.launch["inner_argv"], "--crash-dump-folder") == "/run/glm52/crash-dumps"


@pytest.mark.parametrize(
    ("needle", "replacement", "match"),
    [
        (
            "/cache/glm52/venvs/sglang",
            "/workspace/monarch/.venv-rootfs",
            "venv_path must be /cache/glm52/venvs/sglang",
        ),
        (
            "/cache/glm52/hf-home",
            "/workspace/monarch/.cache/huggingface",
            "hf_home must be /cache/glm52/hf-home",
        ),
        ("cache_root: cache://glm52-local-serving", "cache_root: /tmp/glm52", "must use logical path refs"),
        ("    cache: /cache/glm52/sglang\n", "", "sandbox.sglang.cache is required"),
    ],
)
def test_declared_overlay_rejects_invalid_paths(
    tmp_path: Path,
    needle: str,
    replacement: str,
    match: str,
) -> None:
    declared_path = write_spec(
        tmp_path / "declared.yaml",
        VALID_DECLARED_WITH_OVERLAY.replace(needle, replacement),
    )

    with pytest.raises(RuntimeConfigError, match=match):
        load_declared_spec(declared_path)


def test_prepare_sglang_venv_uses_rootfs_managed_python_and_uv(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    emitted_plans: list[dict[str, object]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        inner = argv[argv.index("--") + 1 :]
        if inner[:2] == ["uv", "venv"]:
            return subprocess.CompletedProcess(argv, 0, stdout="Using Python 3.12\nCreating virtual environment\n", stderr="")
        expected_sync_prefix = [
            "env",
            "VIRTUAL_ENV=/cache/glm52/venvs/sglang",
            "UV_PROJECT_ENVIRONMENT=/cache/glm52/venvs/sglang",
            "uv",
            "sync",
            "--active",
            "--locked",
            "--no-sources-package",
            "torch",
            "--no-install-project",
            "--only-group",
            "glm52-runtime",
        ]
        if inner[: len(expected_sync_prefix)] == expected_sync_prefix:
            assert "--python" in inner
            assert inner[inner.index("--python") + 1] == "/cache/glm52/venvs/sglang/bin/python"
            assert kwargs["env"]["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
            assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"
            return subprocess.CompletedProcess(argv, 0, stdout="resolved glm52 runtime deps\n", stderr="")
        if inner[:4] == [
            "/cache/glm52/venvs/sglang/bin/python",
            "/workspace/monarch/scripts/glm52_sglang_offloader_patch.py",
            "--offloader",
            "/cache/glm52/venvs/sglang/lib/python3.12/site-packages/sglang/srt/utils/offloader.py",
        ]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"patch_id":"glm52-offloader-v1-plain-tensor-attrs-v1",'
                    '"sha256_after":"patched-sha","changed":true}\n'
                ),
                stderr="",
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-c", glm52_sglang_runtime.SGLANG_VENV_PROBE_SCRIPT]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"python": "/cache/glm52/venvs/sglang/bin/python", '
                    '"sys_prefix": "/cache/glm52/venvs/sglang", '
                    '"packages": {"sglang": "0.4.0"}, '
                    '"platform": {"class": "CpuSRTPlatform", "device_name": "cpu", "device_type": "cpu", '
                    '"is_cpu": true, "is_cuda": false, "utils_is_cpu": true, '
                    '"rotary_base_is_cpu": true, "rotary_base_is_cuda": false}}'
                ),
                stderr="",
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-m", "sglang.launch_server"]:
            return subprocess.CompletedProcess(argv, 0, stdout="usage: --served-model-name NAME\n", stderr="")
        raise AssertionError(f"unexpected command: {inner}")

    record = prepare_sglang_venv(
        declared_path=write_spec(tmp_path / "declared.yaml", CPU_DECLARED),
        local_environment_path=write_local_environment(tmp_path),
        run_id="prepare-venv-test",
        run=fake_run,
        plan_emitter=lambda config, inner_argv, env=None: (
            emitted_plans.append({**valid_emitted_preparation_plan(config, inner_argv, env=env), "emitted_marker": "venv-plan"})
            or emitted_plans[-1]
        ),
    )

    flattened_calls = [" ".join(call) for call in calls]
    assert any("/cache/glm52/venvs/sglang" in call for call in flattened_calls)
    assert any("uv sync --active --locked --no-sources-package torch --no-install-project --only-group glm52-runtime" in call for call in flattened_calls)
    assert record["venv"]["python"] == "/cache/glm52/venvs/sglang/bin/python"
    assert record["venv"]["sys_prefix"] == "/cache/glm52/venvs/sglang"
    assert record["venv"]["packages"] == glm52_sglang_runtime.SGLANG_PREPARE_PACKAGES
    assert record["venv"]["installed_packages"]["sglang"] == "0.4.0"
    assert record["checks"]["platform"]["is_cpu"] is True
    assert record["checks"]["platform"]["utils_is_cpu"] is True
    assert record["checks"]["platform"]["rotary_base_is_cpu"] is True
    assert record["checks"]["platform"]["rotary_base_is_cuda"] is False
    assert record["dependency_resolution"]["group"] == "glm52-runtime"
    assert record["dependency_resolution"]["lockfile"] == "repo://uv.lock"
    assert len(record["dependency_resolution"]["lock_sha256"]) == 64
    assert record["dependency_resolution"]["selection"] == "only_group"
    assert record["dependency_resolution"]["sources"] == "standard_metadata_for_torch"
    assert record["commands"][1]["env"]["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
    assert record["commands"][1]["env"]["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"
    assert record["checks"]["offloader_patch"]["patch_id"] == "glm52-offloader-v1-plain-tensor-attrs-v1"
    assert record["checks"]["offloader_patch"]["sha256_after"] == "patched-sha"
    assert record["bwrap_plan"]["plan_sha256"] == glm52_sglang_runtime._stable_json_digest(emitted_plans[0])


def test_prepare_sglang_venv_accepts_cuda_platform_for_cuda_declared_spec(tmp_path: Path) -> None:
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        inner = argv[argv.index("--") + 1 :]
        if inner[:2] == ["uv", "venv"]:
            return subprocess.CompletedProcess(argv, 0, stdout="Using Python 3.12\nCreating virtual environment\n", stderr="")
        expected_sync_prefix = [
            "env",
            "VIRTUAL_ENV=/cache/glm52/venvs/sglang",
            "UV_PROJECT_ENVIRONMENT=/cache/glm52/venvs/sglang",
            "uv",
            "sync",
            "--active",
            "--locked",
            "--no-sources-package",
            "torch",
            "--no-install-project",
            "--only-group",
            "glm52-runtime",
        ]
        if inner[: len(expected_sync_prefix)] == expected_sync_prefix:
            assert kwargs["env"]["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
            assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"
            return subprocess.CompletedProcess(argv, 0, stdout="resolved glm52 runtime deps\n", stderr="")
        if inner[:4] == [
            "/cache/glm52/venvs/sglang/bin/python",
            "/workspace/monarch/scripts/glm52_sglang_offloader_patch.py",
            "--offloader",
            "/cache/glm52/venvs/sglang/lib/python3.12/site-packages/sglang/srt/utils/offloader.py",
        ]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"patch_id":"glm52-offloader-v1-plain-tensor-attrs-v1",'
                    '"sha256_after":"patched-sha","changed":true}\n'
                ),
                stderr="",
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-c", glm52_sglang_runtime.SGLANG_VENV_PROBE_SCRIPT]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"python": "/cache/glm52/venvs/sglang/bin/python", '
                    '"sys_prefix": "/cache/glm52/venvs/sglang", '
                    '"packages": {"sglang": "0.4.0"}, '
                    '"platform": {"class": "CudaSRTPlatform", "device_name": "cuda", "device_type": "cuda", '
                    '"is_cpu": false, "is_cuda": true, "utils_is_cpu": false, '
                    '"rotary_base_is_cpu": false, "rotary_base_is_cuda": true}}'
                ),
                stderr="",
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-m", "sglang.launch_server"]:
            return subprocess.CompletedProcess(argv, 0, stdout="usage: --served-model-name NAME\n", stderr="")
        raise AssertionError(f"unexpected command: {inner}")

    record = prepare_sglang_venv(
        declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
        local_environment_path=write_local_environment(tmp_path),
        run_id="prepare-venv-cuda-test",
        run=fake_run,
        plan_emitter=lambda config, inner_argv, env=None: valid_emitted_preparation_plan(config, inner_argv, env=env),
    )

    assert record["checks"]["platform"]["is_cuda"] is True
    assert record["checks"]["platform"]["rotary_base_is_cuda"] is True


def test_preparation_command_creates_writable_mount_sources(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19021)
    cache_mounts = [
        Path(glm52_sglang_runtime._resolve_host_path_ref(config, mount["host_path_ref"]))
        for mount in config.sandbox["mounts"]
        if mount["mode"] == "rw" and mount["host_path_ref"].startswith(("cache://", "temp://", "run://"))
    ]
    for path in cache_mounts:
        assert not path.exists()

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        for path in cache_mounts:
            assert path.is_dir(), f"missing mount source before bwrap command: {path}"
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    completed = glm52_sglang_runtime._run_preparation_command(
        config,
        ["true"],
        run=fake_run,
    )

    assert completed.returncode == 0


def test_preparation_command_creates_repo_projected_writable_mountpoints(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19021)
    target_mountpoint = (
        Path(config.resolved_paths["repo"])
        / "target"
        / "bwrap"
        / glm52_sglang_runtime._rootfs_recipe_digest(config)
    )
    assert not target_mountpoint.exists()

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        assert target_mountpoint.is_dir()
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    completed = glm52_sglang_runtime._run_preparation_command(
        config,
        ["true"],
        run=fake_run,
    )

    assert completed.returncode == 0


def test_sglang_offloader_patch_helper_is_idempotent(tmp_path: Path) -> None:
    offloader = tmp_path / "offloader.py"
    offloader.write_text(
        '''import torch
from torch.func import functional_call
from typing import Callable, List

_SubmoduleAccessor = Callable[[torch.nn.Module], torch.nn.Module]
_WhitelistParamNamesCreator = Callable[[torch.nn.Module], List[str]]


class OffloaderV1:
    def maybe_offload_to_cpu(self, module, device):
        original_forward = module.forward
        offloaded_parameters = True
        if offloaded_parameters:
            def forward(*args, **kwargs):
                module.forward = original_forward
                device_state = {
                    # here we blindly call `to(device)`
                    # if the parameter is already on the device, it will be a no-op
                    k: v.to(device, non_blocking=True)
                    for k, v in module.state_dict().items()
                }
                output = functional_call(
                    module,
                    device_state,
                    args=args,
                    kwargs=kwargs,
                )
                module.forward = forward
                return output
'''
    )

    first = glm52_sglang_offloader_patch.apply_patch(offloader)
    second = glm52_sglang_offloader_patch.apply_patch(offloader)
    verified = glm52_sglang_offloader_patch.verify_patch(offloader)

    assert first["patch_id"] == "glm52-offloader-v1-plain-tensor-attrs-v1"
    assert first["changed"] is True
    assert second["changed"] is False
    assert second["already_patched"] is True
    assert verified["patched"] is True
    text = offloader.read_text()
    assert "_move_plain_tensor_attrs_for_forward" in text
    assert "tie_weights=False" in text


def test_sglang_offloader_patch_helper_handles_single_line_functional_call(tmp_path: Path) -> None:
    offloader = tmp_path / "offloader.py"
    offloader.write_text(
        '''import torch
from torch.func import functional_call
from typing import Callable, List

_SubmoduleAccessor = Callable[[torch.nn.Module], torch.nn.Module]
_WhitelistParamNamesCreator = Callable[[torch.nn.Module], List[str]]


class OffloaderV1:
    def maybe_offload_to_cpu(self, module, device):
        original_forward = module.forward
        offloaded_parameters = True
        if offloaded_parameters:
            def forward(*args, **kwargs):
                module.forward = original_forward
                device_state = {
                    # here we blindly call `to(device)`
                    # if the parameter is already on the device, it will be a no-op
                    k: v.to(device, non_blocking=True)
                    for k, v in module.state_dict().items()
                }
                output = functional_call(module, device_state, args=args, kwargs=kwargs)
                module.forward = forward
                return output
'''
    )

    evidence = glm52_sglang_offloader_patch.apply_patch(offloader)

    assert evidence["changed"] is True
    text = offloader.read_text()
    assert "_move_plain_tensor_attrs_for_forward" in text
    assert "tie_weights=False" in text


def test_prepare_model_cache_uses_rootfs_hf_home(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    validator_paths: list[Path] = []
    emitted_plans: list[dict[str, object]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc"}',
            stderr="",
        )

    record = prepare_model_cache(
        declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
        local_environment_path=write_local_environment(tmp_path),
        run_id="prepare-model-test",
        run=fake_run,
        snapshot_validator=lambda path: (
            validator_paths.append(path)
            or {"snapshot_path": str(path), "shard_count": 1, "missing_shard_count": 0}
        ),
        plan_emitter=lambda config, inner_argv, env=None: (
            emitted_plans.append({**valid_emitted_preparation_plan(config, inner_argv, env=env), "emitted_marker": "model-plan"})
            or emitted_plans[-1]
        ),
    )

    assert len(calls) == 1
    command = calls[0][calls[0].index("--") + 1 :]
    assert command[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-c", glm52_sglang_runtime.MODEL_CACHE_PREPARE_SCRIPT]
    assert command[3:] == ["zai-org/GLM-5.2"]
    assert validator_paths
    assert not str(validator_paths[0]).startswith("/cache/")
    assert str(validator_paths[0]).endswith("hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc")
    assert record["model_cache"]["missing_shard_count"] == 0
    assert record["bwrap_plan"]["plan_sha256"] == glm52_sglang_runtime._stable_json_digest(emitted_plans[0])


def test_prepare_sglang_venv_rejects_emitted_plan_drift_before_install(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def drifted_plan(config, inner_argv, env=None):
        plan = valid_emitted_preparation_plan(config, inner_argv, env=env)
        plan["env"] = {**plan["env"], "HF_HOME": "/cache/glm52/drifted-hf"}
        return plan

    with pytest.raises(RuntimeConfigError, match="rootfs plan HF_HOME does not match materialized config"):
        prepare_sglang_venv(
            declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
            local_environment_path=write_local_environment(tmp_path),
            run_id="prepare-venv-test",
            run=fake_run,
            plan_emitter=drifted_plan,
        )

    assert calls == []


def test_prepare_model_cache_rejects_emitted_plan_drift_before_download(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def drifted_plan(config, inner_argv, env=None):
        plan = valid_emitted_preparation_plan(config, inner_argv, env=env)
        plan["env"] = {**plan["env"], "SGLANG_CACHE_DIR": "/cache/glm52/drifted-sglang"}
        return plan

    with pytest.raises(RuntimeConfigError, match="rootfs plan SGLANG_CACHE_DIR does not match materialized config"):
        prepare_model_cache(
            declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
            local_environment_path=write_local_environment(tmp_path),
            run_id="prepare-model-test",
            run=fake_run,
            snapshot_validator=lambda path: {"snapshot_path": str(path), "shard_count": 1, "missing_shard_count": 0},
            plan_emitter=drifted_plan,
        )

    assert calls == []


def test_validate_preparation_records_rejects_plan_digest_mismatch(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19021)
    expected_rootfs = glm52_sglang_runtime._rootfs_recipe_digest(config)
    records = {
        "sglang_venv_record": {
            "schema_version": 1,
            "run_id": config.run_id,
            "venv": {
                "path": "/cache/glm52/venvs/sglang",
                "python": "/cache/glm52/venvs/sglang/bin/python",
                "packages": glm52_sglang_runtime.SGLANG_PREPARE_PACKAGES,
                "installed_packages": {"sglang": "0.4.0"},
            },
            "dependency_resolution": glm52_sglang_runtime._locked_dependency_resolution_record(),
            "rootfs": {"recipe_sha256": expected_rootfs},
            "bwrap_plan": {"plan_sha256": "wrong"},
            "checks": {
                "served_model_name_flag": True,
                "platform": {
                    "class": "CudaSRTPlatform",
                    "device_name": "cuda",
                    "device_type": "cuda",
                    "is_cpu": False,
                    "is_cuda": True,
                    "utils_is_cpu": False,
                    "rotary_base_is_cpu": False,
                    "rotary_base_is_cuda": True,
                },
                "offloader_patch": {
                    "patch_id": "glm52-offloader-v1-plain-tensor-attrs-v1",
                    "sha256_after": "patched-sha",
                },
            },
        },
        "model_cache_record": {
            "schema_version": 1,
            "run_id": config.run_id,
            "model_cache": {
                "model_id": "zai-org/GLM-5.2",
                "snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc",
                "shard_count": 1,
                "missing_shard_count": 0,
            },
            "rootfs": {"recipe_sha256": expected_rootfs},
            "bwrap_plan": {
                "plan_sha256": glm52_sglang_runtime._preparation_plan_digest_for(
                    config,
                    glm52_sglang_runtime._model_cache_prepare_command(config),
                    env=glm52_sglang_runtime._model_cache_prepare_env(),
                )
            },
        },
    }
    for name, record in records.items():
        path = glm52_sglang_runtime._preparation_record_path(config, name)
        glm52_sglang_runtime._write_json(path, record)
    venv_plan = valid_emitted_preparation_plan(config, glm52_sglang_runtime._sglang_venv_prepare_command())
    model_plan = valid_emitted_preparation_plan(
        config,
        glm52_sglang_runtime._model_cache_prepare_command(config),
        env=glm52_sglang_runtime._model_cache_prepare_env(),
    )
    venv_plan_path = glm52_sglang_runtime._preparation_plan_path_for_record(config, "sglang_venv_record")
    venv_plan_path.parent.mkdir(parents=True, exist_ok=True)
    venv_plan_path.write_text(yaml.safe_dump(venv_plan, sort_keys=False))
    model_plan_path = glm52_sglang_runtime._preparation_plan_path_for_record(config, "model_cache_record")
    model_plan_path.parent.mkdir(parents=True, exist_ok=True)
    model_plan_path.write_text(yaml.safe_dump(model_plan, sort_keys=False))

    with pytest.raises(RuntimeConfigError, match="bwrap plan digest mismatch"):
        validate_preparation_records(config=config)


def test_validate_preparation_records_accepts_generated_prepare_records(tmp_path: Path) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_environment_path = write_local_environment(tmp_path)

    def fake_venv_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        inner = argv[argv.index("--") + 1 :]
        if inner[:2] == ["uv", "venv"]:
            return subprocess.CompletedProcess(argv, 0, stdout="Using Python 3.12\nCreating virtual environment\n", stderr="")
        expected_sync_prefix = [
            "env",
            "VIRTUAL_ENV=/cache/glm52/venvs/sglang",
            "UV_PROJECT_ENVIRONMENT=/cache/glm52/venvs/sglang",
            "uv",
            "sync",
            "--active",
            "--locked",
            "--no-sources-package",
            "torch",
            "--no-install-project",
            "--only-group",
            "glm52-runtime",
        ]
        if inner[: len(expected_sync_prefix)] == expected_sync_prefix:
            assert kwargs["env"]["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
            assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"
            return subprocess.CompletedProcess(argv, 0, stdout="resolved glm52 runtime deps\n", stderr="")
        if inner[:4] == [
            "/cache/glm52/venvs/sglang/bin/python",
            "/workspace/monarch/scripts/glm52_sglang_offloader_patch.py",
            "--offloader",
            "/cache/glm52/venvs/sglang/lib/python3.12/site-packages/sglang/srt/utils/offloader.py",
        ]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"patch_id":"glm52-offloader-v1-plain-tensor-attrs-v1",'
                    '"sha256_after":"patched-sha","changed":false}\n'
                ),
                stderr="",
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-c", glm52_sglang_runtime.SGLANG_VENV_PROBE_SCRIPT]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"python": "/cache/glm52/venvs/sglang/bin/python", '
                    '"sys_prefix": "/cache/glm52/venvs/sglang", '
                    '"packages": {"sglang": "0.4.0"}, '
                    '"platform": {"class": "CudaSRTPlatform", "device_name": "cuda", "device_type": "cuda", '
                    '"is_cpu": false, "is_cuda": true, "utils_is_cpu": false, '
                    '"rotary_base_is_cpu": false, "rotary_base_is_cuda": true}}'
                ),
                stderr="",
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-m", "sglang.launch_server"]:
            return subprocess.CompletedProcess(argv, 0, stdout="usage: --served-model-name NAME\n", stderr="")
        raise AssertionError(f"unexpected venv command: {inner}")

    prepare_sglang_venv(
        declared_path=declared_path,
        local_environment_path=local_environment_path,
        run_id="prepare-generated",
        run=fake_venv_run,
        plan_emitter=lambda config, inner_argv, env=None: valid_emitted_preparation_plan(config, inner_argv, env=env),
    )

    prepare_model_cache(
        declared_path=declared_path,
        local_environment_path=local_environment_path,
        run_id="prepare-generated",
        run=lambda argv, **kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc"}',
            stderr="",
        ),
        snapshot_validator=lambda path: {"snapshot_path": str(path), "shard_count": 1, "missing_shard_count": 0},
        plan_emitter=lambda config, inner_argv, env=None: valid_emitted_preparation_plan(config, inner_argv, env=env),
    )

    config = materialize_runtime_config(
        declared=load_declared_spec(declared_path),
        local_environment=load_local_environment(local_environment_path),
        run_id="prepare-generated",
        port=19000,
    )
    write_model_snapshot_for_record(
        config,
        glm52_sglang_runtime._load_json_mapping(
            glm52_sglang_runtime._preparation_record_path(config, "model_cache_record")
        ),
    )

    records = validate_preparation_records(config=config)

    assert records["sglang_venv"]["run_id"] == "prepare-generated"
    assert records["model_cache"]["run_id"] == "prepare-generated"


def test_validate_preparation_records_rejects_cpu_platform_record_for_cuda_config(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19021)
    records = valid_preparation_records_for_config(
        config,
        platform={
            "class": "CpuSRTPlatform",
            "device_name": "cpu",
            "device_type": "cpu",
            "is_cpu": True,
            "is_cuda": False,
            "utils_is_cpu": True,
            "rotary_base_is_cpu": True,
            "rotary_base_is_cuda": False,
        },
    )
    for name, record in records.items():
        path = glm52_sglang_runtime._preparation_record_path(config, name)
        glm52_sglang_runtime._write_json(path, record)
    for name, inner_argv, env in (
        ("sglang_venv_record", glm52_sglang_runtime._sglang_venv_prepare_command(), None),
        ("model_cache_record", glm52_sglang_runtime._model_cache_prepare_command(config), glm52_sglang_runtime._model_cache_prepare_env()),
    ):
        plan_path = glm52_sglang_runtime._preparation_plan_path_for_record(config, name)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(yaml.safe_dump(valid_emitted_preparation_plan(config, inner_argv, env=env), sort_keys=False))

    with pytest.raises(RuntimeConfigError, match="reports CPU platform for CUDA route"):
        validate_preparation_records(config=config)


def valid_preparation_records_for_config(
    config,
    *,
    platform: dict[str, object],
) -> dict[str, dict[str, object]]:
    expected_rootfs = glm52_sglang_runtime._rootfs_recipe_digest(config)
    return {
        "sglang_venv_record": {
            "schema_version": 1,
            "run_id": config.run_id,
            "venv": {
                "path": "/cache/glm52/venvs/sglang",
                "python": "/cache/glm52/venvs/sglang/bin/python",
                "packages": glm52_sglang_runtime.SGLANG_PREPARE_PACKAGES,
                "installed_packages": {"sglang": "0.4.0"},
            },
            "dependency_resolution": glm52_sglang_runtime._locked_dependency_resolution_record(),
            "rootfs": {"recipe_sha256": expected_rootfs},
            "bwrap_plan": {
                "plan_sha256": glm52_sglang_runtime._preparation_plan_digest_for(
                    config,
                    glm52_sglang_runtime._sglang_venv_prepare_command(),
                )
            },
            "checks": {
                "served_model_name_flag": True,
                "platform": platform,
                "offloader_patch": {
                    "patch_id": "glm52-offloader-v1-plain-tensor-attrs-v1",
                    "sha256_after": "patched-sha",
                },
            },
        },
        "model_cache_record": {
            "schema_version": 1,
            "run_id": config.run_id,
            "model_cache": {
                "model_id": config.model["id"],
                "snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc",
                "shard_count": 1,
                "missing_shard_count": 0,
            },
            "rootfs": {"recipe_sha256": expected_rootfs},
            "bwrap_plan": {
                "plan_sha256": glm52_sglang_runtime._preparation_plan_digest_for(
                    config,
                    glm52_sglang_runtime._model_cache_prepare_command(config),
                    env=glm52_sglang_runtime._model_cache_prepare_env(),
                )
            },
        },
    }


def write_model_snapshot_for_record(
    config,
    model_record: dict[str, object],
) -> Path:
    model_cache = model_record["model_cache"]
    assert isinstance(model_cache, dict)
    snapshot_path = Path(
        glm52_sglang_runtime._host_path_from_cache_sandbox_path(
            config,
            str(model_cache["snapshot_path"]),
        )
    )
    snapshot_path.mkdir(parents=True, exist_ok=True)
    (snapshot_path / "model.safetensors").write_text("weights")
    return snapshot_path


def write_valid_preparation_records_for_config(
    config,
    *,
    platform: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    records = valid_preparation_records_for_config(
        config,
        platform=platform
        or {
            "class": "CudaSRTPlatform",
            "device_name": "cuda",
            "device_type": "cuda",
            "is_cpu": False,
            "is_cuda": True,
            "utils_is_cpu": False,
            "rotary_base_is_cpu": False,
            "rotary_base_is_cuda": True,
        },
    )
    command_specs = {
        "sglang_venv_record": (glm52_sglang_runtime._sglang_venv_prepare_command(), None),
        "model_cache_record": (glm52_sglang_runtime._model_cache_prepare_command(config), glm52_sglang_runtime._model_cache_prepare_env()),
    }
    for name, record in records.items():
        if name == "model_cache_record":
            write_model_snapshot_for_record(config, record)
        preparation_config = glm52_sglang_runtime._preparation_config_for_record(config, name)
        inner_argv, env = command_specs[name]
        record["run_id"] = preparation_config.run_id
        record["bwrap_plan"] = {
            "plan_sha256": glm52_sglang_runtime._preparation_plan_digest_for(
                preparation_config,
                inner_argv,
                env=env,
            )
        }
        path = glm52_sglang_runtime._preparation_record_path(config, name)
        glm52_sglang_runtime._write_json(path, record)
    for name, (inner_argv, env) in command_specs.items():
        preparation_config = glm52_sglang_runtime._preparation_config_for_record(config, name)
        plan_path = glm52_sglang_runtime._preparation_plan_path_for_record(config, name)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(yaml.safe_dump(valid_emitted_preparation_plan(preparation_config, inner_argv, env=env), sort_keys=False))
    return records


def test_validate_preparation_records_rejects_missing_records(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19021)

    with pytest.raises(RuntimeConfigError, match="missing SGLang venv preparation record"):
        validate_preparation_records(config=config)


def test_ensure_preparation_records_regenerates_stale_model_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_environment_path = write_local_environment(tmp_path)
    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_environment_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19021,
    )
    config = glm52_sglang_runtime.with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_env,
    )
    records = write_valid_preparation_records_for_config(config)
    records["model_cache_record"]["model_cache"]["model_id"] = "Qwen/Qwen3-0.6B"
    glm52_sglang_runtime._write_json(
        glm52_sglang_runtime._preparation_record_path(config, "model_cache_record"),
        records["model_cache_record"],
    )
    prepare_calls: list[str] = []

    def fake_prepare_sglang_venv(**_kwargs):
        prepare_calls.append("venv")
        raise AssertionError("valid venv record should not be regenerated")

    def fake_prepare_model_cache(
        *,
        declared_path: Path,
        local_environment_path: Path,
        run_id: str,
    ):
        prepare_calls.append("model")
        assert declared_path == declared.source_path
        assert local_environment_path == local_env.source_path
        assert run_id == glm52_sglang_runtime.MODEL_CACHE_PREPARE_RUN_ID
        records = write_valid_preparation_records_for_config(config)
        return records["model_cache_record"]

    monkeypatch.setattr(glm52_sglang_runtime, "prepare_sglang_venv", fake_prepare_sglang_venv)
    monkeypatch.setattr(glm52_sglang_runtime, "prepare_model_cache", fake_prepare_model_cache)

    result = glm52_sglang_runtime.ensure_preparation_records(
        config=config,
        declared=declared,
        local_environment=local_env,
    )

    assert result["status"] == "healed"
    assert result["regenerated"] == ["model_cache_record"]
    assert prepare_calls == ["model"]
    validate_preparation_records(config=config)


def test_ensure_preparation_records_regenerates_incomplete_model_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_environment_path = write_local_environment(tmp_path)
    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_environment_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19021,
    )
    config = glm52_sglang_runtime.with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_env,
    )
    records = write_valid_preparation_records_for_config(config)
    snapshot_path = Path(
        glm52_sglang_runtime._host_path_from_cache_sandbox_path(
            config,
            records["model_cache_record"]["model_cache"]["snapshot_path"],
        )
    )
    (snapshot_path / "model.safetensors").unlink()
    prepare_calls: list[str] = []

    def fake_prepare_sglang_venv(**_kwargs):
        prepare_calls.append("venv")
        raise AssertionError("valid venv record should not be regenerated")

    def fake_prepare_model_cache(
        *,
        declared_path: Path,
        local_environment_path: Path,
        run_id: str,
    ):
        prepare_calls.append("model")
        assert declared_path == declared.source_path
        assert local_environment_path == local_env.source_path
        assert run_id == glm52_sglang_runtime.MODEL_CACHE_PREPARE_RUN_ID
        return write_valid_preparation_records_for_config(config)["model_cache_record"]

    monkeypatch.setattr(glm52_sglang_runtime, "prepare_sglang_venv", fake_prepare_sglang_venv)
    monkeypatch.setattr(glm52_sglang_runtime, "prepare_model_cache", fake_prepare_model_cache)

    result = glm52_sglang_runtime.ensure_preparation_records(
        config=config,
        declared=declared,
        local_environment=local_env,
    )

    assert result == {"status": "healed", "regenerated": ["model_cache_record"]}
    assert prepare_calls == ["model"]
    validate_preparation_records(config=config)


def test_ensure_preparation_records_regenerates_stale_venv_record_with_strict_only_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_environment_path = write_local_environment(tmp_path)
    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_environment_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19021,
    )
    config = glm52_sglang_runtime.with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_env,
    )
    records = write_valid_preparation_records_for_config(config)
    del records["sglang_venv_record"]["checks"]["offloader_patch"]["sha256_after"]
    glm52_sglang_runtime._write_json(
        glm52_sglang_runtime._preparation_record_path(config, "sglang_venv_record"),
        records["sglang_venv_record"],
    )
    prepare_calls: list[str] = []

    def fake_prepare_sglang_venv(
        *,
        declared_path: Path,
        local_environment_path: Path,
        run_id: str,
    ):
        prepare_calls.append("venv")
        assert declared_path == declared.source_path
        assert local_environment_path == local_env.source_path
        assert run_id == glm52_sglang_runtime.SGLANG_PREPARE_RUN_ID
        records = write_valid_preparation_records_for_config(config)
        return records["sglang_venv_record"]

    def fake_prepare_model_cache(**_kwargs):
        prepare_calls.append("model")
        raise AssertionError("valid model record should not be regenerated")

    monkeypatch.setattr(glm52_sglang_runtime, "prepare_sglang_venv", fake_prepare_sglang_venv)
    monkeypatch.setattr(glm52_sglang_runtime, "prepare_model_cache", fake_prepare_model_cache)

    result = glm52_sglang_runtime.ensure_preparation_records(
        config=config,
        declared=declared,
        local_environment=local_env,
    )

    assert result["status"] == "healed"
    assert result["regenerated"] == ["sglang_venv_record"]
    assert prepare_calls == ["venv"]
    validate_preparation_records(config=config)


def test_ensure_preparation_records_real_model_prepare_targets_stable_record_path(
    tmp_path: Path,
) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_environment_path = write_local_environment(tmp_path)
    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_environment_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19021,
    )
    config = glm52_sglang_runtime.with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_env,
    )
    records = write_valid_preparation_records_for_config(config)
    records["model_cache_record"]["model_cache"]["model_id"] = "Qwen/Qwen3-0.6B"
    glm52_sglang_runtime._write_json(
        glm52_sglang_runtime._preparation_record_path(config, "model_cache_record"),
        records["model_cache_record"],
    )
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc"}',
            stderr="",
        )

    result = glm52_sglang_runtime.ensure_preparation_records(
        config=config,
        declared=declared,
        local_environment=local_env,
        declared_path=declared_path,
        local_environment_path=local_environment_path,
        prepare_model_cache_fn=lambda **kwargs: glm52_sglang_runtime.prepare_model_cache(
            **kwargs,
            run=fake_run,
            snapshot_validator=lambda path: {"snapshot_path": str(path), "shard_count": 1, "missing_shard_count": 0},
            plan_emitter=lambda prepare_config, inner_argv, env=None: valid_emitted_preparation_plan(
                prepare_config,
                inner_argv,
                env=env,
            ),
        ),
    )

    assert result == {"status": "healed", "regenerated": ["model_cache_record"]}
    assert calls
    assert glm52_sglang_runtime._preparation_record_path(config, "model_cache_record").exists()
    validate_preparation_records(config=config)


def test_ensure_preparation_records_reraises_when_regeneration_still_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_environment_path = write_local_environment(tmp_path)
    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_environment_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19021,
    )
    config = glm52_sglang_runtime.with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_env,
    )
    records = write_valid_preparation_records_for_config(config)
    records["model_cache_record"]["model_cache"]["model_id"] = "Qwen/Qwen3-0.6B"
    glm52_sglang_runtime._write_json(
        glm52_sglang_runtime._preparation_record_path(config, "model_cache_record"),
        records["model_cache_record"],
    )

    def fake_prepare_model_cache(*, declared_path, local_environment_path, run_id):
        stale_records = write_valid_preparation_records_for_config(config)
        stale_records["model_cache_record"]["model_cache"]["model_id"] = "Qwen/Qwen3-0.6B"
        glm52_sglang_runtime._write_json(
            glm52_sglang_runtime._preparation_record_path(config, "model_cache_record"),
            stale_records["model_cache_record"],
        )
        return stale_records["model_cache_record"]

    monkeypatch.setattr(glm52_sglang_runtime, "prepare_model_cache", fake_prepare_model_cache)

    with pytest.raises(RuntimeConfigError, match="model cache preparation record model id mismatch"):
        glm52_sglang_runtime.ensure_preparation_records(
            config=config,
            declared=declared,
            local_environment=local_env,
        )


def test_ensure_preparation_records_noop_when_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY))
    local_env = load_local_environment(write_local_environment(tmp_path))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19021,
    )
    config = glm52_sglang_runtime.with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_env,
    )
    write_valid_preparation_records_for_config(config)

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "prepare_sglang_venv",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("prepare_sglang_venv should not run")),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "prepare_model_cache",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("prepare_model_cache should not run")),
    )

    result = glm52_sglang_runtime.ensure_preparation_records(
        config=config,
        declared=declared,
        local_environment=local_env,
    )

    assert result["status"] == "already_valid"
    assert result["regenerated"] == []


def test_ensure_preparation_records_requires_existing_source_paths_for_heal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY))
    local_env = load_local_environment(write_local_environment(tmp_path))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19021,
    )
    config = glm52_sglang_runtime.with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_env,
    )
    records = write_valid_preparation_records_for_config(config)
    records["model_cache_record"]["model_cache"]["model_id"] = "Qwen/Qwen3-0.6B"
    glm52_sglang_runtime._write_json(
        glm52_sglang_runtime._preparation_record_path(config, "model_cache_record"),
        records["model_cache_record"],
    )
    declared_without_source = replace(declared, source_path=None)
    local_env_without_source = replace(local_env, source_path=None)

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "prepare_model_cache",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("prepare should not run without source paths")),
    )

    with pytest.raises(RuntimeConfigError, match="declared spec source path is required for preparation healing"):
        glm52_sglang_runtime.ensure_preparation_records(
            config=config,
            declared=declared_without_source,
            local_environment=local_env_without_source,
        )


def test_repeatability_rejects_default_ports(tmp_path: Path) -> None:
    declared_path = write_spec(
        tmp_path / "declared.yaml",
        VALID_DECLARED_WITH_OVERLAY.replace("range_start: 19000", "range_start: 8000").replace(
            "range_end: 19100",
            "range_end: 8000",
        ),
    )

    with pytest.raises(RuntimeConfigError, match="disallowed port"):
        glm52_sglang_runtime.run_repeatability_cycles(
            declared_path=declared_path,
            local_environment_path=write_local_environment(tmp_path),
            run_id="bad-port",
        )


def test_launch_cycle_rejects_inner_argv_drift(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19031)
    drifted = config.replace_launch_inner(config.launch["inner_argv"] + ["--port", "8000"])

    with pytest.raises(RuntimeConfigError, match="inner argv mismatch"):
        validate_materialized_config(drifted)


def test_launch_failure_tears_down_when_debug_disabled(tmp_path: Path) -> None:
    events: list[str] = []

    def fake_launch(config: MaterializedSglangRuntimeConfig) -> Any:
        events.append("launch")
        return glm52_sglang_runtime.ProcessRecord(
            pid=1234,
            pgid=1234,
            argv=config.launch["inner_argv"],
            port=config.service["port"],
        )

    def fake_probe(config: MaterializedSglangRuntimeConfig) -> None:
        events.append("probe")
        raise RuntimeLaunchError("probe failed")

    def fake_teardown(record: Any) -> dict[str, Any]:
        events.append("teardown")
        return {"ok": True, "port_closed": True, "process_gone": True}

    original_preflight = glm52_sglang_runtime.preflight_model_cache
    glm52_sglang_runtime.preflight_model_cache = lambda config: {
        "model_cache": {"snapshot_path": "/cache/glm52/hf-home/snapshots/fake", "missing_shard_count": 0}
    }
    with pytest.raises(RuntimeLaunchError, match="probe failed"):
        try:
            glm52_sglang_runtime.run_one_cycle(
                config=materialized_config_for_test(tmp_path, port=19032),
                launch=fake_launch,
                probe=fake_probe,
                teardown=fake_teardown,
            )
        finally:
            glm52_sglang_runtime.preflight_model_cache = original_preflight

    assert events == ["launch", "probe", "teardown"]


def test_launch_uses_prepared_model_snapshot_in_actual_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_config_for_test(tmp_path, port=19033)
    launched: list[MaterializedSglangRuntimeConfig] = []

    def fake_preflight_model_cache(_config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
        return {
            "model_cache": {
                "snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123",
                "missing_shard_count": 0,
            }
        }

    def fake_launch(cycle_config: MaterializedSglangRuntimeConfig) -> Any:
        launched.append(cycle_config)
        return glm52_sglang_runtime.ProcessRecord(
            pid=1234,
            pgid=1234,
            argv=cycle_config.launch["inner_argv"],
            port=cycle_config.service["port"],
        )

    monkeypatch.setattr(glm52_sglang_runtime, "preflight_model_cache", fake_preflight_model_cache)

    result = glm52_sglang_runtime.run_one_cycle(
        config=config,
        launch=fake_launch,
        probe=lambda _config: {"ok": True},
        teardown=lambda _record: {"ok": True, "port_closed": True, "process_gone": True},
    )

    assert result["ok"] is True
    assert launched
    effective = launched[0]
    assert effective.model["path"] == "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123"
    assert glm52_sglang_runtime._argv_value(effective.launch["inner_argv"], "--model-path") == effective.model["path"]
    assert "zai-org/GLM-5.2" != effective.model["path"]


def test_launch_runtime_probe_failure_uses_recorded_teardown_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_local_environment(tmp_path))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-probe-failure",
        port=19034,
    )
    teardown_configs: list[MaterializedSglangRuntimeConfig] = []

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("launch_runtime must not use direct process termination after recording process")

        def wait(self, timeout=None):
            raise AssertionError("launch_runtime must not wait through direct process termination")

    monkeypatch.setattr(glm52_sglang_runtime, "run_sglang_help_preflight", lambda _config: "--served-model-name")
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "emit_and_load_rootfs_plan",
        lambda cycle_config, *, resolved_plan_path: valid_rootfs_plan(cycle_config),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_model_cache",
        lambda _config: {"model_cache": {"snapshot_path": "/cache/glm52/hf-home/snapshots/abc123"}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_gpu_occupancy",
        lambda _config: {"status": "free", "checked_gpus": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "wait_for_models_probe",
        lambda _config, *, process=None: (_ for _ in ()).throw(RuntimeConfigError("model identity mismatch")),
    )

    def fake_teardown_runtime(cycle_config, *, local_environment):
        teardown_configs.append(cycle_config)
        record_path = Path(
            glm52_sglang_runtime._resolve_host_path_ref(
                cycle_config,
                cycle_config.artifacts["process_record"],
            )
        )
        record = load_yaml_mapping(record_path)
        assert "sglang.launch_server" in record["inner_argv"]
        assert glm52_sglang_runtime._argv_value(record["inner_argv"], "--port") == str(cycle_config.service["port"])
        summary_path = Path(
            glm52_sglang_runtime._resolve_host_path_ref(
                cycle_config,
                cycle_config.artifacts["teardown_summary"],
            )
        )
        glm52_sglang_runtime._write_json(
            summary_path,
            {"status": "teardown_passed", "run_id": cycle_config.run_id, "port": cycle_config.service["port"]},
        )
        return {"status": "teardown_passed", "run_id": cycle_config.run_id, "port": cycle_config.service["port"]}

    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "terminate_process",
        lambda _process: (_ for _ in ()).throw(AssertionError("direct terminate_process path used")),
    )

    with pytest.raises(RuntimeConfigError, match="model identity mismatch"):
        glm52_sglang_runtime.launch_runtime(config, local_environment=local_env)

    assert len(teardown_configs) == 1
    assert teardown_configs[0].model["path"] == "/cache/glm52/hf-home/snapshots/abc123"
    run_dir = tmp_path / "repo" / "glm52-serving-results" / config.run_id
    launch_summary = glm52_sglang_runtime._load_json_mapping(run_dir / "launch-summary.json")
    teardown_summary = glm52_sglang_runtime._load_json_mapping(run_dir / "teardown-summary.json")
    assert launch_summary["teardown_action"] == "teardown_runtime"
    assert teardown_summary["status"] == "teardown_passed"


def test_launch_runtime_probe_failure_emits_owned_diagnostic_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_local_environment(tmp_path))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-probe-diagnostic",
        port=19035,
    )
    events: list[tuple[str, int, int | None]] = []

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

    monkeypatch.setattr(glm52_sglang_runtime, "run_sglang_help_preflight", lambda _config: "--served-model-name")
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "emit_and_load_rootfs_plan",
        lambda cycle_config, *, resolved_plan_path: valid_rootfs_plan(cycle_config),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_model_cache",
        lambda _config: {"model_cache": {"snapshot_path": "/cache/glm52/hf-home/snapshots/abc123"}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_gpu_occupancy",
        lambda _config: {"status": "free", "checked_gpus": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "wait_for_models_probe",
        lambda _config, *, process=None: {"models": ["zai-org/GLM-5.2"], "served_model_name": "zai-org/GLM-5.2"},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "probe_generate",
        lambda _config: (_ for _ in ()).throw(RuntimeLaunchError("generate probe timed out after 300s")),
    )
    monkeypatch.setattr(glm52_sglang_runtime.os, "getpgid", lambda _pid: 12345)
    monkeypatch.setattr(glm52_sglang_runtime, "_live_process_argv", lambda _pid: config.launch["inner_argv"])
    monkeypatch.setattr(
        glm52_sglang_runtime.os,
        "killpg",
        lambda pgid, sig: events.append(("signal", pgid, sig)),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime.time,
        "sleep",
        lambda seconds: events.append(("sleep", int(seconds), None)),
    )

    def fake_teardown_runtime(cycle_config, *, local_environment):
        events.append(("teardown", cycle_config.service["port"], None))
        summary_path = Path(
            glm52_sglang_runtime._resolve_host_path_ref(
                cycle_config,
                cycle_config.artifacts["teardown_summary"],
            )
        )
        glm52_sglang_runtime._write_json(
            summary_path,
            {"status": "teardown_passed", "run_id": cycle_config.run_id, "port": cycle_config.service["port"]},
        )
        return {"status": "teardown_passed", "run_id": cycle_config.run_id, "port": cycle_config.service["port"]}

    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)
    crash_dump_dir = tmp_path / "repo" / "glm52-serving-results" / config.run_id / "crash-dumps"
    crash_dump_dir.mkdir(parents=True)
    (crash_dump_dir / "rank0.txt").write_text("diagnostic\n")

    with pytest.raises(RuntimeLaunchError, match="generate probe timed out after 300s"):
        glm52_sglang_runtime.launch_runtime(config, local_environment=local_env)

    assert events == [
        ("signal", 12345, glm52_sglang_runtime.signal.SIGQUIT),
        ("sleep", 6, None),
        ("teardown", 19035, None),
    ]
    launch_summary = glm52_sglang_runtime._load_json_mapping(
        tmp_path / "repo" / "glm52-serving-results" / config.run_id / "launch-summary.json"
    )
    assert launch_summary["diagnostic_action"] == {
        "status": "sent",
        "signal": "SIGQUIT",
        "process_group": 12345,
        "reason": "probe_failure",
        "flush_wait_seconds": 6,
        "crash_dump_folder": "/run/glm52/crash-dumps",
        "crash_dump_host_path": str(crash_dump_dir),
        "crash_dump_files": ["rank0.txt"],
    }


def test_emit_failure_diagnostic_signal_rejects_live_command_drift_before_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_config_for_test(tmp_path, port=19017)
    artifact_paths = glm52_sglang_runtime._resolve_artifact_paths(config)
    artifact_paths["process_record"].parent.mkdir(parents=True, exist_ok=True)
    glm52_sglang_runtime._write_yaml(
        artifact_paths["process_record"],
        {
            "schema_version": 1,
            "run_id": config.run_id,
            "status": "running",
            "pid": 12345,
            "pgid": 12345,
            "process_group": 12345,
            "port": config.service["port"],
            "outer_argv": glm52_sglang_runtime._resolved_outer_argv(config),
            "inner_argv": config.launch["inner_argv"],
            "env": config.launch["env"],
        },
    )
    sent_signals: list[int] = []

    monkeypatch.setattr(glm52_sglang_runtime.os, "getpgid", lambda _pid: 12345)
    monkeypatch.setattr(glm52_sglang_runtime, "_live_process_argv", lambda _pid: ["python", "-m", "unrelated.server", "--port", "19017"])
    monkeypatch.setattr(glm52_sglang_runtime.os, "killpg", lambda pgid, sig: sent_signals.append(sig))

    with pytest.raises(RuntimeConfigError, match="live process command guard missing sglang.launch_server"):
        glm52_sglang_runtime.emit_failure_diagnostic_signal(config, reason="probe_failure")

    assert sent_signals == []


def test_launch_runtime_writes_required_throughput_probe_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_local_environment(tmp_path))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-throughput",
        port=19036,
    )
    events: list[str] = []

    class FakeProcess:
        pid = 12346

    monkeypatch.setattr(glm52_sglang_runtime, "run_sglang_help_preflight", lambda _config: "--served-model-name")
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "emit_and_load_rootfs_plan",
        lambda cycle_config, *, resolved_plan_path: valid_rootfs_plan(cycle_config),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_model_cache",
        lambda _config: {"model_cache": {"snapshot_path": "/cache/glm52/hf-home/snapshots/abc123"}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_gpu_occupancy",
        lambda _config: {"status": "free", "checked_gpus": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime.os, "getpgid", lambda _pid: 12346)
    monkeypatch.setattr(glm52_sglang_runtime, "_live_process_argv", lambda _pid: config.launch["inner_argv"])
    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "wait_for_models_probe",
        lambda _config, *, process=None: events.append("models") or {"models": ["zai-org/GLM-5.2"]},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "probe_generate",
        lambda _config: events.append("generate") or {"content": "ok", "payload": {}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "probe_completion",
        lambda _config: events.append("completion") or {"content": "ok", "payload": {}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "probe_chat",
        lambda _config: events.append("chat") or {"content": "ok", "payload": {}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "probe_throughput",
        lambda _config: events.append("throughput")
        or {
            "content": "warm throughput text",
            "payload": {"meta_info": {"completion_tokens": 128, "e2e_latency": 4.0}},
            "metrics": {"completion_tokens": 128, "e2e_latency_s": 4.0, "tokens_per_second": 32.0},
        },
    )

    summary = glm52_sglang_runtime.launch_runtime(config, local_environment=local_env)

    assert summary["status"] == "launch_passed"
    assert events == ["models", "generate", "completion", "chat", "throughput"]
    throughput_path = tmp_path / "repo" / "glm52-serving-results" / config.run_id / "probes" / "throughput.json"
    throughput = glm52_sglang_runtime._load_json_mapping(throughput_path)
    assert throughput["metrics"] == {
        "completion_tokens": 128,
        "e2e_latency_s": 4.0,
        "tokens_per_second": 32.0,
    }


def test_teardown_reports_killed_when_group_clears_after_escalation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_config_for_test(tmp_path, port=19017)
    artifact_paths = glm52_sglang_runtime._resolve_artifact_paths(config)
    artifact_paths["process_record"].parent.mkdir(parents=True, exist_ok=True)
    glm52_sglang_runtime._write_yaml(
        artifact_paths["process_record"],
        {
            "schema_version": 1,
            "run_id": config.run_id,
            "status": "running",
            "pid": 12345,
            "pgid": 12345,
            "process_group": 12345,
            "port": config.service["port"],
            "outer_argv": glm52_sglang_runtime._resolved_outer_argv(config),
            "inner_argv": config.launch["inner_argv"],
            "env": config.launch["env"],
        },
    )
    sent_signals: list[int] = []
    group_exists_results = iter([True, False])
    time_values = iter([0, 1, 31])
    has_running_members_results = iter([True, False])

    monkeypatch.setattr(glm52_sglang_runtime.os, "killpg", lambda _pgid, sig: sent_signals.append(sig))
    monkeypatch.setattr(glm52_sglang_runtime, "_process_group_exists", lambda _pgid: next(group_exists_results))
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "_process_group_has_running_members",
        lambda _pgid: next(has_running_members_results),
    )
    monkeypatch.setattr(glm52_sglang_runtime, "_is_port_open", lambda _host, _port: False)
    monkeypatch.setattr(glm52_sglang_runtime.time, "time", lambda: next(time_values))
    monkeypatch.setattr(glm52_sglang_runtime.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(glm52_sglang_runtime.os, "getpgid", lambda _pid: 12345)
    monkeypatch.setattr(glm52_sglang_runtime, "_live_process_argv", lambda _pid: config.launch["inner_argv"])

    summary = glm52_sglang_runtime.teardown_runtime(config)

    assert summary == {
        "status": "teardown_passed",
        "run_id": config.run_id,
        "port": config.service["port"],
        "escalated": True,
    }
    assert sent_signals == [glm52_sglang_runtime.signal.SIGTERM, glm52_sglang_runtime.signal.SIGKILL]


def test_teardown_treats_zombie_only_group_as_stopped_after_escalation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_config_for_test(tmp_path, port=19017)
    artifact_paths = glm52_sglang_runtime._resolve_artifact_paths(config)
    artifact_paths["process_record"].parent.mkdir(parents=True, exist_ok=True)
    glm52_sglang_runtime._write_yaml(
        artifact_paths["process_record"],
        {
            "schema_version": 1,
            "run_id": config.run_id,
            "status": "running",
            "pid": 12345,
            "pgid": 12345,
            "process_group": 12345,
            "port": config.service["port"],
            "outer_argv": glm52_sglang_runtime._resolved_outer_argv(config),
            "inner_argv": config.launch["inner_argv"],
            "env": config.launch["env"],
        },
    )
    sent_signals: list[int] = []
    time_values = iter([0, 31])

    monkeypatch.setattr(glm52_sglang_runtime.os, "killpg", lambda _pgid, sig: sent_signals.append(sig))
    monkeypatch.setattr(glm52_sglang_runtime, "_process_group_exists", lambda _pgid: True)
    monkeypatch.setattr(glm52_sglang_runtime, "_process_group_has_running_members", lambda _pgid: False)
    monkeypatch.setattr(glm52_sglang_runtime, "_is_port_open", lambda _host, _port: False)
    monkeypatch.setattr(glm52_sglang_runtime.time, "time", lambda: next(time_values))
    monkeypatch.setattr(glm52_sglang_runtime.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(glm52_sglang_runtime.os, "getpgid", lambda _pid: 12345)
    monkeypatch.setattr(glm52_sglang_runtime, "_live_process_argv", lambda _pid: config.launch["inner_argv"])

    summary = glm52_sglang_runtime.teardown_runtime(config)
    record = load_yaml_mapping(artifact_paths["process_record"])

    assert summary == {
        "status": "teardown_passed",
        "run_id": config.run_id,
        "port": config.service["port"],
        "escalated": True,
    }
    assert record["status"] == "stopped"
    assert record["stop_reason"] == "killed"
    assert sent_signals == [glm52_sglang_runtime.signal.SIGTERM, glm52_sglang_runtime.signal.SIGKILL]


def test_repeatability_summary_uses_ok_contract(tmp_path: Path, monkeypatch) -> None:
    ports: list[int] = []

    def fake_run_one_cycle(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
        ports.append(config.service["port"])
        return {"ok": True, "port": config.service["port"]}

    monkeypatch.setattr(glm52_sglang_runtime, "_is_port_bindable", lambda _host, _port: True)

    summary = glm52_sglang_runtime.run_repeatability_cycles(
        declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
        local_environment_path=write_local_environment(tmp_path),
        run_id="glm52-sglang-repeatability",
        run_one_cycle=fake_run_one_cycle,
        preparation_validator=lambda config: {"ok": True},
    )

    assert summary == {
        "schema_version": 1,
        "run_id": "glm52-sglang-repeatability",
        "ok": True,
        "cycles": [
            {"cycle": 1, "ok": True, "port": 19000},
            {"cycle": 2, "ok": True, "port": 19001},
            {"cycle": 3, "ok": True, "port": 19002},
        ],
    }
    assert ports == [19000, 19001, 19002]


def test_repeatability_consumes_stable_prepare_records(tmp_path: Path) -> None:
    validated_paths: list[dict[str, str]] = []

    def fake_validate(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
        validated_paths.append(dict(config.resolved_paths["preparation"]))
        return {"sglang_venv": {"ok": True}, "model_cache": {"ok": True}}

    def fake_run_one_cycle(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
        return {"ok": True, "port": config.service["port"]}

    glm52_sglang_runtime.run_repeatability_cycles(
        declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
        local_environment_path=write_local_environment(tmp_path),
        run_id="glm52-sglang-repeatability",
        cycles=1,
        run_one_cycle=fake_run_one_cycle,
        preparation_validator=fake_validate,
    )

    assert validated_paths == [
        {
            "sglang_venv_record": str(tmp_path / "repo" / "glm52-serving-results" / "prepare-venv" / "sglang-venv.json"),
            "model_cache_record": str(tmp_path / "repo" / "glm52-serving-results" / "prepare-model" / "model-cache.json"),
        }
    ]


def test_repeat_runtime_skips_teardown_after_not_started_launch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY))
    local_env = load_local_environment(write_local_environment(tmp_path))

    def fake_launch_runtime(config: MaterializedSglangRuntimeConfig, *, local_environment):
        artifact_paths = glm52_sglang_runtime._resolve_artifact_paths(config)
        glm52_sglang_runtime._write_json(
            artifact_paths["launch_summary"],
            {
                "status": "launch_failed",
                "run_id": config.run_id,
                "port": config.service["port"],
                "error": "visible GPU 0 is already occupied",
                "teardown_action": "not_started",
            },
        )
        raise glm52_sglang_runtime.GpuOccupancyError(
            "visible GPU 0 is already occupied",
            blocked_gpus=[
                {
                    "index": 0,
                    "uuid": "GPU-busy",
                    "pid": 1234,
                    "process_name": "VLLM::Worker_TP0_EP0",
                    "used_memory": "103362",
                },
            ],
        )

    def fake_teardown_runtime(_config, *, local_environment):
        raise AssertionError("repeat must not teardown when launch never started a process")

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "ensure_preparation_records",
        lambda **_kwargs: {"status": "already_valid", "regenerated": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)

    with pytest.raises(RuntimeConfigError, match="visible GPU 0 is already occupied"):
        glm52_sglang_runtime.repeat_runtime(declared=declared, local_environment=local_env, cycles=1)

    summary_paths = sorted((tmp_path / "repo" / "glm52-serving-results").glob("*/loop-summary.json"))
    assert len(summary_paths) == 1
    summary = glm52_sglang_runtime._load_json_mapping(summary_paths[0])
    assert summary["status"] == "failed"
    assert summary["cycles"][0]["launch"] == {
        "status": "failed",
        "error": "visible GPU 0 is already occupied",
        "blocked_gpus": [
            {
                "index": 0,
                "uuid": "GPU-busy",
                "pid": 1234,
                "process_name": "VLLM::Worker_TP0_EP0",
                "used_memory": "103362",
            },
        ],
    }
    assert summary["cycles"][0]["teardown"] == {
        "status": "not_started",
        "reason": "launch failed before process start",
    }


def test_repeat_runtime_waits_for_gpu_free_window_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY))
    local_env = load_local_environment(write_local_environment(tmp_path))
    events: list[str] = []
    checks = iter(
        [
            RuntimeConfigError("visible GPU 7 is already occupied"),
            {"status": "free", "checked_gpus": [{"index": 7, "status": "free"}]},
        ]
    )

    def fake_preflight_gpu_occupancy(_config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
        events.append("wait-check")
        result = next(checks)
        if isinstance(result, RuntimeConfigError):
            raise result
        return result

    def fake_launch_runtime(_config: MaterializedSglangRuntimeConfig, *, local_environment):
        events.append("launch")
        return {"status": "launch_passed"}

    def fake_teardown_runtime(_config: MaterializedSglangRuntimeConfig, *, local_environment):
        events.append("teardown")
        return {"status": "teardown_passed"}

    def fake_ensure_preparation_records(**_kwargs):
        events.append("prepare")
        return {"status": "already_valid", "regenerated": []}

    monkeypatch.setattr(glm52_sglang_runtime, "preflight_gpu_occupancy", fake_preflight_gpu_occupancy)
    monkeypatch.setattr(glm52_sglang_runtime, "ensure_preparation_records", fake_ensure_preparation_records)
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)
    monkeypatch.setattr(glm52_sglang_runtime.time, "time", lambda: 0)
    monkeypatch.setattr(glm52_sglang_runtime.time, "sleep", lambda _seconds: events.append("sleep"))

    summary = glm52_sglang_runtime.repeat_runtime(
        declared=declared,
        local_environment=local_env,
        cycles=1,
        wait_for_gpu_free_seconds=60,
    )

    assert summary["status"] == "passed"
    assert events == ["wait-check", "sleep", "wait-check", "prepare", "launch", "teardown"]
    assert summary["cycles"][0]["prepare_heal"] == {"status": "already_valid", "regenerated": []}
    assert summary["cycles"][0]["gpu_wait"] == {
        "status": "free",
        "checked_gpus": [{"index": 7, "status": "free"}],
    }


def test_repeat_runtime_gpu_wait_timeout_fails_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY))
    local_env = load_local_environment(write_local_environment(tmp_path))
    events: list[str] = []
    time_values = iter([0, 1, 61])

    def fake_preflight_gpu_occupancy(_config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
        events.append("wait-check")
        raise glm52_sglang_runtime.GpuOccupancyError(
            "visible GPU 7 is already occupied",
            blocked_gpus=[
                {
                    "index": 7,
                    "uuid": "GPU-busy",
                    "pid": 1234,
                    "process_name": "VLLM::Worker_TP7_EP7",
                    "used_memory": "96520",
                },
            ],
        )

    def fake_launch_runtime(_config: MaterializedSglangRuntimeConfig, *, local_environment):
        raise AssertionError("repeat must not launch before the GPU-free wait gate passes")

    monkeypatch.setattr(glm52_sglang_runtime, "preflight_gpu_occupancy", fake_preflight_gpu_occupancy)
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "ensure_preparation_records",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("prepare must not run before the GPU-free wait gate passes")),
    )
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime.time, "time", lambda: next(time_values))
    monkeypatch.setattr(glm52_sglang_runtime.time, "sleep", lambda _seconds: events.append("sleep"))

    with pytest.raises(RuntimeConfigError, match="GPU-free wait timed out after 60s"):
        glm52_sglang_runtime.repeat_runtime(
            declared=declared,
            local_environment=local_env,
            cycles=1,
            wait_for_gpu_free_seconds=60,
        )

    assert events == ["wait-check", "sleep", "wait-check"]
    summary_paths = sorted((tmp_path / "repo" / "glm52-serving-results").glob("*/loop-summary.json"))
    assert len(summary_paths) == 1
    summary = glm52_sglang_runtime._load_json_mapping(summary_paths[0])
    assert summary["status"] == "failed"
    assert summary["cycles"][0]["gpu_wait"] == {
        "status": "failed",
        "error": "GPU-free wait timed out after 60s: visible GPU 7 is already occupied",
        "blocked_gpus": [
            {
                "index": 7,
                "uuid": "GPU-busy",
                "pid": 1234,
                "process_name": "VLLM::Worker_TP7_EP7",
                "used_memory": "96520",
            },
        ],
    }
    assert "launch" not in summary["cycles"][0]


def test_repeat_runtime_requires_stable_gpu_free_window_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY))
    local_env = load_local_environment(write_local_environment(tmp_path))
    events: list[str] = []
    time_values = iter([0, 0, 3, 6])

    def fake_preflight_gpu_occupancy(_config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
        events.append("wait-check")
        return {"status": "free", "checked_gpus": [{"index": 7, "status": "free"}]}

    def fake_launch_runtime(_config: MaterializedSglangRuntimeConfig, *, local_environment):
        events.append("launch")
        return {"status": "launch_passed"}

    def fake_teardown_runtime(_config: MaterializedSglangRuntimeConfig, *, local_environment):
        return {"status": "teardown_passed"}

    def fake_ensure_preparation_records(**_kwargs):
        events.append("prepare")
        return {"status": "already_valid", "regenerated": []}

    monkeypatch.setattr(glm52_sglang_runtime, "preflight_gpu_occupancy", fake_preflight_gpu_occupancy)
    monkeypatch.setattr(glm52_sglang_runtime, "ensure_preparation_records", fake_ensure_preparation_records)
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)
    monkeypatch.setattr(glm52_sglang_runtime.time, "time", lambda: next(time_values))
    monkeypatch.setattr(glm52_sglang_runtime.time, "sleep", lambda _seconds: events.append("sleep"))

    summary = glm52_sglang_runtime.repeat_runtime(
        declared=declared,
        local_environment=local_env,
        cycles=1,
        wait_for_gpu_free_seconds=60,
        gpu_free_stable_seconds=6,
    )

    assert summary["status"] == "passed"
    assert events == ["wait-check", "sleep", "wait-check", "sleep", "wait-check", "prepare", "launch"]
    assert summary["cycles"][0]["prepare_heal"] == {"status": "already_valid", "regenerated": []}
    assert summary["cycles"][0]["gpu_wait"] == {
        "status": "free",
        "checked_gpus": [{"index": 7, "status": "free"}],
        "stable_seconds": 6,
    }


def test_repeatability_raises_when_cycle_returns_not_ok(tmp_path: Path) -> None:
    with pytest.raises(RuntimeConfigError, match="repeatability cycle 1 returned ok=false"):
        glm52_sglang_runtime.run_repeatability_cycles(
            declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
            local_environment_path=write_local_environment(tmp_path),
            run_id="glm52-sglang-repeatability",
            cycles=1,
            run_one_cycle=lambda config: {"ok": False, "port": config.service["port"]},
            preparation_validator=lambda config: {"ok": True},
        )


def test_repeatability_cli_returns_nonzero_when_cycle_returns_not_ok(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_env = write_local_environment(tmp_path)
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "run_one_cycle",
        lambda config: {"ok": False, "port": config.service["port"]},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "validate_preparation_records",
        lambda *, config: {"ok": True},
    )

    rc = main(
        [
            "repeatability",
            "--declared",
            str(declared),
            "--local-env",
            str(local_env),
            "--run-id",
            "cli-repeat-not-ok",
            "--cycles",
            "1",
        ]
    )

    assert rc == 2


def test_cli_accepts_repeatability_command(tmp_path: Path) -> None:
    exit_code = main(
        [
            "repeatability",
            "--declared",
            str(write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)),
            "--local-env",
            str(write_local_environment(tmp_path)),
            "--run-id",
            "cli-repeat",
            "--dry-run",
        ]
    )

    assert exit_code == 0


def test_runtime_launch_error_is_public_exception_type() -> None:
    assert issubclass(RuntimeLaunchError, RuntimeError)


def test_validate_sglang_help_requires_served_model_name_flag() -> None:
    validate_sglang_help("usage: launch_server --model-path X --served-model-name NAME\n")

    with pytest.raises(RuntimeConfigError, match="--served-model-name"):
        validate_sglang_help("usage: launch_server --model-path X\n")


def test_parse_models_response_accepts_served_model_name() -> None:
    parsed = parse_models_response(
        b'{"object":"list","data":[{"id":"zai-org/GLM-5.2"}]}',
        expected_model_ids=["zai-org/GLM-5.2"],
        served_model_name="zai-org/GLM-5.2",
    )

    assert parsed["models"] == ["zai-org/GLM-5.2"]


def test_parse_models_response_rejects_path_identity_when_served_name_expected() -> None:
    with pytest.raises(RuntimeConfigError, match="model identity mismatch"):
        parse_models_response(
            b'{"object":"list","data":[{"id":"/models/glm52"}]}',
            expected_model_ids=["zai-org/GLM-5.2"],
            served_model_name="zai-org/GLM-5.2",
        )


def test_parse_models_response_rejects_missing_expected_model_intersection() -> None:
    with pytest.raises(RuntimeConfigError, match="model identity mismatch"):
        parse_models_response(
            b'{"object":"list","data":[{"id":"zai-org/GLM-5.2"}]}',
            expected_model_ids=["other-model"],
            served_model_name="zai-org/GLM-5.2",
        )


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"object":"list","data":[]}',
        b'{"object":"list","data":{"id":"zai-org/GLM-5.2"}}',
    ],
)
def test_parse_models_response_rejects_invalid_models_payload(body: bytes) -> None:
    with pytest.raises(RuntimeConfigError):
        parse_models_response(
            body,
            expected_model_ids=["zai-org/GLM-5.2"],
            served_model_name="zai-org/GLM-5.2",
        )


def test_parse_models_response_collects_only_string_model_ids() -> None:
    parsed = parse_models_response(
        b'{"object":"list","data":[{"id":17},{"id":"zai-org/GLM-5.2"},{"object":"model"}]}',
        expected_model_ids=["zai-org/GLM-5.2"],
        served_model_name="zai-org/GLM-5.2",
    )

    assert parsed["models"] == ["zai-org/GLM-5.2"]


def test_validate_model_snapshot_requires_all_indexed_shards(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "model-00001-of-00002.safetensors").write_text("shard")
    (snapshot / "model.safetensors.index.json").write_text(
        glm52_sglang_runtime.json.dumps(
            {
                "metadata": {"total_size": 123},
                "weight_map": {
                    "layer.0": "model-00001-of-00002.safetensors",
                    "layer.1": "model-00002-of-00002.safetensors",
                },
            }
        )
    )

    with pytest.raises(RuntimeConfigError, match="references 1 shard file"):
        validate_model_snapshot(snapshot)

    (snapshot / "model-00002-of-00002.safetensors").write_text("shard")
    evidence = validate_model_snapshot(snapshot)

    assert evidence["status"] == "complete"
    assert evidence["referenced_shard_count"] == 2
    assert evidence["missing_shard_count"] == 0


def test_validate_model_snapshot_accepts_single_safetensors_file(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "model.safetensors").write_text("weights")

    evidence = validate_model_snapshot(snapshot)

    assert evidence["status"] == "complete"
    assert evidence["format"] == "single_safetensors"
    assert evidence["shard_count"] == 1
    assert evidence["missing_shard_count"] == 0


def test_validate_model_snapshot_rejects_snapshot_without_safetensors(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "config.json").write_text("{}\n")

    with pytest.raises(RuntimeConfigError, match="missing model.safetensors"):
        validate_model_snapshot(snapshot)


def test_load_local_environment_accepts_absolute_host_paths(tmp_path: Path) -> None:
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    assert local_env.repo == "/repo/monarch"
    assert local_env.cache == "/repo/monarch/.scratch/glm52-local-serving/cache"
    assert local_env.temp == "/repo/monarch/.scratch/glm52-local-serving/tmp"
    assert local_env.rootfs["monarch-default"] == "/repo/monarch/scripts/rootfs/rootfs"


def test_materialize_runtime_config_writes_custom_port_everywhere(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )

    assert config.service["port"] == 19017
    assert config.service["base_url"] == "http://127.0.0.1:19017/v1"
    assert config.probes["models_url"] == "http://127.0.0.1:19017/v1/models"
    assert config.probes["generate_url"] == "http://127.0.0.1:19017/generate"
    assert config.probes["throughput_url"] == "http://127.0.0.1:19017/generate"
    assert config.probes["completions_url"] == "http://127.0.0.1:19017/v1/completions"
    assert config.probes["chat_url"] == "http://127.0.0.1:19017/v1/chat/completions"
    assert config.probes["chat_timeout_seconds"] == 120
    assert config.probes["generate_payload"] == {
        "text": "Say OK.",
        "sampling_params": {
            "temperature": 0,
            "max_new_tokens": 1,
        },
    }
    assert config.probes["throughput_payload"] == {
        "text": "Say OK.",
        "sampling_params": {
            "temperature": 0,
            "max_new_tokens": 128,
            "ignore_eos": True,
        },
    }
    assert config.probes["completion_payload"] == {
        "model": "zai-org/GLM-5.2",
        "prompt": "Say OK.",
        "max_tokens": 1,
        "temperature": 0,
    }
    assert config.probes["chat_payload"] == {
        "model": "zai-org/GLM-5.2",
        "messages": [{"role": "user", "content": "Say OK."}],
        "max_tokens": 1,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert config.artifacts["generate_probe"] == "run://probes/generate.json"
    assert config.artifacts["throughput_probe"] == "run://probes/throughput.json"
    assert config.artifacts["completion_probe"] == "run://probes/completions.json"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--port") + 1] == "19017"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--host") + 1] == "127.0.0.1"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--served-model-name") + 1] == "zai-org/GLM-5.2"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--device") + 1] == "cuda"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--context-length") + 1] == "262144"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--kv-cache-dtype") + 1] == "fp8_e4m3"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--mem-fraction-static") + 1] == "0.72"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--max-total-tokens") + 1] == "32768"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--max-running-requests") + 1] == "1"
    assert config.launch["inner_argv"][config.launch["inner_argv"].index("--cpu-offload-gb") + 1] == "16"
    assert config.runtime["context_length"] == 262144
    assert config.runtime["device"] == "cuda"
    assert config.runtime["kv_cache_dtype"] == "fp8_e4m3"
    assert config.runtime["mem_fraction_static"] == 0.72
    assert config.runtime["max_total_tokens"] == 32768
    assert config.runtime["max_running_requests"] == 1
    assert config.runtime["cpu_offload_gb"] == 16
    assert config.launch["outer_argv"][1] == "--repo-readonly"
    assert config.launch["outer_argv"][config.launch["outer_argv"].index("--emit-plan") + 1] == "run://sandbox/resolved-bwrap-plan.yaml"
    assert config.launch["outer_argv"].index("--emit-plan") < config.launch["outer_argv"].index("--")
    concrete_ports = {
        config.service["port"],
        int(config.launch["inner_argv"][config.launch["inner_argv"].index("--port") + 1]),
        int(config.launch["outer_argv"][config.launch["outer_argv"].index("--port") + 1]),
    }
    assert concrete_ports == {19017}
    assert concrete_ports.isdisjoint({8000, 8080, 18080})
    assert config.host_layout["run_dir"].startswith("repo://glm52-serving-results/glm52-sglang-local-001")
    assert all(not value.startswith("/") for value in config.host_layout.values())
    assert config.resolved_paths["repo"] == "/repo/monarch"
    assert config.resolved_paths["cache"] == "/repo/monarch/.scratch/glm52-local-serving/cache"
    assert config.resolved_paths["temp"] == "/repo/monarch/.scratch/glm52-local-serving/tmp"
    assert config.resolved_paths["rootfs"]["monarch-default"] == "/repo/monarch/scripts/rootfs/rootfs"
    assert set(config.to_mapping()) == {
        "schema_version",
        "run_id",
        "run_group",
        "fail_fast",
        "allow_fallback",
        "service",
        "model",
        "runtime",
        "observability",
        "host_layout",
        "sandbox",
        "launch",
        "probes",
        "artifacts",
        "resolved_paths",
    }


def test_materialize_runtime_config_uses_rootfs_owned_sglang_venv(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )

    assert config.launch["inner_argv"][:3] == [
        "/cache/glm52/venvs/sglang/bin/python",
        "-m",
        "sglang.launch_server",
    ]
    assert config.resolved_paths["sglang_venv"] == (
        "/repo/monarch/.scratch/glm52-local-serving/cache/"
        "glm52-sglang-local/venvs/sglang"
    )
    assert config.launch["env"]["HF_HOME"] == "/cache/glm52/hf-home"
    assert config.launch["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"
    assert config.launch["env"]["CUDA_VISIBLE_DEVICES"] == "0,1,2,3,4,5,6,7"
    assert config.sandbox["env"]["HF_HOME"] == "/cache/glm52/hf-home"
    assert config.sandbox["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"
    assert all(not value.startswith("/") for value in config.host_layout.values())


def test_materialize_runtime_config_passes_glm_mounts_to_rootfs_entrypoint(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )

    outer = config.launch["outer_argv"]
    assert "--bind-rw" in outer
    bind_specs = [
        outer[index + 1]
        for index, arg in enumerate(outer)
        if arg == "--bind-rw"
    ]
    assert bind_specs == [
        "run://:/run/glm52",
        "temp://glm52-sglang-local-001:/tmp/glm52",
        "cache://glm52-sglang-local:/cache/glm52",
        "cache://glm52-sglang-local/venvs/sglang:/cache/glm52/venvs/sglang",
        "cache://glm52-sglang-local/hf-home:/cache/glm52/hf-home",
        "cache://glm52-sglang-local/sglang:/cache/glm52/sglang",
    ]
    assert outer.index("--bind-rw") < outer.index("--")


def test_materialized_config_rejects_port_command_drift(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    inner = list(config.launch["inner_argv"])
    inner[inner.index("--port") + 1] = "19018"
    drifted = config.replace_launch_inner(inner)

    with pytest.raises(RuntimeConfigError, match="service.port must match"):
        validate_materialized_config(drifted)


def test_materialized_config_rejects_exact_disallowed_port_drift(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    inner = list(config.launch["inner_argv"])
    inner[inner.index("--port") + 1] = "8080"
    probes = dict(config.probes)
    probes["models_url"] = "http://127.0.0.1:8080/v1/models"
    probes["generate_url"] = "http://127.0.0.1:8080/generate"
    probes["throughput_url"] = "http://127.0.0.1:8080/generate"
    probes["completions_url"] = "http://127.0.0.1:8080/v1/completions"
    probes["chat_url"] = "http://127.0.0.1:8080/v1/chat/completions"
    drifted = (
        config.replace_service({"port": 8080, "base_url": "http://127.0.0.1:8080/v1"})
        .replace_launch_inner(inner)
        .replace_launch_outer(
            ["scripts/rootfs/enter_rootfs.sh", "--emit-plan", "run://sandbox/resolved-bwrap-plan.yaml", "--", *inner]
        )
        .replace_probes(probes)
    )

    with pytest.raises(RuntimeConfigError, match="disallowed fallback port"):
        validate_materialized_config(drifted)


def test_materialized_config_rejects_probe_url_port_drift(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    probes = dict(config.probes)
    probes["models_url"] = "http://127.0.0.1:8000/v1/models"
    drifted = config.replace_probes(probes)

    with pytest.raises(RuntimeConfigError, match="probe URLs must derive"):
        validate_materialized_config(drifted)


def test_probe_chat_uses_schema_owned_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)
    observed_timeouts: list[object] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b'{"choices":[{"message":{"content":"monarch-sglang-ready"}}]}'

    def fake_urlopen(_request, *, timeout):
        observed_timeouts.append(timeout)
        return FakeResponse()

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", fake_urlopen)

    result = glm52_sglang_runtime.probe_chat(config)

    assert result["content"] == "monarch-sglang-ready"
    assert observed_timeouts == [120]


def test_probe_chat_names_schema_owned_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)

    def fake_urlopen(_request, *, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeLaunchError, match="chat probe timed out after 120s"):
        glm52_sglang_runtime.probe_chat(config)


def test_probe_completion_uses_schema_owned_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)
    observed_timeouts: list[object] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b'{"choices":[{"text":"monarch-sglang-ready"}]}'

    def fake_urlopen(_request, *, timeout):
        observed_timeouts.append(timeout)
        return FakeResponse()

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", fake_urlopen)

    result = glm52_sglang_runtime.probe_completion(config)

    assert result["content"] == "monarch-sglang-ready"
    assert observed_timeouts == [120]


def test_probe_completion_names_schema_owned_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)

    def fake_urlopen(_request, *, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeLaunchError, match="completion probe timed out after 120s"):
        glm52_sglang_runtime.probe_completion(config)


def test_probe_generate_uses_native_sglang_endpoint_and_schema_owned_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)
    observed_timeouts: list[object] = []
    observed_urls: list[str] = []
    observed_payloads: list[dict[str, Any]] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b'{"text":"monarch-sglang-ready","meta_info":{"finish_reason":{"type":"length"}}}'

    def fake_urlopen(request, *, timeout):
        observed_timeouts.append(timeout)
        observed_urls.append(request.full_url)
        observed_payloads.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", fake_urlopen)

    result = glm52_sglang_runtime.probe_generate(config)

    assert result["content"] == "monarch-sglang-ready"
    assert observed_timeouts == [120]
    assert observed_urls == ["http://127.0.0.1:19017/generate"]
    assert observed_payloads == [config.probes["generate_payload"]]


def test_probe_generate_names_schema_owned_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)

    def fake_urlopen(_request, *, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeLaunchError, match="generate probe timed out after 120s"):
        glm52_sglang_runtime.probe_generate(config)


def test_probe_throughput_reports_tokens_per_second(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b'{"text":"warm throughput text","meta_info":{"completion_tokens":128,"e2e_latency":4.0}}'

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", lambda _request, *, timeout: FakeResponse())

    result = glm52_sglang_runtime.probe_throughput(config)

    assert result["content"] == "warm throughput text"
    assert result["metrics"] == {
        "completion_tokens": 128,
        "e2e_latency_s": 4.0,
        "tokens_per_second": 32.0,
    }
    assert result["payload"]["meta_info"]["completion_tokens"] == 128


def test_probe_throughput_rejects_short_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b'{"text":"warm throughput text","meta_info":{"completion_tokens":17,"e2e_latency":4.0}}'

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", lambda _request, *, timeout: FakeResponse())

    with pytest.raises(RuntimeLaunchError, match=r"throughput probe generated 17 token\(s\), expected 128"):
        glm52_sglang_runtime.probe_throughput(config)


def test_probe_throughput_uses_native_generate_and_ignore_eos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_for_tests(tmp_path)
    observed_urls: list[str] = []
    observed_payloads: list[dict[str, Any]] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b'{"text":"warm throughput text","meta_info":{"completion_tokens":128,"e2e_latency":4.0}}'

    def fake_urlopen(request, *, timeout):
        observed_urls.append(request.full_url)
        observed_payloads.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(glm52_sglang_runtime.urllib.request, "urlopen", fake_urlopen)

    glm52_sglang_runtime.probe_throughput(config)

    assert observed_urls == ["http://127.0.0.1:19017/generate"]
    assert observed_payloads == [config.probes["throughput_payload"]]
    assert observed_payloads[0]["sampling_params"]["max_new_tokens"] == 128
    assert observed_payloads[0]["sampling_params"]["ignore_eos"] is True


def test_materialized_config_rejects_outer_inner_drift(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    outer = list(config.launch["outer_argv"])
    outer[-1] = "float16"
    drifted = config.replace_launch_outer(outer)

    with pytest.raises(RuntimeConfigError, match="outer_argv SGLang tail must equal inner_argv"):
        validate_materialized_config(drifted)


def test_materialized_config_rejects_missing_served_model_name_flag(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    inner = list(config.launch["inner_argv"])
    index = inner.index("--served-model-name")
    del inner[index : index + 2]
    drifted = config.replace_launch_inner(inner).replace_launch_outer(
        ["scripts/rootfs/enter_rootfs.sh", "--emit-plan", "run://sandbox/resolved-bwrap-plan.yaml", "--", *inner]
    )

    with pytest.raises(RuntimeConfigError, match="missing --served-model-name"):
        validate_materialized_config(drifted)


def test_materialize_runtime_config_rejects_extra_args_that_override_schema_flags(tmp_path: Path) -> None:
    declared_text = VALID_DECLARED.replace(
        "  extra_args: []",
        '  extra_args: ["--port", "8000", "--served-model-name", "drifted", "--mem-fraction-static", "0.9", "--cpu-offload-gb", "4"]',
    )
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", declared_text))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))

    with pytest.raises(RuntimeConfigError, match="runtime.extra_args must not override schema-owned flag"):
        materialize_runtime_config(
            declared=declared,
            local_environment=local_env,
            run_id="glm52-sglang-local-001",
            port=19017,
        )


def test_should_teardown_after_failure_defaults_true(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)

    assert should_teardown_after_failure(config) is True


def test_build_insula_invocation_spec_preserves_sglang_runtime_contract(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)

    spec = glm52_sglang_runtime.build_insula_invocation_spec(config)
    outer_argv = glm52_sglang_runtime._resolved_outer_argv(config)

    assert spec.name == "glm52-sglang-local"
    assert spec.rootfs_ref == "rootfs://monarch-default"
    assert spec.command.cwd == "/workspace/monarch"
    assert spec.command.argv == config.launch["inner_argv"]
    for key, value in config.launch["env"].items():
        assert spec.environment.values[key] == value
    assert spec.environment.values["PATH"].startswith("/opt/cuda-synth/bin:")
    assert spec.environment.values["CUDA_HOME"] == "/opt/cuda-synth"
    assert spec.environment.values["UV_PROJECT_ENVIRONMENT"] == "/workspace/monarch/.venv-rootfs"
    assert spec.environment.values["MONARCH_IN_ROOTFS"] == "1"
    assert spec.environment.values["USER"] == "monarch"
    assert spec.environment.values["LOGNAME"] == "monarch"
    assert spec.repo.mode == "ro"
    assert {bind.sandbox for bind in spec.binds} >= {
        "/run/glm52",
        "/tmp/glm52",
        "/cache/glm52",
        "/cache/glm52/venvs/sglang",
        "/cache/glm52/hf-home",
        "/cache/glm52/sglang",
        "/workspace/monarch/scripts/rootfs/cache",
        f"/workspace/monarch/target/bwrap/{glm52_sglang_runtime._rootfs_recipe_digest(config)}",
    }
    assert any(bind.sandbox == "/etc/hosts" for bind in spec.binds)
    assert outer_argv[0] == "bwrap"
    assert "scripts/rootfs/enter_rootfs.sh" not in outer_argv
    assert outer_argv[-len(config.launch["inner_argv"]) :] == config.launch["inner_argv"]
    assert "--setenv" in outer_argv
    assert "CUDA_HOME" in outer_argv


def test_debug_mode_can_leave_process_running_only_when_explicit(tmp_path: Path) -> None:
    declared_text = VALID_DECLARED.replace("debug_mode: false", "debug_mode: true").replace(
        "leave_running_on_failure: false",
        "leave_running_on_failure: true",
    )
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", declared_text))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-debug",
        port=19017,
    )

    assert should_teardown_after_failure(config) is False


def test_leave_running_without_debug_is_rejected(tmp_path: Path) -> None:
    declared_text = VALID_DECLARED.replace(
        "leave_running_on_failure: false",
        "leave_running_on_failure: true",
    )

    with pytest.raises(RuntimeConfigError, match="leave_running_on_failure requires debug_mode"):
        load_declared_spec(write_spec(tmp_path / "declared.yaml", declared_text))


def materialized_for_tests(tmp_path: Path):
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    return materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )


def valid_rootfs_plan(config) -> dict[str, object]:
    return {
        "schema_version": 1,
        "rootfs": "/repo/monarch/scripts/rootfs/rootfs",
        "cwd": "/workspace/monarch",
        "inner_argv": config.launch["inner_argv"],
        "repo_projection_mode": "ro",
        "network": "share-net",
        "gpu": "dev-bind-nvidia-when-present",
        "env_allowlist": [],
        "env": config.launch["env"],
        "mounts": [
            {"host_path": "/repo/monarch", "sandbox_path": "/workspace/monarch", "mode": "ro"},
            {
                "host_path": "/repo/monarch/glm52-serving-results/glm52-sglang-local-001",
                "sandbox_path": "/run/glm52",
                "mode": "rw",
            },
            {
                "host_path": "/repo/monarch/.scratch/glm52-local-serving/tmp/glm52-sglang-local-001",
                "sandbox_path": "/tmp/glm52",
                "mode": "rw",
            },
            {
                "host_path": "/repo/monarch/.scratch/glm52-local-serving/cache/glm52-sglang-local",
                "sandbox_path": "/cache/glm52",
                "mode": "rw",
            },
            {
                "host_path": "/repo/monarch/.scratch/glm52-local-serving/cache/glm52-sglang-local/venvs/sglang",
                "sandbox_path": "/cache/glm52/venvs/sglang",
                "mode": "rw",
            },
            {
                "host_path": "/repo/monarch/.scratch/glm52-local-serving/cache/glm52-sglang-local/hf-home",
                "sandbox_path": "/cache/glm52/hf-home",
                "mode": "rw",
            },
            {
                "host_path": "/repo/monarch/.scratch/glm52-local-serving/cache/glm52-sglang-local/sglang",
                "sandbox_path": "/cache/glm52/sglang",
                "mode": "rw",
            },
        ],
    }


def valid_emitted_preparation_plan(config, inner_argv, env=None) -> dict[str, object]:
    plan = valid_rootfs_plan(config)
    plan["rootfs"] = glm52_sglang_runtime._resolved_rootfs_path(config)
    plan["inner_argv"] = list(inner_argv)
    plan["env"] = {**config.launch["env"], **dict(env or {})}
    for mount in plan["mounts"]:
        for expected in config.sandbox["mounts"]:
            if mount["sandbox_path"] == expected["sandbox_path"]:
                mount["host_path"] = glm52_sglang_runtime._resolve_host_path_ref(config, expected["host_path_ref"])
    return plan


def test_validate_resolved_rootfs_plan_accepts_matching_plan(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)

    validate_resolved_rootfs_plan(config=config, plan=valid_rootfs_plan(config))


def test_validate_resolved_rootfs_plan_rejects_writable_repo_mount(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["repo_projection_mode"] = "rw"

    with pytest.raises(RuntimeConfigError, match="repo projection must be ro"):
        validate_resolved_rootfs_plan(config=config, plan=plan)


def test_validate_resolved_rootfs_plan_rejects_inner_argv_drift(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["inner_argv"] = ["python", "-m", "sglang.launch_server"]

    with pytest.raises(RuntimeConfigError, match="inner_argv must match"):
        validate_resolved_rootfs_plan(config=config, plan=plan)


def test_validate_resolved_rootfs_plan_rejects_env_drift(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["env"] = {**config.launch["env"], "CUDA_VISIBLE_DEVICES": "0"}

    with pytest.raises(RuntimeConfigError, match="resolved rootfs plan env mismatch: CUDA_VISIBLE_DEVICES"):
        validate_resolved_rootfs_plan(config=config, plan=plan)


def test_validate_resolved_rootfs_plan_rejects_missing_mount(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["mounts"] = [
        mount
        for mount in plan["mounts"]
        if mount["sandbox_path"] != "/cache/glm52"
    ]

    with pytest.raises(RuntimeConfigError, match="missing sandbox mount: /cache/glm52"):
        validate_resolved_rootfs_plan(config=config, plan=plan)


def test_validate_resolved_rootfs_plan_rejects_host_path_drift(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["mounts"] = [
        {**mount, "host_path": "/wrong/repo"}
        if mount["sandbox_path"] == "/workspace/monarch"
        else mount
        for mount in plan["mounts"]
    ]

    with pytest.raises(RuntimeConfigError, match="mount host path mismatch: /workspace/monarch"):
        validate_resolved_rootfs_plan(config=config, plan=plan)


def test_validate_resolved_rootfs_plan_rejects_duplicate_sandbox_path(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    duplicate = {
        "host_path": "/wrong/repo",
        "sandbox_path": "/workspace/monarch",
        "mode": "rw",
    }
    plan["mounts"] = [duplicate, *plan["mounts"]]

    with pytest.raises(RuntimeConfigError, match="duplicate sandbox mount: /workspace/monarch"):
        validate_resolved_rootfs_plan(config=config, plan=plan)


def test_validate_sglang_rootfs_overlay_accepts_matching_plan(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)

    validate_sglang_rootfs_overlay(config=config, plan=valid_rootfs_plan(config))


@pytest.mark.parametrize(
    ("env_key", "value", "match"),
    [
        ("HF_HOME", "/cache/glm52/drifted-hf", "rootfs plan HF_HOME does not match materialized config"),
        ("SGLANG_CACHE_DIR", "/cache/glm52/drifted-sglang", "rootfs plan SGLANG_CACHE_DIR does not match materialized config"),
    ],
)
def test_validate_sglang_rootfs_overlay_rejects_env_drift(
    tmp_path: Path,
    env_key: str,
    value: str,
    match: str,
) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["env"] = {**plan["env"], env_key: value}

    with pytest.raises(RuntimeConfigError, match=match):
        validate_sglang_rootfs_overlay(config=config, plan=plan)


def test_validate_sglang_rootfs_overlay_rejects_missing_sglang_mount(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    plan["mounts"] = [
        mount
        for mount in plan["mounts"]
        if mount["sandbox_path"] != "/cache/glm52/hf-home"
    ]

    with pytest.raises(RuntimeConfigError, match="rootfs plan missing SGLang mount: /cache/glm52/hf-home"):
        validate_sglang_rootfs_overlay(config=config, plan=plan)


def test_validate_sglang_rootfs_overlay_rejects_duplicate_sglang_mount(tmp_path: Path) -> None:
    config = materialized_for_tests(tmp_path)
    plan = valid_rootfs_plan(config)
    duplicate = {
        "host_path": "/repo/monarch/.scratch/glm52-local-serving/cache/wrong-hf-home",
        "sandbox_path": "/cache/glm52/hf-home",
        "mode": "rw",
    }
    plan["mounts"] = [duplicate, *plan["mounts"]]

    with pytest.raises(RuntimeConfigError, match="duplicate sandbox mount: /cache/glm52/hf-home"):
        validate_sglang_rootfs_overlay(config=config, plan=plan)


def test_write_and_load_materialized_config_round_trip(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    path = tmp_path / "materialized.yaml"

    write_materialized_config(config, path)
    loaded = load_materialized_config(path)

    assert loaded == config


def test_materialize_cli_writes_config(tmp_path: Path) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV)
    output = tmp_path / "materialized.yaml"

    rc = main(
        [
            "materialize",
            "--declared-spec",
            str(declared),
            "--local-environment",
            str(local_env),
            "--run-id",
            "glm52-sglang-local-001",
            "--port",
            "19017",
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    loaded = load_materialized_config(output)
    assert loaded.service["port"] == 19017


def test_validate_cli_rejects_drifted_materialized_config(tmp_path: Path) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(write_spec(tmp_path / "local-env.yaml", VALID_LOCAL_ENV))
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    drifted = config.replace_launch_inner(["python", "-m", "sglang.launch_server"])
    path = tmp_path / "bad.yaml"
    path.write_text(
        glm52_sglang_runtime.yaml.safe_dump(
            glm52_sglang_runtime._config_to_mapping(drifted),
            sort_keys=False,
        )
    )

    rc = main(["validate", "--materialized-config", str(path)])

    assert rc == 2


def test_launch_failure_tears_down_when_not_debug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env_path = write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "repo" / "scripts" / "rootfs" / "rootfs"}
""",
    )
    local_env = load_local_environment(local_env_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    config_path = tmp_path / "materialized.yaml"
    write_materialized_config(config, config_path)
    events: list[str] = []
    popen_commands: list[list[str]] = []

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            events.append("wait")
            return 0

    def fake_popen(argv, *args, **kwargs):
        popen_commands.append(list(argv))
        return FakeProcess()

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "run_sglang_help_preflight",
        lambda _config: "--served-model-name",
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "emit_and_load_rootfs_plan",
        lambda config, *, resolved_plan_path: valid_rootfs_plan(config),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_model_cache",
        lambda _config: {"model_cache": {"snapshot_path": "/cache/glm52/hf-home/snapshots/abc123"}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_gpu_occupancy",
        lambda _config: {"status": "free", "checked_gpus": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "wait_for_models_probe",
        lambda _config, *, process=None: (_ for _ in ()).throw(RuntimeConfigError("model identity mismatch")),
    )

    def fake_teardown_runtime(cycle_config, *, local_environment):
        events.append("teardown_runtime")
        return {"status": "teardown_passed", "run_id": cycle_config.run_id, "port": cycle_config.service["port"]}

    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)

    rc = main(
        [
            "launch",
            "--materialized-config",
            str(config_path),
            "--local-environment",
            str(local_env_path),
        ]
    )

    assert rc == 2
    assert events == ["teardown_runtime"]
    assert popen_commands
    assert all(not arg.startswith("run://") for arg in popen_commands[0])


def test_launch_fails_fast_when_process_exits_before_models_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(
        write_spec(
            tmp_path / "local-env.yaml",
            f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
        )
    )
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-crash",
        port=19017,
    )

    class FakeProcess:
        pid = 987654

        def poll(self):
            return 42

        def terminate(self):
            raise AssertionError("terminated after process already exited")

        def wait(self, timeout=None):
            return 42

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "run_sglang_help_preflight",
        lambda _config: "--served-model-name",
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "emit_and_load_rootfs_plan",
        lambda config, *, resolved_plan_path: valid_rootfs_plan(config),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_model_cache",
        lambda _config: {"model_cache": {"snapshot_path": "/cache/glm52/hf-home/snapshots/abc123"}},
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_gpu_occupancy",
        lambda _config: {"status": "free", "checked_gpus": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        glm52_sglang_runtime.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionRefusedError("refused")),
    )
    monkeypatch.setattr(glm52_sglang_runtime.os, "getpgid", lambda _pid: 987654)

    def fake_killpg(pgid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(glm52_sglang_runtime.os, "killpg", fake_killpg)

    with pytest.raises(RuntimeConfigError, match="SGLang process exited before /v1/models became ready"):
        glm52_sglang_runtime.launch_runtime(config, local_environment=local_env)

    summary = glm52_sglang_runtime._load_json_mapping(
        tmp_path / "repo" / "glm52-serving-results" / config.run_id / "launch-summary.json"
    )
    assert summary["status"] == "launch_failed"
    assert summary["diagnostic_action"] == {
        "status": "failed",
        "reason": "diagnostic_signal_failed",
        "error": "live process command guard cannot inspect recorded pid command",
    }
    assert summary["teardown_action"] == "teardown_failed: live process command guard cannot inspect recorded pid command"


def test_models_probe_fails_fast_when_scheduler_logs_fatal_startup_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_config_for_test(tmp_path, port=19035)
    artifact_paths = glm52_sglang_runtime._resolve_artifact_paths(config)
    artifact_paths["stderr_log"].parent.mkdir(parents=True, exist_ok=True)
    artifact_paths["stderr_log"].write_text(
        "[2026-08-17 11:36:17 TP2] Scheduler hit an exception: Traceback\n"
        "ValueError: flashinfer_sparse_mla supports only GLM DSA with FP8 KV cache on NVIDIA SM120/SM121\n"
    )

    class FakeProcess:
        def poll(self):
            return None

    monkeypatch.setattr(
        glm52_sglang_runtime.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionRefusedError("refused")),
    )

    with pytest.raises(RuntimeConfigError, match="SGLang startup failed before /v1/models became ready"):
        glm52_sglang_runtime.wait_for_models_probe(config, process=FakeProcess())


def test_launch_help_preflight_failure_writes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(
        write_spec(
            tmp_path / "local-env.yaml",
            f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
        )
    )
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-preflight-failure",
        port=19017,
    )

    def fake_run_sglang_help_preflight(_config):
        raise RuntimeConfigError("sglang help preflight failed: missing sglang")

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "run_sglang_help_preflight",
        fake_run_sglang_help_preflight,
    )

    with pytest.raises(RuntimeConfigError, match="missing sglang"):
        glm52_sglang_runtime.launch_runtime(config, local_environment=local_env)

    run_dir = tmp_path / "repo" / "glm52-serving-results" / config.run_id
    assert (run_dir / "materialized-sglang-runtime.yaml").exists()
    assert (run_dir / "resolved-local-paths.yaml").exists()
    summary = glm52_sglang_runtime._load_json_mapping(run_dir / "launch-summary.json")
    assert summary["status"] == "launch_failed"
    assert summary["teardown_action"] == "not_started"


def test_launch_fails_before_process_start_when_model_cache_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(
        write_spec(
            tmp_path / "local-env.yaml",
            f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
        )
    )
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "run_sglang_help_preflight",
        lambda _config: "usage: sglang.launch_server --served-model-name NAME\n",
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "emit_and_load_rootfs_plan",
        lambda _config, *, resolved_plan_path: valid_rootfs_plan(_config),
    )
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "preflight_model_cache",
        lambda _config: (_ for _ in ()).throw(RuntimeConfigError("model snapshot is incomplete")),
    )

    popen_calls: list[object] = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        raise AssertionError("launch must not start SGLang with an incomplete model cache")

    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeConfigError, match="model snapshot is incomplete"):
        glm52_sglang_runtime.launch_runtime(config, local_environment=local_env)

    assert popen_calls == []
    run_dir = tmp_path / "repo" / "glm52-serving-results" / config.run_id
    summary = glm52_sglang_runtime._load_json_mapping(run_dir / "launch-summary.json")
    assert summary["status"] == "launch_failed"
    assert summary["teardown_action"] == "not_started"


def test_gpu_occupancy_preflight_rejects_busy_visible_gpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_config_for_test(tmp_path, port=19017)

    def fake_run(argv, **_kwargs):
        if "--query-gpu=index,uuid" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "0, GPU-busy\n"
                    "1, GPU-free\n"
                    "2, GPU-idle-2\n"
                    "3, GPU-idle-3\n"
                    "4, GPU-idle-4\n"
                    "5, GPU-idle-5\n"
                    "6, GPU-idle-6\n"
                    "7, GPU-idle-7\n"
                ),
                stderr="",
            )
        if "--query-compute-apps=pid,process_name,gpu_uuid,used_memory" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "1234, VLLM::Worker_TP0_EP0, GPU-busy, 97200\n"
                    "5678, VLLM::Worker_TP1_EP1, GPU-free, 96300\n"
                ),
                stderr="",
            )
        raise AssertionError(argv)

    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "run", fake_run)

    with pytest.raises(
        glm52_sglang_runtime.GpuOccupancyError,
        match="visible GPU 0 is already occupied by pid 1234",
    ) as error_info:
        glm52_sglang_runtime.preflight_gpu_occupancy(config)
    assert error_info.value.blocked_gpus == [
        {
            "index": 0,
            "uuid": "GPU-busy",
            "pid": 1234,
            "process_name": "VLLM::Worker_TP0_EP0",
            "used_memory": "97200",
        },
        {
            "index": 1,
            "uuid": "GPU-free",
            "pid": 5678,
            "process_name": "VLLM::Worker_TP1_EP1",
            "used_memory": "96300",
        },
    ]


def test_sglang_help_preflight_uses_rootfs_owned_venv_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(
        write_spec(
            tmp_path / "local-env.yaml",
            f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
        )
    )
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    calls: list[dict[str, object]] = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = "usage: sglang.launch_server --served-model-name NAME\n"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append({"command": list(command), **kwargs})
        return FakeCompletedProcess()

    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "run", fake_run)

    glm52_sglang_runtime.run_sglang_help_preflight(config)

    assert calls
    command = calls[0]["command"]
    marker = command.index("--")
    assert command[marker + 1 : marker + 4] == [
        "/cache/glm52/venvs/sglang/bin/python",
        "-m",
        "sglang.launch_server",
    ]
    assert "python" not in command[marker + 1 : marker + 2]
    assert calls[0]["env"]["UV_CACHE_DIR"] == "/cache/glm52/uv"
    assert calls[0]["env"]["XDG_CACHE_HOME"] == "/cache/glm52/xdg"
    assert calls[0]["env"]["HF_HOME"] == "/cache/glm52/hf-home"
    assert calls[0]["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"
    assert calls[0]["env"]["TORCHINDUCTOR_CACHE_DIR"] == "/cache/glm52/torchinductor"
    assert calls[0]["env"]["TRITON_CACHE_DIR"] == "/cache/glm52/triton"
    assert calls[0]["env"]["USER"] == "monarch"
    assert calls[0]["env"]["LOGNAME"] == "monarch"


def test_prepare_sglang_venv_cli_installs_and_writes_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    calls: list[dict[str, object]] = []

    class FakeCompletedProcess:
        def __init__(self, stdout: str = "", stderr: str = "") -> None:
            self.returncode = 0
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **kwargs):
        calls.append({"command": list(command), **kwargs})
        inner = list(command)[list(command).index("--") + 1 :]
        if inner[:2] == ["uv", "venv"]:
            return FakeCompletedProcess("Using Python 3.12\nCreating virtual environment\n")
        expected_sync_prefix = [
            "env",
            "VIRTUAL_ENV=/cache/glm52/venvs/sglang",
            "UV_PROJECT_ENVIRONMENT=/cache/glm52/venvs/sglang",
            "uv",
            "sync",
            "--active",
            "--locked",
            "--no-sources-package",
            "torch",
            "--no-install-project",
            "--only-group",
            "glm52-runtime",
        ]
        if inner[: len(expected_sync_prefix)] == expected_sync_prefix:
            assert kwargs["env"]["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
            assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"
            return FakeCompletedProcess("resolved glm52 runtime deps\n")
        if inner[:4] == [
            "/cache/glm52/venvs/sglang/bin/python",
            "/workspace/monarch/scripts/glm52_sglang_offloader_patch.py",
            "--offloader",
            "/cache/glm52/venvs/sglang/lib/python3.12/site-packages/sglang/srt/utils/offloader.py",
        ]:
            return FakeCompletedProcess(
                '{"patch_id":"glm52-offloader-v1-plain-tensor-attrs-v1",'
                '"sha256_after":"patched-sha","changed":true}\n'
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-c", glm52_sglang_runtime.SGLANG_VENV_PROBE_SCRIPT]:
            return FakeCompletedProcess(
                '{"python":"/cache/glm52/venvs/sglang/bin/python",'
                '"sys_prefix":"/cache/glm52/venvs/sglang",'
                '"packages":{"sglang":"0.4.0"},'
                '"platform":{"class":"CudaSRTPlatform","device_name":"cuda","device_type":"cuda",'
                '"is_cpu":false,"is_cuda":true,"utils_is_cpu":false,'
                '"rotary_base_is_cpu":false,"rotary_base_is_cuda":true}}\n'
            )
        if inner[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-m", "sglang.launch_server"]:
            return FakeCompletedProcess("usage: --served-model-name NAME\n")
        raise AssertionError(f"unexpected command: {inner}")

    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(glm52_sglang_runtime, "validate_sglang_help", lambda help_text: None)

    rc = main(
        [
            "prepare-venv",
            "--declared",
            str(declared),
            "--local-env",
            str(local_env),
        ]
    )

    assert rc == 0
    assert len(calls) == 5
    venv_call = calls[0]["command"][calls[0]["command"].index("--") + 1 :]
    install_call = calls[1]["command"][calls[1]["command"].index("--") + 1 :]
    patch_call = calls[2]["command"][calls[2]["command"].index("--") + 1 :]
    probe_call = calls[3]["command"][calls[3]["command"].index("--") + 1 :]
    help_call = calls[4]["command"][calls[4]["command"].index("--") + 1 :]
    assert venv_call == [
        "uv",
        "venv",
        "/cache/glm52/venvs/sglang",
        "--python",
        "3.12",
        "--clear",
    ]
    assert install_call == [
        "env",
        "VIRTUAL_ENV=/cache/glm52/venvs/sglang",
        "UV_PROJECT_ENVIRONMENT=/cache/glm52/venvs/sglang",
        "uv",
        "sync",
        "--active",
        "--locked",
        "--no-sources-package",
        "torch",
        "--no-install-project",
        "--only-group",
        "glm52-runtime",
        "--python",
        "/cache/glm52/venvs/sglang/bin/python",
    ]
    assert calls[1]["env"]["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
    assert calls[1]["env"]["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"
    assert patch_call == [
        "/cache/glm52/venvs/sglang/bin/python",
        "/workspace/monarch/scripts/glm52_sglang_offloader_patch.py",
        "--offloader",
        "/cache/glm52/venvs/sglang/lib/python3.12/site-packages/sglang/srt/utils/offloader.py",
    ]
    assert probe_call == [
        "/cache/glm52/venvs/sglang/bin/python",
        "-c",
        glm52_sglang_runtime.SGLANG_VENV_PROBE_SCRIPT,
    ]
    assert help_call == [
        "/cache/glm52/venvs/sglang/bin/python",
        "-m",
        "sglang.launch_server",
        "--help",
    ]
    for call in calls:
        command = call["command"]
        assert command[0] == "bwrap"
        assert str(tmp_path / "rootfs") in command
        assert str(tmp_path / "repo") in command
        assert "python" not in command
        assert call["env"]["UV_CACHE_DIR"] == "/cache/glm52/uv"
        assert call["env"]["TORCHINDUCTOR_CACHE_DIR"] == "/cache/glm52/torchinductor"
        assert call["env"]["TRITON_CACHE_DIR"] == "/cache/glm52/triton"
        assert call["env"]["USER"] == "monarch"
        assert call["env"]["LOGNAME"] == "monarch"
    evidence = glm52_sglang_runtime._load_json_mapping(
        tmp_path / "repo" / "glm52-serving-results" / "prepare-venv" / "sglang-venv.json"
    )
    assert evidence["run_id"] == "prepare-venv"
    assert evidence["venv"]["path"] == "/cache/glm52/venvs/sglang"
    assert evidence["venv"]["python"] == "/cache/glm52/venvs/sglang/bin/python"
    assert evidence["venv"]["packages"] == glm52_sglang_runtime.SGLANG_PREPARE_PACKAGES
    assert evidence["venv"]["sys_prefix"] == "/cache/glm52/venvs/sglang"
    assert evidence["venv"]["installed_packages"]["sglang"] == "0.4.0"
    assert evidence["dependency_resolution"]["group"] == "glm52-runtime"
    assert evidence["dependency_resolution"]["lockfile"] == "repo://uv.lock"
    assert evidence["dependency_resolution"]["selection"] == "only_group"
    assert evidence["dependency_resolution"]["sources"] == "standard_metadata_for_torch"
    assert evidence["commands"][1]["env"]["VIRTUAL_ENV"] == "/cache/glm52/venvs/sglang"
    assert evidence["commands"][1]["env"]["UV_PROJECT_ENVIRONMENT"] == "/cache/glm52/venvs/sglang"
    assert evidence["checks"]["served_model_name_flag"] is True
    assert evidence["checks"]["platform"]["is_cuda"] is True
    assert evidence["checks"]["platform"]["rotary_base_is_cuda"] is True
    assert evidence["checks"]["platform"]["is_cpu"] is False
    assert evidence["checks"]["platform"]["rotary_base_is_cpu"] is False
    assert evidence["checks"]["offloader_patch"]["patch_id"] == "glm52-offloader-v1-plain-tensor-attrs-v1"
    assert evidence["checks"]["offloader_patch"]["sha256_after"] == "patched-sha"
    assert "plan_sha256" in evidence["bwrap_plan"]
    plan = load_yaml_mapping(tmp_path / "repo" / "glm52-serving-results" / "prepare-venv" / "sandbox" / "sglang_venv_record-bwrap-plan.yaml")
    assert plan["insula"]["invocation_id"] == "prepare-venv"
    assert plan["inner_argv"] == ["uv", "venv", "/cache/glm52/venvs/sglang", "--python", "3.12", "--clear"]


def test_prepare_model_cache_cli_downloads_validates_and_writes_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    snapshot = tmp_path / "cache" / "glm52-sglang-local" / "hf-home" / "hub" / "models--zai-org--GLM-5.2" / "snapshots" / "abc123"
    calls: list[dict[str, object]] = []
    validator_paths: list[Path] = []

    class FakeCompletedProcess:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(command, **kwargs):
        calls.append({"command": list(command), **kwargs})
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "model-00001-of-00001.safetensors").write_text("shard")
        (snapshot / "model.safetensors.index.json").write_text(
            glm52_sglang_runtime.json.dumps(
                {
                    "weight_map": {
                        "layer.0": "model-00001-of-00001.safetensors",
                    },
                }
            )
        )
        return FakeCompletedProcess(f'{{"snapshot_path":"/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123"}}\n')

    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(
        glm52_sglang_runtime,
        "validate_model_snapshot",
        lambda path: (
            validator_paths.append(path)
            or {"snapshot_path": str(path), "referenced_shard_count": 1, "missing_shard_count": 0}
        ),
    )

    rc = main(
        [
            "prepare-model",
            "--declared",
            str(declared),
            "--local-env",
            str(local_env),
        ]
    )

    assert rc == 0
    assert len(calls) == 1
    command = calls[0]["command"][calls[0]["command"].index("--") + 1 :]
    assert command[:3] == ["/cache/glm52/venvs/sglang/bin/python", "-c", glm52_sglang_runtime.MODEL_CACHE_PREPARE_SCRIPT]
    assert command[3:] == ["zai-org/GLM-5.2"]
    assert calls[0]["command"][0] == "bwrap"
    assert calls[0]["env"]["HF_HOME"] == "/cache/glm52/hf-home"
    assert calls[0]["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"
    assert calls[0]["env"]["TRANSFORMERS_CACHE"] == "/cache/glm52/hf-home"
    assert validator_paths == [snapshot]
    evidence = glm52_sglang_runtime._load_json_mapping(
        tmp_path / "repo" / "glm52-serving-results" / "prepare-model" / "model-cache.json"
    )
    assert evidence["run_id"] == "prepare-model"
    assert evidence["model_cache"]["model_id"] == "zai-org/GLM-5.2"
    assert evidence["model_cache"]["snapshot_path"] == "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123"
    assert evidence["model_cache"]["shard_count"] == 1
    assert evidence["model_cache"]["missing_shard_count"] == 0
    assert "plan_sha256" in evidence["bwrap_plan"]
    plan = load_yaml_mapping(tmp_path / "repo" / "glm52-serving-results" / "prepare-model" / "sandbox" / "model_cache_record-bwrap-plan.yaml")
    assert plan["insula"]["invocation_id"] == "prepare-model"
    assert plan["inner_argv"][:3] == ["/cache/glm52/venvs/sglang/bin/python", "-c", glm52_sglang_runtime.MODEL_CACHE_PREPARE_SCRIPT]


def test_rootfs_plan_emission_uses_materialized_env_cwd_and_rootfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONARCH_IN_ROOTFS", raising=False)
    monkeypatch.setenv("HF_HOME", "/ambient/hf")
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(
        write_spec(
            tmp_path / "local-env.yaml",
            f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
        )
    )
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    resolved_plan_path = Path(
        glm52_sglang_runtime._resolve_host_path_ref(
            config,
            config.artifacts["resolved_rootfs_plan"],
        )
    )

    def fake_run(command, **kwargs):
        raise AssertionError(f"plan emission must not shell out: {command}")

    monkeypatch.setattr(glm52_sglang_runtime.subprocess, "run", fake_run)

    emit_and_load_rootfs_plan = glm52_sglang_runtime.emit_and_load_rootfs_plan
    plan = emit_and_load_rootfs_plan(config, resolved_plan_path=resolved_plan_path)

    assert resolved_plan_path.exists()
    assert load_yaml_mapping(resolved_plan_path) == plan
    assert plan["rootfs"] == str(tmp_path / "rootfs")
    assert plan["cwd"] == "/workspace/monarch"
    assert plan["inner_argv"] == config.launch["inner_argv"]
    for key, value in config.launch["env"].items():
        assert plan["env"][key] == value
    assert plan["env"]["HF_HOME"] == "/cache/glm52/hf-home"
    assert plan["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"
    assert plan["env"]["CUDA_HOME"] == "/opt/cuda-synth"
    assert plan["env"]["UV_PROJECT_ENVIRONMENT"] == "/workspace/monarch/.venv-rootfs"
    assert plan["env"]["MONARCH_IN_ROOTFS"] == "1"
    assert plan["repo_projection_mode"] == "ro"
    by_sandbox = {mount["sandbox_path"]: mount for mount in plan["mounts"]}
    assert by_sandbox["/workspace/monarch"]["host_path"] == str(tmp_path / "repo")
    assert by_sandbox["/workspace/monarch"]["mode"] == "ro"
    assert by_sandbox["/cache/glm52"]["host_path"] == str(tmp_path / "cache" / "glm52-sglang-local")


def test_runtime_subprocess_cwd_uses_sandbox_cwd_inside_rootfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = materialized_config_for_test(tmp_path, port=19017)

    monkeypatch.delenv("MONARCH_IN_ROOTFS", raising=False)
    assert glm52_sglang_runtime._runtime_subprocess_cwd(config) == str(tmp_path / "repo")

    monkeypatch.setenv("MONARCH_IN_ROOTFS", "1")
    assert glm52_sglang_runtime._runtime_subprocess_cwd(config) == "/workspace/monarch"


@pytest.mark.parametrize(
    ("env_key", "value", "match"),
    [
        ("HF_HOME", "/cache/glm52/drifted-hf", "rootfs plan HF_HOME does not match materialized config"),
        ("SGLANG_CACHE_DIR", "/cache/glm52/drifted-sglang", "rootfs plan SGLANG_CACHE_DIR does not match materialized config"),
    ],
)
def test_rootfs_plan_emission_rejects_sglang_env_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    value: str,
    match: str,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(
        write_spec(
            tmp_path / "local-env.yaml",
            f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
        )
    )
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    resolved_plan_path = Path(
        glm52_sglang_runtime._resolve_host_path_ref(
            config,
            config.artifacts["resolved_rootfs_plan"],
        )
    )

    original_legacy_converter = glm52_sglang_runtime._legacy_rootfs_plan_from_insula

    def drifted_legacy_converter(**kwargs):
        plan = original_legacy_converter(**kwargs)
        plan["env"] = {**plan["env"], env_key: value}
        return plan

    monkeypatch.setattr(glm52_sglang_runtime, "_legacy_rootfs_plan_from_insula", drifted_legacy_converter)

    with pytest.raises(RuntimeConfigError, match=match):
        glm52_sglang_runtime.emit_and_load_rootfs_plan(config, resolved_plan_path=resolved_plan_path)


def test_teardown_rejects_process_record_drift_before_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = load_declared_spec(write_spec(tmp_path / "declared.yaml", VALID_DECLARED))
    local_env = load_local_environment(
        write_spec(
            tmp_path / "local-env.yaml",
            f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
        )
    )
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="glm52-sglang-local-001",
        port=19017,
    )
    process_record_path = Path(
        glm52_sglang_runtime._resolve_host_path_ref(
            config,
            config.artifacts["process_record"],
        )
    )
    process_record_path.parent.mkdir(parents=True, exist_ok=True)
    process_record_path.write_text(
        glm52_sglang_runtime.yaml.safe_dump(
            {
                "schema_version": 1,
                "run_id": config.run_id,
                "status": "running",
                "pid": os.getpid(),
                "process_group": os.getpgrp(),
                "port": config.service["port"],
                "outer_argv": ["drifted"],
                "inner_argv": config.launch["inner_argv"],
                "env": config.launch["env"],
            },
            sort_keys=False,
        )
    )
    killed: list[int] = []
    monkeypatch.setattr(glm52_sglang_runtime.os, "killpg", lambda pgid, sig: killed.append(pgid))

    with pytest.raises(RuntimeConfigError, match="process record outer_argv must match"):
        glm52_sglang_runtime.teardown_runtime(config, local_environment=local_env)

    assert killed == []


@pytest.mark.parametrize("command", ["launch", "teardown"])
def test_lifecycle_cli_commands_require_local_environment(
    command: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "materialized.yaml"

    with pytest.raises(SystemExit) as error:
        main([command, "--materialized-config", str(path)])

    assert error.value.code == 2


def test_repeat_cli_runs_requested_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    runs: list[str] = []
    teardown_runs: list[str] = []

    def fake_launch_runtime(config, *, local_environment):
        assert local_environment.repo == str(tmp_path / "repo")
        runs.append(config.run_id)
        return {"status": "launch_passed", "run_id": config.run_id}

    def fake_teardown_runtime(config, *, local_environment):
        assert local_environment.repo == str(tmp_path / "repo")
        teardown_runs.append(config.run_id)
        return {"status": "teardown_passed", "run_id": config.run_id}

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "ensure_preparation_records",
        lambda **_kwargs: {"status": "already_valid", "regenerated": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)

    rc = main([
        "repeat",
        "--declared-spec",
        str(declared),
        "--local-environment",
        str(local_env),
        "--cycles",
        "3",
    ])

    assert rc == 0
    assert len(runs) == 3
    assert len(set(runs)) == 3
    assert teardown_runs == runs
    for run_id in runs:
        config_path = tmp_path / "repo" / "glm52-serving-results" / run_id / "materialized-sglang-runtime.yaml"
        loaded = load_materialized_config(config_path)
        assert loaded.run_id == run_id
        assert 19000 <= loaded.service["port"] <= 19100
        assert loaded.service["port"] not in {8000, 8080, 18080}
        assert loaded.resolved_paths["preparation"] == {
            "sglang_venv_record": str(tmp_path / "repo" / "glm52-serving-results" / "prepare-venv" / "sglang-venv.json"),
            "model_cache_record": str(tmp_path / "repo" / "glm52-serving-results" / "prepare-model" / "model-cache.json"),
        }
    summaries = list((tmp_path / "repo" / "glm52-serving-results").glob("*-repeat-*/loop-summary.json"))
    assert len(summaries) == 1
    summary = glm52_sglang_runtime._load_json_mapping(summaries[0])
    assert summary["status"] == "passed"
    assert [cycle["run_id"] for cycle in summary["cycles"]] == runs


def test_repeat_cli_tears_down_and_returns_nonzero_after_cycle_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    teardown_runs: list[str] = []

    def fake_launch_runtime(config, *, local_environment):
        raise RuntimeConfigError("launch failed")

    def fake_teardown_runtime(config, *, local_environment):
        teardown_runs.append(config.run_id)
        return {"status": "teardown_passed", "run_id": config.run_id}

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "ensure_preparation_records",
        lambda **_kwargs: {"status": "already_valid", "regenerated": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)

    rc = main([
        "repeat",
        "--declared-spec",
        str(declared),
        "--local-environment",
        str(local_env),
        "--cycles",
        "3",
    ])

    assert rc == 2
    assert len(teardown_runs) == 1
    summaries = list((tmp_path / "repo" / "glm52-serving-results").glob("*-repeat-*/loop-summary.json"))
    assert len(summaries) == 1
    summary = glm52_sglang_runtime._load_json_mapping(summaries[0])
    assert summary["status"] == "failed"
    assert summary["cycles"][0]["launch"]["status"] == "failed"
    assert summary["cycles"][0]["teardown"]["status"] == "teardown_passed"


def test_repeat_failure_teardown_uses_latest_materialized_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    teardown_model_paths: list[str] = []

    def fake_launch_runtime(config, *, local_environment):
        effective = glm52_sglang_runtime._with_prepared_model_snapshot(
            config,
            {
                "model_cache": {
                    "snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123"
                }
            },
        )
        write_materialized_config(
            effective,
            Path(glm52_sglang_runtime._resolve_host_path_ref(effective, effective.artifacts["materialized_config"])),
        )
        raise RuntimeLaunchError("chat probe timed out")

    def fake_teardown_runtime(config, *, local_environment):
        teardown_model_paths.append(config.model["path"])
        return {"status": "teardown_passed", "run_id": config.run_id}

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "ensure_preparation_records",
        lambda **_kwargs: {"status": "already_valid", "regenerated": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)

    rc = main([
        "repeat",
        "--declared-spec",
        str(declared),
        "--local-environment",
        str(local_env),
        "--cycles",
        "1",
    ])

    assert rc == 2
    assert teardown_model_paths == ["/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123"]


def test_repeat_success_teardown_uses_latest_materialized_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = write_spec(tmp_path / "declared.yaml", VALID_DECLARED)
    local_env = write_spec(
        tmp_path / "local-env.yaml",
        f"""\
schema_version: 1
roots:
  repo: {tmp_path / "repo"}
  cache: {tmp_path / "cache"}
  temp: {tmp_path / "tmp"}
rootfs:
  monarch-default: {tmp_path / "rootfs"}
""",
    )
    teardown_model_paths: list[str] = []

    def fake_launch_runtime(config, *, local_environment):
        effective = glm52_sglang_runtime._with_prepared_model_snapshot(
            config,
            {
                "model_cache": {
                    "snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123"
                }
            },
        )
        write_materialized_config(
            effective,
            Path(glm52_sglang_runtime._resolve_host_path_ref(effective, effective.artifacts["materialized_config"])),
        )
        return {"status": "launch_passed", "run_id": config.run_id}

    def fake_teardown_runtime(config, *, local_environment):
        teardown_model_paths.append(config.model["path"])
        return {"status": "teardown_passed", "run_id": config.run_id}

    monkeypatch.setattr(
        glm52_sglang_runtime,
        "ensure_preparation_records",
        lambda **_kwargs: {"status": "already_valid", "regenerated": []},
    )
    monkeypatch.setattr(glm52_sglang_runtime, "launch_runtime", fake_launch_runtime)
    monkeypatch.setattr(glm52_sglang_runtime, "teardown_runtime", fake_teardown_runtime)

    rc = main([
        "repeat",
        "--declared-spec",
        str(declared),
        "--local-environment",
        str(local_env),
        "--cycles",
        "1",
    ])

    assert rc == 0
    assert teardown_model_paths == ["/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc123"]


def test_host_control_wrapper_is_executable() -> None:
    wrapper = Path(__file__).resolve().parents[2] / "scripts" / "run_glm52_sglang_runtime.sh"

    assert wrapper.stat().st_mode & stat.S_IXUSR
    text = wrapper.read_text()
    assert 'exec "$python_bin" "$REPO_ROOT/scripts/glm52_sglang_runtime.py" "$@"' in text
    assert '"$REPO_ROOT/scripts/run"' not in text
