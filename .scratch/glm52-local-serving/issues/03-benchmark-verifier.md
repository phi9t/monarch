# Add Local GLM-5.2 Benchmark Verifier

Type: task
Status: ready-for-human
Blocked by: 02

## Current Status

The local benchmark verifier has smoke, calibration, prepare, manifest
validation, failure taxonomy, source-pin preflight, SWE-bench metadata, and
Harbor execution-domain guardrails implemented and tested. The remaining work
needs live GLM-5.2 Responses output and official benchmark-provider evidence
for the Docker-backed suites. Current host-control artifacts for
Terminal-Bench 2 and SWE-bench Verified already show Docker and Harbor available
with `status: ok`; both runs stop at the Responses `/models` preflight because
`http://127.0.0.1:8080/v1/models` returns HTTP 404 instead of a GLM-backed
adapter model list. Do not mark this ticket resolved until Terminal-Bench 2,
SWE-bench Verified, and any published-conformance paths have run with real
backend artifacts rather than classified adapter preflight failures or
fake-Responses tests.

SWE-bench smoke metadata update: see
`.scratch/glm52-local-serving/swebench-image-source-check.md`. The current
Harbor SWE-bench config and lock pin one smoke instance,
`astropy__astropy-12907`, plus its official row image and exact Docker digest.
This is metadata/preflight evidence only, not live Harbor execution, benchmark
success, or published SWE-bench conformance.

SWE-bench dataset revision update:
The benchmark manifest and Harbor SWE-bench smoke config/lock keep the
HuggingFace dataset revision separate from the SWE-bench harness Git revision.
Dataset materialization uses
`SWE-bench/SWE-bench_Verified@78f471bf655a3137b2e8a75af1501690ec009ec3`;
the harness remains pinned to
`SWE-bench/SWE-bench@4e6126978a16bdfebc6538db8f28cacc2c8b77dc`.
The smoke config and lock are `status: ready`, `runnable: true`, and declare
`conformance.claim: none`.

Main-thread verification for the dataset revision update:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 116 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 HF_HOME=.scratch/glm52-local-serving/tmp/hf-home python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-hf-revision-main-20260816T115900Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-main-20260816T115900Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-main-20260816T115900Z/run
# status=prepared; prepare.json records the HF dataset revision, the separate
# SWE-bench harness Git revision, and missing_prerequisite for smoke_instances

scripts/run env PYTHONDONTWRITEBYTECODE=1 HF_HOME=.scratch/glm52-local-serving/tmp/prepare-swebench-current-20260816T153700Z/hf-home python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-current-20260816T153700Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-current-20260816T153700Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-current-20260816T153700Z/run
# status=prepared; prepare.json records cache_preflight status=available and
# swe_bench_smoke_image_preflight status=pass for astropy__astropy-12907 with
# docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907@sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88.
# docker and harbor remain missing prerequisites in tool/gold-path preflight.
```

SWE-bench resolver seam update:
`scripts/glm52_benchmark_verifier.py` now exposes
`resolve_swe_bench_smoke_image_metadata(config, lock)` for local validation of
declared SWE-bench smoke image metadata. It does not call Hugging Face,
DockerHub, Docker, or Harbor; the current config/lock pass because they declare
one selected instance with an official row image plus exact
`repo@sha256:<64 hex>` digest.

Harbor execution-domain update:
Short-path route applied in this session because the task was bounded,
reversible, and limited to clarifying one execution contract. `ask-matt` was
not invocable in this harness, so the written agentic-engineering route was
applied directly. Decision: Option B. `harbor_local_docker` is a host-control
domain outside `scripts/run`; Monarch Python/tests/docs/trusted in-rootfs
verifiers still run through `scripts/run`. If the Harbor smoke verifier observes
`MONARCH_IN_ROOTFS=1`, it must stop before `/models` preflight and before
launching Harbor, write `environment_setup_failed` Contract Artifacts, and
record `environment_diagnostics.execution_domain=scripts_run_rootfs` plus
`required_execution_domain=host`.

## Requirements

- Add a no-Kubernetes local benchmark verifier for GLM-5.2.
- Support smoke, calibration, and conformance modes.
- Load a benchmark manifest that pins suites, datasets, harness revisions,
  execution backends, decoding profiles, and prompt templates.
- Write file-backed run state and cleanup ledgers before launching suite work.
- Emit run-scoped Contract Artifacts for samples, metrics, failures, summaries,
  environment, benchmark manifest, and published-score manifest.
- Support bwrap-backed suites for HumanEval, MBPP, GSM8K, AIME, RULER,
  needle-smoke, and lm-evaluation-harness-style static runs.
- Support Harbor-backed suites through a separate execution adapter when the
  benchmark requires official containers.
- Separate model failures from infrastructure failures using the failure
  taxonomy in the spec.
- Reject conformance mode when a required published-score manifest field is
  missing.
- Reject command-line backend overrides that would change a pinned conformance
  condition.

## Exclusions

- Do not use Kubernetes, KubeRay, Kueue, or cluster-native jobs.
- Do not claim published conformance from smoke or calibration runs.
- Do not require a live GLM-5.2 endpoint for unit tests.

## Verification Evidence

2026-08-16 SWE-bench image metadata resolver seam:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_blocks_current_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_records_selected_digest_rows \
  -q
# red: failed because resolve_swe_bench_smoke_image_metadata did not exist

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_requires_exact_digest_ref \
  -q
# red: failed because the generic digest matcher allowed a suffix

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_blocks_current_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_records_selected_digest_rows \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_requires_exact_digest_ref \
  -q
# 3 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 111 passed
```

2026-08-16 Harbor local-Docker execution-domain contract:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_refuses_harbor_launch_inside_rootfs \
  -q
# red: failed because _cmd_harbor_smoke still launched /usr/bin/harbor when
# MONARCH_IN_ROOTFS=1 and the tool names were visible on PATH

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_refuses_harbor_launch_inside_rootfs \
  -q
# 1 passed
```

2026-08-16 SWE-bench prepare artifact wiring:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  -q
# red: failed because DEFAULT_HARBOR_SWEBENCH_SMOKE_CONFIG was not defined

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  -q
# red: failed because the default config/lock Path arguments were bound before
# the synthetic monkeypatched files were installed, so prepare still read the
# checked-in placeholder config

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  -q
# 1 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_write_prepare_artifact_records_placeholder_swe_bench_image_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_blocks_current_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_records_selected_digest_rows \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_requires_exact_digest_ref \
  -q
# 5 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_current_swe_bench_placeholders \
  -q
# red: failed because generic container image preflight rejected the current
# SWE-bench manifest before the SWE-bench-specific metadata preflight could
# report the intended placeholder status

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_current_swe_bench_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_write_prepare_artifact_records_placeholder_swe_bench_image_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_blocks_current_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_records_selected_digest_rows \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_requires_exact_digest_ref \
  -q
# 6 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 115 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --run-id prepare-swebench-current-20260816T000000Z \
  --results-root /tmp/glm52-prepare-swebench-results \
  --run-root /tmp/glm52-prepare-swebench-run \
  --skip-endpoints
# exit 2: current checked-in SWE-bench dataset_source revision is still a
# placeholder/non-materializable input for Hugging Face cache preparation

scripts/run python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-image-preflight-real-20260816T114600Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-image-preflight-real-20260816T114600Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-image-preflight-real-20260816T114600Z/run
# exit 2: Revision not found in dataset 'SWE-bench/SWE-bench_Verified';
# suite-level container_image validation no longer hides this source blocker

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct \
  -q
# red: failed because the checked-in SWE-bench dataset_revision still used the
# SWE-bench harness Git commit

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct \
  -q
# 1 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-hf-revision-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-20260816T000000Z/run
# status=prepared; cache_preflight records dataset_source_revision
# 78f471bf655a3137b2e8a75af1501690ec009ec3 and harness_source_revision
# 4e6126978a16bdfebc6538db8f28cacc2c8b77dc. The SWE-bench smoke image
# preflight still reported missing_prerequisite for smoke_instances in this
# older run; see prepare-swebench-current-20260816T153700Z above for current
# status=pass metadata.
```

Prepare artifacts now include `swe_bench_smoke_image_preflight` when the
selected manifest contains `swe-bench-verified`. The section is populated from
`resolve_swe_bench_smoke_image_metadata(config, lock)` using the current
Harbor SWE-bench smoke config and lock files. The current checked-in files
produce `pass` records for the pinned `astropy__astropy-12907` row image and
digest. Generic suite-level image preflight now skips
`swe-bench-verified` because its image contract is per-instance and handled by
this section. This does not prove live SWE-bench execution, Harbor execution,
benchmark success, or published conformance.


- Focused tests for manifest loading, backend selection, conformance validation,
  artifact writing, failure taxonomy, resume behavior, and cleanup-ledger
  writing.
- A smoke command that can run without live GLM-5.2 by using fixture model
  responses for parser and artifact behavior.

## Answer

Partial implementation completed for the first benchmark verifier slice:

- Added `scripts/glm52_benchmark_verifier.py` and
  `scripts/run_glm52_benchmark_verifier.sh`.
- Added `bwrap-sandbox-smoke` dispatch through the bwrap task backend.
- Added manifest-backed fixture `smoke` and `calibration` runs for suites such
  as `needle-smoke`.
- Added deterministic `needle-smoke` fixture prompt generation for beginning,
  middle, and end needle placement. Each sample records the reproducible seed,
  prompt hash, needle key, needle position, expected answer, extracted answer,
  and pass/fail state.
- Added deterministic GSM8K and AIME fixture scoring. The fixture samples store
  prompt hash, raw response, extracted final answer, expected answer,
  normalization metadata, decoding profile, dataset revision, harness revision,
  latency, usage, and pass/fail state.
- Added run-scoped Contract Artifacts under `glm52-benchmark-results/<run-id>/`:
  `run.json`, `environment.json`, `benchmark-manifest.json`,
  `published-scores.json` when provided, `summary.json`, and suite-scoped
  `samples.jsonl`, `metrics.json`, and `failures.jsonl`.
- Added `archive-manifest.json` for terminal benchmark result directories. It
  records the run ID, terminal summary status, relative summary path, and
  relative Contract Artifact paths so an archived run can be inspected without
  live services.
- Added file-backed run state and cleanup ledgers under
  `.scratch/glm52-local-serving/run/`.
