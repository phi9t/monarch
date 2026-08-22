#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from typing import Literal
from typing import TypeGuard

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml

from ginkgo.eval.manifest import campaign_manifest_sha256
from ginkgo.eval.orchestrator import EvalRunStateError
from ginkgo.eval.orchestrator import begin_campaign_materialization
from ginkgo.eval.orchestrator import begin_campaign_summary
from ginkgo.eval.orchestrator import begin_grading
from ginkgo.eval.orchestrator import begin_suite_preparation
from ginkgo.eval.orchestrator import begin_suite_summary
from ginkgo.eval.orchestrator import begin_trial_generation
from ginkgo.eval.orchestrator import complete_campaign_materialization
from ginkgo.eval.orchestrator import complete_campaign_summary
from ginkgo.eval.orchestrator import complete_grading
from ginkgo.eval.orchestrator import complete_suite_preparation
from ginkgo.eval.orchestrator import complete_suite_summary
from ginkgo.eval.orchestrator import complete_trial_generation
from ginkgo.eval.orchestrator import resume_eval_run_state


DEFAULT_RESULTS_ROOT = Path("glm52-benchmark-results")
DEFAULT_RUN_ROOT = Path(".scratch/glm52-local-serving/run")
DEFAULT_BENCHMARK_MANIFEST = Path(
    ".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"
)
DEFAULT_HARBOR_SMOKE_CONFIG = Path(
    ".scratch/glm52-local-serving/harbor/configs/terminal-bench-2-smoke.yaml"
)
DEFAULT_HARBOR_SWEBENCH_SMOKE_CONFIG = Path(
    ".scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml"
)
DEFAULT_HARBOR_SWEBENCH_LOCK = Path(
    ".scratch/glm52-local-serving/harbor/datasets/swe-bench-verified.lock.yaml"
)
DEFAULT_RESPONSES_TIMEOUT_SECONDS = 30.0
HARBOR_AGENT_VERSION = "glm52-harbor-agent-v1"
HARBOR_TERMINAL_BENCH_REPO_REVISION = (
    "9dd349f28b969268aef419e910e1998149b612a5"
)
HARBOR_TERMINAL_BENCH_REPO = (
    f"harbor-framework/harbor@{HARBOR_TERMINAL_BENCH_REPO_REVISION}"
)
HARBOR_TERMINAL_BENCH_DATASET = "terminal-bench"
HARBOR_TERMINAL_BENCH_DATASET_VERSION = "2.0"
HARBOR_SMOKE_SUITES = {"terminal-bench-2", "swe-bench-verified"}


class BenchmarkVerifierError(RuntimeError):
    pass


REQUIRED_SUITE_FIELDS = {
    "id",
    "profile",
    "dataset_revision",
    "harness_revision",
    "prompt_template",
    "execution_backend",
    "decoding_profile",
    "metric",
}
REQUIRED_METRICS_CONDITION_FIELDS = {
    "profile",
    "dataset_revision",
    "harness_revision",
    "prompt_template",
    "execution_backend",
    "decoding_profile",
    "metric",
}
REQUIRED_PUBLISHED_SCORE_FIELDS = {
    "suite",
    "model",
    "profile",
    "metric",
    "score",
    "tolerance",
    "tolerance_basis",
    "source_url",
    "source_type",
    "prompt_template",
    "dataset_revision",
    "harness_revision",
    "execution_backend",
    "decoding_profile",
}
ALLOWED_EXECUTION_BACKENDS = {
    "bwrap_rootfs",
    "scripts_run",
    "local_docker",
    "harbor_local_docker",
    "host_subprocess",
}
FAILURE_STATES = {
    "errored",
    "environment_setup_failed",
    "environment_crashed",
    "grader_failed",
}
REQUIRED_HARBOR_TRIAL_FIELDS = {
    "agent_version",
    "endpoint",
    "environment_provider",
    "local_host_route",
    "model_id",
    "task_id",
    "trial_id",
}
REQUIRED_MANIFEST_SUITES = {
    "gsm8k",
    "aime",
    "humaneval",
    "mbpp",
    "swe-bench-verified",
    "terminal-bench-2",
    "ruler",
    "needle-smoke",
}


def build_harbor_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[1])
    existing_pythonpath = env.get("PYTHONPATH")
    entries = (
        [
            entry
            for entry in existing_pythonpath.split(os.pathsep)
            if entry and entry != repo_root
        ]
        if existing_pythonpath
        else []
    )
    env["PYTHONPATH"] = os.pathsep.join([repo_root, *entries])
    return env


def load_yaml_object(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text())
    except FileNotFoundError as error:
        raise BenchmarkVerifierError(f"manifest not found: {path}") from error
    if not isinstance(payload, dict):
        raise BenchmarkVerifierError(f"manifest must be a YAML object: {path}")
    return payload


def load_harbor_smoke_config(path: Path) -> dict[str, Any]:
    config = load_yaml_object(path)
    suite_id = config.get("suite")
    if suite_id == "terminal-bench-2":
        _validate_terminal_bench_harbor_smoke_config(config)
    elif suite_id == "swe-bench-verified":
        _validate_swe_bench_harbor_smoke_config(config)
    else:
        raise BenchmarkVerifierError(
            "Harbor smoke config must target terminal-bench-2 or swe-bench-verified"
        )
    return config


def _validate_common_harbor_smoke_config(
    config: dict[str, Any],
    *,
    required_top_level: set[str],
) -> None:
    missing = sorted(required_top_level - set(config))
    if missing:
        raise BenchmarkVerifierError(
            f"Harbor smoke config missing fields: {', '.join(missing)}"
        )
    if config.get("endpoint") != "responses":
        raise BenchmarkVerifierError("Harbor smoke config must use the Responses endpoint")
    if config.get("stream") is not True:
        raise BenchmarkVerifierError("Harbor smoke config must enable streaming")
    if config.get("tools") != "enabled":
        raise BenchmarkVerifierError("Harbor smoke config must enable tools")
    execution = config.get("execution")
    if not isinstance(execution, dict):
        raise BenchmarkVerifierError("Harbor smoke config execution must be an object")
    if execution.get("harness") != "harbor":
        raise BenchmarkVerifierError("Harbor smoke config execution.harness must be harbor")
    if execution.get("execution_backend") != "harbor_local_docker":
        raise BenchmarkVerifierError(
            "Harbor smoke config execution.execution_backend must be harbor_local_docker"
        )
    subset = config.get("subset")
    if not isinstance(subset, dict):
        raise BenchmarkVerifierError("Harbor smoke config subset must be an object")


def _validate_pinned_harbor_source(config: dict[str, Any], field: str) -> None:
    source = config.get(field)
    if not isinstance(source, dict):
        raise BenchmarkVerifierError(f"Harbor smoke config {field} must be an object")
    revision = source.get("revision")
    if (
        not isinstance(revision, str)
        or not revision
        or revision.startswith("<")
        or "placeholder" in revision.lower()
    ):
        raise BenchmarkVerifierError(
            f"Harbor smoke config {field}.revision must be pinned"
        )


def _validate_terminal_bench_harbor_smoke_config(config: dict[str, Any]) -> None:
    required_top_level = {
        "schema_version",
        "suite",
        "profile",
        "endpoint",
        "stream",
        "tools",
        "harness_source",
        "benchmark_source",
        "execution",
        "subset",
        "metric",
    }
    _validate_common_harbor_smoke_config(
        config,
        required_top_level=required_top_level,
    )
    execution = config.get("execution")
    if not isinstance(execution, dict):
        raise BenchmarkVerifierError("Harbor smoke config execution must be an object")
    expected_execution = {
        "harness": "harbor",
        "dataset": HARBOR_TERMINAL_BENCH_DATASET,
        "dataset_version": HARBOR_TERMINAL_BENCH_DATASET_VERSION,
        "repo": HARBOR_TERMINAL_BENCH_REPO,
        "execution_backend": "harbor_local_docker",
        "container": "required",
    }
    for key, expected in expected_execution.items():
        if execution.get(key) != expected:
            if key == "dataset" and execution.get(key) == "terminal-bench-2":
                raise BenchmarkVerifierError(
                    "terminal-bench-2 is not available in Harbor registry; "
                    "use terminal-bench@2.0 from "
                    f"{HARBOR_TERMINAL_BENCH_REPO}"
                )
            raise BenchmarkVerifierError(
                f"Harbor smoke config execution.{key} must be {expected}"
            )
    if not isinstance(execution.get("timeout_seconds_per_task"), int):
        raise BenchmarkVerifierError(
            "Harbor smoke config requires integer timeout_seconds_per_task"
        )

    subset = config.get("subset")
    if not isinstance(subset, dict):
        raise BenchmarkVerifierError("Harbor smoke config subset must be an object")
    smoke_tasks = subset.get("smoke_tasks")
    if (
        not isinstance(smoke_tasks, list)
        or not smoke_tasks
        or not all(isinstance(task, str) and task for task in smoke_tasks)
    ):
        raise BenchmarkVerifierError(
            "Harbor smoke config requires a non-empty pinned smoke_tasks list"
        )
    if smoke_tasks in (["<small pinned task list>"], ["TODO"]):
        raise BenchmarkVerifierError("Harbor smoke config smoke_tasks must be pinned")

    for field in ("harness_source", "benchmark_source"):
        _validate_pinned_harbor_source(config, field)


def _validate_swe_bench_harbor_smoke_config(config: dict[str, Any]) -> None:
    required_top_level = {
        "schema_version",
        "suite",
        "profile",
        "status",
        "runnable",
        "endpoint",
        "stream",
        "tools",
        "dataset_source",
        "harness_source",
        "execution",
        "subset",
        "metric",
        "official_images",
        "conformance",
    }
    _validate_common_harbor_smoke_config(
        config,
        required_top_level=required_top_level,
    )
    if config.get("runnable") is not True:
        raise BenchmarkVerifierError("SWE-bench Harbor smoke config must be runnable")
    if config.get("status") != "ready":
        raise BenchmarkVerifierError("SWE-bench Harbor smoke config status must be ready")
    for field in ("dataset_source", "harness_source"):
        _validate_pinned_harbor_source(config, field)

    execution = config["execution"]
    if execution.get("dataset_adapter") != "swebench_verified":
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config execution.dataset_adapter must be swebench_verified"
        )
    if execution.get("docker") != "required":
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config execution.docker must be required"
        )
    if not isinstance(execution.get("timeout_seconds_per_instance"), int):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config requires integer timeout_seconds_per_instance"
        )

    subset = config["subset"]
    smoke_instances = subset.get("smoke_instances")
    if (
        not isinstance(smoke_instances, list)
        or not smoke_instances
        or not all(isinstance(instance, str) and instance for instance in smoke_instances)
    ):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config requires a non-empty pinned smoke_instances list"
        )
    if smoke_instances in (["<small pinned instance list>"], ["TODO"]):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config smoke_instances must be pinned"
        )

    conformance = config.get("conformance")
    if not isinstance(conformance, dict):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config conformance must be an object"
        )
    if conformance.get("claim") != "none":
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config must not claim conformance"
        )
    if conformance.get("comparable_to_published") is not False:
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config must not be comparable to published scores"
        )

    image_results = resolve_swe_bench_smoke_image_metadata(config, config)
    failures = [result for result in image_results if result.get("status") != "pass"]
    if failures:
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config requires selected official row images "
            "and digest-pinned image metadata"
        )


def write_harbor_smoke_config_artifact(
    harbor_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    configs_dir = harbor_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    config_text = yaml.safe_dump(config, sort_keys=True)
    suite_id = config.get("suite")
    if not isinstance(suite_id, str) or not suite_id:
        raise BenchmarkVerifierError("Harbor smoke config suite must be declared")
    config_path = configs_dir / f"{suite_id}-smoke.yaml"
    config_path.write_text(config_text)
    return {
        "path": config_path,
        "sha256": hashlib.sha256(config_text.encode("utf-8")).hexdigest(),
    }


def write_harbor_job_config(
    *,
    path: Path,
    run_id: str,
    harbor_output_dir: Path,
    smoke_config: dict[str, Any],
    responses_base_url: str,
    local_host_route: str,
    local_container_runtime: str,
) -> Path:
    suite_id = smoke_config.get("suite")
    if suite_id == "swe-bench-verified":
        dataset_config = _build_swe_bench_harbor_dataset_config(smoke_config)
    elif suite_id == "terminal-bench-2":
        dataset_config = _build_terminal_bench_harbor_dataset_config(smoke_config)
    else:
        raise BenchmarkVerifierError(
            "Harbor smoke config must target terminal-bench-2 or swe-bench-verified"
        )
    agent_responses_base_url = harbor_agent_responses_base_url(
        responses_base_url=responses_base_url,
        local_host_route=local_host_route,
    )
    timeout_seconds = _harbor_agent_timeout_seconds(smoke_config)
    job_config = {
        "job_name": run_id,
        "jobs_dir": str(harbor_output_dir),
        "n_attempts": 1,
        "n_concurrent_trials": 1,
        "quiet": True,
        "environment": {
            "type": local_container_runtime,
            "extra_allowed_hosts": [local_host_route],
        },
        "agents": [
            {
                "import_path": "scripts.glm52_harbor_agent:GLM52HarborAgent",
                "model_name": "zai-org/GLM-5.2",
                "override_timeout_sec": timeout_seconds,
                "kwargs": {
                    "responses_base_url": agent_responses_base_url,
                    "local_host_route": local_host_route,
                    "responses_timeout_seconds": timeout_seconds,
                    "stream": bool(smoke_config.get("stream")),
                },
            }
        ],
        "datasets": [dataset_config],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(job_config, sort_keys=False))
    return path


def _harbor_agent_timeout_seconds(smoke_config: dict[str, Any]) -> int:
    execution = smoke_config.get("execution")
    if not isinstance(execution, dict):
        raise BenchmarkVerifierError("Harbor smoke config execution must be an object")
    suite_id = smoke_config.get("suite")
    field = (
        "timeout_seconds_per_instance"
        if suite_id == "swe-bench-verified"
        else "timeout_seconds_per_task"
    )
    timeout_seconds = execution.get(field)
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise BenchmarkVerifierError(
            f"Harbor smoke config execution.{field} must be a positive integer"
        )
    return timeout_seconds


def _build_terminal_bench_harbor_dataset_config(
    smoke_config: dict[str, Any],
) -> dict[str, Any]:
    subset = smoke_config.get("subset")
    if not isinstance(subset, dict):
        raise BenchmarkVerifierError("Harbor smoke config subset must be an object")
    smoke_tasks = subset.get("smoke_tasks")
    if (
        not isinstance(smoke_tasks, list)
        or not smoke_tasks
        or not all(isinstance(task, str) and task for task in smoke_tasks)
    ):
        raise BenchmarkVerifierError(
            "Harbor smoke config requires a non-empty pinned smoke_tasks list"
        )
    benchmark_source = smoke_config.get("benchmark_source")
    if not isinstance(benchmark_source, dict):
        raise BenchmarkVerifierError(
            "Harbor smoke config benchmark_source must be an object"
        )
    benchmark_revision = benchmark_source.get("revision")
    if not isinstance(benchmark_revision, str) or not benchmark_revision:
        raise BenchmarkVerifierError(
            "Harbor smoke config benchmark_source.revision must be pinned"
        )
    execution = smoke_config.get("execution")
    if not isinstance(execution, dict):
        raise BenchmarkVerifierError("Harbor smoke config execution must be an object")
    dataset_name = execution.get("dataset")
    dataset_version = execution.get("dataset_version")
    dataset_repo = execution.get("repo")
    if not isinstance(dataset_name, str) or not dataset_name:
        raise BenchmarkVerifierError("Harbor smoke config execution.dataset must be pinned")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise BenchmarkVerifierError(
            "Harbor smoke config execution.dataset_version must be pinned"
        )
    if not isinstance(dataset_repo, str) or not dataset_repo:
        raise BenchmarkVerifierError("Harbor smoke config execution.repo must be pinned")
    return {
        "name": dataset_name,
        "version": dataset_version,
        "repo": dataset_repo,
        "task_names": smoke_tasks,
    }


def _build_swe_bench_harbor_dataset_config(
    smoke_config: dict[str, Any],
) -> dict[str, Any]:
    subset = smoke_config.get("subset")
    if not isinstance(subset, dict):
        raise BenchmarkVerifierError("Harbor smoke config subset must be an object")
    smoke_instances = subset.get("smoke_instances")
    if (
        not isinstance(smoke_instances, list)
        or not smoke_instances
        or not all(isinstance(instance, str) and instance for instance in smoke_instances)
    ):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config requires a non-empty pinned smoke_instances list"
        )
    dataset_source = smoke_config.get("dataset_source")
    if not isinstance(dataset_source, dict):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config dataset_source must be an object"
        )
    harness_source = smoke_config.get("harness_source")
    if not isinstance(harness_source, dict):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config harness_source must be an object"
        )
    execution = smoke_config.get("execution")
    if not isinstance(execution, dict):
        raise BenchmarkVerifierError("Harbor smoke config execution must be an object")
    dataset_adapter = execution.get("dataset_adapter")
    if not isinstance(dataset_adapter, str) or not dataset_adapter:
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config execution.dataset_adapter must be pinned"
        )
    image_records = resolve_swe_bench_smoke_image_metadata(smoke_config, smoke_config)
    if any(record.get("status") != "pass" for record in image_records):
        raise BenchmarkVerifierError(
            "SWE-bench Harbor smoke config requires pass image metadata"
        )
    return {
        "name": "swe-bench-verified",
        "adapter": dataset_adapter,
        "dataset_source": dataset_source,
        "harness_source": harness_source,
        "instance_ids": smoke_instances,
        "instance_images": [
            {
                "instance_id": record["instance_id"],
                "row_image": record["row_image"],
                "image_digest": record["image_digest"],
            }
            for record in image_records
        ],
    }


def select_suites(manifest: dict[str, Any], suite_ids: list[str]) -> list[dict[str, Any]]:
    suites = manifest_suites(manifest)
    by_id = {}
    for suite in suites:
        by_id[suite["id"]] = suite
    selected = []
    for suite_id in suite_ids:
        try:
            selected.append(by_id[suite_id])
        except KeyError as error:
            raise BenchmarkVerifierError(f"unknown suite: {suite_id}") from error
    return selected


def manifest_suite_ids(manifest: dict[str, Any]) -> list[str]:
    return [suite["id"] for suite in manifest_suites(manifest)]


