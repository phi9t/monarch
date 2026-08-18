#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import urllib.request
import uuid

import yaml

from ginkgo.insula.bwrap_plan import build_bwrap_argv
from ginkgo.insula.bwrap_plan import emit_plan as emit_insula_plan
from ginkgo.insula.bwrap_plan import validate_plan as validate_insula_plan
from ginkgo.insula.local_environment import local_environment_from_mapping as insula_local_environment_from_mapping
from ginkgo.insula.materialize import materialize_invocation as materialize_insula_invocation
from ginkgo.insula.schema import InsulaBindSpec
from ginkgo.insula.schema import InsulaCommandSpec
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import InsulaEnvironmentSpec
from ginkgo.insula.schema import InsulaInvocationSpec

SGLANG_VENV_SANDBOX_PATH = "/cache/glm52/venvs/sglang"
SGLANG_VENV_PYTHON = f"{SGLANG_VENV_SANDBOX_PATH}/bin/python"
SGLANG_HF_HOME_SANDBOX_PATH = "/cache/glm52/hf-home"
SGLANG_CACHE_SANDBOX_PATH = "/cache/glm52/sglang"
SGLANG_PREPARE_PACKAGES = ["sglang[all]"]
SGLANG_PREPARE_RUN_ID = "prepare-venv"
MODEL_CACHE_PREPARE_RUN_ID = "prepare-model"
SGLANG_OFFLOADER_PATCH_ID = "glm52-offloader-v1-plain-tensor-attrs-v1"
SGLANG_OFFLOADER_PATH = f"{SGLANG_VENV_SANDBOX_PATH}/lib/python3.12/site-packages/sglang/srt/utils/offloader.py"
SGLANG_OFFLOADER_PATCH_SCRIPT = "/workspace/monarch/scripts/glm52_sglang_offloader_patch.py"
SGLANG_VENV_PROBE_SCRIPT = (
    "import importlib.metadata as metadata, json, sys; "
    "packages = {}; "
    "\nfor name in ('sglang',):\n"
    "    try:\n"
    "        packages[name] = metadata.version(name)\n"
    "    except metadata.PackageNotFoundError:\n"
    "        packages[name] = None\n"
    "from sglang.srt import platforms; "
    "from sglang.srt import utils; "
    "from sglang.srt.layers.rotary_embedding import base as rotary_base; "
    "platform = platforms.current_platform; "
    "platform_checks = {"
    "'class': type(platform).__name__, "
    "'device_name': getattr(platform, 'device_name', None), "
    "'device_type': getattr(platform, 'device_type', None), "
    "'is_cpu': bool(getattr(platform, 'is_cpu', lambda: False)()), "
    "'is_cuda': bool(getattr(platform, 'is_cuda', lambda: False)()), "
    "'utils_is_cpu': bool(utils.is_cpu()), "
    "'rotary_base_is_cpu': bool(getattr(rotary_base, '_is_cpu', False)), "
    "'rotary_base_is_cuda': bool(getattr(rotary_base, '_is_cuda', False)), "
    "}; "
    "print(json.dumps({'python': sys.executable, 'sys_prefix': sys.prefix, 'packages': packages, 'platform': platform_checks}))"
)
MODEL_CACHE_PREPARE_SCRIPT = (
    "import json, sys; "
    "from huggingface_hub import snapshot_download; "
    "snapshot_path = snapshot_download(repo_id=sys.argv[1]); "
    "print(json.dumps({'snapshot_path': snapshot_path}))"
)


class RuntimeConfigError(RuntimeError):
    """Raised when a runtime configuration file violates the schema."""