- Added manifest-hash-based resume behavior for completed fixture/static suite
  artifacts. Re-running the same run id with matching manifest and
  published-score inputs skips completed suite artifacts and records the suite
  as `resumed` in `run.json`.
- Added bwrap-backed code-generation smoke for HumanEval/MBPP-style suites. It
  launches generated-code fixtures in per-task bwrap roots, records task roots
  in the cleanup ledger, and writes suite-scoped samples, metrics, and failures.
  The code-generation samples now include prompt hash, endpoint, decoding
  profile, latency, usage, dataset revision, harness revision, and result state
  so the smoke artifacts match the benchmark sample audit schema.
  The code-generation runner now preserves the task runner's
  `duration_seconds` as the benchmark sample's `latency_seconds`, so local
  bwrap smoke artifacts carry real task execution timing instead of the default
  fixture zero.
  Code-generation task artifacts are now copied out of the per-task bwrap root
  into the run-scoped suite `artifacts/` directory and referenced from both the
  sample's `contract_artifacts.codegen_artifact` field and the top-level
  `archive-manifest.json`.
  Code-generation smoke result directories now also emit the minimum benchmark
  run layout: `run.json`, `environment.json`, `benchmark-manifest.json`,
  `summary.json`, suite artifacts, and `archive-manifest.json`.
- Extended `scripts/run_glm52_deployment.sh status|cleanup --state` to inspect
  and dry-run cleanup for benchmark cleanup ledgers that contain bwrap task
  roots.
- Added `.scratch/glm52-local-serving/run/deployment.json`, a safe
  local-process deployment state fixture for the prompt's documented Phase 2
  `status` and `cleanup --dry-run` commands. The fixture records the
  Responses adapter and Dynamo/SGLang process ownership, pidfiles, and guarded
  expected commands without pointing at live PIDs.
- Added conformance preflight validation that rejects missing or placeholder
  published-score fields before inference and rejects backend overrides in
  conformance mode.
- Added a `prepare` stage that validates manifest suite coverage and writes a
  run-scoped preparation artifact before scored runs.
- Extended `prepare` to record `/v1/models` preflight results for the Chat and
  Responses endpoints unless `--skip-endpoints` is passed. The artifact records
  each endpoint URL, status, model IDs when available, and any HTTP or transport
  error.
- Extended `prepare` to record local tool preflight results for `bwrap`,
  `docker`, and `harbor`. Missing Harbor is recorded as an environment
  prerequisite gap for Harbor-backed suites, not as a model failure.
- Extended `prepare` to record manifest-driven gold-path preflight results. The
  artifact now records available fixture/oracle checks for bwrap-backed suites
  and `missing_prerequisite` records for Harbor-backed suites when Harbor is not
  installed.
- Extended `prepare` to record planned dataset and harness cache locations for
  every suite plus Docker/Harbor image digest preflight status for
  container-backed suites. In the current environment, Terminal-Bench 2 image
  digest capture is classified as `missing_prerequisite` because Harbor is not
  installed.
- Extended `prepare` to accept `--run-root` and write file-backed prepare run
  state plus an empty cleanup ledger under `.scratch/glm52-local-serving/run/`
  or the configured run root. This keeps prepare aligned with the benchmark
  verifier contract that run state exists before or at suite work.
- Added initial benchmark and published-score manifests under
  `.scratch/glm52-local-serving/benchmarks/`.
- Added tests in `python/tests/test_glm52_benchmark_verifier.py`.

This does not yet implement real benchmark adapters for HumanEval, MBPP, GSM8K,
AIME, RULER, Harbor, or live GLM-5.2 model inference. The GSM8K/AIME work here
is fixture-only extractor and artifact validation, not full calibration. Keep
this ticket open for those remaining requirements.

Verification evidence:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 50 passed

python3 -m py_compile \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_deployment.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_benchmark_verifier.sh

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite bwrap-sandbox-smoke \
  --pool code_sandbox \
  --execution-backend bwrap_rootfs \
  --run-id bwrap-smoke-20260815T215317Z
# pass; summary written to
# glm52-benchmark-results/bwrap-smoke-20260815T215317Z/summary.json

scripts/run_glm52_benchmark_verifier.sh prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --run-id prepare-tool-preflight-20260815T000000Z
# pass; artifact records unavailable Chat and Responses `/v1/models` endpoints:
# chat -> HTTP Error 404: File not found
# responses -> HTTP Error 404: Not Found
# and local tool preflight:
# bwrap -> /usr/bin/bwrap
# docker -> /usr/bin/docker
# harbor -> missing
# glm52-benchmark-results/prepare-tool-preflight-20260815T000000Z/prepare.json

scripts/run_glm52_benchmark_verifier.sh prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --run-id prepare-gold-path-20260815T000000Z
# pass; artifact records gold_path_preflight entries:
# aime/gsm8k -> answer-extraction-fixture available
# humaneval/mbpp -> known-good-bad-fixtures available
# needle-smoke/ruler -> local-answer-fixture available
# terminal-bench-2 -> harbor-oracle missing_prerequisite: harbor
# glm52-benchmark-results/prepare-gold-path-20260815T000000Z/prepare.json

scripts/run_glm52_benchmark_verifier.sh prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --run-id prepare-cache-image-20260815T000000Z
# pass; artifact records cache_preflight entries for all suite dataset and
# harness cache paths under .scratch/glm52-local-serving/benchmarks/, and
# image_preflight records terminal-bench-2 as missing_prerequisite: harbor:
# glm52-benchmark-results/prepare-cache-image-20260815T000000Z/prepare.json

2026-08-16 declared container-image digest slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_records_declared_image_digest \
  -q
# red: image_preflight for a suite with `container_image` still returned
# digest_pending instead of inspecting the image and recording immutable
# metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_records_declared_image_digest \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 46 passed
```

`build_image_preflight()` now records `image`, `runtime`, `image_id`, and
`repo_digest` when a Docker or Harbor-backed suite declares `container_image`
and the selected local container runtime returns a repo digest from
`image inspect`. The `prepare --local-container-runtime` selection is threaded
into image inspection, so podman prepare artifacts do not claim Docker
provenance. Later guardrails make suites without a declared image fail prepare
before artifact writes when Docker and Harbor prerequisites are otherwise
available; the current checked-in Terminal-Bench 2 manifest still lacks a
pinned official image source.

2026-08-16 mutable container-image guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_rejects_mutable_container_image \
  -q
# red before implementation:
# AssertionError: mutable image references must fail before image inspect

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_rejects_mutable_container_image \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_records_declared_image_digest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_uses_selected_container_runtime \
  -q
# 3 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 70 passed before the command-level prepare guardrail

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 119 passed before the command-level prepare guardrail

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`build_image_preflight()` now classifies tag-only or placeholder
`container_image` declarations as `invalid_container_image` and does not call
the local container runtime for them. Digest-pinned declarations still run image
inspection and record the selected runtime, local image ID, and repo digest.

2026-08-16 prepare hard-fail for invalid container images:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_mutable_container_image_before_artifacts \
  -q
# red before implementation:
# Failed: DID NOT RAISE <class 'glm52_benchmark_verifier.BenchmarkVerifierError'>
# captured stdout included `"status": "prepared"`

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_mutable_container_image_before_artifacts \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_rejects_mutable_container_image \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_records_declared_image_digest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_uses_selected_container_runtime \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 71 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 120 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

The prepare command now raises before writing `prepare.json`, benchmark state,
or cleanup state when image preflight classifies a container-backed suite as
`invalid_container_image`. Missing Docker or Harbor remain classified
environment setup gaps, not hard manifest failures.

2026-08-16 prepare image validation before source materialization:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_source_fetch \
  -q
# red before implementation:
# AssertionError: source materialization should not run before image validation

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_source_fetch \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_artifacts \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_mutable_container_image_before_artifacts \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 95 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 144 passed
```

Prepare now validates missing, mutable, or placeholder `container_image`
declarations before materializing benchmark source caches. This keeps invalid
official-image metadata as the fast pre-artifact failure for Docker/Harbor
suites and avoids fetching upstream benchmark sources before the manifest names
the required image.

2026-08-16 selected prepare source-materialization slice:

- Added repeated `prepare --suite` selectors.
- Prepare filters the manifest through the existing suite-selection helper
  before image preflight and source-cache materialization, so a selected
  non-Docker suite can be prepared without weakening the full-manifest
  Docker/Harbor image guardrails.
- `write_prepare_artifact()` now validates selected suites by field contract
  without requiring the selected manifest to contain every default conformance
  suite. Full coverage validation remains on the conformance/manifest-specific
  paths that rely on the default suite set.
- Ran selected prepare against the checked-in manifest for `needle-smoke`.
  The artifact records only `needle-smoke`, an available local-path cache, and
  an empty image preflight.
- Ran selected prepare against the checked-in manifest for `ruler`. The artifact
  records only `ruler`, available Git dataset and harness caches, and an empty
  image preflight. Direct Git inspection of those caches matched the checked-in
  manifest pins:
  `c3f5e3b4f87f97e048793bb510a3a6b19a46bf3a` for RULER and
  `8a07e1110d060de48cfc7a9a7987b7659060b60b` for
  `lm-evaluation-harness`.
- Repaired the local rootfs Hugging Face tooling by installing
  `huggingface-hub==1.27.0` with
  `scripts/run env UV_CACHE_DIR=/tmp/glm52-uv-cache uv pip install huggingface-hub`.
  That version provides `hf` at `/workspace/monarch/.venv-rootfs/bin/hf`;
  its legacy `huggingface-cli` binary is deprecated and nonfunctional, so the
  verifier now prefers `hf download` and falls back to `huggingface-cli` only
  for older environments.
- Ran selected prepare against the checked-in manifest for `humaneval`. The
  artifact records only `humaneval`, an available Hugging Face dataset cache,
  an available Git harness cache, and an empty image preflight. The source
  metadata matches the checked-in pins:
  `7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544` for `openai/openai_humaneval`
  and `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e` for EvalPlus.
- Ran selected prepare against the checked-in manifest for `mbpp`, `gsm8k`, and
  `aime`. Each artifact records only its selected suite, an available Hugging
  Face dataset cache, an available Git harness cache, and an empty image
  preflight. Direct inspection matched the checked-in source pins:
  `4bb6404fdc6cacfda99d4ac4205087b89d32030c` for MBPP,
  `740312add88f781978c0658806c59bc2815b9866` for GSM8K,
  `8d88b2876a82a080e2f172cc9b25d0d9d2cb4792` for AIME,
  `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e` for EvalPlus, and
  `8a07e1110d060de48cfc7a9a7987b7659060b60b` for
  `lm-evaluation-harness`.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_filters_selected_suites_before_image_preflight \
  -q