def manifest_suites(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    suites = manifest.get("suites")
    if not isinstance(suites, list):
        raise BenchmarkVerifierError("benchmark manifest requires a suites list")
    validated = []
    seen = set()
    for suite in suites:
        if not isinstance(suite, dict) or not isinstance(suite.get("id"), str):
            raise BenchmarkVerifierError("each suite must be an object with string id")
        suite_id = suite["id"]
        if suite_id in seen:
            raise BenchmarkVerifierError(f"duplicate suite id: {suite_id}")
        seen.add(suite_id)
        validated.append(suite)
    return validated


def validate_suite_fields(suite: dict[str, Any]) -> None:
    missing = sorted(field for field in REQUIRED_SUITE_FIELDS if field not in suite)
    if missing:
        raise BenchmarkVerifierError(
            f"suite {suite.get('id', '<unknown>')} missing fields: {', '.join(missing)}"
        )
    execution_backend = suite["execution_backend"]
    if execution_backend not in ALLOWED_EXECUTION_BACKENDS:
        raise BenchmarkVerifierError(
            f"suite {suite['id']} execution_backend is not allowed: {execution_backend}"
        )


def validate_manifest_suite_coverage(manifest: dict[str, Any]) -> None:
    suites = manifest_suites(manifest)
    suite_ids = {suite["id"] for suite in suites}
    missing = sorted(REQUIRED_MANIFEST_SUITES - suite_ids)
    if missing:
        raise BenchmarkVerifierError(f"missing suite entries: {', '.join(missing)}")
    for suite in suites:
        validate_suite_fields(suite)


def validate_prepare_manifest_revisions(manifest: dict[str, Any]) -> None:
    for suite in manifest.get("suites", []):
        if not isinstance(suite, dict):
            continue
        validate_suite_fields(suite)
        suite_id = suite["id"]
        for field in ("dataset_revision", "harness_revision"):
            if _is_placeholder_revision(suite.get(field)):
                raise BenchmarkVerifierError(
                    f"suite {suite_id} {field} must be pinned"
                )
        _validate_source_revision_matches_suite(
            suite=suite,
            suite_id=suite_id,
            suite_revision_field="dataset_revision",
            source_field="dataset_source",
        )
        _validate_source_revision_matches_suite(
            suite=suite,
            suite_id=suite_id,
            suite_revision_field="harness_revision",
            source_field="harness_source",
        )


def _validate_source_revision_matches_suite(
    *,
    suite: dict[str, Any],
    suite_id: str,
    suite_revision_field: str,
    source_field: str,
) -> None:
    source = suite.get(source_field)
    if not isinstance(source, dict):
        return
    source_revision = source.get("revision")
    if source_revision is None:
        return
    if _is_placeholder_revision(source_revision):
        raise BenchmarkVerifierError(
            f"suite {suite_id} {source_field}.revision must be pinned"
        )
    suite_revision = suite[suite_revision_field]
    expected_revision = _revision_suffix(suite_revision)
    if source_revision != expected_revision and source_revision != suite_revision:
        raise BenchmarkVerifierError(
            f"suite {suite_id} {suite_revision_field} must match "
            f"{source_field}.revision"
        )


def validate_conformance_inputs(
    *,
    manifest: dict[str, Any],
    published_scores: dict[str, Any],
    suite_ids: list[str],
    execution_backend_override: str | None,
) -> None:
    if execution_backend_override is not None:
        raise BenchmarkVerifierError("backend override is not allowed in conformance mode")
    manifest_model = manifest.get("model")
    if not isinstance(manifest_model, str) or _is_placeholder(manifest_model):
        raise BenchmarkVerifierError("benchmark manifest model must be declared")
    published_manifest_model = published_scores.get("model")
    if isinstance(published_manifest_model, str):
        if _is_placeholder(published_manifest_model):
            raise BenchmarkVerifierError("published-score manifest model must be declared")
        if published_manifest_model != manifest_model:
            raise BenchmarkVerifierError(
                "published-score manifest model does not match benchmark manifest model"
            )
    selected = select_suites(manifest, suite_ids)
    score_by_suite = published_score_by_suite(published_scores)
    for suite in selected:
        validate_suite_fields(suite)
        suite_id = suite["id"]
        for field in ("dataset_revision", "harness_revision"):
            if _is_placeholder_revision(suite.get(field)):
                raise BenchmarkVerifierError(
                    f"suite {suite_id} {field} must be pinned"
                )
        score = score_by_suite.get(suite_id)
        if not isinstance(score, dict):
            raise BenchmarkVerifierError(f"missing published score for suite: {suite_id}")
        missing = sorted(
            field
            for field in REQUIRED_PUBLISHED_SCORE_FIELDS
            if field not in score or _is_placeholder(score[field])
        )
        if missing:
            raise BenchmarkVerifierError(
                f"published score for {suite_id} missing fields: {', '.join(missing)}"
            )
        if not is_valid_score(score["score"]):
            raise BenchmarkVerifierError(
                f"published score for {suite_id} score must be numeric"
            )
        if not is_http_url(score["source_url"]):
            raise BenchmarkVerifierError(
                f"published score for {suite_id} source_url must be an http(s) URL"
            )
        if score.get("source_type") != "primary":
            raise BenchmarkVerifierError(
                f"published score for {suite_id} source_type must be primary"
            )
        if score["model"] != manifest_model:
            raise BenchmarkVerifierError(
                f"published score for {suite_id} does not match manifest model"
            )
        if not is_valid_tolerance(score["tolerance"]):
            raise BenchmarkVerifierError(
                f"published score for {suite_id} tolerance must be numeric"
            )
        if not is_valid_tolerance_basis(score["tolerance_basis"]):
            raise BenchmarkVerifierError(
                f"published score for {suite_id} tolerance_basis must be declared"
            )
        if score.get("comparable") is False:
            raise BenchmarkVerifierError(
                f"published score for {suite_id} is marked non-comparable"
            )
        for field in (
            "profile",
            "metric",
            "prompt_template",
            "dataset_revision",
            "harness_revision",
            "execution_backend",
            "decoding_profile",
        ):
            if score[field] != suite[field]:
                raise BenchmarkVerifierError(
                    f"published score for {suite_id} does not match suite {field}"
                )
        validate_suite_source_metadata(suite)
        if suite.get("execution_backend") in {"local_docker", "harbor_local_docker"}:
            container_image = suite.get("container_image")
            if not isinstance(container_image, str) or _is_placeholder(container_image):
                raise BenchmarkVerifierError(
                    f"suite {suite_id} container_image must be pinned"
                )
            if not is_digest_pinned_container_image(container_image):
                raise BenchmarkVerifierError(
                    f"suite {suite_id} container_image must be digest-pinned"
                )
        if suite_id == "swe-bench-verified":
            instance_images = suite.get("instance_images")
            if not isinstance(instance_images, dict) or not instance_images:
                raise BenchmarkVerifierError(
                    "suite swe-bench-verified instance_images must be declared"
                )
            for instance_id, image in instance_images.items():
                if not isinstance(instance_id, str) or not isinstance(image, str):
                    raise BenchmarkVerifierError(
                        "suite swe-bench-verified instance_images must map strings to strings"
                    )
                if not is_digest_pinned_container_image(image):
                    raise BenchmarkVerifierError(
                        f"suite swe-bench-verified instance image {instance_id} must be digest-pinned"
                    )


def published_score_by_suite(published_scores: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scores = published_scores.get("scores")
    if not isinstance(scores, list):
        raise BenchmarkVerifierError("published-score manifest requires a scores list")
    score_by_suite: dict[str, dict[str, Any]] = {}
    for score in scores:
        if not isinstance(score, dict) or not isinstance(score.get("suite"), str):
            raise BenchmarkVerifierError(
                "each published score must be an object with string suite"
            )
        suite_id = score["suite"]
        if suite_id in score_by_suite:
            raise BenchmarkVerifierError(f"duplicate published score for suite: {suite_id}")
        score_by_suite[suite_id] = score
    return score_by_suite


def validate_suite_source_metadata(suite: dict[str, Any]) -> None:
    suite_id = suite["id"]
    for source_field, revision_field in (
        ("dataset_source", "dataset_revision"),
        ("harness_source", "harness_revision"),
    ):
        source = suite.get(source_field)
        if not isinstance(source, dict):
            raise BenchmarkVerifierError(
                f"suite {suite_id} {source_field} must be declared"
            )
        if source.get("revision") is None:
            raise BenchmarkVerifierError(
                f"suite {suite_id} {source_field}.revision must be declared"
            )
        _validate_source_revision_matches_suite(
            suite=suite,
            suite_id=suite_id,
            suite_revision_field=revision_field,
            source_field=source_field,
        )


def is_digest_pinned_container_image(image: str) -> bool:
    return re.search(r"@sha256:[0-9a-fA-F]{64}(?:$|[/?#])", image) is not None


def _is_exact_digest_pinned_container_image(image: str) -> bool:
    return re.fullmatch(r"[^@]+@sha256:[0-9a-fA-F]{64}", image) is not None


def resolve_swe_bench_smoke_image_metadata(
    config: dict[str, Any],
    lock: dict[str, Any],
) -> list[dict[str, Any]]:
    source_revision = _swe_bench_source_revision(config, lock)
    provider_namespace = _swe_bench_provider_namespace(lock)
    base_record: dict[str, Any] = {
        "suite": "swe-bench-verified",
        "provider_namespace": provider_namespace,
    }
    if source_revision is not None:
        base_record["source_revision"] = source_revision

    missing = []
    errors = []
    smoke_instances = _swe_bench_smoke_instances(config, lock)
    if not smoke_instances:
        missing.append("smoke_instances")
        errors.append("SWE-bench Verified smoke_instances must select at least one instance")
    if source_revision is None:
        missing.append("source_revision")
        errors.append("SWE-bench Verified dataset source revision must be pinned")
    if missing:
        return [
            {
                **base_record,
                "status": "missing_prerequisite",
                "missing": missing,
                "error": "; ".join(errors),
            }
        ]

    image_by_instance = _swe_bench_image_metadata_by_instance(lock)
    records = []
    for instance_id in smoke_instances:
        record = {
            **base_record,
            "status": "pass",
            "instance_id": instance_id,
        }
        image_metadata = image_by_instance.get(instance_id)
        if image_metadata is None:
            record.update(
                {
                    "status": "missing_prerequisite",
                    "missing": ["official_row_image", "image_digest"],
                    "error": (
                        "SWE-bench Verified instance must declare official row image "
                        "and digest"
                    ),
                }
            )
            records.append(record)
            continue
        row_image = image_metadata.get("row_image")
        image_digest = image_metadata.get("image_digest")
        row_missing = []
        row_errors = []
        if not isinstance(row_image, str) or _is_placeholder(row_image):
            row_missing.append("official_row_image")
            row_errors.append("official row image must be declared")
        else:
            record["row_image"] = row_image
        if not isinstance(image_digest, str) or _is_placeholder(image_digest):
            row_missing.append("image_digest")
            row_errors.append("image digest must be declared")
        elif not _is_exact_digest_pinned_container_image(image_digest):
            row_missing.append("image_digest")
            row_errors.append("image digest must use repo@sha256:<64 hex>")
        else:
            record["image_digest"] = image_digest
        if row_missing:
            record["status"] = "missing_prerequisite"
            record["missing"] = row_missing
            record["error"] = "; ".join(row_errors)
        records.append(record)
    return records


def is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def harbor_agent_responses_base_url(
    *, responses_base_url: str, local_host_route: str
) -> str:
    parsed = urllib.parse.urlparse(responses_base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return responses_base_url
    if not local_host_route:
        return responses_base_url
    netloc = local_host_route
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


def is_valid_tolerance(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value) and value >= 0


def is_valid_tolerance_basis(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    if "sample_size" not in value or "variance" not in value:
        return False
    for basis_value in value.values():
        if isinstance(basis_value, str) and _is_placeholder(basis_value):
            return False
    return True


def is_valid_score(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value)


def write_conformance_validation_artifact(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    published_scores: dict[str, Any],
    suite_ids: list[str],
) -> Path:
    selected = select_suites(manifest, suite_ids)
    score_by_suite = published_score_by_suite(published_scores)
    selected_scores = [score_by_suite[suite["id"]] for suite in selected]
    result_dir = results_root / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest_sha256 = _json_sha256(manifest)
    published_scores_sha256 = _json_sha256(published_scores)
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode="conformance",
        manifest=manifest,
        suite_ids=[suite["id"] for suite in selected],
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (result_dir / "published-scores.json").write_text(
        json.dumps(published_scores, indent=2, sort_keys=True) + "\n"
    )
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "conformance",
        "status": "validated",
        "created_at": created_at,
        "manifest_sha256": manifest_sha256,
        "published_scores_sha256": published_scores_sha256,
        "suites": [suite["id"] for suite in selected],
        "scores": selected_scores,
    }
    path = result_dir / "conformance.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "conformance",
        "status": "validated",
        "created_at": created_at,
        "manifest_sha256": manifest_sha256,
        "published_scores_sha256": published_scores_sha256,
        "suites": [
            {
                "id": suite["id"],
                "status": "validated",
                "metric": suite["metric"],
                "execution_backend": suite["execution_backend"],
            }
            for suite in selected
        ],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": "conformance",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode="conformance",
        status="validated",
        created_at=created_at,
        result_dir=result_dir,
    )
    _complete_evalrun_materialization(result_dir)
    for suite in selected:
        _begin_evalrun_suite(result_dir, suite["id"])
        _complete_evalrun_trial_generation(
            result_dir=result_dir,
            suite_dir=result_dir,
            suite_id=suite["id"],
            tasks_total=1,
            samples_artifacts=["conformance.json"],
        )
        _begin_evalrun_grading(result_dir, suite["id"])
        _complete_evalrun_suite(
            result_dir=result_dir,
            suite_dir=result_dir,
            suite_id=suite["id"],
            tasks_graded=1,
            status="validated",
            metrics_artifacts=["conformance.json"],
            summary_artifacts=["conformance.json"],
        )
    _begin_evalrun_campaign_summary(result_dir)
    _complete_evalrun_campaign_summary(
        result_dir=result_dir,
        status="validated",
        artifacts=["conformance.json", "run.json"],
    )
    write_archive_manifest(result_dir=result_dir, summary=payload, summary_path="conformance.json")
    return path


def write_prepare_artifact(
    *,
    results_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    rootfs_path: Path,
    endpoints_checked: bool,
    endpoint_results: list[dict[str, Any]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    gold_path_results: list[dict[str, Any]] | None = None,
    cache_results: list[dict[str, Any]] | None = None,
    image_results: list[dict[str, Any]] | None = None,
    container_runtime_results: list[dict[str, Any]] | None = None,
    swe_bench_smoke_image_results: list[dict[str, Any]] | None = None,
) -> Path:
    for suite in manifest_suites(manifest):
        validate_suite_fields(suite)
    result_dir = results_root / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode="prepare",
        manifest=manifest,
        suite_ids=[
            suite["id"]
            for suite in manifest["suites"]
            if isinstance(suite, dict) and isinstance(suite.get("id"), str)
        ],
    )
    endpoint_preflight = endpoint_results or []
    tool_preflight = tool_results or []
    gold_path_preflight = gold_path_results or []
    cache_preflight = cache_results or []
    image_preflight = image_results or []
    container_runtime_preflight = container_runtime_results or []
    swe_bench_smoke_image_preflight = swe_bench_smoke_image_results or []
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "prepared",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "manifest_sha256": _json_sha256(manifest),
        "rootfs_path": str(rootfs_path),
        "rootfs_exists": rootfs_path.exists(),
        "endpoints_checked": endpoints_checked,
        "endpoint_preflight": endpoint_preflight,
        "tool_preflight": tool_preflight,
        "gold_path_preflight": gold_path_preflight,
        "cache_preflight": cache_preflight,
        "image_preflight": image_preflight,
        "container_runtime_preflight": container_runtime_preflight,
        "swe_bench_smoke_image_preflight": swe_bench_smoke_image_preflight,
        "suites": sorted(
            suite["id"]
            for suite in manifest["suites"]
            if isinstance(suite, dict) and isinstance(suite.get("id"), str)
        ),
    }
    path = result_dir / "prepare.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "prepare",
        "status": "prepared",
        "created_at": payload["created_at"],
        "manifest_sha256": payload["manifest_sha256"],
        "artifact": str(path),
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": payload["created_at"],
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": "prepare",
                "rootfs_path": str(rootfs_path),
                "rootfs_exists": rootfs_path.exists(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    _complete_evalrun_materialization(result_dir)
    for suite_id in payload["suites"]:
        _begin_evalrun_suite(result_dir, suite_id)
        _complete_evalrun_trial_generation(
            result_dir=result_dir,
            suite_dir=result_dir,
            suite_id=suite_id,
            tasks_total=1,
            samples_artifacts=["prepare.json"],
        )
        _begin_evalrun_grading(result_dir, suite_id)
        _complete_evalrun_suite(
            result_dir=result_dir,
            suite_dir=result_dir,
            suite_id=suite_id,
            tasks_graded=1,
            status="prepared",
            metrics_artifacts=["prepare.json"],
            summary_artifacts=["prepare.json"],
        )
    _begin_evalrun_campaign_summary(result_dir)
    _complete_evalrun_campaign_summary(
        result_dir=result_dir,
        status="prepared",
        artifacts=["prepare.json", "run.json"],
    )
    write_archive_manifest(
        result_dir=result_dir,
        summary=payload,
        summary_path="prepare.json",
    )
    return path


def write_prepare_run_state(
    *,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    artifact_path: Path,
) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "prepare",
        "status": "prepared",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "manifest_sha256": _json_sha256(manifest),
        "artifact": str(artifact_path),
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode="prepare",
        status="prepared",
        created_at=run_record["created_at"],
        result_dir=artifact_path.parent,
    )


def build_cache_preflight(
    manifest: dict[str, Any],
    cache_root: Path | None = None,
) -> list[dict[str, Any]]:
    if cache_root is None:
        cache_root = DEFAULT_RUN_ROOT.parent / "benchmarks"
    records = []
    for suite in manifest.get("suites", []):
        if not isinstance(suite, dict) or not isinstance(suite.get("id"), str):
            continue
        suite_id = suite["id"]
        dataset_cache = cache_root / "datasets" / suite_id
        harness_cache = cache_root / "harnesses" / suite_id
        dataset_cache_exists = dataset_cache.exists()
        harness_cache_exists = harness_cache.exists()
        record = {
            "suite": suite_id,
            "dataset_revision": suite.get("dataset_revision"),
            "dataset_cache": str(dataset_cache),
            "dataset_cache_exists": dataset_cache_exists,
            "harness_revision": suite.get("harness_revision"),
            "harness_cache": str(harness_cache),
            "harness_cache_exists": harness_cache_exists,
            "status": "available"
            if dataset_cache_exists and harness_cache_exists
            else "planned",
        }
        if suite_id == "ruler" and dataset_cache_exists:
            smoke_sample = _ruler_smoke_sample_path(dataset_cache)
            if smoke_sample is not None:
                record["smoke_sample"] = str(smoke_sample)
        records.append(record)
    return sorted(records, key=lambda record: record["suite"])


def materialize_prepare_caches(
    manifest: dict[str, Any],
    cache_root: Path | None = None,
) -> list[dict[str, Any]]:
    if cache_root is None:
        cache_root = DEFAULT_RUN_ROOT.parent / "benchmarks"
    for suite in manifest.get("suites", []):
        if not isinstance(suite, dict) or not isinstance(suite.get("id"), str):
            continue
        suite_id = suite["id"]
        _materialize_cache_source(
            source=suite.get("dataset_source"),
            destination=cache_root / "datasets" / suite_id,
            source_name="dataset_source",
        )
        _materialize_cache_source(
            source=suite.get("harness_source"),
            destination=cache_root / "harnesses" / suite_id,
            source_name="harness_source",
        )
        if suite_id == "ruler":
            _ensure_ruler_smoke_sample(cache_root / "datasets" / suite_id)
    records = build_cache_preflight(manifest, cache_root=cache_root)
    for record in records:
        suite = _manifest_suite_by_id(manifest, record["suite"])
        _add_cache_source_metadata(
            record,
            prefix="dataset",
            source=suite.get("dataset_source"),
        )
        _add_cache_source_metadata(
            record,
            prefix="harness",
            source=suite.get("harness_source"),
        )
    return records


def _ruler_smoke_sample_path(dataset_cache: Path) -> Path | None:
    sample = _read_first_ruler_jsonl_sample(dataset_cache)
    if sample is None:
        return None
    if dataset_cache.is_file():
        return dataset_cache
    preferred = dataset_cache / "samples.jsonl"
    if preferred.is_file():
        return preferred
    for candidate in (
        dataset_cache / "test.jsonl",
        dataset_cache / "validation.jsonl",
        dataset_cache / "problems.jsonl",
    ):
        if candidate.is_file():
            return candidate
    for candidate in sorted(dataset_cache.glob("*.jsonl")):
        return candidate
    return None


def _ensure_ruler_smoke_sample(dataset_cache: Path) -> None:
    if not dataset_cache.exists():
        return
    if _read_first_ruler_jsonl_sample(dataset_cache) is not None:
        return
    source_markers = [
        dataset_cache / "scripts" / "synthetic.yaml",
        dataset_cache / "scripts" / "data" / "synthetic" / "niah.py",
    ]
    if not any(marker.exists() for marker in source_markers):
        raise BenchmarkVerifierError(
            "RULER dataset cache does not contain a usable sample or generator"
        )
    samples_path = dataset_cache / "samples.jsonl"
    sample = {
        "id": "ruler-smoke-niah-single-1",
        "input": (
            "Read the context and answer the question exactly.\n\n"
            "Context:\n"
            "Operational note: the deployment cleanup token is ORCHID-7194.\n\n"
            "Question:\n"
            "What is the deployment cleanup token?"
        ),
        "outputs": ["ORCHID-7194"],
        "source": "monarch-ruler-smoke-fixture",
    }
    samples_path.write_text(json.dumps(sample, sort_keys=True) + "\n")


def _manifest_suite_by_id(manifest: dict[str, Any], suite_id: str) -> dict[str, Any]:
    for suite in manifest.get("suites", []):
        if isinstance(suite, dict) and suite.get("id") == suite_id:
            return suite
    raise BenchmarkVerifierError(f"unknown suite: {suite_id}")


def _materialize_cache_source(
    *,
    source: Any,
    destination: Path,
    source_name: str,
) -> None:
    if source is None:
        return
    if not isinstance(source, dict):
        raise BenchmarkVerifierError(f"{source_name} must be an object")
    source_type = source.get("type")
    if source_type == "local_path":
        source_path_value = source.get("path")
        if not isinstance(source_path_value, str) or not source_path_value:
            raise BenchmarkVerifierError(f"{source_name}.path must be a non-empty string")
        source_path = Path(source_path_value)
        if not source_path.exists():
            raise BenchmarkVerifierError(f"{source_name}.path does not exist: {source_path}")
        if destination.exists():
            shutil.rmtree(destination)
        if source_path.is_dir():
            shutil.copytree(source_path, destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination / source_path.name)
        return
    if source_type == "git":
        url = source.get("url")
        revision = source.get("revision")
        if not isinstance(url, str) or not url:
            raise BenchmarkVerifierError(f"{source_name}.url must be a non-empty string")
        if not isinstance(revision, str) or not revision or revision.startswith("<"):
            raise BenchmarkVerifierError(
                f"{source_name}.revision must be a pinned non-empty string"
            )
        if destination.exists():
            shutil.rmtree(destination)
        clone = subprocess.run(
            ["git", "clone", "--no-checkout", url, str(destination)],
            check=False,
            capture_output=True,
            text=True,
        )
        if clone.returncode != 0:
            raise BenchmarkVerifierError(
                f"{source_name} git clone failed: {clone.stderr.strip()}"
            )
        checkout = subprocess.run(
            ["git", "-C", str(destination), "checkout", "--detach", revision],
            check=False,
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            raise BenchmarkVerifierError(
                f"{source_name} git checkout failed: {checkout.stderr.strip()}"
            )
        return
    if source_type == "http_archive":
        url = source.get("url")
        expected_sha256 = source.get("sha256")
        if not isinstance(url, str) or not url:
            raise BenchmarkVerifierError(f"{source_name}.url must be a non-empty string")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise BenchmarkVerifierError(
                f"{source_name}.sha256 must be a non-empty string"
            )
        download_path = destination.with_name(f"{destination.name}.download")
        download_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(url, str(download_path))
        except (OSError, urllib.error.URLError) as error:
            raise BenchmarkVerifierError(
                f"{source_name} archive download failed: {error}"
            ) from error
        actual_sha256 = hashlib.sha256(download_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            download_path.unlink(missing_ok=True)
            raise BenchmarkVerifierError(
                f"{source_name} archive sha256 mismatch: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        try:
            with tarfile.open(download_path) as archive:
                archive.extractall(destination, filter="data")
        except tarfile.TarError as error:
            raise BenchmarkVerifierError(
                f"{source_name} archive extraction failed: {error}"
            ) from error
        finally:
            download_path.unlink(missing_ok=True)
        return
    if source_type in {"huggingface", "huggingface_or_swebench"}:
        repo_id = source.get("repo_id") or source.get("dataset")
        revision = source.get("revision")
        if not isinstance(repo_id, str) or not repo_id:
            raise BenchmarkVerifierError(
                f"{source_name}.repo_id or {source_name}.dataset must be a non-empty string"
            )
        if not isinstance(revision, str) or not revision or revision.startswith("<"):
            raise BenchmarkVerifierError(
                f"{source_name}.revision must be a pinned non-empty string"
            )
        repo_type = source.get("repo_type")
        if repo_type is None:
            repo_type = "dataset" if source_name == "dataset_source" else "model"
        if not isinstance(repo_type, str) or not repo_type:
            raise BenchmarkVerifierError(
                f"{source_name}.repo_type must be a non-empty string"
            )
        if destination.exists():
            shutil.rmtree(destination)
        executable = _huggingface_download_executable()
        command = [
            executable,
            "download",
            repo_id,
            "--repo-type",
            repo_type,
            "--revision",
            revision,
            "--local-dir",
            str(destination),
        ]
        if executable == "huggingface-cli":
            command.extend(["--local-dir-use-symlinks", "False"])
        try:
            download = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as error:
            raise BenchmarkVerifierError(
                f"{source_name} huggingface download failed: executable not found: "
                f"{command[0]}"
            ) from error
        if download.returncode != 0:
            raise BenchmarkVerifierError(
                f"{source_name} huggingface download failed: {download.stderr.strip()}"
            )
        return
    raise BenchmarkVerifierError(f"unsupported {source_name}.type: {source_type!r}")


def _huggingface_download_executable() -> str:
    if shutil.which("hf"):
        return "hf"
    return "huggingface-cli"


def _add_cache_source_metadata(
    record: dict[str, Any],
    *,
    prefix: str,
    source: Any,
) -> None:
    if not isinstance(source, dict):
        return
    source_type = source.get("type")
    if isinstance(source_type, str):
        record[f"{prefix}_source_type"] = source_type
    source_sha256 = source.get("sha256")
    if isinstance(source_sha256, str):
        record[f"{prefix}_source_sha256"] = source_sha256
    source_revision = source.get("revision")
    if isinstance(source_revision, str):
        record[f"{prefix}_source_revision"] = source_revision


def build_image_preflight(
    manifest: dict[str, Any],
    tool_results: list[dict[str, Any]],
    runtime: str = "docker",
) -> list[dict[str, Any]]:
    tool_status = {
        result["name"]: result["status"]
        for result in tool_results
        if isinstance(result.get("name"), str) and isinstance(result.get("status"), str)
    }
    records = []
    for suite in manifest.get("suites", []):
        if not isinstance(suite, dict) or not isinstance(suite.get("id"), str):
            continue
        if suite["id"] == "swe-bench-verified":
            continue
        execution_backend = suite.get("execution_backend")
        if execution_backend not in {"local_docker", "harbor_local_docker"}:
            continue
        missing = []
        if tool_status.get("docker") != "ok":
            missing.append("docker")
        if execution_backend == "harbor_local_docker" and tool_status.get("harbor") != "ok":
            missing.append("harbor")
        record: dict[str, Any] = {
            "suite": suite["id"],
            "execution_backend": execution_backend,
            "status": "digest_pending" if not missing else "missing_prerequisite",
        }
        if isinstance(suite.get("container_image"), str):
            image = suite["container_image"]
            record["image"] = image
            if _is_placeholder(image):
                record["status"] = "invalid_container_image"
                record["error"] = "container_image must be pinned"
            elif not is_digest_pinned_container_image(image):
                record["status"] = "invalid_container_image"
                record["error"] = "container_image must be digest-pinned"
            elif missing:
                record["missing"] = missing
            else:
                record.update(inspect_container_image(image=image, runtime=runtime))
        else:
            record["status"] = "invalid_container_image"
            record["error"] = "container_image must be declared"
        records.append(record)
    return sorted(records, key=lambda record: record["suite"])


def build_swe_bench_smoke_image_preflight(
    manifest: dict[str, Any],
    config_path: Path | None = None,
    lock_path: Path | None = None,
) -> list[dict[str, Any]]:
    if "swe-bench-verified" not in manifest_suite_ids(manifest):
        return []
    if config_path is None:
        config_path = DEFAULT_HARBOR_SWEBENCH_SMOKE_CONFIG
    if lock_path is None:
        lock_path = DEFAULT_HARBOR_SWEBENCH_LOCK
    config = load_yaml_object(config_path)
    lock = load_yaml_object(lock_path)
    return resolve_swe_bench_smoke_image_metadata(config, lock)


def validate_prepare_image_preflight(image_results: list[dict[str, Any]]) -> None:
    for record in image_results:
        if record.get("status") != "invalid_container_image":
            continue
        suite_id = record.get("suite", "<unknown>")
        error = record.get("error")
        if error == "container_image must be pinned":
            raise BenchmarkVerifierError(f"suite {suite_id} container_image must be pinned")
        if error == "container_image must be declared":
            raise BenchmarkVerifierError(
                f"suite {suite_id} container_image must be declared"
            )
        raise BenchmarkVerifierError(
            f"suite {suite_id} container_image must be digest-pinned"
        )


def inspect_container_image(*, image: str, runtime: str) -> dict[str, Any]:
    completed = subprocess.run(
        [runtime, "image", "inspect", image, "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    record: dict[str, Any] = {
        "image": image,
        "runtime": runtime,
    }
    if completed.returncode != 0:
        record["status"] = "inspect_failed"
        record["stderr"] = completed.stderr.strip()
        return record
    try:
        inspected = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        record["status"] = "inspect_failed"
        record["error"] = f"invalid image inspect json: {error}"
        return record
    if not isinstance(inspected, list) or not inspected or not isinstance(inspected[0], dict):
        record["status"] = "inspect_failed"
        record["error"] = "image inspect returned no image metadata"
        return record
    metadata = inspected[0]
    image_id = metadata.get("Id")
    repo_digests = metadata.get("RepoDigests")
    if not isinstance(image_id, str):
        record["status"] = "inspect_failed"
        record["error"] = "image inspect did not return an image id"
        return record
    if not isinstance(repo_digests, list) or not repo_digests or not isinstance(repo_digests[0], str):
        record["status"] = "inspect_failed"
        record["image_id"] = image_id
        record["error"] = "image inspect did not return a repo digest"
        return record
    record["status"] = "ok"
    record["image_id"] = image_id
    record["repo_digest"] = repo_digests[0]
    return record


def build_container_runtime_preflight(
    manifest: dict[str, Any],
    runtime: str,
) -> list[dict[str, Any]]:
    required = any(
        isinstance(suite, dict)
        and suite.get("execution_backend") in {"local_docker", "harbor_local_docker"}
        for suite in manifest.get("suites", [])
    )
    if not required:
        return []
    record: dict[str, Any] = {
        "runtime": runtime,
        "required": True,
    }
    try:
        version = subprocess.run(
            [runtime, "version", "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
        info = subprocess.run(
            [runtime, "info", "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        record.update(
            {
                "status": "missing",
                "error": str(error),
            }
        )
        return [record]
    record["version"] = _parse_json_command_output(version.stdout)
    record["info"] = _parse_json_command_output(info.stdout)
    if version.returncode == 0 and info.returncode == 0:
        record["status"] = "ok"
    else:
        record["status"] = "unavailable"
        record["version_exit_code"] = version.returncode
        record["info_exit_code"] = info.returncode
        record["stderr"] = "\n".join(
            part for part in (version.stderr.strip(), info.stderr.strip()) if part
        )
    return [record]


def build_gold_path_preflight(
    manifest: dict[str, Any], tool_results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    tool_status = {
        result["name"]: result["status"]
        for result in tool_results
        if isinstance(result.get("name"), str) and isinstance(result.get("status"), str)
    }
    records = []
    for suite in manifest.get("suites", []):
        if not isinstance(suite, dict) or not isinstance(suite.get("id"), str):
            continue
        suite_id = suite["id"]
        execution_backend = suite.get("execution_backend")
        missing = _gold_path_missing_prerequisites(
            suite_id=suite_id,
            execution_backend=execution_backend,
            tool_status=tool_status,
        )
        record: dict[str, Any] = {
            "suite": suite_id,
            "check": _gold_path_check_name(suite_id),
            "status": "available" if not missing else "missing_prerequisite",
            "execution_backend": execution_backend,
        }
        if missing:
            record["missing"] = missing
        elif suite_id in {"aime", "gsm8k", "needle-smoke"}:
            record.update(_run_local_gold_path_fixture(suite))
        records.append(record)
    return sorted(records, key=lambda record: record["suite"])


def _gold_path_check_name(suite_id: str) -> str:
    return {
        "aime": "answer-extraction-fixture",
        "gsm8k": "answer-extraction-fixture",
        "humaneval": "known-good-bad-fixtures",
        "mbpp": "known-good-bad-fixtures",
        "needle-smoke": "local-answer-fixture",
        "ruler": "local-answer-fixture",
        "swe-bench-verified": "swe-bench-official-harness",
        "terminal-bench-2": "harbor-oracle",
    }.get(suite_id, "benchmark-native-oracle")


def _run_local_gold_path_fixture(suite: dict[str, Any]) -> dict[str, Any]:
    suite_id = suite["id"]
    if suite_id in {"aime", "gsm8k"}:
        samples = _static_gold_path_fixture_samples(suite_id)
    else:
        fixture_suite = _suite_with_fixture_defaults(suite)
        samples = _fixture_samples(
            "gold-path-preflight",
            fixture_suite,
            fixture_suite["execution_backend"],
        )
    fixtures_passed = sum(1 for sample in samples if sample.get("passed") is True)
    return {
        "status": "passed" if fixtures_passed == len(samples) else "failed",
        "fixtures_total": len(samples),
        "fixtures_passed": fixtures_passed,
    }


def _suite_with_fixture_defaults(suite: dict[str, Any]) -> dict[str, Any]:
    suite_id = suite["id"]
    return {
        "id": suite_id,
        "profile": suite.get("profile", "gold-path-fixture"),
        "dataset_revision": suite.get("dataset_revision", "gold-path-fixture"),
        "harness_revision": suite.get("harness_revision", "gold-path-fixture"),
        "prompt_template": suite.get("prompt_template", f"{suite_id}-gold-path"),
        "execution_backend": suite.get("execution_backend", "bwrap_rootfs"),
        "decoding_profile": suite.get("decoding_profile", {"temperature": 0}),
        "metric": suite.get("metric", "exact_match"),
    }


def _static_gold_path_fixture_samples(suite_id: str) -> list[dict[str, Any]]:
    if suite_id == "gsm8k":
        fixtures = [
            ("19 + 23 = 42\n#### 42", "42"),
            ("The total is 1,234.\n#### 1,234", "1234"),
        ]
    elif suite_id == "aime":
        fixtures = [
            ("The final integer answer is 042.", "42"),
            ("Modulo 1000 gives 999.", "999"),
        ]
    else:
        raise BenchmarkVerifierError(f"unsupported static gold-path suite: {suite_id}")
    samples = []
    for index, (raw_response, expected_answer) in enumerate(fixtures, start=1):
        extracted_answer = extract_static_final_answer(suite_id, raw_response)
        samples.append(
            {
                "case_id": f"{suite_id}/gold-path-{index:03d}",
                "passed": extracted_answer == expected_answer,
            }
        )
    return samples


def _gold_path_missing_prerequisites(
    *,
    suite_id: str,
    execution_backend: Any,
    tool_status: dict[str, str],
) -> list[str]:
    missing = []
    trusted_local_fixture = suite_id in {"aime", "gsm8k", "needle-smoke"}
    if (
        not trusted_local_fixture
        and execution_backend in {"bwrap_rootfs", "scripts_run"}
        and tool_status.get("bwrap") != "ok"
    ):
        missing.append("bwrap")
    if execution_backend in {"local_docker", "harbor_local_docker"} and tool_status.get("docker") != "ok":
        missing.append("docker")
    if suite_id == "terminal-bench-2" or execution_backend == "harbor_local_docker":
        if tool_status.get("harbor") != "ok":
            missing.append("harbor")
    return missing


def check_local_tool(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    if path is None:
        return {
            "name": name,
            "status": "missing",
        }
    return {
        "name": name,
        "status": "ok",
        "path": path,
    }


def build_harbor_environment_diagnostics(
    *,
    local_container_runtime: str,
    harbor_executable: str | None = None,
    runtime_executable: str | None = None,
) -> dict[str, Any]:
    repo_harbor_candidate = Path(
        ".scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor"
    )
    docker_socket_paths = ["/var/run/docker.sock", "/run/docker.sock"]
    harbor_tool: dict[str, Any] = {
        "status": "ok" if harbor_executable is not None else "missing",
        "repo_candidate": str(repo_harbor_candidate),
        "repo_candidate_exists": repo_harbor_candidate.exists(),
    }
    if harbor_executable is not None:
        harbor_tool["path"] = harbor_executable
    if repo_harbor_candidate.exists():
        try:
            harbor_tool["repo_candidate_shebang"] = (
                repo_harbor_candidate.read_text().splitlines()[0]
            )
        except OSError as error:
            harbor_tool["repo_candidate_error"] = str(error)

    runtime_tool: dict[str, Any] = {
        "status": "ok" if runtime_executable is not None else "missing",
        "socket_paths": docker_socket_paths,
        "socket_exists": any(Path(path).exists() for path in docker_socket_paths),
    }
    if runtime_executable is not None:
        runtime_tool["path"] = runtime_executable

    missing_tools = [
        name
        for name, tool in [
            ("harbor", harbor_tool),
            (local_container_runtime, runtime_tool),
        ]
        if tool["status"] != "ok"
    ]
    execution_domain = (
        "scripts_run_rootfs" if os.environ.get("MONARCH_IN_ROOTFS") == "1" else "host"
    )
    wrong_execution_domain = execution_domain != "host"
    return {
        "execution_domain": execution_domain,
        "required_execution_domain": "host",
        "host_bootstrap_required": wrong_execution_domain or bool(missing_tools),
        "path": os.environ.get("PATH", ""),
        "missing_tools": missing_tools,
        "tools": {
            "harbor": harbor_tool,
            local_container_runtime: runtime_tool,
        },
    }


def check_models_endpoint(*, name: str, base_url: str, timeout_seconds: float = 2.0) -> dict[str, Any]:
    models_url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(models_url, timeout=timeout_seconds) as response:
            body = response.read()
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        return {
            "name": name,
            "models_url": models_url,
            "status": "unavailable",
            "error": str(error),
        }
    models = _parse_models_response(body)
    return {
        "name": name,
        "models_url": models_url,
        "status": "ok",
        "models": models,
    }


def check_required_models_endpoint(
    *, name: str, base_url: str, timeout_seconds: float = 2.0
) -> dict[str, Any]:
    result = check_models_endpoint(
        name=name,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    if result.get("status") != "ok":
        return result
    if not result.get("models"):
        return {
            "name": name,
            "models_url": result["models_url"],
            "status": "unavailable",
            "error": "endpoint did not return JSON with a non-empty data list",
        }
    return result


def _harbor_responses_preflight_error(
    *,
    responses_preflight: dict[str, Any],
    local_host_route: str,
) -> str:
    error = str(responses_preflight.get("error", "endpoint unavailable"))
    models_url = str(responses_preflight["models_url"])
    if local_host_route and local_host_route in models_url and "Name or service not known" in error:
        error = (
            f"{error}; host process could not resolve {local_host_route}; "
            "use a host-resolvable --responses-base-url for the adapter "
            f"and keep --local-host-route {local_host_route} for Docker containers"
        )
    return f"Responses /models preflight failed for {models_url}: {error}"


def write_fixture_benchmark_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    mode: str,
    suite_ids: list[str],
    manifest: dict[str, Any],
    published_scores: dict[str, Any] | None,
    execution_backend: str,
    serving_summary_path: Path | None = None,
    responses_base_url: str | None = None,
    chat_base_url: str | None = None,
) -> Path:
    if execution_backend == "host_subprocess":
        raise BenchmarkVerifierError(
            "host_subprocess is reserved for trusted preparation and scoring helpers"
        )
    selected = select_suites(manifest, suite_ids)
    for suite in selected:
        validate_suite_fields(suite)
        if suite["execution_backend"] != execution_backend:
            raise BenchmarkVerifierError(
                f"suite {suite['id']} requires backend {suite['execution_backend']}"
            )

    result_dir = results_root / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest_sha256 = _json_sha256(manifest)
    published_scores_sha256 = _json_sha256(published_scores or {})
    previous_run = _read_json_object(result_dir / "run.json")
    can_resume_run = (
        previous_run.get("manifest_sha256") == manifest_sha256
        and previous_run.get("published_scores_sha256") == published_scores_sha256
        and previous_run.get("mode") == mode
    )
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        suite_ids=[suite["id"] for suite in selected],
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": mode,
                "execution_backend": execution_backend,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    if published_scores is not None:
        (result_dir / "published-scores.json").write_text(
            json.dumps(published_scores, indent=2, sort_keys=True) + "\n"
        )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": manifest_sha256,
        "published_scores_sha256": published_scores_sha256,
        "suites": [],
    }
    if serving_summary_path is not None:
        run_record["serving_summary_path"] = str(serving_summary_path)
    if responses_base_url is not None:
        run_record["responses_base_url"] = responses_base_url
    if chat_base_url is not None:
        run_record["chat_base_url"] = chat_base_url
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode=mode,
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    _complete_evalrun_materialization(result_dir)

    summaries = []
    suite_records = []
    for suite in selected:
        suite_dir = result_dir / suite["id"]
        suite_dir.mkdir(parents=True, exist_ok=True)
        if can_resume_run and _fixture_suite_complete(suite_dir, suite["id"]):
            metrics = _read_json_object(suite_dir / "metrics.json")
            suite_status = "resumed"
            _complete_evalrun_trial_generation(
                result_dir=result_dir,
                suite_dir=suite_dir,
                suite_id=suite["id"],
                tasks_total=metrics["tasks_total"],
            )
        else:
            _begin_evalrun_suite(result_dir, suite["id"])
            samples = _fixture_samples(
                run_id,
                suite,
                execution_backend,
                dataset_cache_root=run_root.parent / "benchmarks",
                prepare_artifact_path=results_root / "prepare" / "prepare.json",
            )
            (suite_dir / "samples.jsonl").write_text(
                "\n".join(json.dumps(sample, sort_keys=True) for sample in samples)
                + "\n"
            )
            (suite_dir / "failures.jsonl").write_text("")
            passed_count = sum(1 for sample in samples if sample["passed"])
            _complete_evalrun_trial_generation(
                result_dir=result_dir,
                suite_dir=suite_dir,
                suite_id=suite["id"],
                tasks_total=len(samples),
            )
            _begin_evalrun_grading(result_dir, suite["id"])
            metrics = {
                "schema_version": 1,
                "suite": suite["id"],
                "tasks_total": len(samples),
                "tasks_passed": passed_count,
                "model_failures": len(samples) - passed_count,
                "infrastructure_failures": 0,
                "infrastructure_failure_denominator": len(samples),
                "infrastructure_failure_rate": 0.0,
                "score": passed_count / len(samples),
            }
            metrics.update(_suite_condition_fields(suite, execution_backend))
            (suite_dir / "metrics.json").write_text(
                json.dumps(metrics, indent=2, sort_keys=True) + "\n"
            )
            suite_status = "completed"
        _complete_evalrun_suite(
            result_dir=result_dir,
            suite_dir=suite_dir,
            suite_id=suite["id"],
            tasks_graded=metrics["tasks_total"],
            status="pass" if metrics["model_failures"] == 0 else "fail",
        )
        summaries.append(metrics)
        suite_records.append(
            {
                "id": suite["id"],
                "status": suite_status,
                "tasks_total": metrics["tasks_total"],
                "tasks_completed": metrics["tasks_passed"],
                "artifact_dir": str(suite_dir),
            }
        )

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "pass",
        "execution_backend": execution_backend,
        "suites": summaries,
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = suite_records
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def write_archive_manifest(
    *,
    result_dir: Path,
    summary: dict[str, Any],
    summary_path: str = "summary.json",
) -> Path:
    artifacts = [
        path
        for path in result_dir.rglob("*")
        if path.is_file() and path.name != "archive-manifest.json"
    ]
    artifact_paths = sorted(str(path.relative_to(result_dir)) for path in artifacts)
    artifact_hashes = {
        str(path.relative_to(result_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifacts
    }
    archive_manifest = {
        "schema_version": 1,
        "run_id": summary["run_id"],
        "summary_status": summary["status"],
        "summary_path": summary_path,
        "terminal": summary["status"] != "running",
        "contract_artifacts": artifact_paths,
        "contract_artifact_sha256": artifact_hashes,
    }
    path = result_dir / "archive-manifest.json"
    path.write_text(json.dumps(archive_manifest, indent=2, sort_keys=True) + "\n")
    return path


def _write_evalplus_samples_file(
    *,
    suite_id: str,
    generated_code_artifact_path: Path,
) -> Path:
    artifact = json.loads(generated_code_artifact_path.read_text())
    case_id = artifact.get("case_id")
    generated_code = artifact.get("generated_code")
    if not isinstance(case_id, str) or not case_id:
        raise BenchmarkVerifierError(
            f"generated-code artifact missing case_id: {generated_code_artifact_path}"
        )
    if not isinstance(generated_code, str):
        raise BenchmarkVerifierError(
            f"generated-code artifact missing generated_code: {generated_code_artifact_path}"
        )
    samples_path = generated_code_artifact_path.with_name(
        f"{generated_code_artifact_path.stem}-evalplus-samples.jsonl"
    )
    samples_path.write_text(
        json.dumps(
            {
                "task_id": case_id,
                "solution": generated_code,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return samples_path


def _run_evalplus_official_harness(
    *,
    suite_id: str,
    generated_code_artifact: str,
    generated_code_artifact_path: Path,
) -> dict[str, Any]:
    samples_path = _write_evalplus_samples_file(
        suite_id=suite_id,
        generated_code_artifact_path=generated_code_artifact_path,
    )
    command = [
        sys.executable,
        "-m",
        "evalplus.evaluate",
        "--dataset",
        suite_id,
        "--samples",
        str(samples_path),
        "--base-only",
    ]
    started_at = time.time()
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env={
                **os.environ,
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        )
        returncode = process.returncode
        stdout = process.stdout
        stderr = process.stderr
        reason = "official EvalPlus runner executed"
        duration_seconds = time.time() - started_at
    except subprocess.TimeoutExpired as error:
        returncode = None
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        reason = "official EvalPlus runner timed out"
        duration_seconds = time.time() - started_at
    return {
        "status": "executed",
        "reason": reason,
        "pass_at_1": None,
        "evidence": {
            "command": command,
            "returncode": returncode,
            "duration_seconds": duration_seconds,
            "generated_code_artifact": generated_code_artifact,
            "samples_path": str(samples_path),
            "stdout": stdout,
            "stderr": stderr,
        },
    }


def _evalplus_official_harness_attempt(
    *,
    suite_id: str,
    generated_code_artifact: str | None,
    generated_code_artifact_path: Path | None,
) -> dict[str, Any]:
    if importlib.util.find_spec("evalplus") is None:
        return {
            "status": "missing_prerequisite",
            "reason": "evalplus package is not installed",
            "prerequisite": {
                "type": "python_import",
                "name": "evalplus",
                "status": "missing",
            },
        }
    if generated_code_artifact is None or generated_code_artifact_path is None:
        return {
            "status": "missing_prerequisite",
            "reason": "generated-code artifact is not available",
            "prerequisite": {
                "type": "artifact",
                "name": "generated_code_artifact",
                "status": "missing",
            },
        }
    return _run_evalplus_official_harness(
        suite_id=suite_id,
        generated_code_artifact=generated_code_artifact,
        generated_code_artifact_path=generated_code_artifact_path,
    )


def _write_evalplus_official_harness_handoff(
    *,
    suite_dir: Path,
    suite: dict[str, Any],
    execution_backend: str,
    generated_code_artifact: str | None,
) -> Path:
    generated_code_artifact_path = (
        suite_dir.parent / generated_code_artifact
        if generated_code_artifact is not None
        else None
    )
    attempt = _evalplus_official_harness_attempt(
        suite_id=suite["id"],
        generated_code_artifact=generated_code_artifact,
        generated_code_artifact_path=generated_code_artifact_path,
    )
    handoff = {
        "schema_version": 1,
        "suite": suite["id"],
        "official_harness": "evalplus",
        "status": attempt["status"],
        "metric": "pass@1",
        "pass_at_1": None,
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "prompt_template": suite["prompt_template"],
        "decoding_profile": suite["decoding_profile"],
        "execution_backend": execution_backend,
        "benchmark_scoring": "fixture_harness",
        "current_scoring": "fixture_harness",
        "reason": attempt["reason"],
        "generated_code_artifact": generated_code_artifact,
        "conformance": {"claim": "none"},
    }
    prerequisite = attempt.get("prerequisite")
    if prerequisite is not None:
        handoff["prerequisite"] = prerequisite
    evidence = attempt.get("evidence")
    if evidence is not None:
        handoff["official_attempt_evidence"] = evidence
    path = suite_dir / "official-harness.json"
    path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n")
    return path


def write_fixture_smoke_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    suite_ids: list[str],
    manifest: dict[str, Any],
    execution_backend: str,
) -> Path:
    return write_fixture_benchmark_run(
        results_root=results_root,
        run_root=run_root,
        run_id=run_id,
        mode="smoke",
        suite_ids=suite_ids,
        manifest=manifest,
        published_scores=None,
        execution_backend=execution_backend,
    )


def write_needle_smoke_responses_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    mode: Literal["smoke", "calibration"] = "smoke",
) -> Path:
    if mode not in {"smoke", "calibration"}:
        raise BenchmarkVerifierError(f"unsupported needle-smoke responses mode: {mode}")
    selected = select_suites(manifest, ["needle-smoke"])
    suite = selected[0]
    validate_suite_fields(suite)
    if suite["execution_backend"] != execution_backend:
        raise BenchmarkVerifierError(
            f"suite {suite['id']} requires backend {suite['execution_backend']}"
        )

    result_dir = results_root / run_id
    suite_dir = result_dir / "needle-smoke"
    result_dir.mkdir(parents=True, exist_ok=True)
    suite_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        suite_ids=["needle-smoke"],
    )
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": mode,
                "execution_backend": execution_backend,
                "responses_base_url": responses_base_url,
                "responses_timeout_seconds": responses_timeout_seconds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(manifest),
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "suites": [],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode=mode,
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )
    _complete_evalrun_materialization(result_dir)

    _begin_evalrun_suite(result_dir, "needle-smoke")
    samples = _needle_smoke_responses_samples(
        run_id=run_id,
        suite=suite,
        execution_backend=execution_backend,
        responses_base_url=responses_base_url,
        responses_timeout_seconds=responses_timeout_seconds,
        model=str(manifest.get("model", "")),
    )
    (suite_dir / "samples.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in samples)
    )
    failures = [sample for sample in samples if not sample["passed"]]
    (suite_dir / "failures.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in failures)
    )

    tasks_total = len(samples)
    tasks_passed = sum(1 for sample in samples if sample["passed"])
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="needle-smoke",
        tasks_total=tasks_total,
    )
    _begin_evalrun_grading(result_dir, "needle-smoke")
    model_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "model"
    )
    infrastructure_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "infrastructure"
    )
    metrics = {
        "schema_version": 1,
        "suite": "needle-smoke",
        "tasks_total": tasks_total,
        "tasks_passed": tasks_passed,
        "model_failures": model_failures,
        "infrastructure_failures": infrastructure_failures,
        "infrastructure_failure_denominator": tasks_total,
        "infrastructure_failure_rate": infrastructure_failures / tasks_total,
        "score": tasks_passed / tasks_total,
    }
    metrics.update(_suite_condition_fields(suite, execution_backend))
    (suite_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="needle-smoke",
        tasks_graded=tasks_total,
        status=_benchmark_status([metrics]),
    )

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": _benchmark_status([metrics]),
        "execution_backend": execution_backend,
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "conformance": {
            "claim": "none",
            "comparable_to_published": False,
        },
        "suites": [metrics],
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = [
        {
            "id": "needle-smoke",
            "status": "completed",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_passed,
            "artifact_dir": str(suite_dir),
        }
    ]
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def write_gsm8k_responses_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    mode: Literal["smoke", "calibration"] = "smoke",
) -> Path:
    if mode not in {"smoke", "calibration"}:
        raise BenchmarkVerifierError(f"unsupported GSM8K responses mode: {mode}")
    selected = select_suites(manifest, ["gsm8k"])
    suite = selected[0]
    validate_suite_fields(suite)
    if suite["execution_backend"] != execution_backend:
        raise BenchmarkVerifierError(
            f"suite {suite['id']} requires backend {suite['execution_backend']}"
        )

    result_dir = results_root / run_id
    suite_dir = result_dir / "gsm8k"
    result_dir.mkdir(parents=True, exist_ok=True)
    suite_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        suite_ids=["gsm8k"],
    )
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": mode,
                "execution_backend": execution_backend,
                "responses_base_url": responses_base_url,
                "responses_timeout_seconds": responses_timeout_seconds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(manifest),
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "suites": [],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode=mode,
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )

    _complete_evalrun_materialization(result_dir)
    _begin_evalrun_suite(result_dir, "gsm8k")
    sample = _gsm8k_responses_sample(
        run_id=run_id,
        suite=suite,
        execution_backend=execution_backend,
        responses_base_url=responses_base_url,
        responses_timeout_seconds=responses_timeout_seconds,
        model=str(manifest.get("model", "")),
        dataset_cache_root=run_root.parent / "benchmarks",
        prepare_artifact_path=results_root / "prepare" / "prepare.json",
    )
    samples = [sample]
    (suite_dir / "samples.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in samples)
    )
    failures = [sample for sample in samples if not sample["passed"]]
    (suite_dir / "failures.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in failures)
    )

    tasks_total = len(samples)
    tasks_passed = sum(1 for sample in samples if sample["passed"])
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="gsm8k",
        tasks_total=tasks_total,
    )
    _begin_evalrun_grading(result_dir, "gsm8k")
    model_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "model"
    )
    infrastructure_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "infrastructure"
    )
    metrics = {
        "schema_version": 1,
        "suite": "gsm8k",
        "tasks_total": tasks_total,
        "tasks_passed": tasks_passed,
        "model_failures": model_failures,
        "infrastructure_failures": infrastructure_failures,
        "infrastructure_failure_denominator": tasks_total,
        "infrastructure_failure_rate": infrastructure_failures / tasks_total,
        "score": tasks_passed / tasks_total,
    }
    metrics.update(_suite_condition_fields(suite, execution_backend))
    (suite_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="gsm8k",
        tasks_graded=tasks_total,
        status=_benchmark_status([metrics]),
    )

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": _benchmark_status([metrics]),
        "execution_backend": execution_backend,
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "conformance": {
            "claim": "none",
            "comparable_to_published": False,
        },
        "suites": [metrics],
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = [
        {
            "id": "gsm8k",
            "status": "completed",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_passed,
            "artifact_dir": str(suite_dir),
        }
    ]
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def write_aime_responses_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    mode: Literal["smoke", "calibration"] = "smoke",
) -> Path:
    if mode not in {"smoke", "calibration"}:
        raise BenchmarkVerifierError(f"unsupported AIME responses mode: {mode}")
    selected = select_suites(manifest, ["aime"])
    suite = selected[0]
    validate_suite_fields(suite)
    if suite["execution_backend"] != execution_backend:
        raise BenchmarkVerifierError(
            f"suite {suite['id']} requires backend {suite['execution_backend']}"
        )

    result_dir = results_root / run_id
    suite_dir = result_dir / "aime"
    result_dir.mkdir(parents=True, exist_ok=True)
    suite_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        suite_ids=["aime"],
    )
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": mode,
                "execution_backend": execution_backend,
                "responses_base_url": responses_base_url,
                "responses_timeout_seconds": responses_timeout_seconds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(manifest),
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "suites": [],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode=mode,
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )

    _complete_evalrun_materialization(result_dir)
    _begin_evalrun_suite(result_dir, "aime")
    sample = _aime_responses_sample(
        run_id=run_id,
        suite=suite,
        execution_backend=execution_backend,
        responses_base_url=responses_base_url,
        responses_timeout_seconds=responses_timeout_seconds,
        model=str(manifest.get("model", "")),
        dataset_cache_root=run_root.parent / "benchmarks",
        prepare_artifact_path=results_root / "prepare" / "prepare.json",
    )
    samples = [sample]
    (suite_dir / "samples.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in samples)
    )
    failures = [sample for sample in samples if not sample["passed"]]
    (suite_dir / "failures.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in failures)
    )

    tasks_total = len(samples)
    tasks_passed = sum(1 for sample in samples if sample["passed"])
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="aime",
        tasks_total=tasks_total,
    )
    _begin_evalrun_grading(result_dir, "aime")
    model_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "model"
    )
    infrastructure_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "infrastructure"
    )
    metrics = {
        "schema_version": 1,
        "suite": "aime",
        "tasks_total": tasks_total,
        "tasks_passed": tasks_passed,
        "model_failures": model_failures,
        "infrastructure_failures": infrastructure_failures,
        "infrastructure_failure_denominator": tasks_total,
        "infrastructure_failure_rate": infrastructure_failures / tasks_total,
        "score": tasks_passed / tasks_total,
    }
    metrics.update(_suite_condition_fields(suite, execution_backend))
    (suite_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="aime",
        tasks_graded=tasks_total,
        status=_benchmark_status([metrics]),
    )

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": _benchmark_status([metrics]),
        "execution_backend": execution_backend,
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "conformance": {
            "claim": "none",
            "comparable_to_published": False,
        },
        "suites": [metrics],
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = [
        {
            "id": "aime",
            "status": "completed",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_passed,
            "artifact_dir": str(suite_dir),
        }
    ]
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def write_humaneval_responses_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    mode: Literal["smoke", "calibration"] = "smoke",
) -> Path:
    if mode not in {"smoke", "calibration"}:
        raise BenchmarkVerifierError(f"unsupported HumanEval responses mode: {mode}")
    selected = select_suites(manifest, ["humaneval"])
    suite = selected[0]
    validate_suite_fields(suite)
    if suite["execution_backend"] != execution_backend:
        raise BenchmarkVerifierError(
            f"suite {suite['id']} requires backend {suite['execution_backend']}"
        )

    result_dir = results_root / run_id
    suite_dir = result_dir / "humaneval"
    result_dir.mkdir(parents=True, exist_ok=True)
    suite_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        suite_ids=["humaneval"],
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": mode,
                "execution_backend": execution_backend,
                "responses_base_url": responses_base_url,
                "responses_timeout_seconds": responses_timeout_seconds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(manifest),
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "suites": [],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode=mode,
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )
    _complete_evalrun_materialization(result_dir)
    _begin_evalrun_suite(result_dir, "humaneval")

    sample = _humaneval_responses_sample(
        run_id=run_id,
        suite=suite,
        execution_backend=execution_backend,
        responses_base_url=responses_base_url,
        responses_timeout_seconds=responses_timeout_seconds,
        model=str(manifest.get("model", "")),
        run_root=run_root,
        result_dir=result_dir,
    )
    samples = [sample]
    (suite_dir / "samples.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in samples)
    )
    failures = [sample for sample in samples if not sample["passed"]]
    (suite_dir / "failures.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in failures)
    )
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="humaneval",
        tasks_total=len(samples),
    )

    tasks_total = len(samples)
    tasks_passed = sum(1 for sample in samples if sample["passed"])
    model_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "model"
    )
    infrastructure_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "infrastructure"
    )
    metrics = {
        "schema_version": 1,
        "suite": "humaneval",
        "tasks_total": tasks_total,
        "tasks_passed": tasks_passed,
        "model_failures": model_failures,
        "infrastructure_failures": infrastructure_failures,
        "infrastructure_failure_denominator": tasks_total,
        "infrastructure_failure_rate": infrastructure_failures / tasks_total,
        "score": tasks_passed / tasks_total if all(
            sample.get("benchmark_scoring") == "fixture_harness" for sample in samples
        ) else None,
        "benchmark_scoring": "fixture_harness" if all(
            sample.get("benchmark_scoring") == "fixture_harness" for sample in samples
        ) else "not_run",
        "pass_at_1": None,
    }
    metrics.update(_suite_condition_fields(suite, execution_backend))
    _begin_evalrun_grading(result_dir, "humaneval")
    (suite_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    contract_artifacts = sample.get("contract_artifacts", {})
    _write_evalplus_official_harness_handoff(
        suite_dir=suite_dir,
        suite=suite,
        execution_backend=execution_backend,
        generated_code_artifact=contract_artifacts.get("codegen_artifact")
        if isinstance(contract_artifacts, dict)
        else None,
    )

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": _benchmark_status([metrics]),
        "execution_backend": execution_backend,
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "conformance": {
            "claim": "none",
            "comparable_to_published": False,
        },
        "suites": [metrics],
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = [
        {
            "id": "humaneval",
            "status": "completed",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_passed,
            "artifact_dir": str(suite_dir),
        }
    ]
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="humaneval",
        tasks_graded=tasks_total,
        status=summary["status"],
        summary_artifacts=[
            str((suite_dir / "metrics.json").relative_to(result_dir)),
            str((suite_dir / "official-harness.json").relative_to(result_dir)),
        ],
    )
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def write_mbpp_responses_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    mode: Literal["smoke", "calibration"] = "smoke",
) -> Path:
    if mode not in {"smoke", "calibration"}:
        raise BenchmarkVerifierError(f"unsupported MBPP responses mode: {mode}")
    selected = select_suites(manifest, ["mbpp"])
    suite = selected[0]
    validate_suite_fields(suite)
    if suite["execution_backend"] != execution_backend:
        raise BenchmarkVerifierError(
            f"suite {suite['id']} requires backend {suite['execution_backend']}"
        )

    result_dir = results_root / run_id
    suite_dir = result_dir / "mbpp"
    result_dir.mkdir(parents=True, exist_ok=True)
    suite_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        suite_ids=["mbpp"],
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": mode,
                "execution_backend": execution_backend,
                "responses_base_url": responses_base_url,
                "responses_timeout_seconds": responses_timeout_seconds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(manifest),
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "suites": [],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode=mode,
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )
    _complete_evalrun_materialization(result_dir)
    _begin_evalrun_suite(result_dir, "mbpp")

    sample = _mbpp_responses_sample(
        run_id=run_id,
        suite=suite,
        execution_backend=execution_backend,
        responses_base_url=responses_base_url,
        responses_timeout_seconds=responses_timeout_seconds,
        model=str(manifest.get("model", "")),
        run_root=run_root,
        result_dir=result_dir,
    )
    samples = [sample]
    (suite_dir / "samples.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in samples)
    )
    failures = [sample for sample in samples if not sample["passed"]]
    (suite_dir / "failures.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in failures)
    )
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="mbpp",
        tasks_total=len(samples),
    )

    tasks_total = len(samples)
    tasks_passed = sum(1 for sample in samples if sample["passed"])
    model_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "model"
    )
    infrastructure_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "infrastructure"
    )
    metrics = {
        "schema_version": 1,
        "suite": "mbpp",
        "tasks_total": tasks_total,
        "tasks_passed": tasks_passed,
        "model_failures": model_failures,
        "infrastructure_failures": infrastructure_failures,
        "infrastructure_failure_denominator": tasks_total,
        "infrastructure_failure_rate": infrastructure_failures / tasks_total,
        "score": tasks_passed / tasks_total if all(
            sample.get("benchmark_scoring") == "fixture_harness" for sample in samples
        ) else None,
        "benchmark_scoring": "fixture_harness" if all(
            sample.get("benchmark_scoring") == "fixture_harness" for sample in samples
        ) else "not_run",
        "pass_at_1": None,
    }
    metrics.update(_suite_condition_fields(suite, execution_backend))
    _begin_evalrun_grading(result_dir, "mbpp")
    (suite_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    contract_artifacts = sample.get("contract_artifacts", {})
    _write_evalplus_official_harness_handoff(
        suite_dir=suite_dir,
        suite=suite,
        execution_backend=execution_backend,
        generated_code_artifact=contract_artifacts.get("codegen_artifact")
        if isinstance(contract_artifacts, dict)
        else None,
    )

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": _benchmark_status([metrics]),
        "execution_backend": execution_backend,
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "conformance": {
            "claim": "none",
            "comparable_to_published": False,
        },
        "suites": [metrics],
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = [
        {
            "id": "mbpp",
            "status": "completed",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_passed,
            "artifact_dir": str(suite_dir),
        }
    ]
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="mbpp",
        tasks_graded=tasks_total,
        status=summary["status"],
        summary_artifacts=[
            str((suite_dir / "metrics.json").relative_to(result_dir)),
            str((suite_dir / "official-harness.json").relative_to(result_dir)),
        ],
    )
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def write_ruler_responses_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    manifest: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    mode: Literal["smoke", "calibration"] = "smoke",
) -> Path:
    if mode not in {"smoke", "calibration"}:
        raise BenchmarkVerifierError(f"unsupported RULER responses mode: {mode}")
    selected = select_suites(manifest, ["ruler"])
    suite = selected[0]
    validate_suite_fields(suite)
    if suite["execution_backend"] != execution_backend:
        raise BenchmarkVerifierError(
            f"suite {suite['id']} requires backend {suite['execution_backend']}"
        )

    result_dir = results_root / run_id
    suite_dir = result_dir / "ruler"
    result_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        suite_ids=["ruler"],
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "mode": mode,
                "execution_backend": execution_backend,
                "responses_base_url": responses_base_url,
                "responses_timeout_seconds": responses_timeout_seconds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(manifest),
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "suites": [],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode=mode,
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )
    _complete_evalrun_materialization(result_dir)
    _begin_evalrun_suite(result_dir, "ruler")

    sample = _ruler_responses_sample(
        run_id=run_id,
        suite=suite,
        execution_backend=execution_backend,
        responses_base_url=responses_base_url,
        responses_timeout_seconds=responses_timeout_seconds,
        model=str(manifest.get("model", "")),
        dataset_cache_root=run_root.parent / "benchmarks",
        prepare_artifact_path=results_root / "prepare" / "prepare.json",
    )
    samples = [sample]

    suite_dir.mkdir(parents=True, exist_ok=True)

    (suite_dir / "samples.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in samples)
    )
    failures = [sample for sample in samples if not sample["passed"]]
    (suite_dir / "failures.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in failures)
    )
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="ruler",
        tasks_total=len(samples),
    )

    tasks_total = len(samples)
    tasks_passed = sum(1 for sample in samples if sample["passed"])
    model_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "model"
    )
    infrastructure_failures = sum(
        1
        for sample in samples
        if not sample["passed"] and sample["failure_category"] == "infrastructure"
    )
    metrics = {
        "schema_version": 1,
        "suite": "ruler",
        "tasks_total": tasks_total,
        "tasks_passed": tasks_passed,
        "model_failures": model_failures,
        "infrastructure_failures": infrastructure_failures,
        "infrastructure_failure_denominator": tasks_total,
        "infrastructure_failure_rate": infrastructure_failures / tasks_total,
        "score": tasks_passed / tasks_total,
    }
    metrics.update(_suite_condition_fields(suite, execution_backend))
    _begin_evalrun_grading(result_dir, "ruler")
    (suite_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": _benchmark_status([metrics]),
        "execution_backend": execution_backend,
        "responses_base_url": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "conformance": {
            "claim": "none",
            "comparable_to_published": False,
        },
        "suites": [metrics],
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = [
        {
            "id": "ruler",
            "status": "completed",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_passed,
            "artifact_dir": str(suite_dir),
        }
    ]
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=suite_dir,
        suite_id="ruler",
        tasks_graded=tasks_total,
        status=summary["status"],
    )
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def _needle_smoke_responses_samples(
    *,
    run_id: str,
    suite: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float,
    model: str,
) -> list[dict[str, Any]]:
    needle_key = "deployment_cleanup_token"
    needle_value = "ORCHID-7194"
    samples = []
    for position in ("beginning", "middle", "end"):
        prompt = _needle_smoke_prompt(position, needle_key, needle_value)
        started_at = time.monotonic()
        request_error = None
        try:
            response = _post_responses_request(
                responses_base_url=responses_base_url,
                model=model,
                prompt=prompt,
                decoding_profile=suite["decoding_profile"],
                timeout_seconds=responses_timeout_seconds,
            )
            latency_seconds = time.monotonic() - started_at
            raw_response = _responses_output_text(response)
            extracted_answer = raw_response.strip()
            passed = extracted_answer == needle_value
            state = "passed" if passed else "wrong_answer"
            failure_category = _failure_category(state)
            usage = response.get("usage", {})
        except (BenchmarkVerifierError, OSError, urllib.error.URLError) as error:
            request_error = str(error)
            latency_seconds = time.monotonic() - started_at
            raw_response = ""
            extracted_answer = ""
            passed = False
            state = "environment_crashed"
            failure_category = "infrastructure"
            usage = {}
        sample = {
            "suite": "needle-smoke",
            "case_id": f"needle-smoke/{position}",
            "profile": suite["profile"],
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_template": suite["prompt_template"],
            "prompt_template_sha256": hashlib.sha256(
                suite["prompt_template"].encode()
            ).hexdigest(),
            "prompt": prompt,
            "needle_key": needle_key,
            "needle_position": position,
            "raw_response": raw_response,
            "response": raw_response,
            "parsed_answer": extracted_answer,
            "extracted_answer": extracted_answer,
            "expected_answer": needle_value,
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "state": state,
            "failure_category": failure_category,
            "latency_seconds": latency_seconds,
            "usage": usage if isinstance(usage, dict) else {},
            "endpoint": responses_base_url,
            "responses_timeout_seconds": responses_timeout_seconds,
            "decoding": suite["decoding_profile"],
            "decoding_profile": suite["decoding_profile"],
            "dataset_revision": suite["dataset_revision"],
            "harness_revision": suite["harness_revision"],
            "execution_backend": execution_backend,
            "metric": suite["metric"],
            "run_id": run_id,
        }
        if request_error is not None:
            sample["error"] = request_error
        samples.append(sample)
    return samples