class GpuOccupancyError(RuntimeConfigError):
    """Raised when visible GPUs are occupied by non-owned processes."""

    def __init__(self, message: str, *, blocked_gpus: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.blocked_gpus = blocked_gpus


class RuntimeLaunchError(RuntimeError):
    """Raised when a validated runtime cannot be launched."""


def validate_sglang_help(help_text: str) -> None:
    if "--served-model-name" not in help_text:
        raise RuntimeConfigError("installed SGLang launcher does not support --served-model-name")


def parse_models_response(
    body: bytes,
    *,
    expected_model_ids: list[str],
    served_model_name: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeConfigError("invalid /v1/models JSON") from error

    data = _require_mapping(payload, "/v1/models response").get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeConfigError("/v1/models response must contain a non-empty data list")

    models = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            models.append(item["id"])

    if served_model_name not in models:
        raise RuntimeConfigError("model identity mismatch")
    if not set(models).intersection(expected_model_ids):
        raise RuntimeConfigError("model identity mismatch")
    return {"models": models, "payload": payload}


def validate_model_snapshot(snapshot_path: Path) -> dict[str, Any]:
    index_path = snapshot_path / "model.safetensors.index.json"
    if not index_path.exists():
        weights_path = snapshot_path / "model.safetensors"
        if not weights_path.is_file():
            raise RuntimeConfigError(f"missing model.safetensors or model.safetensors.index.json in {snapshot_path}")
        return {
            "status": "complete",
            "snapshot_path": str(snapshot_path),
            "format": "single_safetensors",
            "weight_path": str(weights_path),
            "shard_count": 1,
            "missing_shard_count": 0,
            "metadata": {},
        }
    try:
        index = json.loads(index_path.read_text())
    except json.JSONDecodeError as error:
        raise RuntimeConfigError(f"invalid model.safetensors.index.json in {snapshot_path}") from error

    weight_map = _require_mapping(index, str(index_path)).get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        raise RuntimeConfigError(f"model.safetensors.index.json in {snapshot_path} must contain a non-empty weight_map")

    shard_names: set[str] = set()
    for shard_name in weight_map.values():
        if not isinstance(shard_name, str) or not shard_name:
            raise RuntimeConfigError(f"model.safetensors.index.json in {snapshot_path} contains a non-string shard name")
        shard = Path(shard_name)
        if shard.is_absolute() or ".." in shard.parts:
            raise RuntimeConfigError(f"model.safetensors.index.json in {snapshot_path} contains an unsafe shard path")
        shard_names.add(shard_name)

    missing = sorted(shard_name for shard_name in shard_names if not (snapshot_path / shard_name).is_file())
    if missing:
        raise RuntimeConfigError(
            f"model.safetensors.index.json references {len(missing)} shard file(s) missing from {snapshot_path} "
            "(incomplete download?)"
        )

    metadata = index.get("metadata")
    return {
        "status": "complete",
        "snapshot_path": str(snapshot_path),
        "index_path": str(index_path),
        "referenced_shard_count": len(shard_names),
        "missing_shard_count": 0,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        value = yaml.safe_load(handle)
    return _require_mapping(value, str(path))


@dataclass(frozen=True)
class PortPolicy:
    mode: str
    bind_host: str
    range_start: int
    range_end: int
    disallowed_ports: list[int]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    path: str
    served_model_name: str
    expected_model_ids: list[str]


@dataclass(frozen=True)
class SglangRuntimeSpec:
    kind: str
    device: str
    cuda_visible_devices: str
    tensor_parallel_size: int
    dtype: str
    context_length: int
    kv_cache_dtype: str
    mem_fraction_static: float
    max_total_tokens: int
    max_running_requests: int
    cpu_offload_gb: int
    extra_args: list[str]


@dataclass(frozen=True)
class SglangRootfsOverlaySpec:
    venv_path: str
    hf_home: str
    sglang_cache: str
    telemetry_root: str


@dataclass(frozen=True)
class SglangVenvSpec:
    path: str
    python: str


@dataclass(frozen=True)
class ModelCacheSpec:
    hf_home: str
    sglang_cache: str


@dataclass(frozen=True)
class SandboxSpec:
    kind: str
    rootfs_ref: str
    cwd: str
    network: str
    gpu: str
    sglang: SglangRootfsOverlaySpec


@dataclass(frozen=True)
class TelemetrySpec:
    local_artifacts: bool
    remote_export: bool


@dataclass(frozen=True)
class ObservabilitySpec:
    debug_mode: bool
    leave_running_on_failure: bool
    log_level: str
    crash_dump_folder: str
    telemetry: TelemetrySpec


@dataclass(frozen=True)
class LocalPathsSpec:
    results_root: str
    scratch_root: str
    cache_root: str
    temp_root: str


@dataclass(frozen=True)
class ProbeSpec:
    startup_timeout_seconds: int
    chat_timeout_seconds: int
    models_required: bool
    chat_required: bool
    prompt: str
    max_new_tokens: int
    chat_template_kwargs: dict[str, Any]


@dataclass(frozen=True)
class RepeatabilitySpec:
    cycles: int


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    pgid: int
    argv: list[str]
    port: int


@dataclass(frozen=True)
class DeclaredSglangLaunchSpec:
    schema_version: int
    run_group: str
    fail_fast: bool
    allow_fallback: bool
    port_policy: PortPolicy
    model: ModelSpec
    runtime: SglangRuntimeSpec
    sandbox: SandboxSpec
    observability: ObservabilitySpec
    local_paths: LocalPathsSpec
    probes: ProbeSpec
    repeatability: RepeatabilitySpec


def load_declared_spec(path: Path) -> DeclaredSglangLaunchSpec:
    mapping = load_yaml_mapping(path)
    _reject_unknown(
        mapping,
        {
            "schema_version",
            "run_group",
            "fail_fast",
            "allow_fallback",
            "port_policy",
            "model",
            "runtime",
            "sandbox",
            "observability",
            "local_paths",
            "probes",
            "repeatability",
        },
        "declared_spec",
    )

    fail_fast = _required_bool(mapping, "fail_fast", "declared_spec")
    if not fail_fast:
        raise RuntimeConfigError("fail_fast must be true")
    allow_fallback = _required_bool(mapping, "allow_fallback", "declared_spec")
    if allow_fallback:
        raise RuntimeConfigError("allow_fallback must be false")

    declared = DeclaredSglangLaunchSpec(
        schema_version=_required_int(mapping, "schema_version", "declared_spec"),
        run_group=_required_str(mapping, "run_group", "declared_spec"),
        fail_fast=fail_fast,
        allow_fallback=allow_fallback,
        port_policy=_parse_port_policy(mapping.get("port_policy")),
        model=_parse_model(mapping.get("model")),
        runtime=_parse_runtime(mapping.get("runtime")),
        sandbox=_parse_sandbox(mapping.get("sandbox")),
        observability=_parse_observability(mapping.get("observability")),
        local_paths=_parse_local_paths(mapping.get("local_paths")),
        probes=_parse_probes(mapping.get("probes")),
        repeatability=_parse_repeatability(mapping.get("repeatability")),
    )
    _validate_device_sandbox_contract(declared.runtime, declared.sandbox)
    return declared


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"{path} must be a mapping")
    return value


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise RuntimeConfigError(f"unknown field at {path}: {unknown[0]}")


def _validate_device_sandbox_contract(runtime: SglangRuntimeSpec, sandbox: SandboxSpec) -> None:
    if runtime.device == "cpu" and sandbox.gpu != "none":
        raise RuntimeConfigError("sandbox.gpu must be none for cpu")
    if runtime.device == "cuda" and sandbox.gpu != "required":
        raise RuntimeConfigError("sandbox.gpu must be required for cuda")


def _required_str(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeConfigError(f"{path}.{key} is required")
    return value


def _required_string(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise RuntimeConfigError(f"{path}.{key} is required")
    return value


def _required_int(mapping: dict[str, Any], key: str, path: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeConfigError(f"{path}.{key} is required")
    return value


def _required_float(mapping: dict[str, Any], key: str, path: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise RuntimeConfigError(f"{path}.{key} is required")
    return float(value)


def _required_bool(mapping: dict[str, Any], key: str, path: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise RuntimeConfigError(f"{path}.{key} is required")
    return value


def _required_str_list(mapping: dict[str, Any], key: str, path: str) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RuntimeConfigError(f"{path}.{key} must be a non-empty string list")
    return list(value)


def _required_int_list(mapping: dict[str, Any], key: str, path: str) -> list[int]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise RuntimeConfigError(f"{path}.{key} must be an integer list")
    return list(value)


def _logical_local_ref(value: str, path: str) -> str:
    if value.startswith("/") or not value.startswith(("repo://", "run://", "cache://", "temp://")):
        raise RuntimeConfigError(f"{path} must use logical path refs")
    return value


def _parse_port_policy(data: Any) -> PortPolicy:
    mapping = _require_mapping(data, "port_policy")
    _reject_unknown(mapping, {"mode", "bind_host", "range_start", "range_end", "disallowed_ports"}, "port_policy")

    mode = _required_str(mapping, "mode", "port_policy")
    if mode != "strict_run_owned_range":
        raise RuntimeConfigError("port_policy.mode must be strict_run_owned_range")

    bind_host = _required_str(mapping, "bind_host", "port_policy")
    range_start = _required_int(mapping, "range_start", "port_policy")
    range_end = _required_int(mapping, "range_end", "port_policy")
    if range_start < 1 or range_end > 65535 or range_start > range_end:
        raise RuntimeConfigError("port_policy range must be valid")

    disallowed_ports = _required_int_list(mapping, "disallowed_ports", "port_policy")
    if not {8000, 8080, 18080}.issubset(set(disallowed_ports)):
        raise RuntimeConfigError("disallowed_ports must include 8000, 8080, and 18080")

    return PortPolicy(
        mode=mode,
        bind_host=bind_host,
        range_start=range_start,
        range_end=range_end,
        disallowed_ports=disallowed_ports,
    )


def _parse_model(data: Any) -> ModelSpec:
    mapping = _require_mapping(data, "model")
    _reject_unknown(mapping, {"id", "path", "served_model_name", "expected_model_ids"}, "model")

    model = ModelSpec(
        id=_required_str(mapping, "id", "model"),
        path=_required_str(mapping, "path", "model"),
        served_model_name=_required_str(mapping, "served_model_name", "model"),
        expected_model_ids=_required_str_list(mapping, "expected_model_ids", "model"),
    )
    if model.served_model_name not in model.expected_model_ids:
        raise RuntimeConfigError("expected_model_ids must include served_model_name")
    return model


def _parse_runtime(data: Any) -> SglangRuntimeSpec:
    mapping = _require_mapping(data, "runtime")
    _reject_unknown(
        mapping,
        {
            "kind",
            "device",
            "cuda_visible_devices",
            "tensor_parallel_size",
            "dtype",
            "context_length",
            "kv_cache_dtype",
            "mem_fraction_static",
            "max_total_tokens",
            "max_running_requests",
            "cpu_offload_gb",
            "extra_args",
        },
        "runtime",
    )

    kind = _required_str(mapping, "kind", "runtime")
    if kind != "sglang_openai":
        raise RuntimeConfigError("runtime.kind must be sglang_openai")
    device = _required_str(mapping, "device", "runtime")
    if device not in {"cpu", "cuda"}:
        raise RuntimeConfigError("runtime.device must be cpu or cuda")
    cuda_visible_devices = _required_string(mapping, "cuda_visible_devices", "runtime")
    if device == "cuda" and not cuda_visible_devices.strip():
        raise RuntimeConfigError("runtime.cuda_visible_devices is required for cuda")
    if device == "cpu" and cuda_visible_devices.strip():
        raise RuntimeConfigError("runtime.cuda_visible_devices must be empty for cpu")
    context_length = _required_int(mapping, "context_length", "runtime")
    if context_length <= 0:
        raise RuntimeConfigError("runtime.context_length must be positive")
    mem_fraction_static = _required_float(mapping, "mem_fraction_static", "runtime")
    if mem_fraction_static <= 0 or mem_fraction_static >= 1:
        raise RuntimeConfigError("runtime.mem_fraction_static must be between 0 and 1")
    max_total_tokens = _required_int(mapping, "max_total_tokens", "runtime")
    if max_total_tokens <= 0:
        raise RuntimeConfigError("runtime.max_total_tokens must be positive")
    max_running_requests = _required_int(mapping, "max_running_requests", "runtime")
    if max_running_requests <= 0:
        raise RuntimeConfigError("runtime.max_running_requests must be positive")
    cpu_offload_gb = _required_int(mapping, "cpu_offload_gb", "runtime")
    if cpu_offload_gb < 0:
        raise RuntimeConfigError("runtime.cpu_offload_gb must be non-negative")

    extra_args = mapping.get("extra_args")
    if not isinstance(extra_args, list) or not all(isinstance(arg, str) for arg in extra_args):
        raise RuntimeConfigError("runtime.extra_args must be a string list")

    return SglangRuntimeSpec(
        kind=kind,
        device=device,
        cuda_visible_devices=cuda_visible_devices,
        tensor_parallel_size=_required_int(mapping, "tensor_parallel_size", "runtime"),
        dtype=_required_str(mapping, "dtype", "runtime"),
        context_length=context_length,
        kv_cache_dtype=_required_str(mapping, "kv_cache_dtype", "runtime"),
        mem_fraction_static=mem_fraction_static,
        max_total_tokens=max_total_tokens,
        max_running_requests=max_running_requests,
        cpu_offload_gb=cpu_offload_gb,
        extra_args=list(extra_args),
    )


def _parse_sandbox(data: Any) -> SandboxSpec:
    mapping = _require_mapping(data, "sandbox")
    _reject_unknown(mapping, {"kind", "rootfs_ref", "cwd", "network", "gpu", "sglang"}, "sandbox")

    kind = _required_str(mapping, "kind", "sandbox")
    if kind != "bwrap_rootfs":
        raise RuntimeConfigError("sandbox.kind must be bwrap_rootfs")
    rootfs_ref = _required_str(mapping, "rootfs_ref", "sandbox")
    if not rootfs_ref.startswith("rootfs://"):
        raise RuntimeConfigError("sandbox.rootfs_ref must use rootfs://")
    cwd = _required_str(mapping, "cwd", "sandbox")
    if not cwd.startswith("/"):
        raise RuntimeConfigError("sandbox.cwd must be an absolute sandbox path")

    return SandboxSpec(
        kind=kind,
        rootfs_ref=rootfs_ref,
        cwd=cwd,
        network=_required_str(mapping, "network", "sandbox"),
        gpu=_required_str(mapping, "gpu", "sandbox"),
        sglang=_parse_sglang_rootfs_overlay(mapping.get("sglang")),
    )


def _parse_sglang_rootfs_overlay(data: Any) -> SglangRootfsOverlaySpec:
    mapping = _require_mapping(data, "sandbox.sglang")
    _reject_unknown(mapping, {"venv_path", "hf_home", "cache", "telemetry_root"}, "sandbox.sglang")
    overlay = SglangRootfsOverlaySpec(
        venv_path=_required_str(mapping, "venv_path", "sandbox.sglang"),
        hf_home=_required_str(mapping, "hf_home", "sandbox.sglang"),
        sglang_cache=_required_str(mapping, "cache", "sandbox.sglang"),
        telemetry_root=_required_str(mapping, "telemetry_root", "sandbox.sglang"),
    )
    if overlay.venv_path != SGLANG_VENV_SANDBOX_PATH:
        raise RuntimeConfigError("venv_path must be /cache/glm52/venvs/sglang")
    if overlay.hf_home != SGLANG_HF_HOME_SANDBOX_PATH:
        raise RuntimeConfigError("hf_home must be /cache/glm52/hf-home")
    if overlay.sglang_cache != SGLANG_CACHE_SANDBOX_PATH:
        raise RuntimeConfigError("cache must be /cache/glm52/sglang")
    for name, value in {
        "venv_path": overlay.venv_path,
        "hf_home": overlay.hf_home,
        "cache": overlay.sglang_cache,
        "telemetry_root": overlay.telemetry_root,
    }.items():
        if not value.startswith("/"):
            raise RuntimeConfigError(f"sandbox.sglang.{name} must be an absolute sandbox path")
    return overlay


def _parse_observability(data: Any) -> ObservabilitySpec:
    mapping = _require_mapping(data, "observability")
    _reject_unknown(
        mapping,
        {"debug_mode", "leave_running_on_failure", "log_level", "crash_dump_folder", "telemetry"},
        "observability",
    )

    telemetry = _require_mapping(mapping.get("telemetry"), "observability.telemetry")
    _reject_unknown(telemetry, {"local_artifacts", "remote_export"}, "observability.telemetry")
    debug_mode = _required_bool(mapping, "debug_mode", "observability")
    leave_running_on_failure = _required_bool(mapping, "leave_running_on_failure", "observability")
    if leave_running_on_failure and not debug_mode:
        raise RuntimeConfigError("leave_running_on_failure requires debug_mode")
    crash_dump_folder = _required_str(mapping, "crash_dump_folder", "observability")
    if not crash_dump_folder.startswith("/run/glm52/"):
        raise RuntimeConfigError("observability.crash_dump_folder must be under /run/glm52/")

    return ObservabilitySpec(
        debug_mode=debug_mode,
        leave_running_on_failure=leave_running_on_failure,
        log_level=_required_str(mapping, "log_level", "observability"),
        crash_dump_folder=crash_dump_folder,
        telemetry=TelemetrySpec(
            local_artifacts=_required_bool(telemetry, "local_artifacts", "observability.telemetry"),
            remote_export=_required_bool(telemetry, "remote_export", "observability.telemetry"),
        ),
    )


def _parse_local_paths(data: Any) -> LocalPathsSpec:
    mapping = _require_mapping(data, "local_paths")
    _reject_unknown(mapping, {"results_root", "scratch_root", "cache_root", "temp_root"}, "local_paths")

    return LocalPathsSpec(
        results_root=_logical_local_ref(_required_str(mapping, "results_root", "local_paths"), "local_paths.results_root"),
        scratch_root=_logical_local_ref(_required_str(mapping, "scratch_root", "local_paths"), "local_paths.scratch_root"),
        cache_root=_logical_local_ref(_required_str(mapping, "cache_root", "local_paths"), "local_paths.cache_root"),
        temp_root=_logical_local_ref(_required_str(mapping, "temp_root", "local_paths"), "local_paths.temp_root"),
    )


def _parse_probes(data: Any) -> ProbeSpec:
    mapping = _require_mapping(data, "probes")
    _reject_unknown(
        mapping,
        {
            "startup_timeout_seconds",
            "chat_timeout_seconds",
            "models_required",
            "chat_required",
            "prompt",
            "max_new_tokens",
            "chat_template_kwargs",
        },
        "probes",
    )

    prompt = _required_str(mapping, "prompt", "probes")
    if not prompt.strip():
        raise RuntimeConfigError("probes.prompt must be non-empty")
    max_new_tokens = _required_int(mapping, "max_new_tokens", "probes")
    if max_new_tokens <= 0:
        raise RuntimeConfigError("probes.max_new_tokens must be positive")
    chat_template_kwargs = _require_mapping(mapping.get("chat_template_kwargs"), "probes.chat_template_kwargs")
    if chat_template_kwargs.get("enable_thinking") is not False:
        raise RuntimeConfigError("probes.chat_template_kwargs.enable_thinking must be false")
    startup_timeout_seconds = _required_int(mapping, "startup_timeout_seconds", "probes")
    chat_timeout_seconds = _required_int(mapping, "chat_timeout_seconds", "probes")
    if startup_timeout_seconds <= 0:
        raise RuntimeConfigError("probes.startup_timeout_seconds must be positive")
    if chat_timeout_seconds <= 0:
        raise RuntimeConfigError("probes.chat_timeout_seconds must be positive")

    return ProbeSpec(
        startup_timeout_seconds=startup_timeout_seconds,
        chat_timeout_seconds=chat_timeout_seconds,
        models_required=_required_bool(mapping, "models_required", "probes"),
        chat_required=_required_bool(mapping, "chat_required", "probes"),
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        chat_template_kwargs=dict(chat_template_kwargs),
    )


def _parse_repeatability(data: Any) -> RepeatabilitySpec:
    mapping = _require_mapping(data, "repeatability")
    _reject_unknown(mapping, {"cycles"}, "repeatability")

    cycles = _required_int(mapping, "cycles", "repeatability")
    if cycles < 1:
        raise RuntimeConfigError("repeatability.cycles must be positive")
    return RepeatabilitySpec(cycles=cycles)


@dataclass(frozen=True)
class LocalEnvironmentConfig:
    repo: str
    cache: str
    temp: str
    rootfs: dict[str, str]


@dataclass(frozen=True)
class MaterializedSglangRuntimeConfig:
    schema_version: int
    run_id: str
    run_group: str
    fail_fast: bool
    allow_fallback: bool
    service: dict[str, Any]
    model: dict[str, Any]
    runtime: dict[str, Any]
    observability: dict[str, Any]
    host_layout: dict[str, Any]
    sandbox: dict[str, Any]
    launch: dict[str, Any]
    probes: dict[str, Any]
    artifacts: dict[str, Any]
    resolved_paths: dict[str, Any]

    def to_mapping(self) -> dict[str, Any]:
        return _config_to_mapping(self)

    def replace_service(self, service: dict[str, Any]) -> "MaterializedSglangRuntimeConfig":
        return MaterializedSglangRuntimeConfig(
            schema_version=self.schema_version,
            run_id=self.run_id,
            run_group=self.run_group,
            fail_fast=self.fail_fast,
            allow_fallback=self.allow_fallback,
            service={**self.service, **service},
            model=self.model,
            runtime=self.runtime,
            observability=self.observability,
            host_layout=self.host_layout,
            sandbox=self.sandbox,
            launch=self.launch,
            probes=self.probes,
            artifacts=self.artifacts,
            resolved_paths=self.resolved_paths,
        )

    def replace_launch_inner(self, inner_argv: list[str]) -> "MaterializedSglangRuntimeConfig":
        launch = dict(self.launch)
        launch["inner_argv"] = inner_argv
        return MaterializedSglangRuntimeConfig(
            schema_version=self.schema_version,
            run_id=self.run_id,
            run_group=self.run_group,
            fail_fast=self.fail_fast,
            allow_fallback=self.allow_fallback,
            service=self.service,
            model=self.model,
            runtime=self.runtime,
            observability=self.observability,
            host_layout=self.host_layout,
            sandbox=self.sandbox,
            launch=launch,
            probes=self.probes,
            artifacts=self.artifacts,
            resolved_paths=self.resolved_paths,
        )

    def replace_launch_outer(self, outer_argv: list[str]) -> "MaterializedSglangRuntimeConfig":
        launch = dict(self.launch)
        launch["outer_argv"] = outer_argv
        return MaterializedSglangRuntimeConfig(
            schema_version=self.schema_version,
            run_id=self.run_id,
            run_group=self.run_group,
            fail_fast=self.fail_fast,
            allow_fallback=self.allow_fallback,
            service=self.service,
            model=self.model,
            runtime=self.runtime,
            observability=self.observability,
            host_layout=self.host_layout,
            sandbox=self.sandbox,
            launch=launch,
            probes=self.probes,
            artifacts=self.artifacts,
            resolved_paths=self.resolved_paths,
        )

    def replace_probes(self, probes: dict[str, Any]) -> "MaterializedSglangRuntimeConfig":
        return MaterializedSglangRuntimeConfig(
            schema_version=self.schema_version,
            run_id=self.run_id,
            run_group=self.run_group,
            fail_fast=self.fail_fast,
            allow_fallback=self.allow_fallback,
            service=self.service,
            model=self.model,
            runtime=self.runtime,
            observability=self.observability,
            host_layout=self.host_layout,
            sandbox=self.sandbox,
            launch=self.launch,
            probes=probes,
            artifacts=self.artifacts,
            resolved_paths=self.resolved_paths,
        )


def load_local_environment(path: Path) -> LocalEnvironmentConfig:
    mapping = load_yaml_mapping(path)
    _reject_unknown(mapping, {"schema_version", "roots", "rootfs"}, "local_environment")
    if _required_int(mapping, "schema_version", "local_environment") != 1:
        raise RuntimeConfigError("local_environment.schema_version must be 1")

    roots = _require_mapping(mapping.get("roots"), "local_environment.roots")
    _reject_unknown(roots, {"repo", "cache", "temp"}, "local_environment.roots")
    rootfs = _require_mapping(mapping.get("rootfs"), "local_environment.rootfs")

    config = LocalEnvironmentConfig(
        repo=_absolute_host_path(_required_str(roots, "repo", "local_environment.roots"), "local_environment.roots.repo"),
        cache=_absolute_host_path(_required_str(roots, "cache", "local_environment.roots"), "local_environment.roots.cache"),
        temp=_absolute_host_path(_required_str(roots, "temp", "local_environment.roots"), "local_environment.roots.temp"),
        rootfs={
            str(name): _absolute_host_path(str(value), f"local_environment.rootfs.{name}")
            for name, value in rootfs.items()
        },
    )
    if not config.rootfs:
        raise RuntimeConfigError("local_environment.rootfs must not be empty")
    return config


def materialize_runtime_config(
    *,
    declared: DeclaredSglangLaunchSpec,
    local_environment: LocalEnvironmentConfig,
    run_id: str,
    port: int | None = None,
) -> MaterializedSglangRuntimeConfig:
    _ensure_rootfs_ref_resolves(declared.sandbox.rootfs_ref, local_environment)
    _reject_schema_owned_extra_args(declared.runtime.extra_args)
    selected_port = _select_port(declared.port_policy, port)
    base_url = f"http://{declared.port_policy.bind_host}:{selected_port}/v1"
    cache_dir_ref = f"cache://{declared.run_group}"
    sglang_venv_ref = f"{cache_dir_ref}/venvs/sglang"
    hf_home_ref = f"{cache_dir_ref}/hf-home"
    sglang_cache_ref = f"{cache_dir_ref}/sglang"
    inner_argv = [
        SGLANG_VENV_PYTHON,
        "-m",
        "sglang.launch_server",
        "--model-path",
        declared.model.path,
        "--served-model-name",
        declared.model.served_model_name,
        "--host",
        declared.port_policy.bind_host,
        "--port",
        str(selected_port),
        "--tp",
        str(declared.runtime.tensor_parallel_size),
        "--device",
        declared.runtime.device,
        "--dtype",
        declared.runtime.dtype,
        "--context-length",
        str(declared.runtime.context_length),
        "--kv-cache-dtype",
        declared.runtime.kv_cache_dtype,
        "--mem-fraction-static",
        _format_float_arg(declared.runtime.mem_fraction_static),
        "--max-total-tokens",
        str(declared.runtime.max_total_tokens),
        "--max-running-requests",
        str(declared.runtime.max_running_requests),
        "--cpu-offload-gb",
        str(declared.runtime.cpu_offload_gb),
        "--crash-dump-folder",
        declared.observability.crash_dump_folder,
        *declared.runtime.extra_args,
    ]
    outer_argv = [
        "scripts/rootfs/enter_rootfs.sh",
        "--repo-readonly",
        "--bind-rw",
        "run://:/run/glm52",
        "--bind-rw",
        f"temp://{run_id}:/tmp/glm52",
        "--bind-rw",
        f"{cache_dir_ref}:/cache/glm52",
        "--bind-rw",
        f"{sglang_venv_ref}:{declared.sandbox.sglang.venv_path}",
        "--bind-rw",
        f"{hf_home_ref}:{declared.sandbox.sglang.hf_home}",
        "--bind-rw",
        f"{sglang_cache_ref}:{declared.sandbox.sglang.sglang_cache}",
        "--emit-plan",
        "run://sandbox/resolved-bwrap-plan.yaml",
        "--",
        *inner_argv,
    ]

    config = MaterializedSglangRuntimeConfig(
        schema_version=1,
        run_id=run_id,
        run_group=declared.run_group,
        fail_fast=declared.fail_fast,
        allow_fallback=declared.allow_fallback,
        service={
            "kind": declared.runtime.kind,
            "bind_host": declared.port_policy.bind_host,
            "port": selected_port,
            "base_url": base_url,
            "expected_model_ids": list(declared.model.expected_model_ids),
        },
        model={
            "id": declared.model.id,
            "path": declared.model.path,
            "served_model_name": declared.model.served_model_name,
            "expected_model_ids": list(declared.model.expected_model_ids),
        },
        runtime={
            "kind": declared.runtime.kind,
            "device": declared.runtime.device,
            "cuda_visible_devices": declared.runtime.cuda_visible_devices,
            "tensor_parallel_size": declared.runtime.tensor_parallel_size,
            "dtype": declared.runtime.dtype,
            "context_length": declared.runtime.context_length,
            "kv_cache_dtype": declared.runtime.kv_cache_dtype,
            "mem_fraction_static": declared.runtime.mem_fraction_static,
            "max_total_tokens": declared.runtime.max_total_tokens,
            "max_running_requests": declared.runtime.max_running_requests,
            "cpu_offload_gb": declared.runtime.cpu_offload_gb,
            "extra_args": list(declared.runtime.extra_args),
        },
        observability={
            "debug_mode": declared.observability.debug_mode,
            "leave_running_on_failure": declared.observability.leave_running_on_failure,
            "log_level": declared.observability.log_level,
            "crash_dump_folder": declared.observability.crash_dump_folder,
            "telemetry": {
                "local_artifacts": declared.observability.telemetry.local_artifacts,
                "remote_export": declared.observability.telemetry.remote_export,
            },
        },
        host_layout={
            "results_root": declared.local_paths.results_root,
            "run_dir": f"{declared.local_paths.results_root.rstrip('/')}/{run_id}",
            "logs_dir": "run://logs",
            "tmp_dir": f"temp://{run_id}",
            "cache_dir": cache_dir_ref,
            "sglang_venv": sglang_venv_ref,
            "materialized_config": "run://materialized-sglang-runtime.yaml",
        },
        sandbox={
            "kind": declared.sandbox.kind,
            "rootfs_ref": declared.sandbox.rootfs_ref,
            "cwd": declared.sandbox.cwd,
            "network": declared.sandbox.network,
            "gpu": declared.sandbox.gpu,
            "sglang": {
                "venv_path": declared.sandbox.sglang.venv_path,
                "python": SGLANG_VENV_PYTHON,
                "hf_home": declared.sandbox.sglang.hf_home,
                "cache": declared.sandbox.sglang.sglang_cache,
                "telemetry_root": declared.sandbox.sglang.telemetry_root,
            },
            "env_allowlist": [],
            "env": _sglang_launch_env(declared),
            "mounts": [
                {"host_path_ref": "repo://", "sandbox_path": "/workspace/monarch", "mode": "ro"},
                {"host_path_ref": "run://", "sandbox_path": "/run/glm52", "mode": "rw"},
                {"host_path_ref": f"temp://{run_id}", "sandbox_path": "/tmp/glm52", "mode": "rw"},
                {"host_path_ref": f"cache://{declared.run_group}", "sandbox_path": "/cache/glm52", "mode": "rw"},
                {"host_path_ref": sglang_venv_ref, "sandbox_path": declared.sandbox.sglang.venv_path, "mode": "rw"},
                {"host_path_ref": hf_home_ref, "sandbox_path": declared.sandbox.sglang.hf_home, "mode": "rw"},
                {"host_path_ref": sglang_cache_ref, "sandbox_path": declared.sandbox.sglang.sglang_cache, "mode": "rw"},
            ],
        },
        launch={
            "outer_argv": outer_argv,
            "inner_argv": inner_argv,
            "env": _sglang_launch_env(declared),
        },
        probes={
            "models_url": f"{base_url}/models",
            "generate_url": f"http://{declared.port_policy.bind_host}:{selected_port}/generate",
            "completions_url": f"{base_url}/completions",
            "chat_url": f"{base_url}/chat/completions",
            "startup_timeout_seconds": declared.probes.startup_timeout_seconds,
            "chat_timeout_seconds": declared.probes.chat_timeout_seconds,
            "generate_payload": {
                "text": declared.probes.prompt,
                "sampling_params": {
                    "temperature": 0,
                    "max_new_tokens": declared.probes.max_new_tokens,
                },
            },
            "completion_payload": {
                "model": declared.model.served_model_name,
                "prompt": declared.probes.prompt,
                "max_tokens": declared.probes.max_new_tokens,
                "temperature": 0,
            },
            "chat_payload": {
                "model": declared.model.served_model_name,
                "messages": [{"role": "user", "content": declared.probes.prompt}],
                "max_tokens": declared.probes.max_new_tokens,
                "temperature": 0,
                "chat_template_kwargs": dict(declared.probes.chat_template_kwargs),
            },
        },
        artifacts={
            "declared_spec_copy": "run://declared-spec.yaml",
            "materialized_config": "run://materialized-sglang-runtime.yaml",
            "resolved_local_paths": "run://resolved-local-paths.yaml",
            "process_record": "run://process.yaml",
            "launch_summary": "run://launch-summary.json",
            "teardown_summary": "run://teardown-summary.json",
            "resolved_rootfs_plan": "run://sandbox/resolved-bwrap-plan.yaml",
            "models_probe": "run://probes/models.json",
            "generate_probe": "run://probes/generate.json",
            "completion_probe": "run://probes/completions.json",
            "chat_probe": "run://probes/chat-completions.json",
            "stdout_log": "run://logs/stdout.log",
            "stderr_log": "run://logs/stderr.log",
            "telemetry_log": "run://logs/telemetry.jsonl",
            "sglang_cli_help": "run://sandbox/sglang-launch-server-help.txt",
            "preparation": {
                "sglang_venv_record": f"run://{run_id}/sglang-venv.json",
                "model_cache_record": f"run://{run_id}/model-cache.json",
            },
        },
        resolved_paths={
            "repo": local_environment.repo,
            "cache": local_environment.cache,
            "temp": local_environment.temp,
            "sglang_venv": _resolve_local_path_ref(local_environment, sglang_venv_ref),
            "preparation": {
                "sglang_venv_record": _resolve_local_path_ref(
                    local_environment,
                    f"{declared.local_paths.results_root.rstrip('/')}/{run_id}/sglang-venv.json",
                ),
                "model_cache_record": _resolve_local_path_ref(
                    local_environment,
                    f"{declared.local_paths.results_root.rstrip('/')}/{run_id}/model-cache.json",
                ),
            },
            "rootfs": dict(local_environment.rootfs),
        },
    )
    validate_materialized_config(config)
    return config


def validate_materialized_config(config: MaterializedSglangRuntimeConfig) -> None:
    _validate_materialized_top_level(config)
    inner = _required_str_sequence(config.launch.get("inner_argv"), "launch.inner_argv")
    outer = _required_str_sequence(config.launch.get("outer_argv"), "launch.outer_argv")
    service_port = _required_section_int(config.service, "port", "service")
    service_host = _required_section_str(config.service, "bind_host", "service")

    _reject_duplicate_inner_argv_schema_flags(inner)
    if _argv_value(inner, "--port") != str(service_port):
        raise RuntimeConfigError("service.port must match launch.inner_argv --port")
    if _argv_value(inner, "--host") != service_host:
        raise RuntimeConfigError("service.bind_host must match launch.inner_argv --host")
    if _argv_value(inner, "--model-path") != _required_section_str(config.model, "path", "model"):
        raise RuntimeConfigError("model.path must match launch.inner_argv --model-path")
    if _argv_value(inner, "--served-model-name") != _required_section_str(config.model, "served_model_name", "model"):
        raise RuntimeConfigError("model.served_model_name must match launch.inner_argv --served-model-name")
    if _argv_value(inner, "--tp") != str(_required_section_int(config.runtime, "tensor_parallel_size", "runtime")):
        raise RuntimeConfigError("runtime.tensor_parallel_size must match launch.inner_argv --tp")
    if _argv_value(inner, "--device") != _required_section_str(config.runtime, "device", "runtime"):
        raise RuntimeConfigError("runtime.device must match launch.inner_argv --device")
    if _argv_value(inner, "--dtype") != _required_section_str(config.runtime, "dtype", "runtime"):
        raise RuntimeConfigError("runtime.dtype must match launch.inner_argv --dtype")
    if _argv_value(inner, "--context-length") != str(_required_section_int(config.runtime, "context_length", "runtime")):
        raise RuntimeConfigError("runtime.context_length must match launch.inner_argv --context-length")
    if _argv_value(inner, "--kv-cache-dtype") != _required_section_str(config.runtime, "kv_cache_dtype", "runtime"):
        raise RuntimeConfigError("runtime.kv_cache_dtype must match launch.inner_argv --kv-cache-dtype")
    if _argv_value(inner, "--mem-fraction-static") != _format_float_arg(
        _required_section_float(config.runtime, "mem_fraction_static", "runtime")
    ):
        raise RuntimeConfigError("runtime.mem_fraction_static must match launch.inner_argv --mem-fraction-static")
    if _argv_value(inner, "--max-total-tokens") != str(_required_section_int(config.runtime, "max_total_tokens", "runtime")):
        raise RuntimeConfigError("runtime.max_total_tokens must match launch.inner_argv --max-total-tokens")
    if _argv_value(inner, "--max-running-requests") != str(
        _required_section_int(config.runtime, "max_running_requests", "runtime")
    ):
        raise RuntimeConfigError("runtime.max_running_requests must match launch.inner_argv --max-running-requests")
    if _argv_value(inner, "--cpu-offload-gb") != str(_required_section_int(config.runtime, "cpu_offload_gb", "runtime")):
        raise RuntimeConfigError("runtime.cpu_offload_gb must match launch.inner_argv --cpu-offload-gb")
    if _argv_value(inner, "--crash-dump-folder") != _required_section_str(
        config.observability,
        "crash_dump_folder",
        "observability",
    ):
        raise RuntimeConfigError("observability.crash_dump_folder must match launch.inner_argv --crash-dump-folder")
    if inner[:3] != [SGLANG_VENV_PYTHON, "-m", "sglang.launch_server"]:
        raise RuntimeConfigError("launch.inner_argv must use the rootfs-owned SGLang venv Python")

    try:
        marker = outer.index("--")
    except ValueError as error:
        raise RuntimeConfigError("launch.outer_argv must contain -- before inner argv") from error
    if outer[marker + 1 :] != inner:
        raise RuntimeConfigError("outer_argv SGLang tail must equal inner_argv")

    base_url = _required_section_str(config.service, "base_url", "service")
    _validate_probe_urls(base_url, config.probes, service_port)
    _validate_launch_env(config)
    _validate_logical_host_layout(config.host_layout)
    _reject_disallowed_ports(config, {8000, 8080, 18080})


def validate_resolved_rootfs_plan(
    *,
    config: MaterializedSglangRuntimeConfig,
    plan: dict[str, Any],
    expected_inner_argv: list[str] | None = None,
) -> None:
    if expected_inner_argv is None:
        expected_inner_argv = config.launch["inner_argv"]
    if plan.get("rootfs") != _resolved_rootfs_path(config):
        raise RuntimeConfigError("resolved rootfs plan rootfs must match materialized config")
    if plan.get("inner_argv") != expected_inner_argv:
        raise RuntimeConfigError("resolved rootfs plan inner_argv must match materialized config")
    if plan.get("cwd") != config.sandbox["cwd"]:
        raise RuntimeConfigError("resolved rootfs plan cwd must match materialized sandbox cwd")
    if plan.get("repo_projection_mode") != "ro":
        raise RuntimeConfigError("repo projection must be ro")
    plan_env = _require_mapping(plan.get("env"), "resolved_rootfs_plan.env")
    for key, value in config.launch["env"].items():
        if key in {"HF_HOME", "SGLANG_CACHE_DIR"}:
            continue
        if plan_env.get(key) != value:
            raise RuntimeConfigError(f"resolved rootfs plan env mismatch: {key}")
    by_sandbox = _mounts_by_sandbox_path(plan)
    for expected in config.sandbox["mounts"]:
        mount = by_sandbox.get(expected["sandbox_path"])
        if mount is None:
            raise RuntimeConfigError(f"missing sandbox mount: {expected['sandbox_path']}")
        if mount.get("mode") != expected["mode"]:
            raise RuntimeConfigError(f"mount mode mismatch: {expected['sandbox_path']}")
        expected_host_path = _resolve_host_path_ref(config, expected["host_path_ref"])
        if mount.get("host_path") != expected_host_path:
            raise RuntimeConfigError(f"mount host path mismatch: {expected['sandbox_path']}")


def validate_sglang_rootfs_overlay(
    *,
    config: MaterializedSglangRuntimeConfig,
    plan: dict[str, Any],
    expected_inner_argv: list[str] | None = None,
) -> None:
    sandbox = _require_mapping(config.sandbox, "sandbox")
    sglang = _require_mapping(sandbox.get("sglang"), "sandbox.sglang")
    env = _require_mapping(plan.get("env"), "rootfs_plan.env")
    if env.get("HF_HOME") != sglang["hf_home"]:
        raise RuntimeConfigError("rootfs plan HF_HOME does not match materialized config")
    if env.get("SGLANG_CACHE_DIR") != sglang["cache"]:
        raise RuntimeConfigError("rootfs plan SGLANG_CACHE_DIR does not match materialized config")
    mounts = _mounts_by_sandbox_path(plan)
    for required in (sglang["venv_path"], sglang["hf_home"], sglang["cache"]):
        if required not in mounts:
            raise RuntimeConfigError(f"rootfs plan missing SGLang mount: {required}")
    validate_resolved_rootfs_plan(config=config, plan=plan, expected_inner_argv=expected_inner_argv)


def should_teardown_after_failure(config: MaterializedSglangRuntimeConfig) -> bool:
    return not (
        bool(config.observability.get("debug_mode"))
        and bool(config.observability.get("leave_running_on_failure"))
    )


def run_sglang_help_preflight(config: MaterializedSglangRuntimeConfig) -> str:
    _ensure_created_bind_sources(config)
    outer = _resolved_outer_argv(config)
    try:
        marker = outer.index("--")
    except ValueError as error:
        raise RuntimeConfigError("launch.outer_argv must contain -- before inner argv") from error
    inner = _required_str_sequence(config.launch.get("inner_argv"), "launch.inner_argv")
    process = subprocess.run(
        outer[: marker + 1] + inner[:3] + ["--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=_runtime_subprocess_cwd(config),
        env=_runtime_subprocess_env(config),
    )
    help_text = process.stdout + process.stderr
    if process.returncode != 0:
        raise RuntimeConfigError(f"sglang help preflight failed: {help_text}")
    validate_sglang_help(help_text)
    return help_text


def prepare_sglang_venv(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str = SGLANG_PREPARE_RUN_ID,
    run: Any | None = None,
    plan_emitter: Any | None = None,
) -> dict[str, Any]:
    declared = load_declared_spec(declared_path)
    local_environment = load_local_environment(local_environment_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_environment,
        run_id=run_id,
        port=declared.port_policy.range_start,
    )
    inner_argv = _sglang_venv_prepare_command()
    install_argv = [
        "uv",
        "pip",
        "install",
        "--python",
        SGLANG_VENV_PYTHON,
        *SGLANG_PREPARE_PACKAGES,
    ]
    patch_argv = [
        SGLANG_VENV_PYTHON,
        SGLANG_OFFLOADER_PATCH_SCRIPT,
        "--offloader",
        SGLANG_OFFLOADER_PATH,
    ]
    probe_argv = [
        SGLANG_VENV_PYTHON,
        "-c",
        SGLANG_VENV_PROBE_SCRIPT,
    ]
    help_argv = [
        SGLANG_VENV_PYTHON,
        "-m",
        "sglang.launch_server",
        "--help",
    ]

    outputs: list[dict[str, Any]] = []
    plan_evidence = _preparation_plan_evidence(
        config,
        "sglang_venv_record",
        inner_argv,
        run=run,
        plan_emitter=plan_emitter,
    )
    for command in (inner_argv, install_argv, patch_argv, probe_argv, help_argv):
        completed = _run_preparation_command(config, command, run=run)
        outputs.append(
            {
                "command": command,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )

    offloader_patch = _parse_offloader_patch_output(outputs[2]["stdout"])
    if _required_section_str(offloader_patch, "patch_id", "offloader patch evidence") != SGLANG_OFFLOADER_PATCH_ID:
        raise RuntimeConfigError("SGLang offloader patch evidence has wrong patch id")
    probe = _parse_prepare_versions(outputs[3]["stdout"])
    if _required_section_str(probe, "python", "sglang venv probe") != SGLANG_VENV_PYTHON:
        raise RuntimeConfigError("SGLang venv preparation used the wrong Python executable")
    sys_prefix = _required_section_str(probe, "sys_prefix", "sglang venv probe")
    packages = _require_mapping(probe.get("packages"), "sglang venv probe packages")
    platform_checks = _require_mapping(probe.get("platform"), "sglang venv probe platform")
    _validate_sglang_platform_checks(
        platform_checks,
        device=_required_section_str(config.runtime, "device", "runtime"),
        source="SGLang venv probe",
    )
    help_text = str(outputs[-1]["stdout"]) + str(outputs[-1]["stderr"])
    if run is None:
        validate_sglang_help(help_text)
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "venv": {
            "path": SGLANG_VENV_SANDBOX_PATH,
            "python": SGLANG_VENV_PYTHON,
            "sys_prefix": sys_prefix,
            "packages": list(SGLANG_PREPARE_PACKAGES),
            "installed_packages": packages,
        },
        "rootfs": {
            "recipe_sha256": _rootfs_recipe_digest(config),
        },
        "bwrap_plan": plan_evidence,
        "checks": {
            "served_model_name_flag": True,
            "offloader_patch": offloader_patch,
            "platform": platform_checks,
        },
        "commands": outputs,
    }
    _write_json(_preparation_record_path(config, "sglang_venv_record"), record)
    return record


def prepare_model_cache(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str = MODEL_CACHE_PREPARE_RUN_ID,
    run: Any | None = None,
    snapshot_validator: Any | None = None,
    plan_emitter: Any | None = None,
) -> dict[str, Any]:
    declared = load_declared_spec(declared_path)
    local_environment = load_local_environment(local_environment_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_environment,
        run_id=run_id,
        port=declared.port_policy.range_start,
    )
    command = _model_cache_prepare_command(config)
    model_cache_prepare_env = _model_cache_prepare_env()
    plan_evidence = _preparation_plan_evidence(
        config,
        "model_cache_record",
        command,
        run=run,
        env=model_cache_prepare_env,
        plan_emitter=plan_emitter,
    )
    completed = _run_preparation_command(
        config,
        command,
        run=run,
        env=model_cache_prepare_env,
    )
    payload = _parse_model_cache_prepare_output(completed.stdout)
    sandbox_snapshot_path = _required_section_str(payload, "snapshot_path", "model cache prepare output")
    validation_path = Path(_host_path_from_cache_sandbox_path(config, sandbox_snapshot_path))
    if snapshot_validator is None:
        snapshot_validator = validate_model_snapshot
    snapshot_evidence = snapshot_validator(validation_path)
    shard_count = _snapshot_shard_count(snapshot_evidence)
    missing_shard_count = _required_section_int(snapshot_evidence, "missing_shard_count", "model_snapshot")
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "model_cache": {
            "model_id": declared.model.id,
            "snapshot_path": sandbox_snapshot_path,
            "shard_count": shard_count,
            "missing_shard_count": missing_shard_count,
        },
        "rootfs": {
            "recipe_sha256": _rootfs_recipe_digest(config),
        },
        "bwrap_plan": plan_evidence,
        "command": {
            "argv": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
    }
    _write_json(_preparation_record_path(config, "model_cache_record"), record)
    return record


def validate_preparation_records(
    *,
    config: MaterializedSglangRuntimeConfig,
) -> dict[str, Any]:
    venv_record = _load_preparation_record(config, "sglang_venv_record", "missing SGLang venv preparation record")
    model_record = _load_preparation_record(config, "model_cache_record", "missing model cache preparation record")

    venv = _require_mapping(venv_record.get("venv"), "sglang_venv_record.venv")
    if _required_section_str(venv, "python", "sglang_venv_record.venv") != SGLANG_VENV_PYTHON:
        raise RuntimeConfigError("SGLang venv preparation record Python does not match rootfs venv")
    packages = venv.get("packages")
    if not isinstance(packages, list) or packages != SGLANG_PREPARE_PACKAGES:
        raise RuntimeConfigError("SGLang venv preparation record package contract mismatch")
    installed_packages = _require_mapping(venv.get("installed_packages"), "sglang_venv_record.venv.installed_packages")
    for package in ("sglang",):
        if not installed_packages.get(package):
            raise RuntimeConfigError(f"SGLang venv preparation record missing installed package: {package}")
    checks = _require_mapping(venv_record.get("checks"), "sglang_venv_record.checks")
    if checks.get("served_model_name_flag") is not True:
        raise RuntimeConfigError("SGLang venv preparation record missing served_model_name_flag")
    if "platform" not in checks:
        raise RuntimeConfigError("SGLang venv preparation record missing platform proof")
    platform_checks = _require_mapping(checks.get("platform"), "sglang_venv_record.checks.platform")
    _validate_sglang_platform_checks(
        platform_checks,
        device=_required_section_str(config.runtime, "device", "runtime"),
        source="SGLang venv preparation record",
    )
    offloader_patch = _require_mapping(checks.get("offloader_patch"), "sglang_venv_record.checks.offloader_patch")
    if _required_section_str(offloader_patch, "patch_id", "sglang_venv_record.checks.offloader_patch") != SGLANG_OFFLOADER_PATCH_ID:
        raise RuntimeConfigError("SGLang venv preparation record has wrong offloader patch id")
    if not _required_section_str(offloader_patch, "sha256_after", "sglang_venv_record.checks.offloader_patch"):
        raise RuntimeConfigError("SGLang venv preparation record missing offloader patch hash")

    model_cache = _require_mapping(model_record.get("model_cache"), "model_cache_record.model_cache")
    snapshot_path = _required_section_str(model_cache, "snapshot_path", "model_cache_record.model_cache")
    if not _is_under_sandbox_path(snapshot_path, SGLANG_HF_HOME_SANDBOX_PATH):
        raise RuntimeConfigError("model cache snapshot path must be under /cache/glm52/hf-home")
    if _required_section_int(model_cache, "missing_shard_count", "model_cache_record.model_cache") != 0:
        raise RuntimeConfigError("model cache preparation record has missing shard files")

    expected_digest = _rootfs_recipe_digest(config)
    for name, key, record, inner_command, env in (
        ("SGLang venv", "sglang_venv_record", venv_record, _sglang_venv_prepare_command(), None),
        ("model cache", "model_cache_record", model_record, _model_cache_prepare_command(config), _model_cache_prepare_env()),
    ):
        rootfs = _require_mapping(record.get("rootfs"), f"{name} preparation record rootfs")
        if _required_section_str(rootfs, "recipe_sha256", f"{name} preparation record rootfs") != expected_digest:
            raise RuntimeConfigError(f"{name} preparation record rootfs recipe digest mismatch")
        preparation_config = _preparation_config_for_record(config, key)
        _validate_preparation_record_plan(preparation_config, key, record, inner_command, env=env)

    return {
        "sglang_venv": venv_record,
        "model_cache": model_record,
    }


def _validate_sglang_platform_checks(platform_checks: dict[str, Any], *, device: str, source: str) -> None:
    if device == "cpu":
        if platform_checks.get("is_cpu") is not True:
            raise RuntimeConfigError(f"{source} missing CPU platform proof: {platform_checks}")
        if platform_checks.get("utils_is_cpu") is not True:
            raise RuntimeConfigError(f"{source} missing utils.is_cpu proof: {platform_checks}")
        if platform_checks.get("rotary_base_is_cpu") is not True:
            raise RuntimeConfigError(f"{source} missing rotary CPU proof: {platform_checks}")
        if platform_checks.get("rotary_base_is_cuda") is True:
            raise RuntimeConfigError(f"{source} reports CUDA rotary mode for CPU route: {platform_checks}")
        return
    if device == "cuda":
        if platform_checks.get("is_cpu") is True:
            raise RuntimeConfigError(f"{source} reports CPU platform for CUDA route: {platform_checks}")
        if platform_checks.get("rotary_base_is_cpu") is True:
            raise RuntimeConfigError(f"{source} reports CPU rotary mode for CUDA route: {platform_checks}")
        if platform_checks.get("is_cuda") is not True:
            raise RuntimeConfigError(f"{source} missing CUDA platform proof: {platform_checks}")
        if platform_checks.get("rotary_base_is_cuda") is not True:
            raise RuntimeConfigError(f"{source} missing rotary CUDA proof: {platform_checks}")
        return
    raise RuntimeConfigError(f"runtime.device must be cpu or cuda: {device}")


def preflight_model_cache(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    return validate_preparation_records(config=config)["model_cache"]


def preflight_gpu_occupancy(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    if _required_section_str(config.runtime, "device", "runtime") == "cpu":
        return {"status": "not_required", "checked_gpus": []}
    visible = _visible_gpu_indices(_required_section_str(config.runtime, "cuda_visible_devices", "runtime"))
    if not visible:
        raise RuntimeConfigError("runtime.cuda_visible_devices must name at least one GPU")
    uuid_by_index = _nvidia_gpu_uuid_by_index()
    busy_by_uuid = {app["gpu_uuid"]: app for app in _nvidia_compute_apps()}

    checked: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for index in visible:
        gpu_uuid = uuid_by_index.get(index)
        if gpu_uuid is None:
            raise RuntimeConfigError(f"visible GPU {index} is not reported by nvidia-smi")
        app = busy_by_uuid.get(gpu_uuid)
        if app is not None:
            blocked.append(
                {
                    "index": index,
                    "uuid": gpu_uuid,
                    "pid": app["pid"],
                    "process_name": app["process_name"],
                    "used_memory": app["used_memory"],
                }
            )
            continue
        checked.append({"index": index, "uuid": gpu_uuid, "status": "free"})
    if blocked:
        first = blocked[0]
        raise GpuOccupancyError(
            f"visible GPU {first['index']} is already occupied by pid {first['pid']} "
            f"({first['process_name']}, {first['used_memory']} MiB)",
            blocked_gpus=blocked,
        )
    return {"status": "free", "checked_gpus": checked}


def wait_for_gpu_free_window(
    config: MaterializedSglangRuntimeConfig,
    *,
    timeout_seconds: int,
    stable_seconds: int = 0,
    poll_seconds: float = 5.0,
) -> dict[str, Any]:
    if timeout_seconds < 0:
        raise RuntimeConfigError("GPU-free wait seconds must be non-negative")
    if stable_seconds < 0:
        raise RuntimeConfigError("GPU-free stable seconds must be non-negative")
    if timeout_seconds == 0 and stable_seconds == 0:
        return preflight_gpu_occupancy(config)
    deadline = time.time() + timeout_seconds
    last_error: RuntimeConfigError | None = None
    last_blocked_gpus: list[dict[str, Any]] = []
    first_free_at: float | None = None
    last_result: dict[str, Any] | None = None
    while True:
        try:
            result = preflight_gpu_occupancy(config)
        except RuntimeConfigError as error:
            last_error = error
            if isinstance(error, GpuOccupancyError):
                last_blocked_gpus = list(error.blocked_gpus)
            first_free_at = None
            now = time.time()
            if now >= deadline:
                message = f"GPU-free wait timed out after {timeout_seconds}s: {last_error}"
                if last_blocked_gpus:
                    raise GpuOccupancyError(message, blocked_gpus=last_blocked_gpus) from error
                raise RuntimeConfigError(message) from error
            time.sleep(min(poll_seconds, max(0.0, deadline - now)))
            continue
        now = time.time()
        if first_free_at is None:
            first_free_at = now
        last_result = result
        if stable_seconds == 0 or now - first_free_at >= stable_seconds:
            if stable_seconds:
                return {**last_result, "stable_seconds": stable_seconds}
            return last_result
        if now >= deadline:
            raise RuntimeConfigError(f"GPU-free wait timed out after {timeout_seconds}s: stable window not reached")
        time.sleep(min(poll_seconds, max(0.0, deadline - now)))


def _run_preparation_command(
    config: MaterializedSglangRuntimeConfig,
    inner_command: list[str],
    *,
    run: Any | None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = dict(env or {})
    _ensure_created_bind_sources(config, inner_argv=inner_command, env=command_env)
    command = _rootfs_preparation_argv(config, inner_command, env=command_env)
    if run is None:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=_runtime_subprocess_cwd(config),
            env={**_runtime_subprocess_env(config), **command_env},
        )
    else:
        completed = run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=_runtime_subprocess_cwd(config),
            env={**_runtime_subprocess_env(config), **command_env},
        )
    if completed.returncode != 0:
        raise RuntimeConfigError(f"rootfs command failed: {' '.join(inner_command)}\n{completed.stderr}")
    return completed


def _visible_gpu_indices(cuda_visible_devices: str) -> list[int]:
    indices: list[int] = []
    for item in cuda_visible_devices.split(","):
        value = item.strip()
        if not value:
            continue
        if not value.isdecimal():
            raise RuntimeConfigError("runtime.cuda_visible_devices must be a comma-separated GPU index list")
        indices.append(int(value))
    return indices


_NVIDIA_CONTROL_DEVICE_NAMES = {
    "nvidiactl",
    "nvidia-uvm",
    "nvidia-uvm-tools",
    "nvidia-modeset",
    "nvidia-caps",
}


def _selected_nvidia_device_paths(cuda_visible_devices: str) -> list[Path]:
    visible_indices = _visible_gpu_indices(cuda_visible_devices)
    if not visible_indices:
        raise RuntimeConfigError("runtime.cuda_visible_devices must name at least one GPU")
    selected_names = {f"nvidia{index}" for index in visible_indices}
    allowed_names = selected_names | _NVIDIA_CONTROL_DEVICE_NAMES
    devices = [dev for dev in sorted(Path("/dev").glob("nvidia*"), key=str) if dev.name in allowed_names]
    present_names = {dev.name for dev in devices}
    missing = sorted(selected_names - present_names)
    if missing:
        raise RuntimeConfigError(f"visible GPU device node is missing: /dev/{missing[0]}")
    return devices


def _nvidia_gpu_uuid_by_index() -> dict[int, str]:
    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeConfigError(f"nvidia-smi GPU inventory failed: {completed.stderr.strip()}")
    mapping: dict[int, str] = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",", 1)]
        if len(parts) != 2 or not parts[0].isdecimal() or not parts[1]:
            raise RuntimeConfigError(f"nvidia-smi GPU inventory returned malformed row: {line}")
        mapping[int(parts[0])] = parts[1]
    return mapping


def _nvidia_compute_apps() -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,gpu_uuid,used_memory", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeConfigError(f"nvidia-smi compute-app query failed: {completed.stderr.strip()}")
    apps: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",", 3)]
        if len(parts) != 4 or not parts[0].isdecimal() or not parts[2]:
            raise RuntimeConfigError(f"nvidia-smi compute-app query returned malformed row: {line}")
        used_memory = parts[3]
        if used_memory.endswith(" MiB"):
            used_memory = used_memory.removesuffix(" MiB").strip()
        apps.append(
            {
                "pid": int(parts[0]),
                "process_name": parts[1],
                "gpu_uuid": parts[2],
                "used_memory": used_memory,
            }
        )
    return apps


def _rootfs_preparation_argv(
    config: MaterializedSglangRuntimeConfig,
    inner_command: list[str],
    *,
    env: dict[str, str],
    emit_plan_path: Path | None = None,
) -> list[str]:
    outer = _resolved_outer_argv(config)
    try:
        marker = outer.index("--")
    except ValueError as error:
        raise RuntimeConfigError("launch.outer_argv must contain -- before inner argv") from error
    if emit_plan_path is not None:
        try:
            emit_index = outer.index("--emit-plan")
        except ValueError as error:
            raise RuntimeConfigError("launch.outer_argv must include --emit-plan") from error
        outer = list(outer)
        outer[emit_index + 1] = str(emit_plan_path)
    return outer[: marker + 1] + inner_command


def _preparation_record_path(config: MaterializedSglangRuntimeConfig, name: str) -> Path:
    preparation = _require_mapping(config.resolved_paths.get("preparation"), "resolved_paths.preparation")
    return Path(_required_section_str(preparation, name, "resolved_paths.preparation"))


def _preparation_plan_path_for_record(config: MaterializedSglangRuntimeConfig, name: str) -> Path:
    return _preparation_record_path(config, name).parent / "sandbox" / f"{name}-bwrap-plan.yaml"


def _preparation_config_for_record(
    config: MaterializedSglangRuntimeConfig,
    name: str,
) -> MaterializedSglangRuntimeConfig:
    record_path = _preparation_record_path(config, name)
    run_id = record_path.parent.name
    host_layout = dict(config.host_layout)
    results_root = _required_section_str(host_layout, "results_root", "host_layout")
    host_layout["run_dir"] = f"{results_root.rstrip('/')}/{run_id}"
    host_layout["tmp_dir"] = f"temp://{run_id}"
    sandbox = dict(config.sandbox)
    mounts = sandbox.get("mounts")
    if not isinstance(mounts, list):
        raise RuntimeConfigError("sandbox.mounts must be a list")
    sandbox["mounts"] = [
        {
            **mount,
            "host_path_ref": "run://" if mount.get("sandbox_path") == "/run/glm52" else f"temp://{run_id}" if mount.get("sandbox_path") == "/tmp/glm52" else mount["host_path_ref"],
        }
        for mount in mounts
        if isinstance(mount, dict)
    ]
    artifacts = dict(config.artifacts)
    if "preparation" in artifacts:
        artifacts = {**artifacts, "preparation": dict(_require_mapping(artifacts["preparation"], "artifacts.preparation"))}
    resolved_paths = dict(config.resolved_paths)
    preparation = dict(_require_mapping(resolved_paths.get("preparation"), "resolved_paths.preparation"))
    preparation[name] = str(record_path)
    resolved_paths["preparation"] = preparation
    return MaterializedSglangRuntimeConfig(
        schema_version=config.schema_version,
        run_id=run_id,
        run_group=config.run_group,
        fail_fast=config.fail_fast,
        allow_fallback=config.allow_fallback,
        service=config.service,
        model=config.model,
        runtime=config.runtime,
        observability=config.observability,
        host_layout=host_layout,
        sandbox=sandbox,
        launch=config.launch,
        probes=config.probes,
        artifacts=artifacts,
        resolved_paths=resolved_paths,
    )


def _load_preparation_record(config: MaterializedSglangRuntimeConfig, name: str, missing_message: str) -> dict[str, Any]:
    path = _preparation_record_path(config, name)
    if not path.exists():
        raise RuntimeConfigError(f"{missing_message}: {path}")
    try:
        return _load_json_mapping(path)
    except json.JSONDecodeError as error:
        raise RuntimeConfigError(f"malformed preparation record: {path}") from error


def _rootfs_recipe_digest(config: MaterializedSglangRuntimeConfig) -> str:
    return hashlib.sha256(_resolved_rootfs_path(config).encode("utf-8")).hexdigest()


def _sglang_venv_prepare_command() -> list[str]:
    return [
        "uv",
        "venv",
        SGLANG_VENV_SANDBOX_PATH,
        "--python",
        "3.12",
        "--clear",
    ]


def _model_cache_prepare_command(config: MaterializedSglangRuntimeConfig) -> list[str]:
    return [SGLANG_VENV_PYTHON, "-c", MODEL_CACHE_PREPARE_SCRIPT, config.model["path"]]


def _model_cache_prepare_env() -> dict[str, str]:
    return {
        "HF_HOME": SGLANG_HF_HOME_SANDBOX_PATH,
        "TRANSFORMERS_CACHE": SGLANG_HF_HOME_SANDBOX_PATH,
    }


def _preparation_plan_evidence(
    config: MaterializedSglangRuntimeConfig,
    name: str,
    inner_command: list[str],
    *,
    run: Any | None = None,
    env: dict[str, str] | None = None,
    plan_emitter: Any | None = None,
) -> dict[str, Any]:
    if plan_emitter is None:
        plan = _emit_preparation_rootfs_plan(config, inner_command, run=run, env=env)
    else:
        plan = plan_emitter(config, inner_command, env=env)
    validate_sglang_rootfs_overlay(config=config, plan=plan, expected_inner_argv=inner_command)
    plan_path = _preparation_plan_path_for_record(config, name)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))
    return {
        "plan_sha256": _stable_json_digest(plan),
    }


def _preparation_plan_digest(config: MaterializedSglangRuntimeConfig) -> str:
    return _stable_json_digest(_preparation_plan(config))


def _preparation_plan_digest_for(
    config: MaterializedSglangRuntimeConfig,
    inner_command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> str:
    plan = _preparation_plan(config)
    plan["inner_argv"] = list(inner_command)
    plan["env"] = {**dict(config.launch["env"]), **dict(env or {})}
    return _stable_json_digest(plan)


def _validate_preparation_record_plan(
    config: MaterializedSglangRuntimeConfig,
    name: str,
    record: dict[str, Any],
    inner_command: list[str],
    *,
    env: dict[str, str] | None,
) -> None:
    bwrap_plan = _require_mapping(record.get("bwrap_plan"), f"{name} preparation record bwrap_plan")
    recorded_digest = _required_section_str(bwrap_plan, "plan_sha256", f"{name} preparation record bwrap_plan")
    plan_path = _preparation_plan_path_for_record(config, name)
    if not plan_path.exists():
        raise RuntimeConfigError(f"{name} preparation record missing emitted bwrap plan: {plan_path}")
    plan = load_yaml_mapping(plan_path)
    validate_sglang_rootfs_overlay(config=config, plan=plan, expected_inner_argv=inner_command)
    expected_env = {**dict(config.launch["env"]), **dict(env or {})}
    plan_env = _require_mapping(plan.get("env"), "preparation bwrap plan env")
    for key, value in expected_env.items():
        if plan_env.get(key) != value:
            raise RuntimeConfigError(f"{name} preparation bwrap plan env mismatch: {key}")
    if _stable_json_digest(plan) != recorded_digest:
        raise RuntimeConfigError(f"{name} preparation record bwrap plan digest mismatch")


def _emit_preparation_rootfs_plan(
    config: MaterializedSglangRuntimeConfig,
    inner_command: list[str],
    *,
    run: Any | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _emit_insula_rootfs_plan(config, inner_argv=inner_command, env=env)


def _preparation_plan_path(config: MaterializedSglangRuntimeConfig) -> Path:
    run_dir = _required_section_str(config.host_layout, "run_dir", "host_layout")
    return Path(_resolve_host_path_ref(config, run_dir)) / "sandbox" / "preparation-bwrap-plan.yaml"


def _preparation_plan(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "rootfs": _resolved_rootfs_path(config),
        "cwd": config.sandbox["cwd"],
        "inner_argv": config.launch["inner_argv"],
        "repo_projection_mode": "ro",
        "network": "share-net",
        "gpu": "dev-bind-nvidia-when-present",
        "env_allowlist": list(config.sandbox["env_allowlist"]),
        "env": dict(config.launch["env"]),
        "mounts": [
            {
                "host_path": _resolve_host_path_ref(config, mount["host_path_ref"]),
                "sandbox_path": mount["sandbox_path"],
                "mode": mount["mode"],
            }
            for mount in config.sandbox["mounts"]
        ],
    }


def _emit_insula_rootfs_plan(
    config: MaterializedSglangRuntimeConfig,
    *,
    inner_argv: list[str] | None = None,
    env: dict[str, str] | None = None,
    resolved_plan_path: Path | None = None,
) -> dict[str, Any]:
    _ensure_created_bind_sources(config, inner_argv=inner_argv, env=env)
    invocation = _materialized_insula_invocation_for(config, inner_argv=inner_argv, env=env)
    insula_plan = emit_insula_plan(invocation)
    try:
        validate_insula_plan(invocation, insula_plan)
    except InsulaConfigError as error:
        raise RuntimeConfigError(f"Insula rootfs plan validation failed: {error}") from error
    plan = _legacy_rootfs_plan_from_insula(config=config, insula_plan=insula_plan)
    validate_sglang_rootfs_overlay(
        config=config,
        plan=plan,
        expected_inner_argv=list(inner_argv) if inner_argv is not None else None,
    )
    if resolved_plan_path is not None:
        resolved_plan_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))
    return plan


def _legacy_rootfs_plan_from_insula(
    *,
    config: MaterializedSglangRuntimeConfig,
    insula_plan: Any,
) -> dict[str, Any]:
    return {
        "schema_version": insula_plan.schema_version,
        "rootfs": insula_plan.rootfs_path,
        "cwd": insula_plan.cwd,
        "inner_argv": list(insula_plan.command_argv),
        "repo_projection_mode": _insula_repo_projection_mode(insula_plan),
        "network": insula_plan.network,
        "gpu": _legacy_gpu_mode(str(insula_plan.gpu)),
        "env_allowlist": list(config.sandbox["env_allowlist"]),
        "env": dict(insula_plan.env),
        "mounts": [
            {
                "host_path": _required_section_str(mount, "host", "insula_plan.mounts"),
                "sandbox_path": _required_section_str(mount, "sandbox", "insula_plan.mounts"),
                "mode": _required_section_str(mount, "mode", "insula_plan.mounts"),
            }
            for mount in insula_plan.mounts
            if mount.get("sandbox") != "/"
        ],
        "insula": {
            "invocation_id": insula_plan.invocation_id,
            "recipe_sha256": insula_plan.recipe_sha256,
            "bwrap_argv_sha256": insula_plan.bwrap_argv_sha256,
        },
    }


def _insula_repo_projection_mode(insula_plan: Any) -> str:
    repo_mounts = [mount for mount in insula_plan.mounts if mount.get("sandbox") == "/workspace/monarch"]
    if len(repo_mounts) != 1:
        raise RuntimeConfigError("Insula rootfs plan must contain one repo projection")
    return _required_section_str(repo_mounts[0], "mode", "insula_plan.repo_mount")


def _legacy_gpu_mode(gpu: str) -> str:
    if gpu == "nvidia-if-present":
        return "dev-bind-nvidia-when-present"
    return gpu


def _stable_json_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _snapshot_shard_count(snapshot_evidence: dict[str, Any]) -> int:
    if "shard_count" in snapshot_evidence:
        return _required_section_int(snapshot_evidence, "shard_count", "model_snapshot")
    if "referenced_shard_count" in snapshot_evidence:
        return _required_section_int(snapshot_evidence, "referenced_shard_count", "model_snapshot")
    raise RuntimeConfigError("model_snapshot.shard_count is required")


def _is_under_sandbox_path(value: str, root: str) -> bool:
    return value == root or value.startswith(f"{root.rstrip('/')}/")


def _run_in_runtime_rootfs(
    config: MaterializedSglangRuntimeConfig,
    inner_command: list[str],
) -> subprocess.CompletedProcess[str]:
    outer = _resolved_outer_argv(config)
    try:
        marker = outer.index("--")
    except ValueError as error:
        raise RuntimeConfigError("launch.outer_argv must contain -- before inner argv") from error
    command = outer[: marker + 1] + inner_command
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=_runtime_subprocess_cwd(config),
        env=_runtime_subprocess_env(config),
    )
    if completed.returncode != 0:
        raise RuntimeConfigError(f"rootfs command failed: {' '.join(inner_command)}\n{completed.stderr}")
    return completed


def _parse_prepare_versions(stdout: str) -> dict[str, Any]:
    try:
        versions = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeConfigError("SGLang venv version probe did not emit JSON") from error
    return _require_mapping(versions, "sglang prepare version probe")


def _parse_offloader_patch_output(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeConfigError("SGLang offloader patch command did not emit JSON") from error
    return _require_mapping(payload, "SGLang offloader patch evidence")


def _parse_model_cache_prepare_output(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeConfigError("model cache prepare command did not emit JSON") from error
    return _require_mapping(payload, "model cache prepare output")


def _runtime_subprocess_env(config: MaterializedSglangRuntimeConfig) -> dict[str, str]:
    return {
        **dict(_require_mapping(config.launch.get("env"), "launch.env")),
        "UV_CACHE_DIR": "/cache/glm52/uv",
        "XDG_CACHE_HOME": "/cache/glm52/xdg",
        "TORCHINDUCTOR_CACHE_DIR": "/cache/glm52/torchinductor",
        "TRITON_CACHE_DIR": "/cache/glm52/triton",
        "USER": "monarch",
        "LOGNAME": "monarch",
    }


def _runtime_subprocess_cwd(config: MaterializedSglangRuntimeConfig) -> str:
    if os.environ.get("MONARCH_IN_ROOTFS") == "1":
        return _required_section_str(config.sandbox, "cwd", "sandbox")
    return _required_section_str(config.resolved_paths, "repo", "resolved_paths")


def emit_and_load_rootfs_plan(
    config: MaterializedSglangRuntimeConfig,
    *,
    resolved_plan_path: Path,
) -> dict[str, Any]:
    return _emit_insula_rootfs_plan(config, resolved_plan_path=resolved_plan_path)


def wait_for_models_probe(
    config: MaterializedSglangRuntimeConfig,
    *,
    process: Any | None = None,
) -> dict[str, Any]:
    timeout_seconds = int(config.probes.get("startup_timeout_seconds", 900))
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(_required_section_str(config.probes, "models_url", "probes"), timeout=5) as response:
                body = response.read()
            return parse_models_response(
                body,
                expected_model_ids=list(config.service["expected_model_ids"]),
                served_model_name=str(config.model["served_model_name"]),
            )
        except Exception as error:
            last_error = error
            if process is not None:
                returncode = process.poll()
                if returncode is not None:
                    raise RuntimeConfigError(
                        f"SGLang process exited before /v1/models became ready: returncode={returncode}; last_error={last_error}"
                    )
            _raise_for_fatal_startup_log(config)
            time.sleep(2)
    raise RuntimeConfigError(f"models probe timed out: {last_error}")


def probe_models(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    url = f"http://{config.service['bind_host']}:{config.service['port']}/v1/models"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read()
    return parse_models_response(
        body,
        expected_model_ids=config.model["expected_model_ids"],
        served_model_name=config.model["served_model_name"],
    )


def probe_generate(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    timeout_seconds = _required_section_int(config.probes, "chat_timeout_seconds", "probes")
    request = urllib.request.Request(
        _required_section_str(config.probes, "generate_url", "probes"),
        data=json.dumps(config.probes["generate_payload"]).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", response.getcode())
            body = response.read()
    except (TimeoutError, socket.timeout) as error:
        raise RuntimeLaunchError(f"generate probe timed out after {timeout_seconds}s") from error
    if status != 200:
        raise RuntimeLaunchError(f"generate probe returned HTTP {status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeLaunchError("invalid /generate JSON") from error
    content = _generate_content(payload)
    if not content:
        raise RuntimeLaunchError("generate probe returned empty text")
    return {"content": content, "payload": payload}


def probe_completion(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    timeout_seconds = _required_section_int(config.probes, "chat_timeout_seconds", "probes")
    request = urllib.request.Request(
        _required_section_str(config.probes, "completions_url", "probes"),
        data=json.dumps(config.probes["completion_payload"]).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", response.getcode())
            body = response.read()
    except (TimeoutError, socket.timeout) as error:
        raise RuntimeLaunchError(f"completion probe timed out after {timeout_seconds}s") from error
    if status != 200:
        raise RuntimeLaunchError(f"completion probe returned HTTP {status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeLaunchError("invalid /v1/completions JSON") from error
    content = _completion_content(payload)
    if not content:
        raise RuntimeLaunchError("completion probe returned empty text")
    return {"content": content, "payload": payload}


def probe_chat(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    timeout_seconds = _required_section_int(config.probes, "chat_timeout_seconds", "probes")
    request = urllib.request.Request(
        _required_section_str(config.probes, "chat_url", "probes"),
        data=json.dumps(config.probes["chat_payload"]).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", response.getcode())
            body = response.read()
    except (TimeoutError, socket.timeout) as error:
        raise RuntimeLaunchError(f"chat probe timed out after {timeout_seconds}s") from error
    if status != 200:
        raise RuntimeLaunchError(f"chat probe returned HTTP {status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeLaunchError("invalid /v1/chat/completions JSON") from error
    content = _chat_completion_content(payload)
    if not content:
        raise RuntimeLaunchError("chat probe returned empty assistant content")
    return {"content": content, "payload": payload}


def terminate_process(process: Any) -> None:
    try:
        process_group = os.getpgid(process.pid)
        os.killpg(process_group, signal.SIGTERM)
    except (AttributeError, OSError):
        process.terminate()
    process.wait(timeout=30)


def launch_runtime(
    config: MaterializedSglangRuntimeConfig,
    *,
    local_environment: LocalEnvironmentConfig | None = None,
) -> dict[str, Any]:
    validate_materialized_config(config)
    if local_environment is not None:
        _validate_local_environment_matches_config(config, local_environment)
    artifact_paths = _resolve_artifact_paths(config)
    _ensure_artifact_dirs(artifact_paths)

    artifact_paths["resolved_local_paths"].write_text(yaml.safe_dump(_resolved_local_paths(config), sort_keys=False))
    write_materialized_config(config, artifact_paths["materialized_config"])
    artifact_paths["telemetry_log"].touch()

    process = None
    process_record_written = False
    try:
        help_text = run_sglang_help_preflight(config)
        artifact_paths["sglang_cli_help"].write_text(help_text)
        rootfs_plan = emit_and_load_rootfs_plan(
            config,
            resolved_plan_path=artifact_paths["resolved_rootfs_plan"],
        )
        artifact_paths["resolved_rootfs_plan"].write_text(yaml.safe_dump(rootfs_plan, sort_keys=False))
        model_cache_record = preflight_model_cache(config)
        config = _with_prepared_model_snapshot(config, model_cache_record)
        validate_materialized_config(config)
        artifact_paths = _resolve_artifact_paths(config)
        write_materialized_config(config, artifact_paths["materialized_config"])
        preflight_gpu_occupancy(config)
        _ensure_created_bind_sources(config)
        with artifact_paths["stdout_log"].open("ab") as stdout_handle, artifact_paths["stderr_log"].open("ab") as stderr_handle:
            process = subprocess.Popen(
                _resolved_outer_argv(config),
                cwd=_runtime_subprocess_cwd(config),
                env=_runtime_subprocess_env(config),
                start_new_session=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
            )
            process_record = _process_record(config, process)
            _write_yaml(artifact_paths["process_record"], process_record)
            process_record_written = True
            models_probe = wait_for_models_probe(config, process=process)
            _write_json(artifact_paths["models_probe"], models_probe)
            generate_probe = probe_generate(config)
            _write_json(artifact_paths["generate_probe"], generate_probe)
            completion_probe = probe_completion(config)
            _write_json(artifact_paths["completion_probe"], completion_probe)
            chat_probe = probe_chat(config)
            _write_json(artifact_paths["chat_probe"], chat_probe)
            summary = {
                "status": "launch_passed",
                "run_id": config.run_id,
                "pid": process_record["pid"],
                "process_group": process_record["process_group"],
                "port": config.service["port"],
            }
            _write_json(artifact_paths["launch_summary"], summary)
            return summary
    except Exception as error:
        teardown_action = "not_started"
        diagnostic_action: dict[str, Any] = {"status": "not_sent", "reason": "process_not_started"}
        if process_record_written and should_teardown_after_failure(config):
            diagnostic_action = emit_failure_diagnostic_signal(config, reason="probe_failure")
            teardown_action = "teardown_runtime"
            try:
                teardown_runtime(config, local_environment=local_environment)
            except Exception as teardown_error:
                teardown_action = f"teardown_failed: {teardown_error}"
        elif process is not None and should_teardown_after_failure(config):
            if process.poll() is None:
                teardown_action = "terminate_process"
                try:
                    terminate_process(process)
                except Exception as teardown_error:
                    teardown_action = f"terminate_failed: {teardown_error}"
            else:
                teardown_action = "already_exited"
        elif process is not None:
            teardown_action = "left_running_debug"
        _write_json(
            artifact_paths["launch_summary"],
            {
                "status": "launch_failed",
                "run_id": config.run_id,
                "port": config.service["port"],
                "error": str(error),
                "diagnostic_action": diagnostic_action,
                "teardown_action": teardown_action,
            },
        )
        if isinstance(error, RuntimeConfigError):
            raise
        raise RuntimeLaunchError(str(error)) from error


def teardown_runtime(
    config: MaterializedSglangRuntimeConfig,
    *,
    local_environment: LocalEnvironmentConfig | None = None,
) -> dict[str, Any]:
    validate_materialized_config(config)
    if local_environment is not None:
        _validate_local_environment_matches_config(config, local_environment)
    artifact_paths = _resolve_artifact_paths(config)
    _ensure_artifact_dirs({"teardown_summary": artifact_paths["teardown_summary"]})

    process_record_path = artifact_paths["process_record"]
    if not process_record_path.exists():
        if artifact_paths["teardown_summary"].exists():
            summary = _load_json_mapping(artifact_paths["teardown_summary"])
            if summary.get("status") in {"teardown_passed", "already_stopped"}:
                return {"status": "already_stopped", "run_id": config.run_id}
        raise RuntimeConfigError("cannot teardown without process record")

    record = load_yaml_mapping(process_record_path)
    _validate_process_record_matches_config(config, record)
    if record.get("status") == "stopped":
        summary = {"status": "already_stopped", "run_id": config.run_id, "port": config.service["port"]}
        _write_json(artifact_paths["teardown_summary"], summary)
        return summary

    process_group = _required_int(record, "process_group", "process_record")
    port = _required_section_int(config.service, "port", "service")
    _validate_live_process_command_guard(record, port)
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        if not _is_port_open(_required_section_str(config.service, "bind_host", "service"), port):
            summary = {"status": "already_stopped", "run_id": config.run_id, "port": port}
            _mark_process_stopped(process_record_path, record, "process_group_absent")
            _write_json(artifact_paths["teardown_summary"], summary)
            return summary
        raise RuntimeConfigError("cannot prove ownership of live port after recorded process group disappeared")
    except PermissionError as error:
        raise RuntimeConfigError("cannot terminate recorded process group") from error

    deadline = time.time() + 30
    while time.time() < deadline:
        if _process_group_is_released(process_group) and not _is_port_open(
            _required_section_str(config.service, "bind_host", "service"),
            port,
        ):
            _mark_process_stopped(process_record_path, record, "terminated")
            summary = {"status": "teardown_passed", "run_id": config.run_id, "port": port}
            _write_json(artifact_paths["teardown_summary"], summary)
            return summary
        time.sleep(0.5)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if _process_group_is_released(process_group) and not _is_port_open(
        _required_section_str(config.service, "bind_host", "service"),
        port,
    ):
        _mark_process_stopped(process_record_path, record, "killed")
        summary = {"status": "teardown_passed", "run_id": config.run_id, "port": port, "escalated": True}
        _write_json(artifact_paths["teardown_summary"], summary)
        return summary
    deadline = time.time() + 10
    while time.time() < deadline:
        if _process_group_is_released(process_group) and not _is_port_open(
            _required_section_str(config.service, "bind_host", "service"),
            port,
        ):
            _mark_process_stopped(process_record_path, record, "killed")
            summary = {"status": "teardown_passed", "run_id": config.run_id, "port": port, "escalated": True}
            _write_json(artifact_paths["teardown_summary"], summary)
            return summary
        time.sleep(0.5)
    raise RuntimeConfigError("teardown timed out waiting for recorded process group and port release")


def emit_failure_diagnostic_signal(config: MaterializedSglangRuntimeConfig, *, reason: str) -> dict[str, Any]:
    artifact_paths = _resolve_artifact_paths(config)
    process_record_path = artifact_paths["process_record"]
    if not process_record_path.exists():
        return {"status": "not_sent", "reason": "missing_process_record"}
    record = load_yaml_mapping(process_record_path)
    _validate_process_record_matches_config(config, record)
    process_group = _required_int(record, "process_group", "process_record")
    try:
        os.killpg(process_group, signal.SIGQUIT)
    except ProcessLookupError:
        return {
            "status": "not_sent",
            "reason": "process_group_absent",
            "signal": "SIGQUIT",
            "process_group": process_group,
        }
    except PermissionError as error:
        raise RuntimeConfigError("cannot signal recorded process group for diagnostics") from error
    flush_wait_seconds = 6
    time.sleep(flush_wait_seconds)
    crash_dump_inventory = _crash_dump_inventory(config)
    return {
        "status": "sent",
        "signal": "SIGQUIT",
        "process_group": process_group,
        "reason": reason,
        "flush_wait_seconds": flush_wait_seconds,
        **crash_dump_inventory,
    }


def run_one_cycle(
    *,
    config: MaterializedSglangRuntimeConfig,
    launch: Any | None = None,
    probe: Any | None = None,
    teardown: Any | None = None,
    local_environment: LocalEnvironmentConfig | None = None,
) -> dict[str, Any]:
    validate_materialized_config(config)
    model_cache_record = preflight_model_cache(config)
    config = _with_prepared_model_snapshot(config, model_cache_record)
    launch_fn = launch or (lambda cycle_config: launch_runtime(cycle_config, local_environment=local_environment))
    probe_fn = probe or (lambda _cycle_config: None)
    teardown_fn = teardown or (lambda _record: teardown_runtime(config, local_environment=local_environment))

    process_record: Any | None = None
    try:
        process_record = launch_fn(config)
        probe_result = probe_fn(config)
    except Exception:
        if process_record is not None and should_teardown_after_failure(config):
            teardown_fn(process_record)
        raise

    teardown_result = teardown_fn(process_record)
    return {
        "ok": True,
        "port": config.service["port"],
        "launch": _record_to_mapping(process_record),
        "probe": probe_result,
        "teardown": teardown_result,
    }


def run_repeatability_cycles(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str = "glm52-sglang-repeatability",
    cycles: int | None = None,
    run_one_cycle: Any | None = None,
    preparation_validator: Any | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    declared = load_declared_spec(declared_path)
    local_environment = load_local_environment(local_environment_path)
    cycle_count = cycles if cycles is not None else declared.repeatability.cycles
    if cycle_count < 1:
        raise RuntimeConfigError("repeatability cycles must be positive")

    run_dir = Path(_resolve_local_path_ref(local_environment, declared.local_paths.results_root)) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "repeatability-summary.json"
    selected_ports: set[int] = set()
    cycle_summaries: list[dict[str, Any]] = []
    cycle_runner = run_one_cycle or globals()["run_one_cycle"]

    for cycle_index in range(1, cycle_count + 1):
        port = _allocate_run_owned_port(declared.port_policy, selected_ports)
        selected_ports.add(port)
        config = materialize_runtime_config(
            declared=declared,
            local_environment=local_environment,
            run_id=f"{run_id}-cycle-{cycle_index}",
            port=port,
        )
        config = _with_stable_preparation_record_paths(
            config,
            declared=declared,
            local_environment=local_environment,
        )
        write_materialized_config(
            config,
            Path(_resolve_host_path_ref(config, config.artifacts["materialized_config"])),
        )
        try:
            if dry_run:
                result = {"ok": True, "port": port}
            else:
                validator = preparation_validator or validate_preparation_records
                validator(config=config)
                result = cycle_runner(config)
            ok = bool(_require_mapping(result, "repeatability cycle result").get("ok"))
            if not ok:
                raise RuntimeConfigError(f"repeatability cycle {cycle_index} returned ok=false")
        except Exception as error:
            cycle_summaries.append({"cycle": cycle_index, "ok": False, "port": port, "error": str(error)})
            summary = _write_repeatability_summary(summary_path, run_id=run_id, ok=False, cycles=cycle_summaries)
            raise RuntimeConfigError(f"repeatability cycle {cycle_index} failed: {error}") from error
        cycle_summaries.append({"cycle": cycle_index, "ok": ok, "port": port})

    return _write_repeatability_summary(summary_path, run_id=run_id, ok=all(cycle["ok"] for cycle in cycle_summaries), cycles=cycle_summaries)


def repeat_runtime(
    *,
    declared: DeclaredSglangLaunchSpec,
    local_environment: LocalEnvironmentConfig,
    cycles: int | None,
    wait_for_gpu_free_seconds: int = 0,
    gpu_free_stable_seconds: int = 0,
) -> dict[str, Any]:
    cycle_count = cycles if cycles is not None else declared.repeatability.cycles
    if cycle_count < 1:
        raise RuntimeConfigError("repeat cycles must be positive")
    if wait_for_gpu_free_seconds < 0:
        raise RuntimeConfigError("GPU-free wait seconds must be non-negative")
    if gpu_free_stable_seconds < 0:
        raise RuntimeConfigError("GPU-free stable seconds must be non-negative")
    if gpu_free_stable_seconds and wait_for_gpu_free_seconds < gpu_free_stable_seconds:
        raise RuntimeConfigError("GPU-free wait seconds must be at least stable seconds")

    repeat_id = f"{declared.run_group}-repeat-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    repeat_dir = Path(_resolve_local_path_ref(local_environment, declared.local_paths.results_root)) / repeat_id
    repeat_dir.mkdir(parents=True, exist_ok=False)
    loop_summary_path = repeat_dir / "loop-summary.json"
    used_ports: set[int] = set()
    summaries: list[dict[str, Any]] = []

    for cycle_index in range(1, cycle_count + 1):
        port = _select_repeat_port(declared.port_policy, used_ports)
        used_ports.add(port)
        run_id = f"{declared.run_group}-{_utc_stamp()}-{cycle_index}-{uuid.uuid4().hex[:8]}"
        config = materialize_runtime_config(
            declared=declared,
            local_environment=local_environment,
            run_id=run_id,
            port=port,
        )
        config = _with_stable_preparation_record_paths(
            config,
            declared=declared,
            local_environment=local_environment,
        )
        write_materialized_config(
            config,
            Path(_resolve_host_path_ref(config, config.artifacts["materialized_config"])),
        )

        cycle_summary: dict[str, Any] = {
            "cycle": cycle_index,
            "run_id": run_id,
            "port": port,
        }
        if wait_for_gpu_free_seconds:
            try:
                cycle_summary["gpu_wait"] = wait_for_gpu_free_window(
                    config,
                    timeout_seconds=wait_for_gpu_free_seconds,
                    stable_seconds=gpu_free_stable_seconds,
                )
            except Exception as wait_error:
                cycle_summary["gpu_wait"] = {
                    "status": "failed",
                    "error": str(wait_error),
                }
                if isinstance(wait_error, GpuOccupancyError):
                    cycle_summary["gpu_wait"]["blocked_gpus"] = wait_error.blocked_gpus
                summaries.append(cycle_summary)
                _write_repeat_summary(
                    loop_summary_path,
                    repeat_id=repeat_id,
                    status="failed",
                    cycles=summaries,
                )
                raise RuntimeConfigError(f"repeat cycle GPU-free wait failed: {wait_error}") from wait_error
        try:
            cycle_summary["launch"] = launch_runtime(config, local_environment=local_environment)
        except Exception as launch_error:
            cycle_summary["launch"] = {
                "status": "failed",
                "error": str(launch_error),
            }
            if isinstance(launch_error, GpuOccupancyError):
                cycle_summary["launch"]["blocked_gpus"] = launch_error.blocked_gpus
            cycle_summary["teardown"] = _repeat_launch_failure_teardown(config, local_environment)
            summaries.append(cycle_summary)
            _write_repeat_summary(
                loop_summary_path,
                repeat_id=repeat_id,
                status="failed",
                cycles=summaries,
            )
            raise RuntimeConfigError(f"repeat cycle failed: {launch_error}") from launch_error

        try:
            cycle_summary["teardown"] = _best_effort_teardown(config, local_environment)
        except Exception as teardown_error:
            cycle_summary["teardown"] = {
                "status": "failed",
                "error": str(teardown_error),
            }
            summaries.append(cycle_summary)
            _write_repeat_summary(
                loop_summary_path,
                repeat_id=repeat_id,
                status="failed",
                cycles=summaries,
            )
            raise RuntimeConfigError(f"repeat cycle teardown failed: {teardown_error}") from teardown_error

        summaries.append(cycle_summary)

    summary = _write_repeat_summary(
        loop_summary_path,
        repeat_id=repeat_id,
        status="passed",
        cycles=summaries,
    )
    return summary


def write_materialized_config(config: MaterializedSglangRuntimeConfig, path: Path) -> None:
    validate_materialized_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_config_to_mapping(config), sort_keys=False))


def load_materialized_config(path: Path) -> MaterializedSglangRuntimeConfig:
    mapping = load_yaml_mapping(path)
    _reject_unknown(
        mapping,
        {
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
        },
        "materialized",
    )
    config = MaterializedSglangRuntimeConfig(
        schema_version=_required_int(mapping, "schema_version", "materialized"),
        run_id=_required_str(mapping, "run_id", "materialized"),
        run_group=_required_str(mapping, "run_group", "materialized"),
        fail_fast=_required_bool(mapping, "fail_fast", "materialized"),
        allow_fallback=_required_bool(mapping, "allow_fallback", "materialized"),
        service=dict(_require_mapping(mapping.get("service"), "materialized.service")),
        model=dict(_require_mapping(mapping.get("model"), "materialized.model")),
        runtime=dict(_require_mapping(mapping.get("runtime"), "materialized.runtime")),
        observability=dict(_require_mapping(mapping.get("observability"), "materialized.observability")),
        host_layout=dict(_require_mapping(mapping.get("host_layout"), "materialized.host_layout")),
        sandbox=dict(_require_mapping(mapping.get("sandbox"), "materialized.sandbox")),
        launch=dict(_require_mapping(mapping.get("launch"), "materialized.launch")),
        probes=dict(_require_mapping(mapping.get("probes"), "materialized.probes")),
        artifacts=dict(_require_mapping(mapping.get("artifacts"), "materialized.artifacts")),
        resolved_paths=dict(_require_mapping(mapping.get("resolved_paths"), "materialized.resolved_paths")),
    )
    validate_materialized_config(config)
    return config


def _absolute_host_path(value: str, path: str) -> str:
    if not value.startswith("/"):
        raise RuntimeConfigError(f"{path} must be an absolute host path")
    return value


def _join_host_path(root: str, suffix: str) -> str:
    suffix = suffix.lstrip("/")
    if not suffix:
        return root
    return f"{root.rstrip('/')}/{suffix}"


def _resolve_local_path_ref(local_environment: LocalEnvironmentConfig, ref: str) -> str:
    if ref == "repo://":
        return local_environment.repo
    if ref.startswith("repo://"):
        return _join_host_path(local_environment.repo, ref.removeprefix("repo://"))
    if ref.startswith("cache://"):
        return _join_host_path(local_environment.cache, ref.removeprefix("cache://"))
    if ref.startswith("temp://"):
        return _join_host_path(local_environment.temp, ref.removeprefix("temp://"))
    raise RuntimeConfigError(f"unsupported local path ref: {ref}")


def _resolve_host_path_ref(config: MaterializedSglangRuntimeConfig, ref: str) -> str:
    resolved_paths = _require_mapping(config.resolved_paths, "materialized.resolved_paths")
    if ref == "repo://":
        return _required_section_str(resolved_paths, "repo", "resolved_paths")
    if ref.startswith("repo://"):
        return _join_host_path(_required_section_str(resolved_paths, "repo", "resolved_paths"), ref.removeprefix("repo://"))
    if ref.startswith("run://"):
        run_dir = _required_section_str(config.host_layout, "run_dir", "host_layout")
        if not run_dir.startswith("repo://"):
            raise RuntimeConfigError("host_layout.run_dir must use repo://")
        return _join_host_path(_resolve_host_path_ref(config, run_dir), ref.removeprefix("run://"))
    if ref.startswith("temp://"):
        return _join_host_path(_required_section_str(resolved_paths, "temp", "resolved_paths"), ref.removeprefix("temp://"))
    if ref.startswith("cache://"):
        return _join_host_path(_required_section_str(resolved_paths, "cache", "resolved_paths"), ref.removeprefix("cache://"))
    raise RuntimeConfigError(f"unsupported host path ref: {ref}")


def _host_path_from_run_sandbox_path(config: MaterializedSglangRuntimeConfig, sandbox_path: str) -> str:
    if not sandbox_path.startswith("/run/glm52/"):
        raise RuntimeConfigError(f"run artifact path must be under /run/glm52: {sandbox_path}")
    return _resolve_host_path_ref(config, f"run://{sandbox_path.removeprefix('/run/glm52/')}")


def _crash_dump_inventory(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    crash_dump_folder = _required_section_str(config.observability, "crash_dump_folder", "observability")
    crash_dump_host_path = Path(_host_path_from_run_sandbox_path(config, crash_dump_folder))
    files: list[str] = []
    if crash_dump_host_path.exists():
        for path in sorted(crash_dump_host_path.rglob("*")):
            if path.is_file():
                files.append(path.relative_to(crash_dump_host_path).as_posix())
    return {
        "crash_dump_folder": crash_dump_folder,
        "crash_dump_host_path": str(crash_dump_host_path),
        "crash_dump_files": files,
    }


def _model_cache_evidence_path(config: MaterializedSglangRuntimeConfig) -> Path:
    cache_dir = _required_section_str(config.host_layout, "cache_dir", "host_layout")
    return Path(_resolve_host_path_ref(config, cache_dir)) / "model-cache-prepare.json"


def _host_path_from_cache_sandbox_path(config: MaterializedSglangRuntimeConfig, sandbox_path: str) -> str:
    if not sandbox_path.startswith("/cache/glm52/"):
        raise RuntimeConfigError(f"model cache path must be under /cache/glm52: {sandbox_path}")
    cache_dir = _required_section_str(config.host_layout, "cache_dir", "host_layout")
    return _join_host_path(_resolve_host_path_ref(config, cache_dir), sandbox_path.removeprefix("/cache/glm52/"))


def _ensure_rootfs_ref_resolves(rootfs_ref: str, local_environment: LocalEnvironmentConfig) -> None:
    name = rootfs_ref.removeprefix("rootfs://")
    if not name or name not in local_environment.rootfs:
        raise RuntimeConfigError(f"sandbox.rootfs_ref does not resolve: {rootfs_ref}")


def _sglang_launch_env(declared: DeclaredSglangLaunchSpec) -> dict[str, str]:
    env = {
        "HF_HOME": declared.sandbox.sglang.hf_home,
        "SGLANG_CACHE_DIR": declared.sandbox.sglang.sglang_cache,
    }
    if declared.runtime.device == "cpu":
        env["SGLANG_USE_CPU_ENGINE"] = "1"
    if declared.runtime.device == "cuda":
        env["CUDA_VISIBLE_DEVICES"] = declared.runtime.cuda_visible_devices
    return env


def _select_port(port_policy: PortPolicy, requested_port: int | None) -> int:
    if requested_port is not None:
        candidates = [requested_port]
    else:
        candidates = range(port_policy.range_start, port_policy.range_end + 1)
    for candidate in candidates:
        if candidate < port_policy.range_start or candidate > port_policy.range_end:
            raise RuntimeConfigError(f"selected port outside declared range: {candidate}")
        if candidate not in port_policy.disallowed_ports:
            return candidate
    raise RuntimeConfigError("port range contains only disallowed ports")


def _select_repeat_port(port_policy: PortPolicy, used_ports: set[int]) -> int:
    for candidate in range(port_policy.range_start, port_policy.range_end + 1):
        if candidate in used_ports or candidate in port_policy.disallowed_ports:
            continue
        if not _is_port_open(port_policy.bind_host, candidate):
            return candidate
    raise RuntimeConfigError("no free port in declared range")


def _reject_schema_owned_extra_args(extra_args: list[str]) -> None:
    schema_owned_flags = {
        "--model-path",
        "--served-model-name",
        "--host",
        "--port",
        "--tp",
        "--device",
        "--dtype",
        "--context-length",
        "--kv-cache-dtype",
        "--mem-fraction-static",
        "--max-total-tokens",
        "--max-running-requests",
        "--cpu-offload-gb",
        "--crash-dump-folder",
    }
    for arg in extra_args:
        if arg in schema_owned_flags:
            raise RuntimeConfigError(f"runtime.extra_args must not override schema-owned flag: {arg}")


def _format_float_arg(value: float) -> str:
    return f"{value:g}"


def _argv_value(argv: list[str], flag: str) -> str:
    if flag not in argv:
        raise RuntimeConfigError(f"missing {flag}")
    index = argv.index(flag)
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        raise RuntimeConfigError(f"missing value for {flag}")
    return argv[index + 1]


def _required_str_sequence(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RuntimeConfigError(f"{path} must be a string list")
    return list(value)


def _mounts_by_sandbox_path(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mounts = plan.get("mounts")
    if not isinstance(mounts, list):
        raise RuntimeConfigError("resolved rootfs plan mounts must be a list")
    by_sandbox: dict[str, dict[str, Any]] = {}
    for mount in mounts:
        if not isinstance(mount, dict) or not isinstance(mount.get("sandbox_path"), str):
            continue
        sandbox_path = mount["sandbox_path"]
        if sandbox_path in by_sandbox:
            raise RuntimeConfigError(f"duplicate sandbox mount: {sandbox_path}")
        by_sandbox[sandbox_path] = mount
    return by_sandbox


def _required_section_str(mapping: dict[str, Any], key: str, path: str) -> str:
    return _required_str(mapping, key, path)


def _required_section_float(mapping: dict[str, Any], key: str, path: str) -> float:
    return _required_float(mapping, key, path)


def _required_section_int(mapping: dict[str, Any], key: str, path: str) -> int:
    return _required_int(mapping, key, path)


def _resolve_artifact_paths(config: MaterializedSglangRuntimeConfig) -> dict[str, Path]:
    artifacts = _require_mapping(config.artifacts, "artifacts")
    return {
        str(name): Path(_resolve_host_path_ref(config, _required_section_str(artifacts, str(name), "artifacts")))
        for name in artifacts
        if isinstance(value := artifacts[name], str)
    }


def _resolved_rootfs_path(config: MaterializedSglangRuntimeConfig) -> str:
    rootfs_ref = _required_section_str(config.sandbox, "rootfs_ref", "sandbox")
    if not rootfs_ref.startswith("rootfs://"):
        raise RuntimeConfigError("sandbox.rootfs_ref must use rootfs://")
    rootfs_name = rootfs_ref.removeprefix("rootfs://")
    if not rootfs_name:
        raise RuntimeConfigError("sandbox.rootfs_ref must name a rootfs")
    rootfs = _require_mapping(config.resolved_paths.get("rootfs"), "resolved_paths.rootfs")
    return _absolute_host_path(
        _required_section_str(rootfs, rootfs_name, "resolved_paths.rootfs"),
        f"resolved_paths.rootfs.{rootfs_name}",
    )


def build_insula_invocation_spec(config: MaterializedSglangRuntimeConfig) -> InsulaInvocationSpec:
    runtime_binds, runtime_env = _rootfs_runtime_binds_and_env(config)
    return InsulaInvocationSpec(
        schema_version=1,
        name=config.run_group,
        rootfs_ref=_required_section_str(config.sandbox, "rootfs_ref", "sandbox"),
        repo=InsulaBindSpec(
            name="repo",
            host="repo://",
            sandbox="/workspace/monarch",
            mode="ro",
            create=False,
            required=True,
        ),
        binds=[
            InsulaBindSpec(
                name=str(mount["sandbox_path"]).strip("/").replace("/", "-") or "root",
                host=_required_section_str(mount, "host_path_ref", "sandbox.mounts"),
                sandbox=_required_section_str(mount, "sandbox_path", "sandbox.mounts"),
                mode=_insula_bind_mode(_required_section_str(mount, "mode", "sandbox.mounts")),
                create=True,
                required=True,
            )
            for mount in _require_list(config.sandbox.get("mounts"), "sandbox.mounts")
            if _required_section_str(mount, "sandbox_path", "sandbox.mounts") != "/workspace/monarch"
        ]
        + runtime_binds,
        environment=InsulaEnvironmentSpec(
            clear=True,
            values={**runtime_env, **{str(key): str(value) for key, value in config.launch["env"].items()}},
            inherit_allowlist=[],
        ),
        command=InsulaCommandSpec(
            cwd=_required_section_str(config.sandbox, "cwd", "sandbox"),
            argv=list(config.launch["inner_argv"]),
        ),
        artifacts={
            "root": "run://insula",
            "stdout": config.artifacts["stdout_log"],
            "stderr": config.artifacts["stderr_log"],
            "plan": config.artifacts["resolved_rootfs_plan"],
            "result": "run://insula/result.json",
        },
        network="share-net",
        gpu=_insula_gpu_mode(config),
        die_with_parent=True,
        unshare_all=True,
    )


def _insula_gpu_mode(config: MaterializedSglangRuntimeConfig) -> str:
    if _required_section_str(config.runtime, "device", "runtime") == "cpu":
        return "none"
    return "nvidia-if-present"


def _rootfs_runtime_binds_and_env(config: MaterializedSglangRuntimeConfig) -> tuple[list[InsulaBindSpec], dict[str, str]]:
    run_group = config.run_group
    rootfs_cache = "repo://scripts/rootfs/cache"
    cargo_target = f"{rootfs_cache}/target/bwrap/{_rootfs_recipe_digest(config)}"
    binds = [
        InsulaBindSpec(
            name="rootfs-cache",
            host=rootfs_cache,
            sandbox="/workspace/monarch/scripts/rootfs/cache",
            mode="rw",
            create=True,
            required=True,
        ),
        InsulaBindSpec(
            name="cargo-target",
            host=cargo_target,
            sandbox=f"/workspace/monarch/target/bwrap/{_rootfs_recipe_digest(config)}",
            mode="rw",
            create=True,
            required=True,
        ),
    ]
    for name in ("resolv.conf", "hosts"):
        host_path = Path("/etc") / name
        if host_path.exists():
            binds.append(
                InsulaBindSpec(
                    name=f"etc-{name}",
                    host=f"host://{host_path}",
                    sandbox=str(host_path),
                    mode="ro",
                    create=False,
                    required=True,
                )
            )

    env = {
        "HOME": "/home/monarch",
        "USER": "monarch",
        "LOGNAME": "monarch",
        "PATH": "/opt/cuda-synth/bin:/opt/cargo/bin:/usr/local/bin:/usr/bin:/bin:/run/nvidia-host",
        "UV_PROJECT_ENVIRONMENT": "/workspace/monarch/.venv-rootfs",
        "UV_CACHE_DIR": "/workspace/monarch/scripts/rootfs/cache/uv",
        "CARGO_HOME": "/workspace/monarch/scripts/rootfs/cache/cargo",
        "CARGO_TARGET_DIR": f"/workspace/monarch/target/bwrap/{_rootfs_recipe_digest(config)}",
        "npm_config_cache": "/workspace/monarch/scripts/rootfs/cache/npm",
        "XDG_CACHE_HOME": "/workspace/monarch/scripts/rootfs/cache/xdg",
        "RUSTUP_HOME": "/opt/rustup",
        "CUDA_HOME": "/opt/cuda-synth",
        "CUDA_PATH": "/opt/cuda-synth",
        "MONARCH_IN_ROOTFS": "1",
        "MONARCH_ROOTFS_RECIPE_SHA256": _rootfs_recipe_digest(config),
    }
    have_nvidia_driver_libs = False
    nvidia_host_dir = f"cache://{run_group}/nvidia-host"
    libs = _nvidia_driver_libraries()
    if libs:
        have_nvidia_driver_libs = True
        binds.append(
            InsulaBindSpec(
                name="nvidia-host",
                host=nvidia_host_dir,
                sandbox="/run/nvidia-host",
                mode="rw",
                create=True,
                required=True,
            )
        )
        for lib in libs:
            binds.append(
                InsulaBindSpec(
                    name=f"nvidia-lib-{lib.name.replace('.', '-')}",
                    host=f"host://{lib}",
                    sandbox=f"/run/nvidia-host/{lib.name}",
                    mode="ro",
                    create=False,
                    required=True,
                )
            )
    if have_nvidia_driver_libs:
        env["LD_LIBRARY_PATH"] = "/run/nvidia-host:/opt/cuda-synth/lib64"
        env["LIBRARY_PATH"] = "/run/nvidia-host:/opt/cuda-synth/lib64"

    if _required_section_str(config.runtime, "device", "runtime") == "cuda":
        cuda_visible_devices = _required_section_str(config.runtime, "cuda_visible_devices", "runtime")
        for dev in _selected_nvidia_device_paths(cuda_visible_devices):
            binds.append(
                InsulaBindSpec(
                    name=f"dev-{dev.name}",
                    host=f"host://{dev}",
                    sandbox=str(dev),
                    mode="dev",
                    create=False,
                    required=True,
                )
            )
        nvidia_smi = Path("/usr/bin/nvidia-smi")
        if nvidia_smi.is_file():
            binds.append(
                InsulaBindSpec(
                    name="nvidia-smi",
                    host=f"host://{nvidia_smi}",
                    sandbox="/run/nvidia-host/nvidia-smi",
                    mode="ro",
                    create=False,
                    required=True,
                )
            )
        env["NVIDIA_VISIBLE_DEVICES"] = cuda_visible_devices
    return binds, dict(sorted(env.items()))


def _nvidia_driver_libraries() -> list[Path]:
    for libdir in (Path("/run/nvidia-host"), Path("/usr/lib/x86_64-linux-gnu")):
        libs = sorted(libdir.glob("libcuda.so*")) + sorted(libdir.glob("libnvidia-*.so*"))
        if libs:
            return libs
    return []


def _insula_local_environment(config: MaterializedSglangRuntimeConfig):
    return insula_local_environment_from_mapping(
        {
            "schema_version": 1,
            "repo": _required_section_str(config.resolved_paths, "repo", "resolved_paths"),
            "rootfs": dict(_require_mapping(config.resolved_paths.get("rootfs"), "resolved_paths.rootfs")),
            "cache": _required_section_str(config.resolved_paths, "cache", "resolved_paths"),
            "temp": _required_section_str(config.resolved_paths, "temp", "resolved_paths"),
            "run": _resolve_host_path_ref(config, "run://"),
            "results": _resolve_host_path_ref(config, "repo://glm52-serving-results"),
            "shared_memory": {},
            "gpu": {"mode": "nvidia-if-present"},
        }
    )


def _materialized_insula_invocation(config: MaterializedSglangRuntimeConfig):
    return _materialized_insula_invocation_for(config)


def _materialized_insula_invocation_for(
    config: MaterializedSglangRuntimeConfig,
    *,
    inner_argv: list[str] | None = None,
    env: dict[str, str] | None = None,
):
    spec = build_insula_invocation_spec(config)
    if inner_argv is not None:
        spec = InsulaInvocationSpec(
            schema_version=spec.schema_version,
            name=spec.name,
            rootfs_ref=spec.rootfs_ref,
            repo=spec.repo,
            binds=spec.binds,
            environment=spec.environment,
            command=InsulaCommandSpec(cwd=spec.command.cwd, argv=list(inner_argv)),
            artifacts=spec.artifacts,
            network=spec.network,
            gpu=spec.gpu,
            die_with_parent=spec.die_with_parent,
            unshare_all=spec.unshare_all,
        )
    if env:
        spec = InsulaInvocationSpec(
            schema_version=spec.schema_version,
            name=spec.name,
            rootfs_ref=spec.rootfs_ref,
            repo=spec.repo,
            binds=spec.binds,
            environment=InsulaEnvironmentSpec(
                clear=spec.environment.clear,
                values={**spec.environment.values, **dict(env)},
                inherit_allowlist=list(spec.environment.inherit_allowlist),
            ),
            command=spec.command,
            artifacts=spec.artifacts,
            network=spec.network,
            gpu=spec.gpu,
            die_with_parent=spec.die_with_parent,
            unshare_all=spec.unshare_all,
        )
    try:
        return materialize_insula_invocation(
            spec=spec,
            local_environment=_insula_local_environment(config),
            invocation_id=config.run_id,
            compatibility={"adapter": "glm52-sglang-runtime"},
        )
    except InsulaConfigError as error:
        raise RuntimeConfigError(f"failed to materialize Insula invocation: {error}") from error


def _ensure_created_bind_sources(
    config: MaterializedSglangRuntimeConfig,
    *,
    inner_argv: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    invocation = _materialized_insula_invocation_for(config, inner_argv=inner_argv, env=env)
    for bind in invocation.binds:
        if not bind.create or bind.mode != "rw":
            continue
        Path(bind.host).mkdir(parents=True, exist_ok=True)
        repo_mountpoint = _repo_projected_mountpoint(config, bind.sandbox)
        if repo_mountpoint is not None:
            repo_mountpoint.mkdir(parents=True, exist_ok=True)


def _repo_projected_mountpoint(config: MaterializedSglangRuntimeConfig, sandbox_path: str) -> Path | None:
    repo_sandbox_path = "/workspace/monarch"
    if sandbox_path == repo_sandbox_path:
        return Path(_required_section_str(config.resolved_paths, "repo", "resolved_paths"))
    if sandbox_path.startswith(f"{repo_sandbox_path}/"):
        relative = sandbox_path.removeprefix(f"{repo_sandbox_path}/")
        return Path(_required_section_str(config.resolved_paths, "repo", "resolved_paths")) / relative
    return None


def _insula_bind_mode(mode: str) -> str:
    if mode in {"ro", "rw"}:
        return mode
    raise RuntimeConfigError(f"unsupported Insula bind mode: {mode}")


def _resolved_outer_argv(config: MaterializedSglangRuntimeConfig) -> list[str]:
    return build_bwrap_argv(_materialized_insula_invocation(config))


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuntimeConfigError(f"{path} must be a list")
    return value


def _resolve_bind_spec(config: MaterializedSglangRuntimeConfig, arg: str) -> str:
    if ":" not in arg:
        return arg
    host_ref, sandbox_path = arg.rsplit(":", 1)
    if not host_ref.startswith(("repo://", "run://", "cache://", "temp://")):
        return arg
    return f"{_resolve_host_path_ref(config, host_ref)}:{sandbox_path}"


def _ensure_artifact_dirs(paths: dict[str, Path]) -> None:
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)


def _resolved_local_paths(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    return {
        "host_layout": {
            key: _resolve_host_path_ref(config, value)
            for key, value in config.host_layout.items()
        },
        "artifacts": {
            key: _resolve_host_path_ref(config, value)
            for key, value in config.artifacts.items()
            if isinstance(value, str)
        },
        "preparation": {
            key: str(_preparation_record_path(config, key))
            for key in _require_mapping(config.resolved_paths.get("preparation"), "resolved_paths.preparation")
        },
    }


def _validate_local_environment_matches_config(
    config: MaterializedSglangRuntimeConfig,
    local_environment: LocalEnvironmentConfig,
) -> None:
    resolved = _require_mapping(config.resolved_paths, "resolved_paths")
    if resolved.get("repo") != local_environment.repo:
        raise RuntimeConfigError("local_environment repo does not match materialized config")
    if resolved.get("cache") != local_environment.cache:
        raise RuntimeConfigError("local_environment cache does not match materialized config")
    if resolved.get("temp") != local_environment.temp:
        raise RuntimeConfigError("local_environment temp does not match materialized config")
    if resolved.get("rootfs") != local_environment.rootfs:
        raise RuntimeConfigError("local_environment rootfs does not match materialized config")


def _process_record(config: MaterializedSglangRuntimeConfig, process: Any) -> dict[str, Any]:
    try:
        process_group = os.getpgid(process.pid)
    except OSError:
        process_group = process.pid
    return {
        "schema_version": 1,
        "run_id": config.run_id,
        "status": "running",
        "pid": process.pid,
        "pgid": process_group,
        "process_group": process_group,
        "port": config.service["port"],
        "outer_argv": _resolved_outer_argv(config),
        "inner_argv": config.launch["inner_argv"],
        "env": config.launch["env"],
    }


def _validate_process_record_matches_config(
    config: MaterializedSglangRuntimeConfig,
    record: dict[str, Any],
) -> None:
    if _required_int(record, "schema_version", "process_record") != 1:
        raise RuntimeConfigError("process record schema_version must be 1")
    if _required_str(record, "run_id", "process_record") != config.run_id:
        raise RuntimeConfigError("process record run_id must match materialized config")
    if _required_int(record, "port", "process_record") != _required_section_int(config.service, "port", "service"):
        raise RuntimeConfigError("process record port must match materialized config")
    if _required_str_sequence(record.get("outer_argv"), "process_record.outer_argv") != _resolved_outer_argv(config):
        raise RuntimeConfigError("process record outer_argv must match materialized config")
    if _required_str_sequence(record.get("inner_argv"), "process_record.inner_argv") != config.launch["inner_argv"]:
        raise RuntimeConfigError("process record inner_argv must match materialized config")
    if _require_mapping(record.get("env"), "process_record.env") != config.launch["env"]:
        raise RuntimeConfigError("process record env must match materialized config")


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_repeat_summary(
    path: Path,
    *,
    repeat_id: str,
    status: str,
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "schema_version": 1,
        "repeat_id": repeat_id,
        "status": status,
        "cycles": cycles,
    }
    _write_json(path, summary)
    return summary


def _write_repeatability_summary(
    path: Path,
    *,
    run_id: str,
    ok: bool,
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "ok": ok,
        "cycles": cycles,
    }
    _write_json(path, summary)
    return summary


def _best_effort_teardown(
    config: MaterializedSglangRuntimeConfig,
    local_environment: LocalEnvironmentConfig,
) -> dict[str, Any]:
    try:
        teardown_config = config
        materialized_path = Path(_resolve_host_path_ref(config, config.artifacts["materialized_config"]))
        if materialized_path.exists():
            teardown_config = load_materialized_config(materialized_path)
        return teardown_runtime(teardown_config, local_environment=local_environment)
    except Exception as error:
        return {
            "status": "failed",
            "error": str(error),
        }


def _repeat_launch_failure_teardown(
    config: MaterializedSglangRuntimeConfig,
    local_environment: LocalEnvironmentConfig,
) -> dict[str, Any]:
    launch_summary_path = Path(_resolve_host_path_ref(config, config.artifacts["launch_summary"]))
    if launch_summary_path.exists():
        launch_summary = _load_json_mapping(launch_summary_path)
        if launch_summary.get("teardown_action") == "not_started":
            return {
                "status": "not_started",
                "reason": "launch failed before process start",
            }
    return _best_effort_teardown(config, local_environment)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_json_mapping(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return _require_mapping(json.load(handle), str(path))


def _raise_for_fatal_startup_log(config: MaterializedSglangRuntimeConfig) -> None:
    stderr_ref = config.artifacts.get("stderr_log")
    if not isinstance(stderr_ref, str):
        return
    stderr_path = Path(_resolve_host_path_ref(config, stderr_ref))
    if not stderr_path.exists():
        return
    try:
        text = _read_text_tail(stderr_path, max_bytes=65536)
    except OSError:
        return
    for marker in (
        "Scheduler hit an exception",
        "Received sigquit from a child process",
        "Traceback (most recent call last):",
    ):
        if marker in text:
            detail = _first_fatal_log_detail(text)
            raise RuntimeConfigError(f"SGLang startup failed before /v1/models became ready: {detail}")


def _read_text_tail(path: Path, *, max_bytes: int) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        return handle.read().decode("utf-8", errors="replace")


def _first_fatal_log_detail(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(("RuntimeError:", "ValueError:", "TypeError:", "ImportError:", "ModuleNotFoundError:")):
            return line
    for line in lines:
        if "Scheduler hit an exception" in line or "Received sigquit from a child process" in line:
            return line
    return "fatal startup marker found in stderr log"


def _mark_process_stopped(path: Path, record: dict[str, Any], reason: str) -> None:
    stopped = dict(record)
    stopped["status"] = "stopped"
    stopped["stop_reason"] = reason
    _write_yaml(path, stopped)


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_is_released(process_group: int) -> bool:
    if not _process_group_exists(process_group):
        return True
    return not _process_group_has_running_members(process_group)


def _process_group_has_running_members(process_group: int) -> bool:
    proc = Path("/proc")
    if not proc.exists():
        return True
    for stat_path in proc.glob("[0-9]*/stat"):
        try:
            stat = stat_path.read_text()
        except OSError:
            return True
        try:
            after_comm = stat.rsplit(") ", 1)[1]
            fields = after_comm.split()
            state = fields[0]
            pgrp = int(fields[2])
        except (IndexError, ValueError):
            return True
        if pgrp == process_group and state != "Z":
            return True
    return False


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def _is_port_bindable(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True


def _validate_materialized_top_level(config: MaterializedSglangRuntimeConfig) -> None:
    if config.schema_version != 1:
        raise RuntimeConfigError("materialized.schema_version must be 1")
    if not config.fail_fast:
        raise RuntimeConfigError("materialized.fail_fast must be true")
    if config.allow_fallback:
        raise RuntimeConfigError("materialized.allow_fallback must be false")
    for section_name in (
        "service",
        "model",
        "runtime",
        "observability",
        "host_layout",
        "sandbox",
        "launch",
        "probes",
        "artifacts",
    ):
        if not isinstance(getattr(config, section_name), dict):
            raise RuntimeConfigError(f"materialized.{section_name} must be a mapping")


def _validate_probe_urls(base_url: str, probes: dict[str, Any], service_port: int) -> None:
    parsed_base = urlparse(base_url)
    if parsed_base.scheme not in {"http", "https"} or parsed_base.hostname is None or parsed_base.port != service_port:
        raise RuntimeConfigError("service.base_url must include service host and port")
    expected_models_url = f"{base_url.rstrip('/')}/models"
    expected_generate_url = f"{parsed_base.scheme}://{parsed_base.hostname}:{service_port}/generate"
    expected_completions_url = f"{base_url.rstrip('/')}/completions"
    expected_chat_url = f"{base_url.rstrip('/')}/chat/completions"
    if _required_section_str(probes, "models_url", "probes") != expected_models_url:
        raise RuntimeConfigError("probe URLs must derive from service.base_url")
    if _required_section_str(probes, "generate_url", "probes") != expected_generate_url:
        raise RuntimeConfigError("probe URLs must derive from service.base_url")
    if _required_section_str(probes, "completions_url", "probes") != expected_completions_url:
        raise RuntimeConfigError("probe URLs must derive from service.base_url")
    if _required_section_str(probes, "chat_url", "probes") != expected_chat_url:
        raise RuntimeConfigError("probe URLs must derive from service.base_url")
    for key in ("models_url", "generate_url", "completions_url", "chat_url"):
        parsed = urlparse(probes[key])
        if parsed.hostname != parsed_base.hostname or parsed.port != service_port:
            raise RuntimeConfigError("probe URLs must derive from service.base_url")


def _validate_launch_env(config: MaterializedSglangRuntimeConfig) -> None:
    launch_env = _require_mapping(config.launch.get("env"), "launch.env")
    sandbox_env = _require_mapping(config.sandbox.get("env"), "sandbox.env")
    device = _required_section_str(config.runtime, "device", "runtime")
    sandbox_gpu = _required_section_str(config.sandbox, "gpu", "sandbox")
    if device == "cpu":
        if "CUDA_VISIBLE_DEVICES" in launch_env or "CUDA_VISIBLE_DEVICES" in sandbox_env:
            raise RuntimeConfigError("CUDA_VISIBLE_DEVICES must be absent for cpu")
        if sandbox_gpu != "none":
            raise RuntimeConfigError("sandbox.gpu must be none for cpu")
    elif device == "cuda":
        if sandbox_gpu != "required":
            raise RuntimeConfigError("sandbox.gpu must be required for cuda")
        if launch_env.get("CUDA_VISIBLE_DEVICES") != sandbox_env.get("CUDA_VISIBLE_DEVICES"):
            raise RuntimeConfigError("CUDA_VISIBLE_DEVICES in launch env must equal sandbox env")
        if not launch_env.get("CUDA_VISIBLE_DEVICES"):
            raise RuntimeConfigError("CUDA_VISIBLE_DEVICES is required for cuda")
    else:
        raise RuntimeConfigError("runtime.device must be cpu or cuda")
    if launch_env.get("HF_HOME") != sandbox_env.get("HF_HOME"):
        raise RuntimeConfigError("HF_HOME in launch env must equal sandbox env")
    if launch_env.get("SGLANG_CACHE_DIR") != sandbox_env.get("SGLANG_CACHE_DIR"):
        raise RuntimeConfigError("SGLANG_CACHE_DIR in launch env must equal sandbox env")
    if launch_env.get("SGLANG_USE_CPU_ENGINE") != sandbox_env.get("SGLANG_USE_CPU_ENGINE"):
        raise RuntimeConfigError("SGLANG_USE_CPU_ENGINE in launch env must equal sandbox env")
    if device == "cpu" and launch_env.get("SGLANG_USE_CPU_ENGINE") != "1":
        raise RuntimeConfigError("SGLANG_USE_CPU_ENGINE=1 is required for cpu")
    if device == "cuda" and "SGLANG_USE_CPU_ENGINE" in launch_env:
        raise RuntimeConfigError("SGLANG_USE_CPU_ENGINE must be absent for cuda")


def _validate_logical_host_layout(host_layout: dict[str, Any]) -> None:
    for key, value in host_layout.items():
        if not isinstance(value, str):
            raise RuntimeConfigError(f"host_layout.{key} must be a string")
        if value.startswith("/") or not value.startswith(("repo://", "run://", "cache://", "temp://")):
            raise RuntimeConfigError(f"host_layout.{key} must use logical path refs")


def _reject_disallowed_ports(config: MaterializedSglangRuntimeConfig, disallowed: set[int]) -> None:
    typed_ports = {
        _required_section_int(config.service, "port", "service"),
        _parsed_url_port(_required_section_str(config.service, "base_url", "service"), "service.base_url"),
        _parsed_url_port(_required_section_str(config.probes, "models_url", "probes"), "probes.models_url"),
        _parsed_url_port(_required_section_str(config.probes, "generate_url", "probes"), "probes.generate_url"),
        _parsed_url_port(_required_section_str(config.probes, "completions_url", "probes"), "probes.completions_url"),
        _parsed_url_port(_required_section_str(config.probes, "chat_url", "probes"), "probes.chat_url"),
        int(_argv_value(_required_str_sequence(config.launch.get("inner_argv"), "launch.inner_argv"), "--port")),
        int(_argv_value(_required_str_sequence(config.launch.get("outer_argv"), "launch.outer_argv"), "--port")),
    }
    if typed_ports & disallowed:
        raise RuntimeConfigError("disallowed fallback port appears in typed port fields")


def _reject_duplicate_inner_argv_schema_flags(inner: list[str]) -> None:
    schema_owned_flags = {
        "--model-path",
        "--served-model-name",
        "--host",
        "--port",
        "--tp",
        "--device",
        "--dtype",
        "--context-length",
        "--kv-cache-dtype",
        "--mem-fraction-static",
        "--max-total-tokens",
        "--max-running-requests",
        "--cpu-offload-gb",
    }
    for flag in schema_owned_flags:
        if inner.count(flag) > 1:
            raise RuntimeConfigError("inner argv mismatch")


def _allocate_run_owned_port(port_policy: PortPolicy, used_ports: set[int]) -> int:
    for candidate in range(port_policy.range_start, port_policy.range_end + 1):
        if candidate in port_policy.disallowed_ports:
            if candidate == port_policy.range_start == port_policy.range_end:
                raise RuntimeConfigError(f"disallowed port in declared range: {candidate}")
            continue
        if candidate in used_ports:
            continue
        if _is_port_bindable(port_policy.bind_host, candidate):
            return candidate
    raise RuntimeConfigError("no free run-owned port in declared range")


def _parsed_url_port(url: str, path: str) -> int:
    parsed = urlparse(url)
    if parsed.port is None:
        raise RuntimeConfigError(f"{path} must include an explicit port")
    return parsed.port


def _chat_completion_content(payload: Any) -> str:
    mapping = _require_mapping(payload, "/v1/chat/completions response")
    choices = mapping.get("choices")
    if isinstance(choices, list):
        fragments: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                fragments.append(message["content"])
            text = choice.get("text")
            if isinstance(text, str):
                fragments.append(text)
        joined = "".join(fragments).strip()
        if joined:
            return joined
    output = mapping.get("output")
    if isinstance(output, list):
        fragments = []
        for item in output:
            if isinstance(item, dict) and isinstance(item.get("content"), list):
                for content_item in item["content"]:
                    if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                        fragments.append(content_item["text"])
        joined = "".join(fragments).strip()
        if joined:
            return joined
    return ""


def _completion_content(payload: Any) -> str:
    mapping = _require_mapping(payload, "/v1/completions response")
    choices = mapping.get("choices")
    if not isinstance(choices, list):
        return ""
    fragments: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        text = choice.get("text")
        if isinstance(text, str):
            fragments.append(text)
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            fragments.append(message["content"])
    return "".join(fragments).strip()


def _generate_content(payload: Any) -> str:
    mapping = _require_mapping(payload, "/generate response")
    text = mapping.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    output = mapping.get("output")
    if isinstance(output, str) and output.strip():
        return output.strip()
    return ""


def _validate_live_process_command_guard(record: dict[str, Any], port: int) -> None:
    inner = _required_str_sequence(record.get("inner_argv"), "process_record.inner_argv")
    if "sglang.launch_server" not in inner:
        raise RuntimeConfigError("process record command guard missing sglang.launch_server")
    if _argv_value(inner, "--port") != str(port):
        raise RuntimeConfigError("process record command guard port mismatch")


def _record_to_mapping(record: Any) -> dict[str, Any] | None:
    if record is None:
        return None
    if isinstance(record, ProcessRecord):
        return {
            "pid": record.pid,
            "pgid": record.pgid,
            "argv": record.argv,
            "port": record.port,
        }
    if isinstance(record, dict):
        return dict(record)
    return {"repr": repr(record)}


def _with_prepared_model_snapshot(
    config: MaterializedSglangRuntimeConfig,
    model_cache_record: dict[str, Any],
) -> MaterializedSglangRuntimeConfig:
    model_cache = _require_mapping(model_cache_record.get("model_cache"), "model_cache_record.model_cache")
    snapshot_path = _required_section_str(model_cache, "snapshot_path", "model_cache_record.model_cache")
    if not _is_under_sandbox_path(snapshot_path, SGLANG_HF_HOME_SANDBOX_PATH):
        raise RuntimeConfigError("prepared model snapshot must be under /cache/glm52/hf-home")
    if snapshot_path == config.model["path"]:
        return config

    inner_argv = _replace_argv_value(config.launch["inner_argv"], "--model-path", snapshot_path)
    outer_argv = list(config.launch["outer_argv"])
    try:
        marker = outer_argv.index("--")
    except ValueError as error:
        raise RuntimeConfigError("launch.outer_argv must contain -- before inner argv") from error
    outer_argv = outer_argv[: marker + 1] + inner_argv
    model = {**config.model, "path": snapshot_path}
    launch = {**config.launch, "inner_argv": inner_argv, "outer_argv": outer_argv}
    effective = MaterializedSglangRuntimeConfig(
        schema_version=config.schema_version,
        run_id=config.run_id,
        run_group=config.run_group,
        fail_fast=config.fail_fast,
        allow_fallback=config.allow_fallback,
        service=config.service,
        model=model,
        runtime=config.runtime,
        observability=config.observability,
        host_layout=config.host_layout,
        sandbox=config.sandbox,
        launch=launch,
        probes=config.probes,
        artifacts=config.artifacts,
        resolved_paths=config.resolved_paths,
    )
    validate_materialized_config(effective)
    return effective


def with_prepared_model_snapshot(
    config: MaterializedSglangRuntimeConfig,
    model_cache_record: dict[str, Any],
) -> MaterializedSglangRuntimeConfig:
    return _with_prepared_model_snapshot(config, model_cache_record)


def _with_stable_preparation_record_paths(
    config: MaterializedSglangRuntimeConfig,
    *,
    declared: DeclaredSglangLaunchSpec,
    local_environment: LocalEnvironmentConfig,
) -> MaterializedSglangRuntimeConfig:
    preparation_paths = {
        "sglang_venv_record": _resolve_local_path_ref(
            local_environment,
            f"{declared.local_paths.results_root.rstrip('/')}/{SGLANG_PREPARE_RUN_ID}/sglang-venv.json",
        ),
        "model_cache_record": _resolve_local_path_ref(
            local_environment,
            f"{declared.local_paths.results_root.rstrip('/')}/{MODEL_CACHE_PREPARE_RUN_ID}/model-cache.json",
        ),
    }
    resolved_paths = dict(config.resolved_paths)
    resolved_paths["preparation"] = preparation_paths
    return MaterializedSglangRuntimeConfig(
        schema_version=config.schema_version,
        run_id=config.run_id,
        run_group=config.run_group,
        fail_fast=config.fail_fast,
        allow_fallback=config.allow_fallback,
        service=config.service,
        model=config.model,
        runtime=config.runtime,
        observability=config.observability,
        host_layout=config.host_layout,
        sandbox=config.sandbox,
        launch=config.launch,
        probes=config.probes,
        artifacts=config.artifacts,
        resolved_paths=resolved_paths,
    )


def with_stable_preparation_record_paths(
    config: MaterializedSglangRuntimeConfig,
    *,
    declared: DeclaredSglangLaunchSpec,
    local_environment: LocalEnvironmentConfig,
) -> MaterializedSglangRuntimeConfig:
    return _with_stable_preparation_record_paths(
        config,
        declared=declared,
        local_environment=local_environment,
    )


def _replace_argv_value(argv: list[str], flag: str, value: str) -> list[str]:
    replaced = list(argv)
    if flag not in replaced:
        raise RuntimeConfigError(f"missing {flag}")
    index = replaced.index(flag)
    if index + 1 >= len(replaced):
        raise RuntimeConfigError(f"missing value for {flag}")
    replaced[index + 1] = value
    return replaced


def _config_to_mapping(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "run_id": config.run_id,
        "run_group": config.run_group,
        "fail_fast": config.fail_fast,
        "allow_fallback": config.allow_fallback,
        "service": config.service,
        "model": config.model,
        "runtime": config.runtime,
        "observability": config.observability,
        "host_layout": config.host_layout,
        "sandbox": config.sandbox,
        "launch": config.launch,
        "probes": config.probes,
        "artifacts": config.artifacts,
        "resolved_paths": config.resolved_paths,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Schema-driven GLM-5.2 SGLang runtime launcher")
    subcommands = parser.add_subparsers(dest="command", required=True)

    materialize = subcommands.add_parser("materialize")
    materialize.add_argument("--declared-spec", type=Path, required=True)
    materialize.add_argument("--local-environment", type=Path, required=True)
    materialize.add_argument("--run-id", required=True)
    materialize.add_argument("--port", type=int)
    materialize.add_argument("--output", type=Path, required=True)

    validate = subcommands.add_parser("validate")
    validate.add_argument("--materialized-config", type=Path, required=True)

    prepare = subcommands.add_parser("prepare-venv")
    prepare.add_argument("--declared", "--declared-spec", dest="declared_spec", type=Path, required=True)
    prepare.add_argument("--local-env", "--local-environment", dest="local_environment", type=Path, required=True)
    prepare.add_argument("--run-id", default=SGLANG_PREPARE_RUN_ID)

    prepare_model = subcommands.add_parser("prepare-model")
    prepare_model.add_argument("--declared", "--declared-spec", dest="declared_spec", type=Path, required=True)
    prepare_model.add_argument("--local-env", "--local-environment", dest="local_environment", type=Path, required=True)
    prepare_model.add_argument("--run-id", default=MODEL_CACHE_PREPARE_RUN_ID)

    launch = subcommands.add_parser("launch")
    launch.add_argument("--materialized-config", type=Path, required=True)
    launch.add_argument("--local-environment", type=Path, required=True)

    teardown = subcommands.add_parser("teardown")
    teardown.add_argument("--materialized-config", type=Path, required=True)
    teardown.add_argument("--local-environment", type=Path, required=True)

    repeat = subcommands.add_parser("repeat")
    repeat.add_argument("--declared-spec", type=Path, required=True)
    repeat.add_argument("--local-environment", type=Path, required=True)
    repeat.add_argument("--cycles", type=int)
    repeat.add_argument("--wait-for-gpu-free-seconds", type=int, default=0)
    repeat.add_argument("--gpu-free-stable-seconds", type=int, default=0)

    repeatability = subcommands.add_parser("repeatability")
    repeatability.add_argument("--declared", "--declared-spec", dest="declared_spec", type=Path, required=True)
    repeatability.add_argument("--local-env", "--local-environment", dest="local_environment", type=Path, required=True)
    repeatability.add_argument("--run-id", default="glm52-sglang-repeatability")
    repeatability.add_argument("--cycles", type=int)
    repeatability.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "materialize":
            declared = load_declared_spec(args.declared_spec)
            local_environment = load_local_environment(args.local_environment)
            config = materialize_runtime_config(
                declared=declared,
                local_environment=local_environment,
                run_id=args.run_id,
                port=args.port,
            )
            write_materialized_config(config, args.output)
            return 0
        if args.command == "validate":
            load_materialized_config(args.materialized_config)
            return 0
        if args.command == "prepare-venv":
            prepare_sglang_venv(
                declared_path=args.declared_spec,
                local_environment_path=args.local_environment,
                run_id=args.run_id,
            )
            return 0
        if args.command == "prepare-model":
            prepare_model_cache(
                declared_path=args.declared_spec,
                local_environment_path=args.local_environment,
                run_id=args.run_id,
            )
            return 0
        if args.command == "launch":
            config = load_materialized_config(args.materialized_config)
            local_environment = load_local_environment(args.local_environment)
            launch_runtime(config, local_environment=local_environment)
            return 0
        if args.command == "teardown":
            config = load_materialized_config(args.materialized_config)
            local_environment = load_local_environment(args.local_environment)
            teardown_runtime(config, local_environment=local_environment)
            return 0
        if args.command == "repeat":
            declared = load_declared_spec(args.declared_spec)
            local_environment = load_local_environment(args.local_environment)
            repeat_runtime(
                declared=declared,
                local_environment=local_environment,
                cycles=args.cycles,
                wait_for_gpu_free_seconds=args.wait_for_gpu_free_seconds,
                gpu_free_stable_seconds=args.gpu_free_stable_seconds,
            )
            return 0
        if args.command == "repeatability":
            run_repeatability_cycles(
                declared_path=args.declared_spec,
                local_environment_path=args.local_environment,
                run_id=args.run_id,
                cycles=args.cycles,
                dry_run=args.dry_run,
            )
            return 0
    except RuntimeConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