# red before implementation:
# __main__.py: error: unrecognized arguments: --suite needle-smoke

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_writes_run_state_and_cleanup_ledger \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_source_fetch \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_filters_selected_suites_before_image_preflight \
  -q
# 5 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 101 passed

scripts/run python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite needle-smoke \
  --run-id prepare-needle-selected-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-needle-selected-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-needle-selected-20260816T000000Z/run \
  --skip-endpoints
# status prepared

scripts/run python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite ruler \
  --run-id prepare-ruler-selected-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-ruler-selected-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-ruler-selected-20260816T000000Z/run \
  --skip-endpoints
# status prepared

git -C .scratch/glm52-local-serving/tmp/prepare-ruler-selected-20260816T000000Z/benchmarks/datasets/ruler rev-parse HEAD
# c3f5e3b4f87f97e048793bb510a3a6b19a46bf3a

git -C .scratch/glm52-local-serving/tmp/prepare-ruler-selected-20260816T000000Z/benchmarks/harnesses/ruler rev-parse HEAD
# 8a07e1110d060de48cfc7a9a7987b7659060b60b

scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home \
  python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite humaneval \
  --run-id prepare-humaneval-selected-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-humaneval-selected-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-humaneval-selected-20260816T000000Z/run \
  --skip-endpoints
# status prepared

scripts/run env UV_CACHE_DIR=/tmp/glm52-uv-cache uv pip install huggingface-hub
# installed huggingface-hub==1.27.0 and hf in .venv-rootfs

git -C .scratch/glm52-local-serving/tmp/prepare-humaneval-selected-20260816T000000Z/benchmarks/harnesses/humaneval rev-parse HEAD
# 26d6d00bb1fd0fa37f39c99d5290da67891d1c5e

find .scratch/glm52-local-serving/tmp/prepare-humaneval-selected-20260816T000000Z/benchmarks/datasets/humaneval -maxdepth 1 -mindepth 1 -printf '%f\n' | sort
# .cache
# .gitattributes
# README.md
# openai_humaneval

scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home \
  python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite mbpp \
  --run-id prepare-mbpp-selected-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-mbpp-selected-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-mbpp-selected-20260816T000000Z/run \
  --skip-endpoints
# status prepared

scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home \
  python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite gsm8k \
  --run-id prepare-gsm8k-selected-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-gsm8k-selected-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-gsm8k-selected-20260816T000000Z/run \
  --skip-endpoints
# status prepared

scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home \
  python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite aime \
  --run-id prepare-aime-selected-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-aime-selected-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-aime-selected-20260816T000000Z/run \
  --skip-endpoints
# status prepared

git -C .scratch/glm52-local-serving/tmp/prepare-mbpp-selected-20260816T000000Z/benchmarks/harnesses/mbpp rev-parse HEAD
# 26d6d00bb1fd0fa37f39c99d5290da67891d1c5e

git -C .scratch/glm52-local-serving/tmp/prepare-gsm8k-selected-20260816T000000Z/benchmarks/harnesses/gsm8k rev-parse HEAD
# 8a07e1110d060de48cfc7a9a7987b7659060b60b

git -C .scratch/glm52-local-serving/tmp/prepare-aime-selected-20260816T000000Z/benchmarks/harnesses/aime rev-parse HEAD
# 8a07e1110d060de48cfc7a9a7987b7659060b60b

find .scratch/glm52-local-serving/tmp/prepare-mbpp-selected-20260816T000000Z/benchmarks/datasets/mbpp -maxdepth 1 -mindepth 1 -printf '%f\n' | sort
# .cache
# .gitattributes
# README.md
# full
# sanitized

find .scratch/glm52-local-serving/tmp/prepare-gsm8k-selected-20260816T000000Z/benchmarks/datasets/gsm8k -maxdepth 1 -mindepth 1 -printf '%f\n' | sort
# .cache
# .gitattributes
# README.md
# eval.yaml
# main
# socratic

find .scratch/glm52-local-serving/tmp/prepare-aime-selected-20260816T000000Z/benchmarks/datasets/aime -maxdepth 1 -mindepth 1 -printf '%f\n' | sort
# .cache
# .gitattributes
# README.md
# aime_2024_problems.parquet

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_reports_missing_huggingface_tool \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_falls_back_to_legacy_huggingface_cli \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  -q
# red before implementation:
# FileNotFoundError: huggingface-cli
# Error: No such option '--local-dir-use-symlinks'.
# green after implementation: 3 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 150 passed
```

2026-08-16 Harbor smoke source pin slice:

- Pinned the checked-in Terminal-Bench 2 Harbor smoke config and dataset lock to
  Harbor revision `9dd349f28b969268aef419e910e1998149b612a5` and
  Terminal-Bench revision `d28711d0da2675d0bb1d56de45ae5df6082438a3`.
- Tightened `load_harbor_smoke_config()` so placeholder-style source revisions
  such as `harbor-placeholder-revision` fail before Harbor launch.
- Updated Harbor positive-path fixtures to use the same pinned source
  revisions, leaving one explicit negative fixture for placeholder rejection.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_harbor_smoke_config_has_pinned_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_rejects_placeholder_source_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_requires_pinned_tasks \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_rejects_unpinned_task_list \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 97 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 146 passed
```

2026-08-16 prepare hard-fail for missing container images:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_artifacts \
  -q
# red before implementation:
# Failed: DID NOT RAISE <class 'glm52_benchmark_verifier.BenchmarkVerifierError'>
# captured stdout included `"status": "prepared"`

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_artifacts \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_mutable_container_image_before_artifacts \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_rejects_mutable_container_image \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_records_declared_image_digest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_uses_selected_container_runtime \
  -q
# 5 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 73 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

Image preflight now classifies a container-backed suite with no
`container_image` as `invalid_container_image`, and prepare raises before
writing artifacts or state when Docker and Harbor prerequisites are otherwise
present. If Docker or Harbor is missing, the same suite remains a classified
environment setup gap instead of a manifest hard failure.

2026-08-16 image validation ordering guard:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_rejects_missing_container_image_before_tool_checks \
  -q
# red before implementation:
# missing Docker/Harbor masked the missing container_image as
# missing_prerequisite

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_writes_run_state_and_cleanup_ledger \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_build_prepare_cache_and_image_preflight_from_manifest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_rejects_missing_container_image_before_tool_checks \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 73 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`build_image_preflight()` now validates `container_image` before checking local
Docker or Harbor availability for container-backed suites. Missing,
placeholder, and mutable image declarations are classified as
`invalid_container_image` even on hosts where the runtime prerequisite is
unavailable. Digest-pinned images still reach the normal tool preflight path, so
missing Docker or Harbor remains an environment setup gap only after the
manifest has declared a concrete immutable image reference.

2026-08-16 SWE-bench Verified manifest coverage slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_coverage_requires_all_named_suites \
  -q
# red before implementation:
# manifest without SWE-bench Verified was accepted by suite coverage validation

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_coverage_requires_all_named_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_scores_cover_default_conformance_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  -q
# 3 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 73 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`REQUIRED_MANIFEST_SUITES` now includes `swe-bench-verified`, and the checked-in
benchmark and published-score manifests include explicit placeholder entries for
that suite. This prevents default manifest coverage from omitting the
SWE-bench Verified requirement named in the benchmark spec. The new entries
remain non-comparable placeholders: official SWE-bench source pins, Harbor
execution, per-instance Docker image metadata, and primary-source score metadata
are still required before conformance can run.

2026-08-16 SWE-bench Verified gold-path preflight naming slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_classifies_missing_harbor \
  -q
# red before implementation:
# SWE-bench Verified gold-path preflight used the generic
# benchmark-native-oracle check name instead of naming the official harness

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_classifies_missing_harbor \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 73 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`build_gold_path_preflight()` now reports `swe-bench-official-harness` for
SWE-bench Verified. Missing Harbor remains `missing_prerequisite`, preserving
the distinction between an unavailable official harness and a model failure.

2026-08-16 SWE-bench Harbor smoke config default guardrail:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q -k 'swe_bench_verified_harbor_smoke_config'
# red before implementation:
# the omitted --harbor-smoke-config path selected the Terminal-Bench default,
# and failed with "Harbor smoke config suite must match requested suite:
# swe-bench-verified"
# green after implementation: 2 passed, 159 deselected

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q -k 'harbor_smoke_config or swe_bench_smoke or terminal_bench_smoke'
# 24 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 161 passed
```

`smoke --suite swe-bench-verified` now resolves the omitted
`--harbor-smoke-config` to
`.scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml`.
Terminal-Bench 2 still defaults to the Terminal-Bench smoke config, and explicit
`--harbor-smoke-config` values are preserved. This is a config-selection
guardrail only; it does not claim live Harbor execution, SWE-bench execution,
or conformance.

Run-scoped non-live artifact check:

```sh
timeout 240s env PATH="$PWD/.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH" \
  GLM52_RESPONSES_BASE_URL=http://127.0.0.1:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite swe-bench-verified \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --local-container-runtime docker \
    --run-id swebench-smoke-default-config-20260816T172813Z \
    --results-root glm52-benchmark-results \
    --run-root .scratch/glm52-local-serving/run