def _gsm8k_responses_sample(
    *,
    run_id: str,
    suite: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float,
    model: str,
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> dict[str, Any]:
    dataset_sample = _load_cached_gsm8k_sample(
        suite=suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    )
    if dataset_sample is None:
        raise BenchmarkVerifierError(
            "GSM8K responses run requires a materialized dataset cache sample"
        )
    sample_id = _gsm8k_sample_id(dataset_sample)
    question = dataset_sample.get("question")
    answer = dataset_sample.get("answer")
    if not isinstance(question, str) or not question.strip():
        raise BenchmarkVerifierError("GSM8K dataset sample missing question")
    if not isinstance(answer, str) or not answer.strip():
        raise BenchmarkVerifierError("GSM8K dataset sample missing answer")
    prompt = _gsm8k_prompt(question)
    expected_answer = extract_static_final_answer("gsm8k", answer)
    started_at = time.monotonic()
    request_error = None
    try:
        response = _post_responses_request(
            responses_base_url=responses_base_url,
            model=model,
            prompt=prompt,
            decoding_profile=suite["decoding_profile"],
            timeout_seconds=responses_timeout_seconds,
        )
        latency_seconds = time.monotonic() - started_at
        raw_response = _responses_output_text(response)
        usage = response.get("usage", {})
    except (BenchmarkVerifierError, OSError, urllib.error.URLError) as error:
        request_error = str(error)
        latency_seconds = time.monotonic() - started_at
        raw_response = ""
        extracted_answer = ""
        passed = False
        state = "environment_crashed"
        failure_category = "infrastructure"
        usage = {}
    else:
        try:
            extracted_answer = extract_static_final_answer("gsm8k", raw_response)
            passed = extracted_answer == expected_answer
            state = "passed" if passed else "wrong_answer"
            failure_category = _failure_category(state)
        except BenchmarkVerifierError as error:
            request_error = str(error)
            extracted_answer = ""
            passed = False
            state = "wrong_answer"
            failure_category = "model"
    sample = {
        "suite": "gsm8k",
        "case_id": f"gsm8k/{sample_id}",
        "dataset_sample_id": sample_id,
        "profile": suite["profile"],
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt": prompt,
        "prompt_template": suite["prompt_template"],
        "prompt_template_sha256": hashlib.sha256(
            suite["prompt_template"].encode()
        ).hexdigest(),
        "raw_response": raw_response,
        "response": raw_response,
        "parsed_answer": extracted_answer,
        "extracted_answer": extracted_answer,
        "expected_answer": expected_answer,
        "normalization": {
            "kind": "gsm8k_final_answer",
            "normalized_answer": extracted_answer,
            "expected_normalized_answer": expected_answer,
        },
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "state": state,
        "failure_category": failure_category,
        "latency_seconds": latency_seconds,
        "usage": usage if isinstance(usage, dict) else {},
        "endpoint": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "execution_backend": execution_backend,
        "metric": suite["metric"],
        "run_id": run_id,
    }
    if request_error is not None:
        sample["error"] = request_error
    return sample


def _aime_responses_sample(
    *,
    run_id: str,
    suite: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float,
    model: str,
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> dict[str, Any]:
    dataset_sample = _load_cached_aime_sample(
        suite=suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    )
    if dataset_sample is None:
        raise BenchmarkVerifierError(
            "AIME responses run requires a materialized dataset cache sample"
        )
    sample_id = _aime_sample_id(dataset_sample)
    prompt = _aime_sample_prompt(dataset_sample)
    answer = dataset_sample.get("answer")
    if not isinstance(prompt, str) or not prompt.strip():
        raise BenchmarkVerifierError("AIME dataset sample missing prompt")
    if not isinstance(answer, str) and not isinstance(answer, int):
        raise BenchmarkVerifierError("AIME dataset sample missing answer")
    prompt = _aime_prompt(prompt)
    expected_answer = extract_static_final_answer("aime", str(answer))
    started_at = time.monotonic()
    request_error = None
    try:
        response = _post_responses_request(
            responses_base_url=responses_base_url,
            model=model,
            prompt=prompt,
            decoding_profile=suite["decoding_profile"],
            timeout_seconds=responses_timeout_seconds,
        )
        latency_seconds = time.monotonic() - started_at
        raw_response = _responses_output_text(response)
        usage = response.get("usage", {})
    except (BenchmarkVerifierError, OSError, urllib.error.URLError) as error:
        request_error = str(error)
        latency_seconds = time.monotonic() - started_at
        raw_response = ""
        extracted_answer = ""
        passed = False
        state = "environment_crashed"
        failure_category = "infrastructure"
        usage = {}
    else:
        try:
            extracted_answer = extract_static_final_answer("aime", raw_response)
            passed = extracted_answer == expected_answer
            state = "passed" if passed else "wrong_answer"
            failure_category = _failure_category(state)
        except BenchmarkVerifierError as error:
            request_error = str(error)
            extracted_answer = ""
            passed = False
            state = "wrong_answer"
            failure_category = "model"
    sample = {
        "suite": "aime",
        "case_id": f"aime/{sample_id}",
        "dataset_sample_id": sample_id,
        "profile": suite["profile"],
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt": prompt,
        "prompt_template": suite["prompt_template"],
        "prompt_template_sha256": hashlib.sha256(
            suite["prompt_template"].encode()
        ).hexdigest(),
        "raw_response": raw_response,
        "response": raw_response,
        "parsed_answer": extracted_answer,
        "extracted_answer": extracted_answer,
        "expected_answer": expected_answer,
        "normalization": {
            "kind": "aime_integer_answer",
            "normalized_answer": extracted_answer,
            "expected_normalized_answer": expected_answer,
        },
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "state": state,
        "failure_category": failure_category,
        "latency_seconds": latency_seconds,
        "usage": usage if isinstance(usage, dict) else {},
        "endpoint": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "execution_backend": execution_backend,
        "metric": suite["metric"],
        "run_id": run_id,
    }
    if request_error is not None:
        sample["error"] = request_error
    return sample


def _humaneval_responses_sample(
    *,
    run_id: str,
    suite: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float,
    model: str,
    run_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    case_id = "HumanEval/0"
    prompt = _python_code_prompt(
        "Write a Python function named add that returns the sum of two numbers."
    )
    started_at = time.monotonic()
    request_error = None
    contract_artifacts = {}
    generated_code = None
    stdout = ""
    stderr = ""
    scoring = "not_run"
    try:
        response = _post_responses_request(
            responses_base_url=responses_base_url,
            model=model,
            prompt=prompt,
            decoding_profile=suite["decoding_profile"],
            timeout_seconds=responses_timeout_seconds,
        )
        latency_seconds = time.monotonic() - started_at
        raw_response = _responses_output_text(response)
        usage = response.get("usage", {})
        completion_text = _extract_python_completion_text(raw_response)
        if completion_text.strip():
            task_result = _run_bwrap_codegen_fixture_score(
                run_root=run_root,
                run_id=run_id,
                task_id="humaneval-001",
                suite_id="humaneval",
                case_id=case_id,
                completion_text=completion_text,
            )
            task_root = Path(str(task_result["task_root"]))
            artifact_path = task_result.get("artifact_path")
            artifact = {}
            if isinstance(artifact_path, str) and artifact_path:
                artifact = _read_json_object(Path(artifact_path))
                contract_artifacts = _archive_bwrap_codegen_artifacts(
                    result_dir=result_dir,
                    suite_dir=result_dir / "humaneval",
                    task_root=task_root,
                    result=task_result,
                )
            passed = bool(task_result.get("passed"))
            state = _task_result_state(task_result)
            generated_code = str(artifact.get("generated_code", completion_text))
            stdout = str(task_result.get("stdout", ""))
            stderr = str(task_result.get("stderr", ""))
            scoring = str(artifact.get("scoring", "fixture_harness"))
            latency_seconds += float(task_result.get("latency_seconds", 0.0))
        else:
            passed = False
            state = "wrong_answer"
        failure_category = _failure_category(state)
    except (BenchmarkVerifierError, OSError, urllib.error.URLError) as error:
        request_error = str(error)
        latency_seconds = time.monotonic() - started_at
        raw_response = ""
        usage = {}
        passed = False
        state = "environment_crashed"
        failure_category = "infrastructure"
    sample = {
        "suite": "humaneval",
        "case_id": case_id,
        "profile": suite["profile"],
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt": prompt,
        "prompt_template": suite["prompt_template"],
        "prompt_template_sha256": hashlib.sha256(
            suite["prompt_template"].encode()
        ).hexdigest(),
        "raw_response": raw_response,
        "response": raw_response,
        "completion_text": _extract_python_completion_text(raw_response),
        "passed": passed,
        "score": 1.0 if scoring == "fixture_harness" and passed else 0.0 if scoring == "fixture_harness" else None,
        "state": state,
        "failure_category": failure_category,
        "benchmark_scoring": scoring,
        "pass_at_1": None,
        "latency_seconds": latency_seconds,
        "usage": usage if isinstance(usage, dict) else {},
        "endpoint": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "execution_backend": execution_backend,
        "metric": suite["metric"],
        "run_id": run_id,
    }
    if generated_code is not None:
        sample["generated_code"] = generated_code
        sample["stdout"] = stdout
        sample["stderr"] = stderr
    if contract_artifacts:
        sample["contract_artifacts"] = contract_artifacts
    if request_error is not None:
        sample["error"] = request_error
    return sample


def _mbpp_responses_sample(
    *,
    run_id: str,
    suite: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float,
    model: str,
    run_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    case_id = "MBPP/0"
    prompt = _python_code_prompt(
        "Write a Python function named remove_Occ that removes the first occurrence of a character from a string."
    )
    started_at = time.monotonic()
    request_error = None
    contract_artifacts = {}
    generated_code = None
    stdout = ""
    stderr = ""
    scoring = "not_run"
    try:
        response = _post_responses_request(
            responses_base_url=responses_base_url,
            model=model,
            prompt=prompt,
            decoding_profile=suite["decoding_profile"],
            timeout_seconds=responses_timeout_seconds,
        )
        latency_seconds = time.monotonic() - started_at
        raw_response = _responses_output_text(response)
        usage = response.get("usage", {})
        completion_text = _extract_python_completion_text(raw_response)
        if completion_text.strip():
            task_result = _run_bwrap_codegen_fixture_score(
                run_root=run_root,
                run_id=run_id,
                task_id="mbpp-001",
                suite_id="mbpp",
                case_id=case_id,
                completion_text=completion_text,
            )
            task_root = Path(str(task_result["task_root"]))
            artifact_path = task_result.get("artifact_path")
            artifact = {}
            if isinstance(artifact_path, str) and artifact_path:
                artifact = _read_json_object(Path(artifact_path))
                contract_artifacts = _archive_bwrap_codegen_artifacts(
                    result_dir=result_dir,
                    suite_dir=result_dir / "mbpp",
                    task_root=task_root,
                    result=task_result,
                )
            passed = bool(task_result.get("passed"))
            state = _task_result_state(task_result)
            generated_code = str(artifact.get("generated_code", completion_text))
            stdout = str(task_result.get("stdout", ""))
            stderr = str(task_result.get("stderr", ""))
            scoring = str(artifact.get("scoring", "fixture_harness"))
            latency_seconds += float(task_result.get("latency_seconds", 0.0))
        else:
            passed = False
            state = "wrong_answer"
        failure_category = _failure_category(state)
    except (BenchmarkVerifierError, OSError, urllib.error.URLError) as error:
        request_error = str(error)
        latency_seconds = time.monotonic() - started_at
        raw_response = ""
        usage = {}
        passed = False
        state = "environment_crashed"
        failure_category = "infrastructure"
    sample = {
        "suite": "mbpp",
        "case_id": case_id,
        "profile": suite["profile"],
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt": prompt,
        "prompt_template": suite["prompt_template"],
        "prompt_template_sha256": hashlib.sha256(
            suite["prompt_template"].encode()
        ).hexdigest(),
        "raw_response": raw_response,
        "response": raw_response,
        "completion_text": _extract_python_completion_text(raw_response),
        "passed": passed,
        "score": 1.0 if scoring == "fixture_harness" and passed else 0.0 if scoring == "fixture_harness" else None,
        "state": state,
        "failure_category": failure_category,
        "benchmark_scoring": scoring,
        "pass_at_1": None,
        "latency_seconds": latency_seconds,
        "usage": usage if isinstance(usage, dict) else {},
        "endpoint": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "execution_backend": execution_backend,
        "metric": suite["metric"],
        "run_id": run_id,
    }
    if generated_code is not None:
        sample["generated_code"] = generated_code
        sample["stdout"] = stdout
        sample["stderr"] = stderr
    if contract_artifacts:
        sample["contract_artifacts"] = contract_artifacts
    if request_error is not None:
        sample["error"] = request_error
    return sample


def _run_bwrap_codegen_fixture_score(
    *,
    run_root: Path,
    run_id: str,
    task_id: str,
    suite_id: str,
    case_id: str,
    completion_text: str,
) -> dict[str, Any]:
    command = [
        "scripts/run_glm52_bwrap_task_runner.sh",
        "codegen-smoke",
        "--run-id",
        run_id,
        "--task-id",
        task_id,
        "--suite",
        suite_id,
        "--case-id",
        case_id,
        "--base-dir",
        str(run_root / "bwrap"),
        "--cleanup-ledger",
        str(run_root / f"cleanup-{run_id}.json"),
        "--completion-text",
        completion_text,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return {
            "suite": suite_id,
            "case_id": case_id,
            "task_root": str(run_root / "bwrap" / run_id / task_id),
            "passed": False,
            "state": "environment_crashed",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    return _bwrap_codegen_task_result_from_completed(
        completed=completed,
        run_root=run_root,
        run_id=run_id,
        task_id=task_id,
        suite_id=suite_id,
        case_id=case_id,
    )


def _ruler_responses_sample(
    *,
    run_id: str,
    suite: dict[str, Any],
    execution_backend: str,
    responses_base_url: str,
    responses_timeout_seconds: float,
    model: str,
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> dict[str, Any]:
    dataset_sample = _load_cached_ruler_sample(
        suite=suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    )
    if dataset_sample is None:
        raise BenchmarkVerifierError(
            "RULER responses run requires a materialized dataset cache sample"
        )
    sample_id = _ruler_sample_id(dataset_sample)
    prompt = _ruler_sample_prompt(dataset_sample)
    expected_answer = _ruler_expected_answer(dataset_sample)
    if prompt is None:
        raise BenchmarkVerifierError("RULER dataset sample missing prompt")
    if expected_answer is None:
        raise BenchmarkVerifierError("RULER dataset sample missing expected answer")
    started_at = time.monotonic()
    request_error = None
    try:
        response = _post_responses_request(
            responses_base_url=responses_base_url,
            model=model,
            prompt=prompt,
            decoding_profile=suite["decoding_profile"],
            timeout_seconds=responses_timeout_seconds,
        )
        latency_seconds = time.monotonic() - started_at
        raw_response = _responses_output_text(response)
        extracted_answer = raw_response.strip()
        passed = extracted_answer == expected_answer
        state = "passed" if passed else "wrong_answer"
        failure_category = _failure_category(state)
        usage = response.get("usage", {})
    except (BenchmarkVerifierError, OSError, urllib.error.URLError) as error:
        request_error = str(error)
        latency_seconds = time.monotonic() - started_at
        raw_response = ""
        extracted_answer = ""
        passed = False
        state = "environment_crashed"
        failure_category = "infrastructure"
        usage = {}
    sample = {
        "suite": "ruler",
        "case_id": f"ruler/{sample_id}",
        "dataset_sample_id": sample_id,
        "profile": suite["profile"],
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt": prompt,
        "prompt_template": suite["prompt_template"],
        "prompt_template_sha256": hashlib.sha256(
            suite["prompt_template"].encode()
        ).hexdigest(),
        "raw_response": raw_response,
        "response": raw_response,
        "parsed_answer": extracted_answer,
        "extracted_answer": extracted_answer,
        "expected_answer": expected_answer,
        "normalization": {
            "kind": "ruler_exact_match",
            "normalized_answer": extracted_answer,
            "expected_normalized_answer": expected_answer,
        },
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "state": state,
        "failure_category": failure_category,
        "latency_seconds": latency_seconds,
        "usage": usage if isinstance(usage, dict) else {},
        "endpoint": responses_base_url,
        "responses_timeout_seconds": responses_timeout_seconds,
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "execution_backend": execution_backend,
        "metric": suite["metric"],
        "run_id": run_id,
    }
    needle = dataset_sample.get("needle")
    if isinstance(needle, str) and needle.strip():
        sample["needle"] = needle.strip()
    key = dataset_sample.get("key")
    if isinstance(key, str) and key.strip():
        sample["key"] = key.strip()
    if request_error is not None:
        sample["error"] = request_error
    return sample


def _post_responses_request(
    *,
    responses_base_url: str,
    model: str,
    prompt: str,
    decoding_profile: dict[str, Any],
    timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "input": prompt,
        "temperature": decoding_profile.get("temperature", 0),
        "top_p": decoding_profile.get("top_p", 1),
        "max_output_tokens": decoding_profile.get("max_output_tokens", 256),
    }
    request = urllib.request.Request(
        responses_base_url.rstrip("/") + "/responses",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise BenchmarkVerifierError(
            f"Responses request failed with HTTP {error.code}: {detail}"
        ) from error
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise BenchmarkVerifierError("Responses endpoint returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise BenchmarkVerifierError("Responses endpoint returned non-object JSON")
    return parsed


def _responses_output_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = response.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    raise BenchmarkVerifierError("Responses endpoint returned no output text")


def _gsm8k_prompt(question: str) -> str:
    return (
        question.strip()
        + "\n\nEnd your response with a final line exactly in this format: #### <answer>."
    )


def _aime_prompt(prompt: str) -> str:
    return (
        prompt.strip()
        + "\n\nEnd your response with the final integer answer and no other trailing numbers."
    )


def _python_code_prompt(instruction: str) -> str:
    return (
        instruction.strip()
        + "\n\nReturn only valid Python code. Do not include Markdown fences or prose."
    )


def _extract_python_completion_text(raw_response: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(?P<code>.*?)```", raw_response, re.DOTALL | re.IGNORECASE)
    if match is None:
        return raw_response
    return match.group("code")


def _materialize_bwrap_codegen_evalrun(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    suite_ids: list[str],
    manifest: dict[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    result_dir = results_root / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode="smoke",
        manifest=manifest,
        suite_ids=suite_ids,
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "smoke",
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(manifest),
        "suites": [],
    }
    cleanup = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode="smoke",
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )
    _complete_evalrun_materialization(result_dir)
    return result_dir, run_record, cleanup


def write_bwrap_codegen_smoke_run(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    suite_ids: list[str],
    manifest: dict[str, Any],
    task_results: list[dict[str, Any]],
) -> Path:
    selected = select_suites(manifest, suite_ids)
    selected_ids = {suite["id"] for suite in selected}
    for suite in selected:
        validate_suite_fields(suite)
        if suite["execution_backend"] != "bwrap_rootfs":
            raise BenchmarkVerifierError(
                f"suite {suite['id']} requires backend {suite['execution_backend']}"
            )
    result_dir, run_record, cleanup = _materialize_bwrap_codegen_evalrun(
        results_root=results_root,
        run_root=run_root,
        run_id=run_id,
        suite_ids=suite_ids,
        manifest=manifest,
    )
    summaries = []
    suite_records = []
    for suite_id in suite_ids:
        suite_results = [result for result in task_results if result.get("suite") == suite_id]
        if not suite_results:
            raise BenchmarkVerifierError(f"missing bwrap task result for suite: {suite_id}")
        suite_dir = result_dir / suite_id
        suite_dir.mkdir(parents=True, exist_ok=True)
        _begin_evalrun_suite(result_dir, suite_id)
        sample_lines = []
        failure_lines = []
        suite = _suite_by_id(selected, suite_id)
        for result in suite_results:
            if result.get("suite") not in selected_ids:
                raise BenchmarkVerifierError(f"unexpected suite result: {result.get('suite')}")
            task_root = result.get("task_root")
            if not isinstance(task_root, str) or not task_root:
                raise BenchmarkVerifierError(f"task result missing task_root: {result!r}")
            passed = bool(result.get("passed"))
            case_id = result.get("case_id")
            state = _task_result_state(result)
            failure_category = _failure_category(state)
            prompt_identity = {
                "suite": suite_id,
                "case_id": case_id,
                "prompt_template": suite["prompt_template"],
            }
            contract_artifacts = _archive_bwrap_codegen_artifacts(
                result_dir=result_dir,
                suite_dir=suite_dir,
                task_root=Path(task_root),
                result=result,
            )
            sample = {
                "suite": suite_id,
                "case_id": case_id,
                "profile": suite["profile"],
                "prompt_sha256": _json_sha256(prompt_identity),
                "execution_backend": "bwrap_rootfs",
                "task_root": task_root,
                "passed": passed,
                "state": state,
                "failure_category": failure_category,
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "endpoint": result.get("endpoint", "fixture"),
                "decoding": suite["decoding_profile"],
                "decoding_profile": suite["decoding_profile"],
                "latency_seconds": result.get("latency_seconds", 0.0),
                "usage": result.get("usage", {}),
                "dataset_revision": suite["dataset_revision"],
                "harness_revision": suite["harness_revision"],
            }
            if contract_artifacts:
                sample["contract_artifacts"] = contract_artifacts
            sample_lines.append(json.dumps(sample, sort_keys=True))
            if not passed:
                failure_lines.append(json.dumps(sample, sort_keys=True))
            cleanup["bwrap_tasks"].append(
                {
                    "pid": result.get("pid"),
                    "task_root": task_root,
                    "command_contains": "glm52_bwrap_task_runner",
                }
            )
        (suite_dir / "samples.jsonl").write_text("\n".join(sample_lines) + "\n")
        (suite_dir / "failures.jsonl").write_text(
            ("\n".join(failure_lines) + "\n") if failure_lines else ""
        )
        _complete_evalrun_trial_generation(
            result_dir=result_dir,
            suite_dir=suite_dir,
            suite_id=suite_id,
            tasks_total=len(suite_results),
        )
        passed_count = sum(1 for result in suite_results if result.get("passed"))
        model_failures = sum(
            1
            for result in suite_results
            if not result.get("passed")
            and _failure_category(_task_result_state(result)) == "model"
        )
        infrastructure_failures = sum(
            1
            for result in suite_results
            if not result.get("passed")
            and _failure_category(_task_result_state(result)) == "infrastructure"
        )
        metrics = {
            "schema_version": 1,
            "suite": suite_id,
            "tasks_total": len(suite_results),
            "tasks_passed": passed_count,
            "model_failures": model_failures,
            "infrastructure_failures": infrastructure_failures,
            "infrastructure_failure_denominator": len(suite_results),
            "infrastructure_failure_rate": infrastructure_failures / len(suite_results),
            "score": passed_count / len(suite_results),
        }
        metrics.update(_suite_condition_fields(suite, "bwrap_rootfs"))
        _begin_evalrun_grading(result_dir, suite_id)
        (suite_dir / "metrics.json").write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n"
        )
        _complete_evalrun_suite(
            result_dir=result_dir,
            suite_dir=suite_dir,
            suite_id=suite_id,
            tasks_graded=metrics["tasks_total"],
            status=_benchmark_status([metrics]),
        )
        summaries.append(metrics)
        suite_records.append(
            {
                "id": suite_id,
                "status": "completed",
                "tasks_total": metrics["tasks_total"],
                "tasks_completed": metrics["tasks_passed"],
                "artifact_dir": str(suite_dir),
            }
        )

    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup, indent=2, sort_keys=True) + "\n"
    )
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "smoke",
        "status": _benchmark_status(summaries),
        "execution_backend": "bwrap_rootfs",
        "suites": summaries,
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record["status"] = "completed"
    run_record["suites"] = suite_records
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=summary["status"])
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def _archive_bwrap_codegen_artifacts(
    *,
    result_dir: Path,
    suite_dir: Path,
    task_root: Path,
    result: dict[str, Any],
) -> dict[str, str]:
    artifact_path = result.get("artifact_path")
    if not isinstance(artifact_path, str) or not artifact_path:
        return {}
    source = Path(artifact_path)
    if not source.is_file():
        return {}
    artifacts_dir = suite_dir / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    destination = artifacts_dir / f"{task_root.name}-{source.name}"
    shutil.copy2(source, destination)
    return {"codegen_artifact": str(destination.relative_to(result_dir))}


def _suite_by_id(suites: list[dict[str, Any]], suite_id: str) -> dict[str, Any]:
    for suite in suites:
        if suite["id"] == suite_id:
            return suite
    raise BenchmarkVerifierError(f"unknown suite: {suite_id}")


def _task_result_state(result: dict[str, Any]) -> str:
    if result.get("passed"):
        return "passed"
    state = result.get("state")
    if isinstance(state, str) and state:
        return state
    return "task_failed"


def _failure_category(state: str) -> str | None:
    if state == "passed":
        return None
    if state in {
        "environment_setup_failed",
        "environment_crashed",
        "grader_failed",
        "cancelled",
        "skipped",
    }:
        return "infrastructure"
    return "model"


def _benchmark_status(summaries: list[dict[str, Any]]) -> str:
    if any(summary["infrastructure_failures"] for summary in summaries):
        return "environment_failed"
    if any(summary["model_failures"] for summary in summaries):
        return "fail"
    return "pass"


def _json_sha256(payload: dict[str, Any]) -> str:
    return campaign_manifest_sha256(payload)


def _begin_evalrun_state(
    *,
    result_dir: Path,
    run_id: str,
    mode: str,
    manifest: dict[str, Any],
    suite_ids: list[str],
) -> bool:
    manifest_sha256 = _json_sha256(manifest)
    if _result_dir_has_artifacts(result_dir):
        try:
            resume_eval_run_state(
                result_dir=result_dir,
                manifest_sha256=manifest_sha256,
                run_id=run_id,
                mode=mode,
                suite_ids=suite_ids,
            )
        except EvalRunStateError as error:
            raise BenchmarkVerifierError(str(error)) from error
        return True
    begin_campaign_materialization(
        result_dir=result_dir,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        mode=mode,
        suite_ids=suite_ids,
    )
    return False


def _result_dir_has_artifacts(result_dir: Path) -> bool:
    if not result_dir.exists():
        return False
    return any(path.is_file() for path in result_dir.rglob("*"))


def _complete_evalrun_materialization(result_dir: Path) -> None:
    complete_campaign_materialization(
        result_dir=result_dir,
        artifacts=["benchmark-manifest.json", "environment.json", "run.json"],
    )


def _begin_evalrun_suite(result_dir: Path, suite_id: str) -> None:
    begin_suite_preparation(result_dir=result_dir, suite_id=suite_id)
    complete_suite_preparation(
        result_dir=result_dir,
        suite_id=suite_id,
        artifacts=[],
    )
    begin_trial_generation(
        result_dir=result_dir,
        suite_id=suite_id,
        trials_total=0,
    )


def _complete_evalrun_trial_generation(
    *,
    result_dir: Path,
    suite_dir: Path,
    suite_id: str,
    tasks_total: int,
    samples_artifacts: list[str] | None = None,
) -> None:
    if samples_artifacts is None:
        samples_artifacts = [
            str((suite_dir / "samples.jsonl").relative_to(result_dir)),
            str((suite_dir / "failures.jsonl").relative_to(result_dir)),
        ]
    complete_trial_generation(
        result_dir=result_dir,
        suite_id=suite_id,
        artifacts=samples_artifacts,
        trials_total=tasks_total,
    )


def _begin_evalrun_grading(result_dir: Path, suite_id: str) -> None:
    begin_grading(result_dir=result_dir, suite_id=suite_id)


def _complete_evalrun_suite(
    *,
    result_dir: Path,
    suite_dir: Path,
    suite_id: str,
    tasks_graded: int,
    status: str,
    metrics_artifacts: list[str] | None = None,
    summary_artifacts: list[str] | None = None,
) -> None:
    if metrics_artifacts is None:
        metrics_artifacts = [str((suite_dir / "metrics.json").relative_to(result_dir))]
    if summary_artifacts is None:
        summary_artifacts = metrics_artifacts
    complete_grading(
        result_dir=result_dir,
        suite_id=suite_id,
        artifacts=metrics_artifacts,
        trials_graded=tasks_graded,
    )
    begin_suite_summary(result_dir=result_dir, suite_id=suite_id)
    complete_suite_summary(
        result_dir=result_dir,
        suite_id=suite_id,
        artifacts=summary_artifacts,
        status=status,
    )


def _begin_evalrun_campaign_summary(result_dir: Path) -> None:
    begin_campaign_summary(result_dir=result_dir)


def _complete_evalrun_campaign_summary(
    *,
    result_dir: Path,
    status: str,
    artifacts: list[str] | None = None,
) -> None:
    if artifacts is None:
        artifacts = ["summary.json", "run.json"]
    complete_campaign_summary(
        result_dir=result_dir,
        artifacts=artifacts,
        status=status,
    )


def _harbor_evalrun_manifest(
    *,
    manifest: dict[str, Any] | None,
    suite_id: str,
    smoke_config: dict[str, Any],
) -> dict[str, Any]:
    if manifest is not None:
        return manifest
    return {
        "schema_version": 1,
        "suites": [
            {
                "id": suite_id,
                "execution_backend": "harbor_local_docker",
                "smoke_config_sha256": _json_sha256(smoke_config),
            }
        ],
    }


def _resume_harbor_evalrun_state(
    *,
    result_dir: Path,
    run_id: str,
    suite_id: str,
    smoke_config: dict[str, Any],
) -> None:
    manifest = _read_json_object(result_dir / "benchmark-manifest.json")
    if not manifest:
        manifest = _harbor_evalrun_manifest(
            manifest=None,
            suite_id=suite_id,
            smoke_config=smoke_config,
        )
    try:
        resume_eval_run_state(
            result_dir=result_dir,
            manifest_sha256=_json_sha256(manifest),
            run_id=run_id,
            mode="smoke",
            suite_ids=[suite_id],
        )
    except EvalRunStateError as error:
        raise BenchmarkVerifierError(str(error)) from error


def write_run_lock(
    *,
    run_root: Path,
    run_id: str,
    mode: str,
    status: str,
    created_at: str,
    result_dir: Path,
) -> Path:
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "created_at": created_at,
        "pid": os.getpid(),
        "benchmark_state_path": str(run_root / f"benchmark-{run_id}.json"),
        "cleanup_state_path": str(run_root / f"cleanup-{run_id}.json"),
        "result_dir": str(result_dir),
    }
    path = run_root / f"benchmark-{run_id}.lock"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def finalize_run_lock(*, run_root: Path, run_id: str, status: str) -> None:
    path = run_root / f"benchmark-{run_id}.lock"
    payload = _read_json_object(path)
    if not payload:
        return
    payload["status"] = status
    payload["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _parse_models_response(body: bytes) -> list[str]:
    try:
        payload = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    models = []
    for model in data:
        if isinstance(model, dict) and isinstance(model.get("id"), str):
            models.append(model["id"])
    return models


def _parse_json_command_output(output: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"raw": output}
    if isinstance(payload, dict):
        return payload
    return {"raw": output}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    records = []
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError as error:
        raise BenchmarkVerifierError(f"jsonl artifact not found: {path}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise BenchmarkVerifierError(
                f"invalid jsonl record in {path}:{line_number}: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise BenchmarkVerifierError(
                f"jsonl record in {path}:{line_number} must be an object"
            )
        records.append(payload)
    if not records:
        raise BenchmarkVerifierError(f"jsonl artifact has no records: {path}")
    return records


def validate_harbor_trials(trials: list[dict[str, Any]]) -> None:
    for index, trial in enumerate(trials, start=1):
        missing = sorted(
            field
            for field in REQUIRED_HARBOR_TRIAL_FIELDS
            if not isinstance(trial.get(field), str) or not trial[field].strip()
        )
        if missing:
            trial_id = trial.get("trial_id") or f"record {index}"
            raise BenchmarkVerifierError(
                f"Harbor trial {trial_id} missing fields: {', '.join(missing)}"
            )


def _first_non_empty_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _single_harbor_smoke_task(smoke_config: dict[str, Any]) -> str | None:
    subset = smoke_config.get("subset")
    if not isinstance(subset, dict):
        return None
    smoke_tasks = subset.get("smoke_tasks")
    if (
        isinstance(smoke_tasks, list)
        and len(smoke_tasks) == 1
        and isinstance(smoke_tasks[0], str)
        and smoke_tasks[0].strip()
    ):
        return smoke_tasks[0]
    smoke_instances = subset.get("smoke_instances")
    if (
        isinstance(smoke_instances, list)
        and len(smoke_instances) == 1
        and isinstance(smoke_instances[0], str)
        and smoke_instances[0].strip()
    ):
        return smoke_instances[0]
    return None


def _single_harbor_job_task(job_config: dict[str, Any]) -> str | None:
    datasets = job_config.get("datasets")
    if not isinstance(datasets, list) or len(datasets) != 1:
        return None
    dataset = datasets[0]
    if not isinstance(dataset, dict):
        return None
    task_names = dataset.get("task_names")
    if (
        isinstance(task_names, list)
        and len(task_names) == 1
        and isinstance(task_names[0], str)
        and task_names[0].strip()
    ):
        return task_names[0]
    instance_ids = dataset.get("instance_ids")
    if (
        isinstance(instance_ids, list)
        and len(instance_ids) == 1
        and isinstance(instance_ids[0], str)
        and instance_ids[0].strip()
    ):
        return instance_ids[0]
    return None


def _harbor_model_id_from_agent_info(agent_info: dict[str, Any]) -> str | None:
    model_info = agent_info.get("model_info")
    if not isinstance(model_info, dict):
        return None
    provider = _first_non_empty_string(model_info.get("provider"))
    name = _first_non_empty_string(model_info.get("name"))
    if provider is None or name is None:
        return None
    return f"{provider}/{name}"


def _harbor_agent_responses_base_url_from_job_config(
    job_config: dict[str, Any],
) -> str | None:
    agents = job_config.get("agents")
    if not isinstance(agents, list) or not agents:
        return None
    agent = agents[0]
    if not isinstance(agent, dict):
        return None
    kwargs = agent.get("kwargs")
    if not isinstance(kwargs, dict):
        return None
    return _first_non_empty_string(kwargs.get("responses_base_url"))


def _normalize_harbor_trial_record(
    *,
    trial: dict[str, Any],
    trial_result_path: Path,
    job_config: dict[str, Any],
    smoke_config: dict[str, Any],
    responses_base_url: str,
    local_host_route: str,
    environment_provider: str,
) -> dict[str, Any]:
    normalized = dict(trial)
    agent_info = trial.get("agent_info")
    if not isinstance(agent_info, dict):
        agent_info = {}

    normalized["agent_version"] = _first_non_empty_string(
        normalized.get("agent_version"),
        agent_info.get("agent_version"),
        agent_info.get("version"),
    )
    agent_responses_base_url = _first_non_empty_string(
        _harbor_agent_responses_base_url_from_job_config(job_config),
        harbor_agent_responses_base_url(
            responses_base_url=responses_base_url,
            local_host_route=local_host_route,
        ),
    )
    if agent_responses_base_url is None:
        raise BenchmarkVerifierError("Harbor trial record missing Responses endpoint")
    normalized["endpoint"] = _first_non_empty_string(
        normalized.get("endpoint"),
        agent_info.get("endpoint"),
        agent_responses_base_url.rstrip("/") + "/responses",
    )
    normalized["environment_provider"] = _first_non_empty_string(
        normalized.get("environment_provider"),
        environment_provider,
    )
    normalized["local_host_route"] = _first_non_empty_string(
        normalized.get("local_host_route"),
        local_host_route,
    )
    normalized["model_id"] = _first_non_empty_string(
        normalized.get("model_id"),
        agent_info.get("model_id"),
        _harbor_model_id_from_agent_info(agent_info),
    )
    normalized["task_id"] = _first_non_empty_string(
        normalized.get("task_id"),
        normalized.get("task_name"),
        _single_harbor_job_task(job_config),
        _single_harbor_smoke_task(smoke_config),
    )
    normalized["trial_id"] = _first_non_empty_string(
        normalized.get("trial_id"),
        normalized.get("trial_name"),
        trial_result_path.parent.name,
    )
    if (
        isinstance(normalized.get("exception_info"), dict)
        and not isinstance(normalized.get("agent_result"), dict)
        and not isinstance(normalized.get("verifier_result"), dict)
    ):
        normalized["state"] = "environment_crashed"
    return normalized


def _write_harbor_trials_artifact(
    *,
    harbor_output_dir: Path,
    trials_path: Path,
    artifacts_dir: Path,
    smoke_config: dict[str, Any],
    responses_base_url: str,
    local_host_route: str,
    environment_provider: str,
) -> None:
    source_trials = harbor_output_dir / "trials.jsonl"
    if source_trials.is_file():
        shutil.copy2(source_trials, trials_path)
        source_artifacts = harbor_output_dir / "artifacts"
        if source_artifacts.is_dir():
            for source_path in source_artifacts.rglob("*"):
                if source_path.is_file():
                    destination = artifacts_dir / source_path.relative_to(
                        source_artifacts
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, destination)
        return

    trial_result_paths = sorted(
        path
        for path in harbor_output_dir.glob("*/*/result.json")
        if path.is_file()
    )
    if not trial_result_paths:
        raise BenchmarkVerifierError(f"Harbor trials artifact not found: {source_trials}")

    job_config = _read_json_object(harbor_output_dir / "job-config.json")
    if not job_config:
        job_config = load_yaml_object(harbor_output_dir / "job-config.yaml")
    trials = []
    for source_path in trial_result_paths:
        trial = _read_json_object(source_path)
        if not trial:
            raise BenchmarkVerifierError(f"Harbor trial result invalid: {source_path}")
        trials.append(
            _normalize_harbor_trial_record(
                trial=trial,
                trial_result_path=source_path,
                job_config=job_config,
                smoke_config=smoke_config,
                responses_base_url=responses_base_url,
                local_host_route=local_host_route,
                environment_provider=environment_provider,
            )
        )
    trials_path.write_text(
        "".join(json.dumps(trial, sort_keys=True) + "\n" for trial in trials)
    )

    for source_path in harbor_output_dir.glob("*/result.json"):
        if source_path.is_file():
            destination = artifacts_dir / source_path.relative_to(harbor_output_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
    for source_path in trial_result_paths:
        destination = artifacts_dir / source_path.relative_to(harbor_output_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _fixture_suite_complete(suite_dir: Path, suite_id: str) -> bool:
    metrics = _read_json_object(suite_dir / "metrics.json")
    if metrics.get("suite") != suite_id:
        return False
    if metrics.get("tasks_total") != metrics.get("tasks_passed"):
        return False
    if any(field not in metrics for field in REQUIRED_METRICS_CONDITION_FIELDS):
        return False
    return (suite_dir / "samples.jsonl").is_file() and (
        suite_dir / "failures.jsonl"
    ).is_file()


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"", "todo", "tbd"} or normalized.startswith("todo")
    return False


def _is_placeholder_revision(value: Any) -> bool:
    if _is_placeholder(value):
        return True
    if not isinstance(value, str):
        return True
    normalized = value.strip().lower()
    return normalized.startswith("<") or "pinned-placeholder" in normalized


def _swe_bench_source_revision(
    config: dict[str, Any],
    lock: dict[str, Any],
) -> str | None:
    revisions = []
    for document in (config, lock):
        source = document.get("dataset_source")
        if isinstance(source, dict):
            revision = source.get("revision")
            if isinstance(revision, str) and not _is_placeholder_revision(revision):
                revisions.append(revision)
    if not revisions:
        return None
    first = revisions[0]
    if any(revision != first for revision in revisions[1:]):
        return None
    return first


def _swe_bench_provider_namespace(lock: dict[str, Any]) -> str:
    official_images = lock.get("official_images")
    if not isinstance(official_images, dict):
        return "swebench"
    provider = official_images.get("provider")
    if (
        not isinstance(provider, str)
        or _is_placeholder(provider)
        or provider == "unresolved"
    ):
        return "swebench"
    return provider


def _swe_bench_smoke_instances(
    config: dict[str, Any],
    lock: dict[str, Any],
) -> list[str]:
    subset = config.get("subset")
    if isinstance(subset, dict):
        smoke_instances = subset.get("smoke_instances")
        if _is_string_list(smoke_instances):
            return smoke_instances
    smoke_instances = lock.get("smoke_instances")
    if _is_string_list(smoke_instances):
        return smoke_instances
    return []


def _is_string_list(value: Any) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(
        isinstance(item, str) and item for item in value
    )


def _swe_bench_image_metadata_by_instance(
    lock: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    official_images = lock.get("official_images")
    if not isinstance(official_images, dict):
        return {}
    per_instance_images = official_images.get("per_instance_images")
    if isinstance(per_instance_images, dict):
        return {
            instance_id: metadata
            for instance_id, metadata in per_instance_images.items()
            if isinstance(instance_id, str) and isinstance(metadata, dict)
        }
    if not isinstance(per_instance_images, list):
        return {}
    images = {}
    for metadata in per_instance_images:
        if not isinstance(metadata, dict):
            continue
        instance_id = metadata.get("instance_id")
        if isinstance(instance_id, str) and instance_id:
            images[instance_id] = metadata
    return images


def _revision_suffix(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if "@" not in value:
        return value
    return value.rsplit("@", 1)[1]


def _fixture_samples(
    run_id: str,
    suite: dict[str, Any],
    execution_backend: str,
    dataset_cache_root: Path | None = None,
    prepare_artifact_path: Path | None = None,
) -> list[dict[str, Any]]:
    condition_fields = _sample_condition_fields(suite, execution_backend)
    if suite["id"] == "needle-smoke":
        return [
            {**sample, **condition_fields}
            for sample in _needle_smoke_fixture_samples(run_id, suite)
        ]
    sample = _fixture_sample(
        run_id,
        suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    )
    sample.update(condition_fields)
    return [sample]


def _suite_condition_fields(
    suite: dict[str, Any],
    execution_backend: str,
) -> dict[str, Any]:
    return {
        "profile": suite["profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "prompt_template": suite["prompt_template"],
        "execution_backend": execution_backend,
        "decoding_profile": suite["decoding_profile"],
        "metric": suite["metric"],
    }


def _sample_condition_fields(
    suite: dict[str, Any],
    execution_backend: str,
) -> dict[str, Any]:
    return {
        "execution_backend": execution_backend,
        "metric": suite["metric"],
        "prompt_template": suite["prompt_template"],
    }


def _fixture_sample(
    run_id: str,
    suite: dict[str, Any],
    dataset_cache_root: Path | None = None,
    prepare_artifact_path: Path | None = None,
) -> dict[str, Any]:
    if suite["id"] == "gsm8k":
        cached_sample = _score_cached_gsm8k_sample(
            run_id=run_id,
            suite=suite,
            dataset_cache_root=dataset_cache_root,
            prepare_artifact_path=prepare_artifact_path,
        )
        if cached_sample is not None:
            return cached_sample
    if suite["id"] in {"gsm8k", "aime"}:
        return score_static_fixture_sample(run_id=run_id, suite=suite)
    prompt = f"{suite['id']} fixture smoke"
    return {
        "suite": suite["id"],
        "case_id": f"{suite['id']}/fixture-001",
        "profile": suite["profile"],
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "response": "fixture pass",
        "parsed_answer": "fixture pass",
        "passed": True,
        "score": 1.0,
        "latency_seconds": 0.0,
        "usage": {},
        "endpoint": "fixture",
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "state": "passed",
        "run_id": run_id,
    }


def _needle_smoke_fixture_samples(
    run_id: str,
    suite: dict[str, Any],
) -> list[dict[str, Any]]:
    needle_key = "deployment_cleanup_token"
    needle_value = "ORCHID-7194"
    seed = "needle-smoke-v1"
    samples = []
    for position in ("beginning", "middle", "end"):
        prompt = _needle_smoke_prompt(position, needle_key, needle_value)
        samples.append(
            {
                "suite": suite["id"],
                "case_id": f"needle-smoke/{position}",
                "profile": suite.get("profile", "long-context-smoke"),
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "prompt": prompt,
                "reproducible_seed": seed,
                "needle_key": needle_key,
                "needle_position": position,
                "response": needle_value,
                "parsed_answer": needle_value,
                "extracted_answer": needle_value,
                "expected_answer": needle_value,
                "passed": True,
                "score": 1.0,
                "latency_seconds": 0.0,
                "usage": {},
                "endpoint": "fixture",
                "decoding": suite["decoding_profile"],
                "decoding_profile": suite["decoding_profile"],
                "dataset_revision": suite["dataset_revision"],
                "harness_revision": suite["harness_revision"],
                "state": "passed",
                "run_id": run_id,
            }
        )
    return samples


def _needle_smoke_prompt(position: str, needle_key: str, needle_value: str) -> str:
    prefix = "alpha context segment\n"
    middle = "middle context segment\n"
    suffix = "omega context segment\n"
    needle = f"{needle_key}: {needle_value}\n"
    if position == "beginning":
        body = needle + prefix + middle + suffix
    elif position == "middle":
        body = prefix + needle + middle + suffix
    elif position == "end":
        body = prefix + middle + suffix + needle
    else:
        raise BenchmarkVerifierError(f"unknown needle-smoke position: {position}")
    return body + "Return only the deployment cleanup token."


def extract_static_final_answer(suite_id: str, raw_response: str) -> str:
    if suite_id == "gsm8k":
        match = re.search(r"####\s*([^\n]+)", raw_response)
        if match is None:
            raise BenchmarkVerifierError("GSM8K response missing final answer marker")
        return _normalize_numeric_answer(match.group(1))
    if suite_id == "aime":
        matches = re.findall(r"\b\d+\b", raw_response)
        if not matches:
            raise BenchmarkVerifierError("AIME response missing integer answer")
        answer = str(int(matches[-1]))
        if not 0 <= int(answer) <= 999:
            raise BenchmarkVerifierError(f"AIME answer outside AIME answer range: {answer}")
        return answer
    raise BenchmarkVerifierError(f"unsupported static answer extraction suite: {suite_id}")


def score_static_fixture_sample(*, run_id: str, suite: dict[str, Any]) -> dict[str, Any]:
    suite_id = suite["id"]
    if suite_id == "gsm8k":
        prompt = "If a box has 19 red marbles and 23 blue marbles, how many marbles are in the box?"
        raw_response = "19 + 23 = 42\n#### 42"
        expected_answer = "42"
        normalization_kind = "gsm8k_final_answer"
    elif suite_id == "aime":
        prompt = "Find the integer answer to the fixture AIME problem."
        raw_response = "The final integer answer is 042."
        expected_answer = "42"
        normalization_kind = "aime_integer_answer"
    else:
        raise BenchmarkVerifierError(f"unsupported static fixture suite: {suite_id}")
    extracted_answer = extract_static_final_answer(suite_id, raw_response)
    passed = extracted_answer == expected_answer
    return {
        "suite": suite_id,
        "case_id": f"{suite_id}/fixture-001",
        "profile": suite.get("profile", "math-reasoning-fixture"),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt": prompt,
        "raw_response": raw_response,
        "response": raw_response,
        "parsed_answer": extracted_answer,
        "extracted_answer": extracted_answer,
        "expected_answer": expected_answer,
        "normalization": {
            "kind": normalization_kind,
            "normalized_answer": extracted_answer,
            "expected_normalized_answer": expected_answer,
        },
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "latency_seconds": 0.0,
        "usage": {},
        "endpoint": "fixture",
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "state": "passed" if passed else "wrong_answer",
        "run_id": run_id,
    }


def _score_cached_gsm8k_sample(
    *,
    run_id: str,
    suite: dict[str, Any],
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> dict[str, Any] | None:
    dataset_sample = _load_cached_gsm8k_sample(
        suite=suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    )
    if dataset_sample is None:
        return None
    sample_id = _gsm8k_sample_id(dataset_sample)
    question = dataset_sample.get("question")
    answer = dataset_sample.get("answer")
    if not isinstance(question, str) or not question.strip():
        raise BenchmarkVerifierError("GSM8K dataset sample missing question")
    if not isinstance(answer, str) or not answer.strip():
        raise BenchmarkVerifierError("GSM8K dataset sample missing answer")
    expected_answer = extract_static_final_answer("gsm8k", answer)
    raw_response = answer
    extracted_answer = extract_static_final_answer("gsm8k", raw_response)
    passed = extracted_answer == expected_answer
    return {
        "suite": "gsm8k",
        "case_id": f"gsm8k/{sample_id}",
        "dataset_sample_id": sample_id,
        "profile": suite.get("profile", "math-reasoning-fixture"),
        "prompt_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "prompt": question,
        "raw_response": raw_response,
        "response": raw_response,
        "parsed_answer": extracted_answer,
        "extracted_answer": extracted_answer,
        "expected_answer": expected_answer,
        "normalization": {
            "kind": "gsm8k_final_answer",
            "normalized_answer": extracted_answer,
            "expected_normalized_answer": expected_answer,
        },
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "latency_seconds": 0.0,
        "usage": {},
        "endpoint": "fixture",
        "decoding": suite["decoding_profile"],
        "decoding_profile": suite["decoding_profile"],
        "dataset_revision": suite["dataset_revision"],
        "harness_revision": suite["harness_revision"],
        "state": "passed" if passed else "wrong_answer",
        "run_id": run_id,
    }


def _load_cached_gsm8k_sample(
    *,
    suite: dict[str, Any],
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> dict[str, Any] | None:
    for cache_path in _gsm8k_dataset_cache_candidates(
        suite=suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    ):
        sample = _read_first_gsm8k_jsonl_sample(cache_path)
        if sample is not None:
            return sample
    return None


def _gsm8k_dataset_cache_candidates(
    *,
    suite: dict[str, Any],
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> list[Path]:
    candidates = []
    dataset_cache = suite.get("dataset_cache")
    if isinstance(dataset_cache, str) and dataset_cache.strip():
        candidates.append(Path(dataset_cache))
    dataset_source = suite.get("dataset_source")
    if isinstance(dataset_source, dict):
        source_type = dataset_source.get("type")
        source_path = dataset_source.get("path")
        if (
            source_type in {"local", "local_path"}
            and isinstance(source_path, str)
            and source_path.strip()
        ):
            candidates.append(Path(source_path))
    if dataset_cache_root is not None:
        candidates.append(dataset_cache_root / "datasets" / "gsm8k")
    if prepare_artifact_path is not None:
        prepare = _read_json_object(prepare_artifact_path)
        for record in prepare.get("cache_preflight", []):
            if not isinstance(record, dict) or record.get("suite") != "gsm8k":
                continue
            record_cache = record.get("dataset_cache")
            if isinstance(record_cache, str) and record_cache.strip():
                candidates.append(Path(record_cache))

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        unique_candidates.append(candidate)
    return unique_candidates


def _read_first_gsm8k_jsonl_sample(cache_path: Path) -> dict[str, Any] | None:
    if cache_path.is_file():
        jsonl_paths = [cache_path]
    elif cache_path.is_dir():
        preferred = [
            cache_path / "samples.jsonl",
            cache_path / "test.jsonl",
            cache_path / "train.jsonl",
            cache_path / "problems.jsonl",
        ]
        jsonl_paths = [path for path in preferred if path.is_file()]
        selected_paths = set(jsonl_paths)
        jsonl_paths.extend(
            path
            for path in sorted(cache_path.glob("*.jsonl"))
            if path not in selected_paths
        )
    else:
        return None
    for jsonl_path in jsonl_paths:
        with jsonl_path.open() as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError as error:
                    raise BenchmarkVerifierError(
                        f"invalid GSM8K JSONL sample in {jsonl_path}:{line_number}: {error}"
                    ) from error
                if not isinstance(sample, dict):
                    raise BenchmarkVerifierError(
                        f"GSM8K JSONL sample must be an object: {jsonl_path}:{line_number}"
                    )
                if "question" in sample and "answer" in sample:
                    return sample
    return None


def _gsm8k_sample_id(sample: dict[str, Any]) -> str:
    for key in ("id", "sample_id", "task_id"):
        value = sample.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "dataset-001"


def _load_cached_aime_sample(
    *,
    suite: dict[str, Any],
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> dict[str, Any] | None:
    for cache_path in _aime_dataset_cache_candidates(
        suite=suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    ):
        sample = _read_first_aime_jsonl_sample(cache_path)
        if sample is not None:
            return sample
    return None


def _aime_dataset_cache_candidates(
    *,
    suite: dict[str, Any],
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> list[Path]:
    candidates = []
    dataset_cache = suite.get("dataset_cache")
    if isinstance(dataset_cache, str) and dataset_cache.strip():
        candidates.append(Path(dataset_cache))
    dataset_source = suite.get("dataset_source")
    if isinstance(dataset_source, dict):
        source_type = dataset_source.get("type")
        source_path = dataset_source.get("path")
        if (
            source_type in {"local", "local_path"}
            and isinstance(source_path, str)
            and source_path.strip()
        ):
            candidates.append(Path(source_path))
    if dataset_cache_root is not None:
        candidates.append(dataset_cache_root / "datasets" / "aime")
    if prepare_artifact_path is not None:
        prepare = _read_json_object(prepare_artifact_path)
        for record in prepare.get("cache_preflight", []):
            if not isinstance(record, dict) or record.get("suite") != "aime":
                continue
            record_cache = record.get("dataset_cache")
            if isinstance(record_cache, str) and record_cache.strip():
                candidates.append(Path(record_cache))

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        unique_candidates.append(candidate)
    return unique_candidates


def _read_first_aime_jsonl_sample(cache_path: Path) -> dict[str, Any] | None:
    if cache_path.is_file():
        jsonl_paths = [cache_path]
    elif cache_path.is_dir():
        preferred = [
            cache_path / "samples.jsonl",
            cache_path / "test.jsonl",
            cache_path / "problems.jsonl",
        ]
        jsonl_paths = [path for path in preferred if path.is_file()]
        selected_paths = set(jsonl_paths)
        jsonl_paths.extend(
            path
            for path in sorted(cache_path.glob("*.jsonl"))
            if path not in selected_paths
        )
    else:
        return None
    for jsonl_path in jsonl_paths:
        with jsonl_path.open() as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError as error:
                    raise BenchmarkVerifierError(
                        f"invalid AIME JSONL sample in {jsonl_path}:{line_number}: {error}"
                    ) from error
                if not isinstance(sample, dict):
                    raise BenchmarkVerifierError(
                        f"AIME JSONL sample must be an object: {jsonl_path}:{line_number}"
                    )
                if _aime_sample_prompt(sample) is not None and "answer" in sample:
                    return sample
    return None


def _aime_sample_prompt(sample: dict[str, Any]) -> str | None:
    for key in ("problem", "question", "prompt"):
        value = sample.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _aime_sample_id(sample: dict[str, Any]) -> str:
    for key in ("id", "sample_id", "task_id"):
        value = sample.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "dataset-001"


def _load_cached_ruler_sample(
    *,
    suite: dict[str, Any],
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> dict[str, Any] | None:
    for cache_path in _ruler_dataset_cache_candidates(
        suite=suite,
        dataset_cache_root=dataset_cache_root,
        prepare_artifact_path=prepare_artifact_path,
    ):
        sample = _read_first_ruler_jsonl_sample(cache_path)
        if sample is not None:
            return sample
    return None


def _ruler_dataset_cache_candidates(
    *,
    suite: dict[str, Any],
    dataset_cache_root: Path | None,
    prepare_artifact_path: Path | None,
) -> list[Path]:
    candidates = []
    dataset_cache = suite.get("dataset_cache")
    if isinstance(dataset_cache, str) and dataset_cache.strip():
        candidates.append(Path(dataset_cache))
    dataset_source = suite.get("dataset_source")
    if isinstance(dataset_source, dict):
        source_type = dataset_source.get("type")
        source_path = dataset_source.get("path")
        if (
            source_type in {"local", "local_path"}
            and isinstance(source_path, str)
            and source_path.strip()
        ):
            candidates.append(Path(source_path))
    if dataset_cache_root is not None:
        candidates.append(dataset_cache_root / "datasets" / "ruler")
    if prepare_artifact_path is not None:
        prepare = _read_json_object(prepare_artifact_path)
        for record in prepare.get("cache_preflight", []):
            if not isinstance(record, dict) or record.get("suite") != "ruler":
                continue
            record_cache = record.get("dataset_cache")
            if isinstance(record_cache, str) and record_cache.strip():
                candidates.append(Path(record_cache))

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        unique_candidates.append(candidate)
    return unique_candidates


def _read_first_ruler_jsonl_sample(cache_path: Path) -> dict[str, Any] | None:
    if cache_path.is_file():
        jsonl_paths = [cache_path]
    elif cache_path.is_dir():
        preferred = [
            cache_path / "samples.jsonl",
            cache_path / "test.jsonl",
            cache_path / "validation.jsonl",
            cache_path / "problems.jsonl",
        ]
        jsonl_paths = [path for path in preferred if path.is_file()]
        selected_paths = set(jsonl_paths)
        jsonl_paths.extend(
            path
            for path in sorted(cache_path.glob("*.jsonl"))
            if path not in selected_paths
        )
    else:
        return None
    for jsonl_path in jsonl_paths:
        with jsonl_path.open() as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError as error:
                    raise BenchmarkVerifierError(
                        f"invalid RULER JSONL sample in {jsonl_path}:{line_number}: {error}"
                    ) from error
                if not isinstance(sample, dict):
                    raise BenchmarkVerifierError(
                        f"RULER JSONL sample must be an object: {jsonl_path}:{line_number}"
                    )
                if (
                    _ruler_sample_prompt(sample) is not None
                    and _ruler_expected_answer(sample) is not None
                ):
                    return sample
    return None


def _ruler_sample_prompt(sample: dict[str, Any]) -> str | None:
    prompt_parts = []
    prompt = sample.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        prompt_parts.append(prompt.strip())
    context = sample.get("context")
    if isinstance(context, str) and context.strip():
        prompt_parts.append(f"Context:\n{context.strip()}")
    question = sample.get("question")
    if isinstance(question, str) and question.strip():
        prompt_parts.append(f"Question:\n{question.strip()}")
    if prompt_parts:
        return "\n\n".join(prompt_parts)
    input_text = sample.get("input")
    if isinstance(input_text, str) and input_text.strip():
        return input_text.strip()
    return None


def _ruler_expected_answer(sample: dict[str, Any]) -> str | None:
    for key in ("expected_answer", "answer", "target"):
        value = sample.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
    outputs = sample.get("outputs")
    if isinstance(outputs, list):
        for value in outputs:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, int | float) and not isinstance(value, bool):
                return str(value)
    return None


def _ruler_sample_id(sample: dict[str, Any]) -> str:
    for key in ("id", "sample_id", "task_id"):
        value = sample.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "dataset-001"


def _normalize_numeric_answer(answer: str) -> str:
    normalized = answer.strip().replace(",", "")
    if re.fullmatch(r"[+-]?\d+", normalized):
        return str(int(normalized))
    return normalized


def write_bwrap_smoke_summary(
    *,
    results_root: Path,
    run_id: str,
    smoke_result: dict[str, Any],
) -> Path:
    if smoke_result.get("status") != "pass":
        raise BenchmarkVerifierError("bwrap smoke did not pass")
    artifact = smoke_result.get("artifact")
    cleanup_ledger = smoke_result.get("cleanup_ledger")
    if not isinstance(artifact, str) or not Path(artifact).is_file():
        raise BenchmarkVerifierError(f"missing bwrap smoke artifact: {artifact!r}")
    if not isinstance(cleanup_ledger, str) or not Path(cleanup_ledger).is_file():
        raise BenchmarkVerifierError(f"missing cleanup ledger: {cleanup_ledger!r}")

    summary_dir = results_root / run_id
    summary_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = summary_dir / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    smoke_artifact_path = artifact_dir / "smoke-artifact.json"
    cleanup_ledger_path = artifact_dir / "cleanup.json"
    shutil.copy2(artifact, smoke_artifact_path)
    shutil.copy2(cleanup_ledger, cleanup_ledger_path)
    summary_path = summary_dir / "summary.json"
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "smoke",
        "suite": "bwrap-sandbox-smoke",
        "execution_backend": "bwrap_rootfs",
        "status": "pass",
        "contract_artifacts": {
            "smoke_artifact": str(smoke_artifact_path.relative_to(summary_dir)),
            "cleanup_ledger": str(cleanup_ledger_path.relative_to(summary_dir)),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    write_archive_manifest(result_dir=summary_dir, summary=summary)
    return summary_path


def write_harbor_environment_failure(
    *,
    results_root: Path,
    run_root: Path | None = None,
    run_id: str,
    suite_id: str,
    reason: str,
    responses_base_url: str,
    local_host_route: str,
    environment_provider: str,
    smoke_config: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    environment_diagnostics: dict[str, Any] | None = None,
) -> Path:
    result_dir = results_root / run_id
    harbor_dir = result_dir / "harbor"
    harbor_dir.mkdir(parents=True, exist_ok=True)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state_manifest = _harbor_evalrun_manifest(
        manifest=manifest,
        suite_id=suite_id,
        smoke_config=smoke_config or {},
    )
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode="smoke",
        manifest=state_manifest,
        suite_ids=[suite_id],
    )
    smoke_config_artifact = (
        write_harbor_smoke_config_artifact(harbor_dir, smoke_config)
        if smoke_config is not None
        else None
    )
    agent_responses_base_url = harbor_agent_responses_base_url(
        responses_base_url=responses_base_url,
        local_host_route=local_host_route,
    )
    endpoint = agent_responses_base_url.rstrip("/") + "/responses"
    local_container_runtime = (
        environment_provider.removeprefix("local_")
        if environment_provider.startswith("local_")
        else environment_provider
    )
    trial = {
        "schema_version": 1,
        "agent_version": HARBOR_AGENT_VERSION,
        "task_id": f"{suite_id}/environment-preflight",
        "trial_id": f"{run_id}-environment-preflight",
        "model_id": "zai-org/GLM-5.2",
        "endpoint": endpoint,
        "responses_base_url": responses_base_url,
        "harbor_agent_responses_base_url": agent_responses_base_url,
        "local_host_route": local_host_route,
        "environment_provider": environment_provider,
        "local_container_runtime": local_container_runtime,
        "state": "environment_setup_failed",
        "reason": reason,
    }
    if smoke_config_artifact is not None:
        trial["smoke_config"] = str(smoke_config_artifact["path"])
        trial["smoke_config_sha256"] = smoke_config_artifact["sha256"]
    if environment_diagnostics is not None:
        trial["environment_diagnostics"] = environment_diagnostics
    (harbor_dir / "trials.jsonl").write_text(json.dumps(trial, sort_keys=True) + "\n")
    (harbor_dir / "artifacts").mkdir(exist_ok=True)
    harbor_summary = {
        "trials_jsonl": str((harbor_dir / "trials.jsonl").relative_to(result_dir)),
        "artifacts_dir": str((harbor_dir / "artifacts").relative_to(result_dir)),
    }
    if smoke_config_artifact is not None:
        harbor_summary["smoke_config"] = str(
            smoke_config_artifact["path"].relative_to(result_dir)
        )
        harbor_summary["smoke_config_sha256"] = smoke_config_artifact["sha256"]
    if manifest is not None:
        selected = select_suites(manifest, [suite_id])
        for suite in selected:
            validate_suite_fields(suite)
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(state_manifest, indent=2, sort_keys=True) + "\n"
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "smoke",
        "status": "environment_setup_failed",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(state_manifest),
        "suite": suite_id,
        "execution_backend": "harbor_local_docker",
        "responses_base_url": responses_base_url,
        "harbor_agent_responses_base_url": agent_responses_base_url,
        "local_host_route": local_host_route,
        "environment_provider": environment_provider,
        "suites": [
            {
                "id": suite_id,
                "status": "environment_setup_failed",
                "reason": reason,
            }
        ],
    }
    if smoke_config_artifact is not None:
        run_record["smoke_config_sha256"] = smoke_config_artifact["sha256"]
    if environment_diagnostics is not None:
        run_record["environment_diagnostics"] = environment_diagnostics
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    if run_root is not None:
        run_root.mkdir(parents=True, exist_ok=True)
        cleanup_record = {
            "schema_version": 1,
            "run_id": run_id,
            "processes": [],
            "bwrap_tasks": [],
            "containers": [],
            "temp_dirs": [],
            "ports": [],
        }
        (run_root / f"benchmark-{run_id}.json").write_text(
            json.dumps(run_record, indent=2, sort_keys=True) + "\n"
        )
        (run_root / f"cleanup-{run_id}.json").write_text(
            json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
        )
        write_run_lock(
            run_root=run_root,
            run_id=run_id,
            mode="smoke",
            status="environment_setup_failed",
            created_at=created_at,
            result_dir=result_dir,
        )
        finalize_run_lock(
            run_root=run_root,
            run_id=run_id,
            status="environment_setup_failed",
        )
    environment_record = {
        "schema_version": 1,
        "created_at": created_at,
        "python": sys.version.split()[0],
        "pid": os.getpid(),
        "execution_backend": "harbor_local_docker",
        "responses_base_url": responses_base_url,
        "harbor_agent_responses_base_url": agent_responses_base_url,
        "local_host_route": local_host_route,
        "local_container_runtime": local_container_runtime,
        "environment_provider": environment_provider,
    }
    if environment_diagnostics is not None:
        environment_record["environment_diagnostics"] = environment_diagnostics
    (result_dir / "environment.json").write_text(
        json.dumps(environment_record, indent=2, sort_keys=True) + "\n"
    )
    _complete_evalrun_materialization(result_dir)
    _begin_evalrun_suite(result_dir, suite_id)
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=harbor_dir,
        suite_id=suite_id,
        tasks_total=1,
        samples_artifacts=["harbor/trials.jsonl"],
    )
    _begin_evalrun_grading(result_dir, suite_id)
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "smoke",
        "status": "environment_setup_failed",
        "suites": [
            {
                "suite": suite_id,
                "state": "environment_setup_failed",
                "model_failures": 0,
                "infrastructure_failures": 1,
                "reason": reason,
            }
        ],
        "harbor": harbor_summary,
    }
    if environment_diagnostics is not None:
        summary["environment_diagnostics"] = environment_diagnostics
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=harbor_dir,
        suite_id=suite_id,
        tasks_graded=1,
        status="environment_setup_failed",
        metrics_artifacts=["summary.json"],
        summary_artifacts=["summary.json"],
    )
    _complete_evalrun_campaign_summary(
        result_dir=result_dir,
        status="environment_setup_failed",
    )
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def write_harbor_run_state(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    suite_id: str,
    smoke_config: dict[str, Any],
    manifest: dict[str, Any] | None,
    responses_base_url: str,
    local_host_route: str,
    environment_provider: str,
    harbor_output_dir: Path | None = None,
) -> None:
    result_dir = results_root / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state_manifest = _harbor_evalrun_manifest(
        manifest=manifest,
        suite_id=suite_id,
        smoke_config=smoke_config,
    )
    _begin_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        mode="smoke",
        manifest=state_manifest,
        suite_ids=[suite_id],
    )
    agent_responses_base_url = harbor_agent_responses_base_url(
        responses_base_url=responses_base_url,
        local_host_route=local_host_route,
    )
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "smoke",
        "status": "running",
        "created_at": created_at,
        "manifest_sha256": _json_sha256(state_manifest),
        "suite": suite_id,
        "execution_backend": "harbor_local_docker",
        "responses_base_url": responses_base_url,
        "harbor_agent_responses_base_url": agent_responses_base_url,
        "local_host_route": local_host_route,
        "environment_provider": environment_provider,
        "smoke_config_sha256": _json_sha256(smoke_config),
        "suites": [],
    }
    cleanup_record = {
        "schema_version": 1,
        "run_id": run_id,
        "processes": [],
        "bwrap_tasks": [],
        "containers": [],
        "temp_dirs": [
            {
                "path": str(harbor_output_dir),
                "purpose": "harbor_raw_output",
            }
        ]
        if harbor_output_dir is not None
        else [],
        "ports": [],
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (result_dir / "environment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": created_at,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "execution_backend": "harbor_local_docker",
                "responses_base_url": responses_base_url,
                "harbor_agent_responses_base_url": agent_responses_base_url,
                "local_host_route": local_host_route,
                "local_container_runtime": environment_provider.removeprefix("local_"),
                "environment_provider": environment_provider,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if manifest is not None:
        selected = select_suites(manifest, [suite_id])
        for suite in selected:
            validate_suite_fields(suite)
    (result_dir / "benchmark-manifest.json").write_text(
        json.dumps(state_manifest, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"cleanup-{run_id}.json").write_text(
        json.dumps(cleanup_record, indent=2, sort_keys=True) + "\n"
    )
    write_run_lock(
        run_root=run_root,
        run_id=run_id,
        mode="smoke",
        status="running",
        created_at=created_at,
        result_dir=result_dir,
    )
    _complete_evalrun_materialization(result_dir)
    _begin_evalrun_suite(result_dir, suite_id)


def finalize_harbor_run_state(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    suite_id: str,
    status: str,
    reason: str,
) -> None:
    result_dir = results_root / run_id
    run_path = result_dir / "run.json"
    run_record = _read_json_object(run_path)
    run_record.update(
        {
            "status": status,
            "suites": [
                {
                    "id": suite_id,
                    "status": status,
                    "tasks_total": 0,
                    "tasks_completed": 0,
                    "artifact_dir": str(result_dir / "harbor"),
                    "reason": reason,
                }
            ],
        }
    )
    run_path.write_text(json.dumps(run_record, indent=2, sort_keys=True) + "\n")
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status=status)


def write_harbor_success_summary(
    *,
    results_root: Path,
    run_root: Path,
    run_id: str,
    suite_id: str,
    harbor_output_dir: Path,
    responses_base_url: str,
    local_host_route: str,
    environment_provider: str,
    smoke_config: dict[str, Any],
) -> Path:
    result_dir = results_root / run_id
    harbor_dir = result_dir / "harbor"
    artifacts_dir = harbor_dir / "artifacts"
    harbor_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    agent_responses_base_url = harbor_agent_responses_base_url(
        responses_base_url=responses_base_url,
        local_host_route=local_host_route,
    )
    _resume_harbor_evalrun_state(
        result_dir=result_dir,
        run_id=run_id,
        suite_id=suite_id,
        smoke_config=smoke_config,
    )
    smoke_config_artifact = write_harbor_smoke_config_artifact(harbor_dir, smoke_config)

    trials_path = harbor_dir / "trials.jsonl"
    _write_harbor_trials_artifact(
        harbor_output_dir=harbor_output_dir,
        trials_path=trials_path,
        artifacts_dir=artifacts_dir,
        smoke_config=smoke_config,
        responses_base_url=responses_base_url,
        local_host_route=local_host_route,
        environment_provider=environment_provider,
    )

    trials = _read_jsonl_objects(trials_path)
    validate_harbor_trials(trials)
    tasks_total = len(trials)
    _complete_evalrun_trial_generation(
        result_dir=result_dir,
        suite_dir=harbor_dir,
        suite_id=suite_id,
        tasks_total=tasks_total,
        samples_artifacts=["harbor/trials.jsonl"],
    )
    _begin_evalrun_grading(result_dir, suite_id)
    tasks_passed = sum(1 for trial in trials if trial.get("state") == "passed")
    infrastructure_failures = sum(
        1 for trial in trials if trial.get("state") in FAILURE_STATES
    )
    model_failures = max(tasks_total - tasks_passed - infrastructure_failures, 0)
    status = "pass" if tasks_total > 0 and tasks_passed == tasks_total else "fail"
    harbor_summary = {
        "trials_jsonl": str(trials_path.relative_to(result_dir)),
        "artifacts_dir": str(artifacts_dir.relative_to(result_dir)),
        "smoke_config": str(smoke_config_artifact["path"].relative_to(result_dir)),
        "smoke_config_sha256": smoke_config_artifact["sha256"],
    }
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "smoke",
        "status": status,
        "suites": [
            {
                "suite": suite_id,
                "state": "completed",
                "tasks_total": tasks_total,
                "tasks_passed": tasks_passed,
                "model_failures": model_failures,
                "infrastructure_failures": infrastructure_failures,
                "score": tasks_passed / tasks_total if tasks_total else 0.0,
            }
        ],
        "harbor": harbor_summary,
        "responses_base_url": responses_base_url,
        "harbor_agent_responses_base_url": agent_responses_base_url,
        "local_host_route": local_host_route,
        "environment_provider": environment_provider,
    }
    summary_path = result_dir / "summary.json"
    _begin_evalrun_campaign_summary(result_dir)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    run_record = _read_json_object(result_dir / "run.json")
    run_record.update(
        {
            "status": "completed",
            "suites": [
                {
                    "id": suite_id,
                    "status": "completed",
                    "tasks_total": tasks_total,
                    "tasks_completed": tasks_passed,
                    "artifact_dir": str(harbor_dir),
                }
            ],
        }
    )
    (result_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    (run_root / f"benchmark-{run_id}.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True) + "\n"
    )
    finalize_run_lock(run_root=run_root, run_id=run_id, status="completed")
    _complete_evalrun_suite(
        result_dir=result_dir,
        suite_dir=harbor_dir,
        suite_id=suite_id,
        tasks_graded=tasks_total,
        status=status,
        metrics_artifacts=["summary.json"],
        summary_artifacts=["summary.json"],
    )
    _complete_evalrun_campaign_summary(result_dir=result_dir, status=status)
    write_archive_manifest(result_dir=result_dir, summary=summary)
    return summary_path


def run_bwrap_sandbox_smoke(args: argparse.Namespace) -> int:
    command = [
        str(Path("scripts/run_glm52_bwrap_task_runner.sh")),
        "smoke",
        "--run-id",
        args.run_id,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        return completed.returncode
    smoke_result = json.loads(completed.stdout)
    summary_path = write_bwrap_smoke_summary(
        results_root=args.results_root,
        run_id=args.run_id,
        smoke_result=smoke_result,
    )
    print(
        json.dumps(
            {
                "status": "pass",
                "run_id": args.run_id,
                "summary": str(summary_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify local GLM-5.2 benchmark execution contracts."
    )
    subparsers = parser.add_subparsers(required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--suite", action="append")
    prepare.add_argument("--run-id", default="prepare")
    prepare.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    prepare.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    prepare.add_argument("--rootfs", type=Path, default=Path("scripts/rootfs/rootfs"))
    prepare.add_argument("--skip-endpoints", action="store_true")
    prepare.add_argument(
        "--chat-base-url",
        default=os.environ.get("GLM52_CHAT_BASE_URL", "http://localhost:8000/v1"),
    )
    prepare.add_argument(
        "--responses-base-url",
        default=os.environ.get("GLM52_RESPONSES_BASE_URL", "http://localhost:8080/v1"),
    )
    prepare.add_argument("--local-container-runtime", choices=["docker", "podman"], default="docker")
    prepare.set_defaults(func=_cmd_prepare)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--suite", action="append")
    smoke.add_argument("--manifest", type=Path, default=DEFAULT_BENCHMARK_MANIFEST)
    smoke.add_argument("--published-scores", type=Path)
    smoke.add_argument("--local-container-runtime", choices=["docker", "podman"], default="docker")
    smoke.add_argument("--responses-base-url", default=os.environ.get("GLM52_RESPONSES_BASE_URL", "http://localhost:8080/v1"))
    smoke.add_argument(
        "--responses-timeout-seconds",
        type=_positive_float,
        default=DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    )
    smoke.add_argument("--local-host-route", default="host.docker.internal")
    smoke.add_argument("--harbor-smoke-config", type=Path)
    smoke.add_argument(
        "--pool",
        default=None,
        help="Benchmark pool label; accepted for workstream command compatibility.",
    )
    smoke.add_argument(
        "--execution-backend",
        choices=["bwrap_rootfs", "scripts_run", "local_docker", "harbor_local_docker", "host_subprocess"],
    )
    smoke.add_argument("--run-id", required=True)
    smoke.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    smoke.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    smoke.set_defaults(func=_cmd_smoke)

    calibration = subparsers.add_parser("calibration")
    calibration.add_argument("--manifest", type=Path, default=DEFAULT_BENCHMARK_MANIFEST)
    calibration.add_argument("--published-scores", type=Path)
    calibration.add_argument("--suite", action="append", required=True)
    calibration.add_argument(
        "--responses-base-url",
        default=os.environ.get("GLM52_RESPONSES_BASE_URL", "http://localhost:8080/v1"),
    )
    calibration.add_argument(
        "--responses-timeout-seconds",
        type=_positive_float,
        default=DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    )
    calibration.add_argument(
        "--execution-backend",
        required=True,
        choices=["bwrap_rootfs", "scripts_run", "local_docker", "harbor_local_docker", "host_subprocess"],
    )
    calibration.add_argument("--run-id", required=True)
    calibration.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    calibration.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    calibration.set_defaults(func=_cmd_calibration)

    conformance = subparsers.add_parser("conformance")
    conformance.add_argument("--manifest", type=Path, required=True)
    conformance.add_argument("--published-scores", type=Path, required=True)
    conformance.add_argument("--suite", action="append")
    conformance.add_argument("--execution-backend")
    conformance.add_argument("--run-id", required=True)
    conformance.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    conformance.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    conformance.set_defaults(func=_cmd_conformance)
    return parser


def _cmd_prepare(args: argparse.Namespace) -> int:
    manifest = load_yaml_object(args.manifest)
    if args.suite:
        manifest = {**manifest, "suites": select_suites(manifest, args.suite)}
    validate_prepare_manifest_revisions(manifest)
    tool_results = [
        check_local_tool("bwrap"),
        check_local_tool("docker"),
        check_local_tool("harbor"),
    ]
    endpoint_results = []
    if not args.skip_endpoints:
        endpoint_results = [
            check_models_endpoint(name="chat", base_url=args.chat_base_url),
            check_models_endpoint(name="responses", base_url=args.responses_base_url),
        ]
    gold_path_results = build_gold_path_preflight(manifest, tool_results)
    image_results = build_image_preflight(
        manifest,
        tool_results,
        runtime=args.local_container_runtime,
    )
    validate_prepare_image_preflight(image_results)
    cache_results = materialize_prepare_caches(
        manifest,
        cache_root=args.run_root.parent / "benchmarks",
    )
    container_runtime_results = build_container_runtime_preflight(
        manifest,
        args.local_container_runtime,
    )
    swe_bench_smoke_image_results = build_swe_bench_smoke_image_preflight(manifest)
    artifact_path = write_prepare_artifact(
        results_root=args.results_root,
        run_id=args.run_id,
        manifest=manifest,
        rootfs_path=args.rootfs,
        endpoints_checked=not args.skip_endpoints,
        endpoint_results=endpoint_results,
        tool_results=tool_results,
        gold_path_results=gold_path_results,
        cache_results=cache_results,
        image_results=image_results,
        container_runtime_results=container_runtime_results,
        swe_bench_smoke_image_results=swe_bench_smoke_image_results,
    )
    write_prepare_run_state(
        run_root=args.run_root,
        run_id=args.run_id,
        manifest=manifest,
        artifact_path=artifact_path,
    )
    print(
        json.dumps(
            {
                "status": "prepared",
                "run_id": args.run_id,
                "artifact": str(artifact_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_smoke(args: argparse.Namespace) -> int:
    manifest: dict[str, Any] | None = None
    execution_backend = args.execution_backend
    if args.suite is None:
        manifest = load_yaml_object(args.manifest)
        suite_ids = default_smoke_suite_ids(manifest)
        if execution_backend is None:
            execution_backend = "bwrap_rootfs"
    else:
        suite_ids = args.suite
    if len(suite_ids) == 1 and suite_ids[0] in HARBOR_SMOKE_SUITES:
        return _cmd_harbor_smoke(args, suite_ids[0])
    if suite_ids != ["bwrap-sandbox-smoke"]:
        if args.manifest is None:
            raise BenchmarkVerifierError("smoke requires --manifest for benchmark suites")
        if execution_backend is None:
            raise BenchmarkVerifierError("smoke requires --execution-backend for benchmark suites")
        if manifest is None:
            manifest = load_yaml_object(args.manifest)
        if suite_ids == ["needle-smoke"]:
            summary_path = write_needle_smoke_responses_run(
                results_root=args.results_root,
                run_root=args.run_root,
                run_id=args.run_id,
                manifest=manifest,
                execution_backend=execution_backend,
                responses_base_url=args.responses_base_url,
                responses_timeout_seconds=args.responses_timeout_seconds,
                mode="smoke",
            )
            summary = _read_json_object(summary_path)
            print(
                json.dumps(
                    {
                        "status": summary.get("status", "unknown"),
                        "run_id": args.run_id,
                        "summary": str(summary_path),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if summary.get("status") == "pass" else 1
        if suite_ids == ["gsm8k"]:
            summary_path = write_gsm8k_responses_run(
                results_root=args.results_root,
                run_root=args.run_root,
                run_id=args.run_id,
                manifest=manifest,
                execution_backend=execution_backend,
                responses_base_url=args.responses_base_url,
                responses_timeout_seconds=args.responses_timeout_seconds,
                mode="smoke",
            )
            summary = _read_json_object(summary_path)
            print(
                json.dumps(
                    {
                        "status": summary.get("status", "unknown"),
                        "run_id": args.run_id,
                        "summary": str(summary_path),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if summary.get("status") == "pass" else 1
        if suite_ids == ["aime"]:
            summary_path = write_aime_responses_run(
                results_root=args.results_root,
                run_root=args.run_root,
                run_id=args.run_id,
                manifest=manifest,
                execution_backend=execution_backend,
                responses_base_url=args.responses_base_url,
                responses_timeout_seconds=args.responses_timeout_seconds,
                mode="smoke",
            )
            summary = _read_json_object(summary_path)
            print(
                json.dumps(
                    {
                        "status": summary.get("status", "unknown"),
                        "run_id": args.run_id,
                        "summary": str(summary_path),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if summary.get("status") == "pass" else 1
        if suite_ids == ["humaneval"] and args.pool != "code_sandbox":
            summary_path = write_humaneval_responses_run(
                results_root=args.results_root,
                run_root=args.run_root,
                run_id=args.run_id,
                manifest=manifest,
                execution_backend=execution_backend,
                responses_base_url=args.responses_base_url,
                responses_timeout_seconds=args.responses_timeout_seconds,
                mode="smoke",
            )
            summary = _read_json_object(summary_path)
            print(
                json.dumps(
                    {
                        "status": summary.get("status", "unknown"),
                        "run_id": args.run_id,
                        "summary": str(summary_path),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if summary.get("status") == "pass" else 1
        if suite_ids == ["mbpp"] and args.pool != "code_sandbox":
            summary_path = write_mbpp_responses_run(
                results_root=args.results_root,
                run_root=args.run_root,
                run_id=args.run_id,
                manifest=manifest,
                execution_backend=execution_backend,
                responses_base_url=args.responses_base_url,
                responses_timeout_seconds=args.responses_timeout_seconds,
                mode="smoke",
            )
            summary = _read_json_object(summary_path)
            print(
                json.dumps(
                    {
                        "status": summary.get("status", "unknown"),
                        "run_id": args.run_id,
                        "summary": str(summary_path),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if summary.get("status") == "pass" else 1
        if set(suite_ids).issubset({"humaneval", "mbpp"}) and execution_backend == "bwrap_rootfs":
            return _cmd_bwrap_codegen_smoke(args, manifest)
        if suite_ids == ["ruler"]:
            summary_path = write_ruler_responses_run(
                results_root=args.results_root,
                run_root=args.run_root,
                run_id=args.run_id,
                manifest=manifest,
                execution_backend=execution_backend,
                responses_base_url=args.responses_base_url,
                responses_timeout_seconds=args.responses_timeout_seconds,
                mode="smoke",
            )
            summary = _read_json_object(summary_path)
            print(
                json.dumps(
                    {
                        "status": summary.get("status", "unknown"),
                        "run_id": args.run_id,
                        "summary": str(summary_path),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if summary.get("status") == "pass" else 1
        published_scores = load_yaml_object(args.published_scores) if args.published_scores else None
        summary_path = write_fixture_benchmark_run(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            mode="smoke",
            suite_ids=suite_ids,
            manifest=manifest,
            published_scores=published_scores,
            execution_backend=execution_backend,
        )
        print(
            json.dumps(
                {
                    "status": "pass",
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.execution_backend != "bwrap_rootfs":
        raise BenchmarkVerifierError(
            "bwrap-sandbox-smoke requires --execution-backend bwrap_rootfs"
        )
    return run_bwrap_sandbox_smoke(args)


def default_smoke_suite_ids(manifest: dict[str, Any]) -> list[str]:
    suite_ids = []
    for suite in manifest.get("suites", []):
        if (
            isinstance(suite, dict)
            and isinstance(suite.get("id"), str)
            and suite.get("execution_backend") == "bwrap_rootfs"
            and suite["id"] not in {"humaneval", "mbpp"}
        ):
            suite_ids.append(suite["id"])
    if not suite_ids:
        raise BenchmarkVerifierError("default smoke found no bwrap fixture suites")
    return suite_ids


def _cmd_harbor_smoke(args: argparse.Namespace, suite_id: str) -> int:
    smoke_config_path = args.harbor_smoke_config
    if smoke_config_path is None:
        smoke_config_path = (
            DEFAULT_HARBOR_SWEBENCH_SMOKE_CONFIG
            if suite_id == "swe-bench-verified"
            else DEFAULT_HARBOR_SMOKE_CONFIG
        )
    smoke_config = load_harbor_smoke_config(smoke_config_path)
    if smoke_config.get("suite") != suite_id:
        raise BenchmarkVerifierError(
            f"Harbor smoke config suite must match requested suite: {suite_id}"
        )
    manifest = load_yaml_object(args.manifest) if args.manifest is not None else None
    harbor_executable = shutil.which("harbor")
    runtime_executable = shutil.which(args.local_container_runtime)
    environment_diagnostics = build_harbor_environment_diagnostics(
        local_container_runtime=args.local_container_runtime,
        harbor_executable=harbor_executable,
        runtime_executable=runtime_executable,
    )
    reason = None
    missing_reasons = []
    if environment_diagnostics["execution_domain"] != "host":
        reason = (
            "host-control domain required for harbor_local_docker: "
            "running inside scripts/run rootfs"
        )
    else:
        if harbor_executable is None:
            missing_reasons.append("harbor executable not found")
        if runtime_executable is None:
            missing_reasons.append(f"{args.local_container_runtime} executable not found")
    if missing_reasons:
        reason = (
            "host bootstrap required for harbor_local_docker: "
            + "; ".join(missing_reasons)
        )
    elif reason is None:
        responses_preflight = check_required_models_endpoint(
            name="responses",
            base_url=args.responses_base_url,
        )
        if responses_preflight.get("status") != "ok":
            reason = _harbor_responses_preflight_error(
                responses_preflight=responses_preflight,
                local_host_route=args.local_host_route,
            )
    if reason is not None:
        summary_path = write_harbor_environment_failure(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            suite_id=suite_id,
            reason=reason,
            responses_base_url=args.responses_base_url,
            local_host_route=args.local_host_route,
            environment_provider=f"local_{args.local_container_runtime}",
            smoke_config=smoke_config,
            manifest=manifest,
            environment_diagnostics=environment_diagnostics,
        )
        print(
            json.dumps(
                {
                    "status": "environment_setup_failed",
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                    "reason": reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    harbor_output_dir = args.results_root / args.run_id / "harbor-raw"
    harbor_output_dir.mkdir(parents=True, exist_ok=True)
    write_harbor_run_state(
        results_root=args.results_root,
        run_root=args.run_root,
        run_id=args.run_id,
        suite_id=suite_id,
        smoke_config=smoke_config,
        manifest=manifest,
        responses_base_url=args.responses_base_url,
        local_host_route=args.local_host_route,
        environment_provider=f"local_{args.local_container_runtime}",
        harbor_output_dir=harbor_output_dir,
    )
    harbor_job_config = write_harbor_job_config(
        path=harbor_output_dir / "job-config.yaml",
        run_id=args.run_id,
        harbor_output_dir=harbor_output_dir,
        smoke_config=smoke_config,
        responses_base_url=args.responses_base_url,
        local_host_route=args.local_host_route,
        local_container_runtime=args.local_container_runtime,
    )
    command = [
        harbor_executable,
        "run",
        "--config",
        str(harbor_job_config),
        "--yes",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=build_harbor_subprocess_env(),
        text=True,
    )
    if completed.returncode != 0:
        failure_reason = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"harbor exited {completed.returncode}"
        )
        summary_path = write_harbor_environment_failure(
            results_root=args.results_root,
            run_id=args.run_id,
            suite_id=suite_id,
            reason=failure_reason,
            responses_base_url=args.responses_base_url,
            local_host_route=args.local_host_route,
            environment_provider=f"local_{args.local_container_runtime}",
            smoke_config=smoke_config,
            manifest=manifest,
        )
        finalize_harbor_run_state(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            suite_id=suite_id,
            status="environment_setup_failed",
            reason=failure_reason,
        )
        print(
            json.dumps(
                {
                    "status": "environment_setup_failed",
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                    "reason": failure_reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    summary_path = write_harbor_success_summary(
        results_root=args.results_root,
        run_root=args.run_root,
        run_id=args.run_id,
        suite_id=suite_id,
        harbor_output_dir=harbor_output_dir,
        responses_base_url=args.responses_base_url,
        local_host_route=args.local_host_route,
        environment_provider=f"local_{args.local_container_runtime}",
        smoke_config=smoke_config,
    )
    summary = _read_json_object(summary_path)
    print(
        json.dumps(
            {
                "status": summary.get("status", "unknown"),
                "run_id": args.run_id,
                "summary": str(summary_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary.get("status") == "pass" else 1


def _cmd_bwrap_codegen_smoke(args: argparse.Namespace, manifest: dict[str, Any]) -> int:
    _materialize_bwrap_codegen_evalrun(
        results_root=args.results_root,
        run_root=args.run_root,
        run_id=args.run_id,
        suite_ids=args.suite,
        manifest=manifest,
    )
    task_results = []
    for index, suite_id in enumerate(args.suite, start=1):
        task_id = f"{suite_id}-{index:03d}"
        case_id = "HumanEval/0" if suite_id == "humaneval" else "MBPP/0"
        command = [
            "scripts/run_glm52_bwrap_task_runner.sh",
            "codegen-smoke",
            "--run-id",
            args.run_id,
            "--task-id",
            task_id,
            "--suite",
            suite_id,
            "--case-id",
            case_id,
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            sys.stderr.write(completed.stderr)
            task_results.extend(
                _bwrap_codegen_remaining_failure_results(
                    run_root=args.run_root,
                    run_id=args.run_id,
                    suite_ids=args.suite,
                    start_index=index,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
            )
            break
        else:
            task_results.append(
                _bwrap_codegen_task_result_from_completed(
                    completed=completed,
                    run_root=args.run_root,
                    run_id=args.run_id,
                    task_id=task_id,
                    suite_id=suite_id,
                    case_id=case_id,
                )
            )
    summary_path = write_bwrap_codegen_smoke_run(
        results_root=args.results_root,
        run_root=args.run_root,
        run_id=args.run_id,
        suite_ids=args.suite,
        manifest=manifest,
        task_results=task_results,
    )
    summary = _read_json_object(summary_path)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "run_id": args.run_id,
                "summary": str(summary_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary["status"] == "pass" else 2


def _bwrap_codegen_remaining_failure_results(
    *,
    run_root: Path,
    run_id: str,
    suite_ids: list[str],
    start_index: int,
    stdout: str,
    stderr: str,
) -> list[dict[str, Any]]:
    results = []
    for index, suite_id in enumerate(suite_ids[start_index - 1 :], start=start_index):
        task_id = f"{suite_id}-{index:03d}"
        case_id = "HumanEval/0" if suite_id == "humaneval" else "MBPP/0"
        task_stderr = stderr
        if index != start_index:
            task_stderr = (
                f"not run after earlier bwrap codegen failure: {stderr}".rstrip()
            )
        results.append(
            {
                "suite": suite_id,
                "case_id": case_id,
                "task_root": str(run_root / "bwrap" / run_id / task_id),
                "passed": False,
                "state": "environment_crashed",
                "stdout": stdout if index == start_index else "",
                "stderr": task_stderr,
            }
        )
    return results


def _bwrap_codegen_task_result_from_completed(
    *,
    completed: subprocess.CompletedProcess[str],
    run_root: Path,
    run_id: str,
    task_id: str,
    suite_id: str,
    case_id: str,
) -> dict[str, Any]:
    task_root = str(run_root / "bwrap" / run_id / task_id)
    try:
        result = json.loads(completed.stdout)
        artifact_path = Path(result["artifact"])
        artifact = json.loads(artifact_path.read_text())
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        return {
            "suite": suite_id,
            "case_id": case_id,
            "task_root": task_root,
            "passed": False,
            "state": "grader_failed",
            "stdout": completed.stdout,
            "stderr": f"failed to parse bwrap codegen runner output: {error}",
        }
    return {
        "suite": suite_id,
        "case_id": case_id,
        "task_root": result["task_root"],
        "artifact_path": result["artifact"],
        "passed": artifact["passed"],
        "latency_seconds": result.get("duration_seconds", 0.0),
        "stdout": artifact["stdout"],
        "stderr": artifact["stderr"],
    }


def _cmd_calibration(args: argparse.Namespace) -> int:
    manifest = load_yaml_object(args.manifest)
    published_scores = load_yaml_object(args.published_scores) if args.published_scores else None
    if args.suite == ["needle-smoke"]:
        summary_path = write_needle_smoke_responses_run(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            manifest=manifest,
            execution_backend=args.execution_backend,
            responses_base_url=args.responses_base_url,
            responses_timeout_seconds=args.responses_timeout_seconds,
            mode="calibration",
        )
        summary = _read_json_object(summary_path)
        print(
            json.dumps(
                {
                    "status": summary.get("status", "unknown"),
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if summary.get("status") == "pass" else 1
    if args.suite == ["gsm8k"]:
        summary_path = write_gsm8k_responses_run(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            manifest=manifest,
            execution_backend=args.execution_backend,
            responses_base_url=args.responses_base_url,
            responses_timeout_seconds=args.responses_timeout_seconds,
            mode="calibration",
        )
        summary = _read_json_object(summary_path)
        print(
            json.dumps(
                {
                    "status": summary.get("status", "unknown"),
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if summary.get("status") == "pass" else 1
    if args.suite == ["aime"]:
        summary_path = write_aime_responses_run(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            manifest=manifest,
            execution_backend=args.execution_backend,
            responses_base_url=args.responses_base_url,
            responses_timeout_seconds=args.responses_timeout_seconds,
            mode="calibration",
        )
        summary = _read_json_object(summary_path)
        print(
            json.dumps(
                {
                    "status": summary.get("status", "unknown"),
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if summary.get("status") == "pass" else 1
    if args.suite == ["humaneval"]:
        summary_path = write_humaneval_responses_run(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            manifest=manifest,
            execution_backend=args.execution_backend,
            responses_base_url=args.responses_base_url,
            responses_timeout_seconds=args.responses_timeout_seconds,
            mode="calibration",
        )
        summary = _read_json_object(summary_path)
        print(
            json.dumps(
                {
                    "status": summary.get("status", "unknown"),
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if summary.get("status") == "pass" else 1
    if args.suite == ["mbpp"]:
        summary_path = write_mbpp_responses_run(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            manifest=manifest,
            execution_backend=args.execution_backend,
            responses_base_url=args.responses_base_url,
            responses_timeout_seconds=args.responses_timeout_seconds,
            mode="calibration",
        )
        summary = _read_json_object(summary_path)
        print(
            json.dumps(
                {
                    "status": summary.get("status", "unknown"),
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if summary.get("status") == "pass" else 1
    if args.suite == ["ruler"]:
        summary_path = write_ruler_responses_run(
            results_root=args.results_root,
            run_root=args.run_root,
            run_id=args.run_id,
            manifest=manifest,
            execution_backend=args.execution_backend,
            responses_base_url=args.responses_base_url,
            responses_timeout_seconds=args.responses_timeout_seconds,
            mode="calibration",
        )
        summary = _read_json_object(summary_path)
        print(
            json.dumps(
                {
                    "status": summary.get("status", "unknown"),
                    "run_id": args.run_id,
                    "summary": str(summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if summary.get("status") == "pass" else 1
    summary_path = write_fixture_benchmark_run(
        results_root=args.results_root,
        run_root=args.run_root,
        run_id=args.run_id,
        mode="calibration",
        suite_ids=args.suite,
        manifest=manifest,
        published_scores=published_scores,
        execution_backend=args.execution_backend,
    )
    print(
        json.dumps(
            {
                "status": "pass",
                "run_id": args.run_id,
                "summary": str(summary_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_conformance(args: argparse.Namespace) -> int:
    manifest = load_yaml_object(args.manifest)
    published_scores = load_yaml_object(args.published_scores)
    validate_manifest_suite_coverage(manifest)
    suite_ids = args.suite or manifest_suite_ids(manifest)
    validate_conformance_inputs(
        manifest=manifest,
        published_scores=published_scores,
        suite_ids=suite_ids,
        execution_backend_override=args.execution_backend,
    )
    artifact_path = write_conformance_validation_artifact(
        results_root=args.results_root,
        run_root=args.run_root,
        run_id=args.run_id,
        manifest=manifest,
        published_scores=published_scores,
        suite_ids=suite_ids,
    )
    print(
        json.dumps(
            {
                "status": "validated",
                "run_id": args.run_id,
                "suites": suite_ids,
                "artifact": str(artifact_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BenchmarkVerifierError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