# exit 2
```

Artifacts:
`glm52-benchmark-results/swebench-smoke-default-config-20260816T172813Z/`.
`summary.json` reports `status=environment_setup_failed`; suite
`swe-bench-verified` reports `state=environment_setup_failed`,
`infrastructure_failures=1`, and `model_failures=0`. The reason is
`Responses /models preflight failed for http://127.0.0.1:8080/v1/models: HTTP
Error 404: Not Found`. The copied config is
`harbor/configs/swe-bench-verified-smoke.yaml`, not a Terminal-Bench config, and
its sha256 is
`7281754e87daf535476ab827e8e898f79f1bd742d838f05f4f74283796112ce5`.
`archive-manifest.json` lists and hashes the copied SWE config. This proves the
omitted-config CLI path reaches the SWE-bench Harbor config before the
classified endpoint preflight failure; it is not live Harbor execution,
SWE-bench success, model-quality evidence, or conformance.

2026-08-16 SWE-bench Verified per-instance image conformance guard:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_swebench_instance_images \
  -q
# red before implementation:
# conformance wrote status=validated for SWE-bench Verified with only a
# suite-level container_image and no per-instance image metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_swebench_instance_images \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_mutable_swebench_instance_images \
  -q
# red before implementation:
# conformance wrote status=validated for SWE-bench Verified with
# ghcr.io/swe-bench/swe-0:latest as per-instance image metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_mutable_swebench_instance_images \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 75 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 124 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`validate_conformance_inputs()` now requires `instance_images` on
`swe-bench-verified` conformance suites and requires every declared
per-instance Docker image to be digest-pinned. This keeps a digest-pinned
suite-level runner image or mutable per-instance tags from standing in for the
official per-instance Docker image metadata required by the SWE-bench contract.

2026-08-16 published-score source URL guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_url_published_score_source \
  -q
# red before implementation:
# non-URL source_url values were accepted as complete published-score metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_url_published_score_source \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 76 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 125 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`validate_conformance_inputs()` now requires published-score `source_url`
values to be absolute HTTP(S) URLs. This is still only a URL shape guard; real
conformance remains blocked until the manifest cites verified primary sources
matching the local run profile.

2026-08-16 published-score primary-source type guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_primary_published_score_source \
  -q
# red: a score with source_type=secondary was accepted as complete
# published-score metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_primary_published_score_source \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 86 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 135 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-16 Harbor rootfs host-bootstrap diagnostics slice:

- Diagnosed the current SWE-bench Verified Harbor smoke blocker under
  `scripts/run`. The rootfs can see the repo-mounted scratch Harbor entrypoint
  at `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor`, but it is not on
  `PATH` and its shebang points at the host checkout path rather than the
  rootfs path. The rootfs does not expose `/usr/bin/docker` or a Docker socket.
- Classified this as a host-bootstrap/rootfs integration blocker for
  `harbor_local_docker`, not a model failure and not a benchmark result.
- The verifier now records `environment_diagnostics` in `summary.json`,
  `environment.json`, and `harbor/trials.jsonl` when Harbor prelaunch fails.
  Diagnostics include the execution domain, current `PATH`, Harbor candidate
  shebang, missing tools, and Docker socket visibility.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_records_rootfs_host_bootstrap_diagnostics \
  -q
# red before implementation: KeyError: 'environment_diagnostics'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_records_rootfs_host_bootstrap_diagnostics \
  -q
# 1 passed
```

2026-08-16 SWE-bench Harbor smoke dispatch slice:

Root cause: `smoke --suite swe-bench-verified` still used the generic fixture
smoke path because `_cmd_smoke` only dispatched Harbor for
`["terminal-bench-2"]`, and `load_harbor_smoke_config` rejected every config
whose suite was not `terminal-bench-2`. The checked-in SWE-bench metadata
preflight was ready, but the smoke command could not reach the Harbor-backed
machinery.

Change: Harbor smoke loading now accepts `terminal-bench-2` and
`swe-bench-verified` through suite-specific validation. SWE-bench validation
requires pinned dataset and harness sources, non-empty selected
`smoke_instances`, resolved official row image plus exact digest metadata,
`runnable: true`, and `conformance.claim: none`. The Harbor job config keeps
the existing Terminal-Bench shape and emits a SWE-bench dataset stanza with the
dataset source, harness source, selected instance IDs, and selected
row-image/digest records. The smoke command dispatches both Harbor suites
through the same environment preflight, run-state, Harbor CLI, and artifact
copying path.

Red/green evidence:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_swe_bench_harbor_smoke_config_is_loadable \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_classifies_bad_responses_models_endpoint_before_fixture_smoke \
  -q
# red: 3 failed because the loader required terminal-bench-2 and smoke
# --suite swe-bench-verified still demanded fixture --execution-backend

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_swe_bench_harbor_smoke_config_is_loadable \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_classifies_bad_responses_models_endpoint_before_fixture_smoke \
  -q
# 3 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_harbor_smoke_config_has_pinned_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_bad_responses_models_endpoint_before_harbor \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# 4 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 119 passed
```

Real command evidence without a live endpoint:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-container-runtime docker \
  --run-id swebench-smoke-no-endpoint-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/swebench-smoke-no-endpoint-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/swebench-smoke-no-endpoint-20260816T000000Z/run
# exit 2: status=environment_setup_failed; reason="harbor executable not found"
# No fake benchmark success was reported. Artifacts include summary.json,
# run.json, harbor/trials.jsonl, and harbor/configs/swe-bench-verified-smoke.yaml.

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_harbor_smoke_config_has_pinned_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_swe_bench_harbor_smoke_config_is_loadable \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_classifies_bad_responses_models_endpoint_before_fixture_smoke \
  -q
# 5 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-container-runtime docker \
  --run-id swebench-smoke-env-preflight-main-20260816T122000Z \
  --results-root .scratch/glm52-local-serving/tmp/swebench-smoke-env-preflight-main-20260816T122000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/swebench-smoke-env-preflight-main-20260816T122000Z/run
# exit 2: status=environment_setup_failed; reason="harbor executable not found"
# artifact inspection confirmed summary.json, run.json, environment.json,
# benchmark-manifest.json, harbor/trials.jsonl,
# harbor/configs/swe-bench-verified-smoke.yaml, and archive-manifest.json.
```

2026-08-16 host-control domain contract verification:

Fresh main-thread verification confirmed Option B: `harbor_local_docker` is a
host-control execution domain, and in-rootfs invocation refuses before Harbor
launch. The real SWE-bench smoke command below exited `2` with
`status=environment_setup_failed`; the generated `summary.json` records
`environment_diagnostics.execution_domain=scripts_run_rootfs`,
`required_execution_domain=host`, `host_bootstrap_required=true`, and
`missing_tools=["harbor", "docker"]`. The summary also records the repo-mounted
Harbor candidate and its host-absolute shebang. No model failure or benchmark
success was reported.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_records_rootfs_host_bootstrap_diagnostics \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_refuses_harbor_launch_inside_rootfs \
  -q
# 2 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-container-runtime docker \
  --run-id swebench-rootfs-domain-20260816T125513Z \
  --results-root .scratch/glm52-local-serving/tmp/swebench-rootfs-domain-20260816T125513Z/results \
  --run-root .scratch/glm52-local-serving/tmp/swebench-rootfs-domain-20260816T125513Z/run
# exit 2: status=environment_setup_failed;
# reason="host-control domain required for harbor_local_docker: running inside scripts/run rootfs"

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 121 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

2026-08-16 host-route guidance slice:

Fresh host-side SWE-bench smoke evidence shows host bootstrap tools are now
available when the scratch Harbor venv is on `PATH`: `environment_diagnostics`
records `execution_domain=host`, `required_execution_domain=host`,
`host_bootstrap_required=false`, no missing tools, Harbor status `ok`, Docker
status `ok`, and Docker socket visibility. The run still exits `2` before
Harbor launch because the host process cannot resolve
`host.docker.internal`. The verifier now appends explicit operator guidance to
that failure: use a host-resolvable `--responses-base-url` for the adapter and
keep `--local-host-route host.docker.internal` for Docker containers. This keeps
the Docker route metadata intact without treating a DNS/setup failure as model
or benchmark evidence.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_explains_host_docker_route_dns_failure \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_bad_responses_models_endpoint_before_harbor \
  -q
# red: focused host-route test first failed because the reason lacked operator
# guidance for the host.docker.internal DNS failure
# green: 2 passed

PATH=".scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH" \
  scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-host-route host.docker.internal \
  --local-container-runtime docker \
  --run-id swebench-host-route-guidance-20260816T130234Z \
  --results-root .scratch/glm52-local-serving/tmp/swebench-host-route-guidance-20260816T130234Z/results \
  --run-root .scratch/glm52-local-serving/tmp/swebench-host-route-guidance-20260816T130234Z/run
# exit 2: status=environment_setup_failed
# reason includes "host process could not resolve host.docker.internal; use a
# host-resolvable --responses-base-url for the adapter and keep
# --local-host-route host.docker.internal for Docker containers"

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

2026-08-16 Harbor agent container URL split:

Clean-context review found that `--responses-base-url` was used both for the
host `/models` preflight and as the Harbor agent's in-container Responses URL.
That made the recommended host-resolvable loopback URL work for preflight but
fail inside Docker, because `127.0.0.1` would resolve to the Harbor task
container. The verifier now keeps the original `--responses-base-url` for the
host preflight and rewrites only the Harbor agent job-config URL when the host
is `localhost`, `127.0.0.1`, or `::1`, preserving scheme, port, path, query,
and fragment while replacing the host with `--local-host-route`.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  -q
# red: generated Harbor job config passed http://127.0.0.1:18081/v1 to the
# Dockerized GLM52HarborAgent instead of http://host.docker.internal:18081/v1
# green: 1 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config \
  -q
# 2 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

Artifact URL-field follow-up:
`run.json`, `environment.json`, environment-failure summaries, and Harbor
success summaries now record both the host-facing `responses_base_url` and the
container-facing `harbor_agent_responses_base_url`. Normalized Harbor trial
records use the Harbor job-config agent URL, or a derived container-facing URL,
before appending `/responses` for endpoint fallback. Raw
`harbor-raw/trials.jsonl` is still copied as Harbor source output and is not
rewritten.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_ingests_harbor_021_native_result_layout \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config \
  -q
# 4 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

2026-08-16 SWE-bench minimal smoke metadata slice:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_harbor_smoke_config_pins_single_row_image \
  -q
# red: failed because the checked-in SWE-bench Harbor config/lock still had
# status=blocked and empty smoke_instances
```

Selected `astropy__astropy-12907` as the first minimal SWE-bench Verified
smoke instance from the materialized dataset parquet produced by
`prepare-swebench-hf-revision-main-20260816T115900Z`. The row records
`repo=astropy/astropy`, `version=4.3`, and row image
`swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest`. Host Docker
registry metadata resolved the tag-level immutable index digest:

```sh
docker buildx imagetools inspect \
  swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest
# Digest: sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88
# linux/amd64 manifest:
# sha256:a39a5c3244a9be4af79d7bb669cae25259452b4f9945561ed433efd0840b85b7
```

The Harbor SWE-bench smoke config and lock now pin:

- `smoke_instances: [astropy__astropy-12907]`
- `row_image: swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest`
- `image_digest:
  docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907@sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88`

This is only a metadata-preflight smoke configuration. `conformance.claim`
remains `none`, no published scores are recorded, and a future slice still must
wire the selected instance into real Harbor/SWE-bench execution artifacts.

2026-08-16 SWE-bench Verified Harbor placeholder slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_harbor_placeholders_preserve_guardrails \
  -q
# red: failed because
# .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml
# was missing

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_harbor_placeholders_preserve_guardrails \
  -q
# 1 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 108 passed

scripts/run python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-probe-20260816T110700Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-probe-20260816T110700Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-probe-20260816T110700Z/run
# exit 2: error: suite swe-bench-verified container_image must be declared
```

Added blocked placeholder files for the benchmark-spec paths
`.scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml`
and `.scratch/glm52-local-serving/harbor/datasets/swe-bench-verified.lock.yaml`.
They preserve the checked-in benchmark manifest's SWE-bench dataset and harness
pins, use Harbor/local-Docker vocabulary, and explicitly record that the suite
is not runnable and makes no conformance claim until official per-instance image
metadata, provider metadata, and smoke instance IDs are pinned.

`REQUIRED_PUBLISHED_SCORE_FIELDS` now includes `source_type`, and
`validate_conformance_inputs()` requires the value to be `primary`. Secondary
or otherwise unclassified URLs can no longer satisfy published-score
conformance metadata.

2026-08-16 published-score tolerance-basis guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_tolerance_basis \
  -q
# red: a complete score with numeric tolerance but no tolerance_basis was
# accepted as conformance metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_tolerance_basis \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 89 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 138 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

`REQUIRED_PUBLISHED_SCORE_FIELDS` now includes `tolerance_basis`, and
`validate_conformance_inputs()` requires it to be a non-empty object without
placeholder string values. A comparable published score can no longer provide
only a numeric tolerance without documenting the tolerance model basis, such as
sample size and expected variance.

2026-08-16 published-score tolerance-basis field guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_sample_size_and_variance_tolerance_basis \
  -q
# red: tolerance_basis objects with only sample_size or only variance were
# accepted as conformance metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_sample_size_and_variance_tolerance_basis \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 89 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 138 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

`is_valid_tolerance_basis()` now requires both `sample_size` and `variance`,
while preserving the previous rejection of placeholder string values. A
comparable published score can no longer satisfy conformance metadata with an
arbitrary non-empty tolerance-basis object.

2026-08-16 published-score model identity guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_published_score_model_mismatch \
  -q
# red before implementation:
# published-score model values could differ from the manifest model

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_published_score_model_mismatch \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 77 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 126 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

When the benchmark manifest declares a top-level `model`,
`validate_conformance_inputs()` now requires every selected published-score
entry to use that same model identity. This prevents a complete score record
for another model from passing the local conformance preflight.

2026-08-16 published-score tolerance type guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_numeric_tolerance \
  -q
# red before implementation:
# string tolerance values could pass as complete published-score metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_numeric_tolerance \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 78 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 127 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`validate_conformance_inputs()` now requires `tolerance` to be a finite
non-negative number. This keeps stringified or non-finite tolerance metadata
from passing the conformance preflight as though it were a usable tolerance
model.

2026-08-16 published-score score type guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_numeric_score \
  -q
# red before implementation:
# string score values could pass as complete published-score metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_numeric_score \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 79 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 128 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

`validate_conformance_inputs()` now requires `score` to be a finite number.
This keeps stringified or non-finite scores from passing the conformance
preflight as though they were usable numeric published results.

2026-08-16 cache readiness preflight slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_cache_preflight_records_available_materialized_caches \
  -q
# red: build_cache_preflight did not accept a cache root and always reported
# planned cache status, even when dataset and harness cache directories existed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_cache_preflight_records_available_materialized_caches \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 47 passed
```

`build_cache_preflight()` now records `dataset_cache_exists` and
`harness_cache_exists` for each suite. It marks a suite cache `available` only
when both materialized cache directories exist, and leaves missing cache inputs
as `planned`. This improves prepare artifact readiness reporting, but it does
not yet clone benchmark harness repositories or download pinned datasets.

2026-08-16 default smoke CLI slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_defaults_to_manifest_bwrap_fixture_suites \
  -q
# red: the smoke parser required --suite and had no default benchmark manifest
# for the prompt's documented `smoke --run-id ...` command shape

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_defaults_to_manifest_bwrap_fixture_suites \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 48 passed
```

The smoke subcommand now defaults to
`.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml` and, when
`--suite` is omitted, selects manifest suites that use `bwrap_rootfs` and the
fixture/static smoke path. It deliberately excludes HumanEval/MBPP codegen and
Terminal-Bench 2 Harbor smoke from the default, because the spec gives those
their own explicit smoke commands and they require stronger sandbox/Harbor
preconditions.

2026-08-16 default calibration manifest slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_calibration_command_defaults_to_checked_in_manifest \
  -q
# red: calibration rejected the prompt's documented command shape because
# --manifest was required

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_calibration_command_defaults_to_checked_in_manifest \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 49 passed
```

The calibration subcommand now defaults to
`.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`, matching the
benchmark spec's documented calibration command. This only covers the local
fixture calibration command shape; real HumanEval, MBPP, GSM8K, AIME, RULER,
and needle-smoke calibration against a live GLM endpoint remains incomplete.

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --execution-backend bwrap_rootfs \
  --run-id needle-three-position-20260815T000000Z
# pass; samples include beginning, middle, and end needle placement with
# reproducible_seed and prompt_sha256; metrics report 3/3 tasks passed under
# glm52-benchmark-results/needle-three-position-20260815T000000Z/

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --execution-backend bwrap_rootfs \
  --run-id archive-manifest-20260815T000000Z
# pass; archive manifest written to
# glm52-benchmark-results/archive-manifest-20260815T000000Z/archive-manifest.json
# with terminal=true, summary_status=pass, summary_path=summary.json, and
# relative Contract Artifact paths for summary, run, environment, manifests,
# samples, metrics, and failures.

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --execution-backend bwrap_rootfs \
  --run-id needle-resume-20260815T000000Z

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --execution-backend bwrap_rootfs \
  --run-id needle-resume-20260815T000000Z
# pass; second run records `needle-smoke` as `resumed` in
# glm52-benchmark-results/needle-resume-20260815T000000Z/run.json

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite gsm8k --suite aime \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --execution-backend bwrap_rootfs \
  --run-id math-static-smoke-20260815T000000Z
# pass; GSM8K/AIME samples include raw_response, extracted_answer,
# expected_answer, and normalization metadata under
# glm52-benchmark-results/math-static-smoke-20260815T000000Z/

scripts/run_glm52_benchmark_verifier.sh calibration \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --execution-backend bwrap_rootfs \
  --run-id calibration-20260815T215827Z
# pass; summary written to
# glm52-benchmark-results/calibration-20260815T215827Z/summary.json

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-smoke-20260815T221100Z
# pass; summary written to
# glm52-benchmark-results/code-bwrap-smoke-20260815T221100Z/summary.json

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-sample-fields-20260815T000000Z
# pass; HumanEval sample includes prompt_sha256, endpoint=fixture, decoding,
# latency_seconds, usage, dataset_revision, harness_revision, and state under
# glm52-benchmark-results/code-bwrap-sample-fields-20260815T000000Z/humaneval/samples.jsonl

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-layout-20260815T000000Z
# pass; result directory includes run.json, environment.json,
# benchmark-manifest.json, summary.json, suite samples/metrics/failures, and
# archive-manifest.json:
# glm52-benchmark-results/code-bwrap-layout-20260815T000000Z/

scripts/run_glm52_deployment.sh status \
  --state .scratch/glm52-local-serving/run/cleanup-code-bwrap-smoke-20260815T221100Z.json
# reports recorded bwrap task roots for humaneval and mbpp

scripts/run_glm52_deployment.sh cleanup \
  --state .scratch/glm52-local-serving/run/cleanup-code-bwrap-smoke-20260815T221100Z.json \
  --dry-run
# reports would-remove for both bwrap task roots

scripts/run python -m pytest \
  python/tests/test_glm52_deployment.py::test_deployment_state_fixture_supports_status_and_dry_run \
  -q
# 1 passed

scripts/run_glm52_deployment.sh status \
  --state .scratch/glm52-local-serving/run/deployment.json
# reports deployment_id=glm52-local-serving-fixture, namespace=glm52-local,
# and absent pidfiles for responses-adapter and dynamo-sglang

scripts/run_glm52_deployment.sh cleanup \
  --state .scratch/glm52-local-serving/run/deployment.json \
  --dry-run
# reports status=clean and reverse-order already-clean results for
# dynamo-sglang then responses-adapter

scripts/run python -m pytest python/tests/test_glm52_deployment.py -q
# 8 passed

scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 58 passed

scripts/run python -m py_compile \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_deployment.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_benchmark_verifier.sh

scripts/run_glm52_benchmark_verifier.sh conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --suite humaneval \
  --run-id conformance-dry-run
# exits 2 before inference:
# error: published score for humaneval missing fields: score, source_url, tolerance

git diff --check
```

2026-08-16 duplicate manifest-suite ID guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_selection_rejects_duplicate_suite_ids \
  -q
# red: duplicate suite ids were silently accepted by manifest selection because
# the later suite overwrote the earlier suite in the lookup map

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_selection_rejects_duplicate_suite_ids \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 80 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 129 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

`manifest_suites()` now validates that `suites` is a list of objects with
string IDs and rejects repeated suite IDs before `select_suites()`,
`manifest_suite_ids()`, or `validate_manifest_suite_coverage()` can use the
manifest. This prevents malformed manifests from masking one suite definition
with another before conformance or prepare validation.

2026-08-16 duplicate published-score suite guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_duplicate_published_score_suites \
  -q
# red: duplicate published-score entries for the same suite were silently
# accepted because the later score overwrote the earlier score in the lookup map

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_duplicate_published_score_suites \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 81 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 130 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

`published_score_by_suite()` now validates the `scores` list and rejects
repeated suite IDs before `validate_conformance_inputs()` or
`write_conformance_validation_artifact()` can use the published-score manifest.
This keeps conformance metadata unambiguous before inference or artifact writes.

2026-08-16 manifest model-identity guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_manifest_model_identity \
  -q
# red: conformance validation accepted an otherwise complete manifest with no
# manifest-level model identity

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_manifest_model_identity \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 82 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 131 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

`validate_conformance_inputs()` now requires `manifest["model"]` to be a
non-placeholder string before selecting suites and comparing published scores.
This makes the spec's model-identity condition mandatory for conformance
instead of only checking it when a manifest happened to declare a model.

2026-08-16 published-score manifest model guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_published_manifest_model_mismatch \
  -q
# red: conformance validation accepted a published-score manifest whose
# top-level model differed from the benchmark manifest model

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_published_manifest_model_mismatch \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 83 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 132 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

When `published-scores.yaml` declares a top-level `model`, it now must be a
non-placeholder string matching the benchmark manifest model. Per-score model
checks remain in place, so both manifest-level and score-level model identity
must agree before conformance artifacts can be written.

2026-08-16 malformed published-score entry guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_malformed_published_score_entries \
  -q
# red: a published-score entry with a non-string `suite` was skipped and later
# reported only as a missing selected score

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_malformed_published_score_entries \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 85 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 134 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

`published_score_by_suite()` now rejects every score entry that is not an
object with a string `suite` key. Malformed primary-source metadata can no
longer disappear from the score map and be misclassified as merely missing
coverage for the selected suite.

2026-08-16 manifest execution-backend allow-list guardrail:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_suite_validation_rejects_unknown_execution_backend \
  -q
# red: a suite with execution_backend=mystery_backend was accepted by manifest
# validation

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_suite_validation_rejects_unknown_execution_backend \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 85 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 134 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

`validate_suite_fields()` now rejects manifest suite `execution_backend` values
outside the verifier's known local backend set: `bwrap_rootfs`, `scripts_run`,
`local_docker`, `harbor_local_docker`, and `host_subprocess`. This prevents a
misspelled or invented backend from reaching prepare, smoke, calibration, or
conformance execution paths.

2026-08-16 conformance digest-pinned image guard slice:

- Extended conformance validation to reject selected `local_docker` and
  `harbor_local_docker` suites whose `container_image` is only a mutable tag.
- This keeps Docker-backed conformance from producing `status: validated` until
  the manifest records immutable image provenance via a `sha256` digest.
- The command-level regression verifies that no `conformance.json`, benchmark
  run state, or cleanup ledger is written when a selected Docker-backed suite
  uses a tag-only image reference.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_mutable_container_image_tags \
  -q
# red before implementation:
# conformance wrote status=validated for terminal-bench-2 with
# container_image=ghcr.io/harbor-framework/terminal-bench-2:smoke

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_mutable_container_image_tags \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 60 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 102 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 prepare cache materialization slice:

- Added a prepare-stage cache materialization helper for explicit local source
  metadata. Suites that declare `dataset_source.type: local_path` or
  `harness_source.type: local_path` now copy those sources into the configured
  benchmark cache under the run root's sibling `benchmarks/` directory.
- `cache_preflight` now records source provenance for materialized local
  sources: `dataset_source_type`, `dataset_source_sha256`,
  `harness_source_type`, and `harness_source_sha256`.
- Suites without explicit source metadata, including the current checked-in
  placeholder remote benchmark entries, remain `planned` rather than implying
  that upstream datasets or harnesses were fetched.
- This narrows the prompt's prepare-stage cache gap but does not yet implement
  remote `git`, `http_archive`, or Hugging Face dataset fetching for pinned
  upstream benchmark sources.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  -q
# red before implementation:
# AttributeError: module 'glm52_benchmark_verifier' has no attribute
# 'materialize_prepare_caches'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# red before prepare command wiring:
# needle-smoke cache_preflight status remained planned instead of available

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 51 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 93 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 pinned Git cache materialization slice:

- Extended prepare-stage cache materialization for `dataset_source.type: git`
  and `harness_source.type: git`.
- The materializer requires a non-placeholder `url` and `revision`, runs
  `git clone --no-checkout`, then checks out the pinned revision with
  `git checkout --detach <revision>`.
- `cache_preflight` now records `dataset_source_revision` and
  `harness_source_revision` for pinned Git sources.
- The regression uses a mocked `git` subprocess to verify command shape and
  artifact records without depending on GitHub availability. Real checked-in
  benchmark manifest entries still use placeholder revisions, so they remain
  non-conformance inputs until replaced with concrete pins.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  -q
# red before implementation:
# git dataset_source and harness_source entries were recorded in cache_preflight
# but not cloned or checked out, so caches stayed planned

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 3 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 52 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 94 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 HTTP archive cache materialization slice:

- Extended prepare-stage cache materialization for
  `dataset_source.type: http_archive` and `harness_source.type: http_archive`.
- The materializer requires `url` and `sha256`, downloads the archive to a
  temporary sibling path, checks the downloaded bytes against the pinned
  SHA-256, extracts the tar archive with Python's data-filtered tar extraction,
  and removes the downloaded archive.
- `cache_preflight` now records `dataset_source_type: http_archive` and
  `dataset_source_sha256` for materialized archive sources.
- The regression uses a mocked `urllib.request.urlretrieve` to verify download
  path, SHA validation, extraction, and cache-preflight records without relying
  on network availability. Real checked-in benchmark manifest entries still use
  placeholder source metadata, so they remain non-conformance inputs until
  replaced with concrete pins.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  -q
# red before implementation:
# http_archive dataset_source entries were recorded in cache_preflight but not
# downloaded or extracted, so caches stayed planned

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 53 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 95 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 Hugging Face cache materialization slice:

- Extended prepare-stage cache materialization for
  `dataset_source.type: huggingface`, `dataset_source.type:
  huggingface_or_swebench`, and the same source types on `harness_source`.
- The materializer requires a concrete `repo_id` or `dataset` plus a pinned
  non-placeholder `revision` before it can populate a cache directory.
- It runs `hf download <repo> --repo-type <type> --revision <rev> --local-dir
  <cache>`, removing any stale cache directory first. On older environments
  without `hf`, it falls back to legacy `huggingface-cli download` and keeps
  that CLI's `--local-dir-use-symlinks False` option. Dataset sources default
  to Hugging Face `dataset` repo type; harness sources default to `model`
  unless the manifest declares `repo_type`.
- `cache_preflight` records `*_source_type` and `*_source_revision`, so prepare
  artifacts distinguish materialized Hugging Face/SWE-bench sources from
  placeholder planned caches.
- The regressions use mocked command lookup and `subprocess.run` calls to verify
  command shape, modern/legacy CLI selection, destination, pinned revision, and
  cache-preflight records without relying on network availability.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  -q
# red before implementation:
# unsupported dataset_source.type: 'huggingface_or_swebench'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 5 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 54 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 96 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 prepare placeholder-revision guard slice:

- Added prepare-stage validation that rejects placeholder suite
  `dataset_revision` and `harness_revision` values before writing a
  `prepared` artifact, run state, or cleanup ledger.
- The guard treats `TODO`, `TBD`, empty values, `<placeholder>` forms, and
  `pinned-placeholder` markers as unpinned prepare inputs.
- This prevents the checked-in benchmark manifest's placeholder revisions from
  producing a successful prepare state that could be confused with a real
  upstream benchmark setup. Fixture-only smoke/calibration paths can still use
  local fixture revisions.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  -q
# red before implementation:
# prepare wrote status=prepared for suites whose dataset_revision was
# <suite>@pinned-placeholder

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_writes_run_state_and_cleanup_ledger \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 55 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 97 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 prepare source-revision consistency slice:

- Added prepare-stage validation that rejects explicit source metadata whose
  `revision` does not match the suite-level `dataset_revision` or
  `harness_revision`.
- The guard accepts either an exact match or the suffix after the suite
  revision's `@`, matching manifest values such as `openai/gsm8k@rev` paired
  with `dataset_source.revision: rev`.
- The guard runs before cache materialization, artifact writing, run state, or
  cleanup-ledger writes. This prevents prepare artifacts from advertising one
  benchmark revision while fetching a different source revision.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_source_revision_mismatch \
  -q
# red before implementation:
# prepare wrote status=prepared when needle-smoke advertised
# dataset_revision=needle-smoke@advertised-rev but dataset_source.revision was
# fetched-rev

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_source_revision_mismatch \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_writes_run_state_and_cleanup_ledger \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_source_revision_mismatch \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  -q
# 5 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 56 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 98 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 conformance placeholder-revision guard slice:

- Extended conformance validation to reject selected suites whose
  `dataset_revision` or `harness_revision` still contains placeholder revision
  markers, including `@pinned-placeholder`.
- This closes a guardrail gap where a published-score manifest with otherwise
  complete fields could match a placeholder benchmark manifest and produce a
  `status: validated` conformance artifact.
- The command-level regression verifies that no `conformance.json`, benchmark
  run state, or cleanup ledger is written for placeholder suite revisions.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_placeholder_suite_revisions \
  -q
# red before implementation:
# conformance wrote status=validated for humaneval when both suite and score
# revisions were openai/humaneval@pinned-placeholder and
# evalplus@pinned-placeholder

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_placeholder_suite_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 57 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 99 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 conformance container-image guard slice:

- Extended conformance validation to reject `local_docker` and
  `harbor_local_docker` suites that do not declare a concrete `container_image`.
- This prevents Docker-backed benchmark conformance from producing
  `status: validated` while the manifest lacks the image reference needed for
  immutable image digest capture and reproducible local execution.
- The command-level regression verifies that no `conformance.json`, benchmark
  run state, or cleanup ledger is written when a selected Docker-backed suite is
  missing `container_image`.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_container_image_for_docker_suites \
  -q
# red before implementation:
# conformance wrote status=validated for terminal-bench-2 with
# execution_backend=harbor_local_docker and no container_image

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_comparable_score \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_container_image_for_docker_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 3 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 58 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 100 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 conformance source-metadata guard slice:

- Extended conformance validation to require selected suites to declare both
  `dataset_source` and `harness_source` metadata before writing a validated
  conformance artifact.
- The guard reuses the prepare-stage source revision consistency check, so a
  conformance suite's source metadata must match the suite-level
  `dataset_revision` and `harness_revision`.
- Validation still reports earlier conformance errors first, such as missing
  published-score fields, non-comparable score metadata, or score/profile
  mismatches. The source-metadata guard blocks only otherwise-valid conformance
  inputs that would not be reproducible from a declared source.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_source_metadata \
  -q
# red before implementation:
# conformance wrote status=validated for humaneval with pinned revisions but no
# dataset_source or harness_source metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_missing_published_score_fields \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_profile_mismatch \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_decoding_profile_mismatch \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_comparable_score \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_defaults_to_all_manifest_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_container_image_for_docker_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_source_metadata \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 8 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 59 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 101 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 prepare container-runtime preflight slice:

- Added prepare-stage `container_runtime_preflight` records for manifests that
  select `local_docker` or `harbor_local_docker` suites.
- The prepare command now accepts `--local-container-runtime` (`docker` or
  `podman`) and records JSON output from `<runtime> version --format json` and
  `<runtime> info --format json` when reachable.
- This covers the benchmark-spec requirement that Harbor-backed preparation
  validate local container runtime access and record runtime version/details
  instead of relying only on `which docker`.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  -q
# red: KeyError: 'container_runtime_preflight'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 44 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 85 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 run lock ledger slice:

- Added `benchmark-<run-id>.lock` writing for local benchmark run ledgers. The
  lock JSON records schema version, run id, mode, initial status, creation time,
  current PID, run-root benchmark state path, cleanup state path, and result
  directory.
- The lock writer is called when the benchmark verifier creates run-root state
  for fixture smoke/calibration, bwrap codegen smoke, Harbor pre-launch,
  prepare, and conformance validation paths.
- The bwrap codegen smoke writer now also seeds its cleanup ledger before task
  result processing and later overwrites it with observed bwrap tasks, matching
  the spec requirement that the run ledger exists before execution.
- Tests now assert lock artifacts on the fixture path and on command-like
  prepare, Harbor pre-launch, and bwrap codegen paths.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_writes_run_lock \
  -q
# red: FileNotFoundError for benchmark-run-lock.lock

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_writes_run_lock \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 43 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 84 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 benchmark run-record serving input slice:

- `write_fixture_benchmark_run` now accepts optional
  `serving_summary_path`, `responses_base_url`, and `chat_base_url` inputs.
- When supplied, both the result-local `run.json` and run-root
  `benchmark-<run-id>.json` preserve those fields so benchmark artifacts can be
  tied back to the serving verifier summary and endpoint configuration.
- Existing callers are unchanged because the fields are optional.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_serving_inputs \
  -q
# red before implementation:
# TypeError: write_fixture_benchmark_run() got an unexpected keyword argument
# 'serving_summary_path'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_serving_inputs \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 42 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 83 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 manifest profile-required validation slice:

- `profile` is now a required benchmark-suite manifest field alongside the
  dataset, harness, prompt template, execution backend, decoding profile, and
  metric pins.
- Added a focused regression test for missing `profile`.
- Updated test-local benchmark manifests so verifier tests exercise explicit
  suite profiles instead of relying on implicit suite IDs.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_suite_validation_requires_profile \
  -q
# red before implementation:
# AssertionError: suite profile should be required

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_suite_validation_requires_profile \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# intermediate fixture fallout after tightening the manifest contract:
# 22 failed, 19 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 41 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 82 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 sample reproducibility metadata slice:

- Fixture and bwrap code-generation `samples.jsonl` records now include
  manifest-derived `profile` and explicit `decoding_profile` fields.
- The existing `decoding` field is preserved for compatibility, but the sample
  artifacts now match the spec vocabulary for audited local benchmark runs.
- Covered both fixture benchmark samples and bwrap code-generation samples.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_emits_required_artifacts \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_records_task_roots \
  -q
# red before implementation:
# KeyError: 'decoding_profile'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_emits_required_artifacts \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_records_task_roots \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 41 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 82 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 Harbor raw-output cleanup-ledger slice:

- The benchmark spec requires the verifier to record every temporary directory
  that must be cleaned up. The Harbor smoke path creates
  `glm52-benchmark-results/<run-id>/harbor-raw` before invoking Harbor, so that
  directory is now recorded in `.scratch/glm52-local-serving/run/cleanup-<run-id>.json`
  under `temp_dirs` before the external Harbor subprocess starts.
- `scripts/glm52_deployment.py` now treats benchmark cleanup-ledger
  `temp_dirs` as actionable host-side cleanup records. Dry-run reports
  `would-remove`; real cleanup removes the directory.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  python/tests/test_glm52_deployment.py::test_cleanup_ledger_removes_temp_dirs \
  -q
# red before implementation:
# cleanup["temp_dirs"] == []
# cleanup_manifest(...).results == []

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  python/tests/test_glm52_deployment.py::test_cleanup_ledger_removes_temp_dirs \
  -q
# 2 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_deployment.py \
  -q
# 49 passed
```

2026-08-16 Harbor post-launch failure state slice:

- Added terminal run-state finalization for the path where Harbor is available
  and `harbor terminal-bench` launches, but exits nonzero before producing
  usable trial artifacts.
- The verifier now writes the classified `environment_setup_failed` summary and
  updates both result-local `run.json` and
  `.scratch/glm52-local-serving/run/benchmark-<run-id>.json` to the same
  terminal status, preserving crash-recovery visibility for cleanup tooling.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_finalizes_state_after_harbor_failure \
  -q
# red before implementation:
# AssertionError: assert 'running' == 'environment_setup_failed'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_finalizes_state_after_harbor_failure \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 40 passed
```

2026-08-16 archive Contract Artifact hash slice:

- Added `contract_artifact_sha256` to every generated
  `archive-manifest.json`.
- The hash map uses file-byte SHA-256 values keyed by the same relative paths
  listed in `contract_artifacts`, preserving the existing artifact list while
  making archived run integrity auditable after files are moved or copied.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_archive_manifest_records_contract_artifact_hashes \
  -q
# red before implementation:
# KeyError: 'contract_artifact_sha256'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_archive_manifest_records_contract_artifact_hashes \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 38 passed
```

2026-08-16 conformance validation artifact slice:

- Added `--results-root` and `--run-root` to the `conformance` subcommand.
- Complete conformance inputs now write run-scoped validation artifacts:
  `conformance.json`, `benchmark-manifest.json`, `published-scores.json`,
  `archive-manifest.json`, and run/cleanup ledgers.
- The command remains validation-only and still refuses incomplete or
  placeholder published-score manifests before inference.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# red before implementation:
# argparse rejected --results-root and --run-root for conformance

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 35 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 75 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 host-subprocess backend guard slice:

- Added a guard to the fixture smoke/calibration path so
  `execution_backend=host_subprocess` cannot run benchmark fixtures.
- This preserves the benchmark spec boundary that `host_subprocess` is reserved
  for trusted preparation and scoring helpers, not model-facing benchmark task
  execution or model-authored code.
- Added `test_fixture_benchmark_run_rejects_host_subprocess_backend`.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_fixture_benchmark_run_rejects_host_subprocess_backend \
  -q
# red before implementation:
# AssertionError: host_subprocess should not run benchmark fixtures

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_fixture_benchmark_run_rejects_host_subprocess_backend \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 36 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 76 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 Harbor run-state ledger slice:

- Added pre-launch run-state and cleanup-ledger writing for the
  `terminal-bench-2` Harbor smoke pass path before `harbor terminal-bench` is
  invoked.
- The fake-Harbor pass-path regression now asserts the benchmark state and
  cleanup ledger exist with `status=running` before the external Harbor command
  can run.
- The Harbor success writer finalizes `run.json` and
  `.scratch/glm52-local-serving/run/benchmark-<run-id>.json` to
  `status=completed` after ingesting Harbor `trials.jsonl`.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# red before implementation:
# AssertionError: benchmark-tbench2-harbor-pass.json was absent before Harbor launch

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 37 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 74 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

2026-08-16 Harbor environment artifact slice:

- Added `environment.json` to the `terminal-bench-2` Harbor smoke pass path so
  the pass-path layout includes the execution environment contract artifact
  required by the benchmark verifier result layout.
- The fake-Harbor pass-path regression now verifies the artifact content and
  requires `environment.json` in `archive-manifest.json`.
- A misplaced intermediate edit briefly inserted Harbor-only environment fields
  into the bwrap codegen writer; `python/tests/test_glm52_benchmark_verifier.py`
  caught the resulting `NameError`, and the duplicate block was removed.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# red before implementation:
# FileNotFoundError: .../environment.json

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 34 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 74 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

2026-08-16 default conformance CLI slice:

- Updated the `conformance` subcommand so `--suite` is optional. When omitted,
  it derives the selected suites from the manifest, matching the execution
  prompt's documented dry-run command.
- Added `test_conformance_command_defaults_to_all_manifest_suites` to verify
  the command reaches conformance validation instead of argparse failure.
- Added checked-in manifest coverage for the default conformance suite set by
  requiring published-score placeholders for every suite in
  `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`.
- Added a non-comparable `needle-smoke` placeholder to
  `.scratch/glm52-local-serving/benchmarks/published-scores.yaml`; it still
  fails conformance before inference because `score`, `source_url`, and
  `tolerance` remain placeholders.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_defaults_to_all_manifest_suites \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_scores_cover_default_conformance_suites \
  -q
# red before adding the needle-smoke placeholder, then 1 passed

scripts/run python scripts/glm52_benchmark_verifier.py conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --run-id conformance-default-suite-dry-run
# exits 2 before inference:
# error: published score for needle-smoke missing fields: score, source_url, tolerance

scripts/run_glm52_benchmark_verifier.sh conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --run-id conformance-default-suite-wrapper-dry-run
# exits 2 before inference:
# error: published score for needle-smoke missing fields: score, source_url, tolerance

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 33 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 73 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

Command-level prepare run-state proof:

```sh
scripts/run_glm52_benchmark_verifier.sh prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --run-id prepare-state-20260816T000000Z \
  --run-root .scratch/glm52-local-serving/run \
  --skip-endpoints
# pass; wrote
# glm52-benchmark-results/prepare-state-20260816T000000Z/prepare.json
# .scratch/glm52-local-serving/run/benchmark-prepare-state-20260816T000000Z.json
# .scratch/glm52-local-serving/run/cleanup-prepare-state-20260816T000000Z.json
# archive-manifest.json records summary_path=prepare.json and
# summary_status=prepared.
```

2026-08-16 prepare run-state and cleanup-ledger slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_writes_run_state_and_cleanup_ledger \
  -q
# red before fix: argparse rejected --run-root for the prepare command.
# green after fix: 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 31 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 71 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-16 bwrap code-generation task artifact archive slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_archives_task_artifact \
  -q
# red before fix: the expected result-local
# humaneval/artifacts/humaneval-001-codegen-artifact.json did not exist.
# green after fix: 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 30 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 70 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-16 bwrap code-generation latency artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_bwrap_codegen_smoke_command_preserves_runner_latency \
  -q
# red before fix: sample["latency_seconds"] was 0.0 when the bwrap runner
# reported duration_seconds=1.234.
# green after fix: 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 29 passed

scripts/run python -m pytest python/tests/test_glm52_bwrap_task_runner.py -q
# 5 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 69 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 Harbor environment-failure portable-artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  -q
# red before implementation: summary["harbor"]["trials_jsonl"] recorded an
# absolute temp path instead of harbor/trials.jsonl

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 28 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 63 passed

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite terminal-bench-2 \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-host-route host.docker.internal \
  --local-container-runtime docker \
  --run-id harbor-relative-artifacts-20260815T010500Z
# exits 2 by design in this environment; summary status is
# environment_setup_failed because the harbor executable is unavailable

scripts/run python - <<'PY'
import json
from pathlib import Path
root = Path("glm52-benchmark-results/harbor-relative-artifacts-20260815T010500Z")
summary = json.loads((root / "summary.json").read_text())
manifest = json.loads((root / "archive-manifest.json").read_text())
print(json.dumps({
    "summary_status": summary["status"],
    "harbor": summary["harbor"],
    "archive_contract_artifacts": manifest["contract_artifacts"],
    "trial_state": json.loads((root / summary["harbor"]["trials_jsonl"]).read_text())["state"],
}, indent=2, sort_keys=True))
PY
# summary_status=environment_setup_failed
# harbor.trials_jsonl=harbor/trials.jsonl
# harbor.artifacts_dir=harbor/artifacts
# harbor.smoke_config=harbor/configs/terminal-bench-2-smoke.yaml
# archive_contract_artifacts includes summary.json, harbor/trials.jsonl, and
# harbor/configs/terminal-bench-2-smoke.yaml
# trial_state=environment_setup_failed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 bwrap sandbox smoke archive-artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_smoke_summary_records_contract_artifacts \
  -q
# red before implementation: summary.json recorded the original task-root
# artifact path instead of result-local artifacts/smoke-artifact.json

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_smoke_summary_records_contract_artifacts \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 28 passed

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite bwrap-sandbox-smoke \
  --pool code_sandbox \
  --execution-backend bwrap_rootfs \
  --run-id bwrap-archive-artifacts-20260815T010000Z
# pass; summary written to
# glm52-benchmark-results/bwrap-archive-artifacts-20260815T010000Z/summary.json

scripts/run python - <<'PY'
import json
from pathlib import Path
root = Path("glm52-benchmark-results/bwrap-archive-artifacts-20260815T010000Z")
summary = json.loads((root / "summary.json").read_text())
manifest = json.loads((root / "archive-manifest.json").read_text())
smoke = json.loads((root / summary["contract_artifacts"]["smoke_artifact"]).read_text())
cleanup = json.loads((root / summary["contract_artifacts"]["cleanup_ledger"]).read_text())
print(json.dumps({
    "summary_status": summary["status"],
    "contract_artifacts": summary["contract_artifacts"],
    "archive_contract_artifacts": manifest["contract_artifacts"],
    "checkout_write": smoke.get("checkout_write"),
    "cleanup_schema_version": cleanup.get("schema_version"),
}, indent=2, sort_keys=True))
PY
# summary_status=pass
# contract_artifacts:
#   smoke_artifact=artifacts/smoke-artifact.json
#   cleanup_ledger=artifacts/cleanup.json
# archive_contract_artifacts includes summary.json,
# artifacts/smoke-artifact.json, and artifacts/cleanup.json
# checkout_write=denied
# cleanup_schema_version=1

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 63 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 fixture/static infrastructure failure-rate artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_emits_required_artifacts \
  -q
# red: fixture/static suite metrics and summary suite records were missing
# infrastructure_failure_denominator and infrastructure_failure_rate

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_emits_required_artifacts \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 28 passed

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --execution-backend bwrap_rootfs \
  --run-id fixture-infra-rate-20260815T000000Z
# pass; summary status pass, infrastructure_failure_denominator=3 and
# infrastructure_failure_rate=0.0 for the needle-smoke fixture suite

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 63 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 infrastructure failure-rate artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_separates_infrastructure_failures \
  -q
# red: infrastructure_failure_denominator and infrastructure_failure_rate were
# missing from suite metrics and top-level summary suite records

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_separates_infrastructure_failures \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 28 passed

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-infra-rate-20260815T000000Z
# pass; summary status pass, infrastructure_failure_denominator=1 and
# infrastructure_failure_rate=0.0 for each successful codegen suite

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 63 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 bwrap codegen multi-suite runner-failure artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_bwrap_codegen_smoke_command_records_all_suites_after_runner_failure \
  -q
# red: the first suite runner failure left later requested suites without task
# results, so summary writing raised `missing bwrap task result for suite: mbpp`

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_bwrap_codegen_smoke_command_records_all_suites_after_runner_failure \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 28 passed

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-multisuite-failure-path-20260815T000000Z
# pass; normal successful bwrap codegen command path still exits 0 and writes
# summary status pass

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 63 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 bwrap codegen malformed-runner artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_bwrap_codegen_smoke_command_writes_summary_for_malformed_runner_output \
  -q
# red: malformed successful runner stdout raised JSONDecodeError before
# glm52-benchmark-results/<run-id>/summary.json could be written

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_bwrap_codegen_smoke_command_writes_summary_for_malformed_runner_output \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 27 passed

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-malformed-path-20260815T000000Z
# pass; normal successful bwrap codegen command path still exits 0 and writes
# summary status pass

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 62 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 bwrap codegen runner-failure artifact slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_bwrap_codegen_smoke_command_writes_summary_for_runner_failure \
  -q
# red: command returned the bwrap runner error before writing
# glm52-benchmark-results/<run-id>/summary.json

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_bwrap_codegen_smoke_command_writes_summary_for_runner_failure \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 26 passed

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-runner-failure-path-20260815T000000Z
# pass; normal successful bwrap codegen command path still exits 0 and writes
# summary status pass

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 61 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-16 fixture sample backend metadata slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_records_execution_backend_in_fixture_samples \
  -q
# red: fixture/static samples omitted execution_backend even when summary.json
# and environment.json recorded the selected backend

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_records_execution_backend_in_fixture_samples \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 90 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 139 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

Fixture/static smoke and calibration samples now record the selected
`execution_backend` in `samples.jsonl`, so per-sample artifacts preserve the
same backend condition as the run-level `summary.json` and `environment.json`.

2026-08-16 fixture sample prompt/metric metadata slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_prompt_template_and_metric_in_samples \
  -q
# red: fixture/static samples omitted prompt_template and metric even though
# those fields define score comparability

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_prompt_template_and_metric_in_samples \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 91 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 140 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

Fixture/static smoke and calibration samples now also record `prompt_template`
and `metric`, so each sample artifact preserves the manifest conditions needed
to interpret score comparability.

2026-08-16 metrics condition metadata slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_manifest_conditions_in_metrics \
  -q
# red: metrics.json omitted manifest condition fields such as profile

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_manifest_conditions_in_metrics \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 93 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 142 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

Fixture/static and bwrap-codegen `metrics.json` artifacts now record `profile`,
`dataset_revision`, `harness_revision`, `prompt_template`, `execution_backend`,
`decoding_profile`, and `metric`, so compact score artifacts preserve the same
run conditions as sample artifacts.

2026-08-16 stale metrics resume guard slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_fixture_benchmark_run_does_not_resume_stale_metrics_schema \
  -q
# red: stale completed metrics missing condition fields were still considered
# resumable, so the stale samples.jsonl sentinel remained after rerun

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_fixture_benchmark_run_does_not_resume_stale_metrics_schema \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 93 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 142 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

Fixture/static resume now requires completed `metrics.json` artifacts to carry
the required condition fields before a suite is marked `resumed`. Older complete
artifacts that lack `profile`, `dataset_revision`, `harness_revision`,
`prompt_template`, `execution_backend`, `decoding_profile`, or `metric` are
regenerated, preventing stale score artifacts from being silently reused after
the benchmark schema changes.

2026-08-16 GSM8K cache-backed calibration slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_calibration_uses_materialized_gsm8k_dataset_cache \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_emits_math_answer_artifacts \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 101 passed
```

GSM8K calibration now reads the first valid sample from a materialized local
JSONL dataset cache when one is available. The focused cache regression writes
`samples.jsonl` under a local `benchmarks/datasets/gsm8k` cache and verifies
the emitted sample preserves `dataset_sample_id=gsm8k-local-0001`,
`prompt=What is 40 plus 2?`, `expected_answer=42`, `extracted_answer=42`, and
`endpoint=fixture`. The same run preserves the normal contract artifact shape:
`gsm8k/metrics.json` records one passed task with zero model and infrastructure
failures, `gsm8k/failures.jsonl` is empty, and `archive-manifest.json` records
`summary_status=pass`. The existing math fixture regression still passes, so
when no materialized GSM8K cache is present, fixture/static math behavior keeps
emitting the fallback answer artifacts for GSM8K and AIME.

2026-08-15 bwrap codegen failure-taxonomy slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_separates_infrastructure_failures \
  -q
# red: summary status was `fail`; infrastructure failures were still treated
# as model-side failures

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_separates_infrastructure_failures \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 25 passed

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite humaneval --suite mbpp \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --pool code_sandbox \
    --execution-backend bwrap_rootfs \
    --run-id code-bwrap-taxonomy-20260815T000000Z
# pass; summary status remains pass for successful bwrap codegen samples,
# with model_failures=0 and infrastructure_failures=0

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 60 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```

2026-08-15 prepare archive-manifest slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_prepare_artifact_records_manifest_and_rootfs \
  -q
# red: failed with FileNotFoundError for archive-manifest.json before
# write_prepare_artifact emitted a prepare-stage archive manifest

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_prepare_artifact_records_manifest_and_rootfs \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 24 passed

scripts/run_glm52_benchmark_verifier.sh prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --run-id prepare-archive-20260815T000000Z \
  --skip-endpoints
# pass; wrote glm52-benchmark-results/prepare-archive-20260815T000000Z/prepare.json
# and archive-manifest.json with summary_path=prepare.json,
# summary_status=prepared, terminal=true, and prepare.json in contract_artifacts

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 59 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
```
