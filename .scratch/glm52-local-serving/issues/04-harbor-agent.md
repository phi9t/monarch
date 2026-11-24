# Add Harbor Agent for GLM-5.2 Responses Adapter

Type: task
Status: ready-for-human
Blocked by: 03

## Current Status

The Harbor agent helper, Terminal-Bench 2 smoke configuration, URL artifact
split, host-route recording, and setup-failure classification are implemented
and tested locally. The remaining work needs host-control Harbor/local Docker
execution against a valid GLM-5.2 Responses adapter URL. Current recorded runs
classify missing or invalid environment as setup failure and do not prove a real
Terminal-Bench 2 task. Do not mark this ticket resolved until real Harbor trial
artifacts are copied into a run-scoped benchmark result directory.

Current host-control artifacts narrow the next blocker to adapter readiness, not
generic Harbor or Docker availability. In
`glm52-benchmark-results/tbench2-smoke-20260816T155253Z/summary.json`, both
`environment_diagnostics.tools.docker.status` and
`environment_diagnostics.tools.harbor.status` are `ok`; the suite stops before
Harbor launch because `http://127.0.0.1:8080/v1/models` returns HTTP 404 rather
than a GLM-backed Responses model list. Do not repeat the Harbor smoke against
that URL. The next non-repeated live gate is to start a valid GLM-5.2 Responses
adapter on a known-free host URL and rerun the same host-control smoke.

## Requirements

- Add a Harbor-compatible agent that drives tasks through the local
  Responses-compatible GLM-5.2 adapter.
- Preserve the Codex-relevant profile: Responses endpoint, streaming enabled,
  tools enabled, and GLM thinking disabled.
- Convert Harbor task observations into Responses requests.
- Convert Responses function calls into Harbor-supported tool actions without
  bypassing the checked-in Responses adapter.
- Preserve task IDs, trial IDs, model IDs, endpoint URLs, and agent version in
  trial artifacts.
- Support Terminal-Bench 2 smoke through Harbor's local Docker execution path.
- Copy Harbor trial artifacts into the run-scoped benchmark result directory.
- Record the local host route used by Harbor containers to reach the adapter.

## Exclusions

- Do not call the SGLang Chat Completions endpoint directly from the Harbor
  agent.
- Do not expose the host Docker socket to the model-controlled task shell.
- Do not replace official Harbor or Terminal-Bench scoring semantics.

## Verification Evidence

- Focused tests for observation-to-Responses conversion, function-call handling,
  final-answer handling, artifact metadata, and route recording.
- A pinned Terminal-Bench 2 smoke configuration that can run one or more small
  tasks against the local adapter.

## Answer

Partial implementation completed for the first Harbor agent slice:

- Added `scripts/glm52_harbor_agent.py`.
- Added `GLM52HarborAgent.build_responses_request()` to preserve the
  Responses endpoint, streaming, tool loop, and `enable_thinking=false` profile.
- Added function-call-to-Harbor-action conversion.
- Added Harbor trial artifact writing with task ID, trial ID, model ID,
  endpoint URL, agent version, environment provider, and local host route.
- Added benchmark-verifier classification for `terminal-bench-2` smoke. When
  Harbor or the local container runtime is missing, the verifier writes
  `glm52-benchmark-results/<run-id>/harbor/trials.jsonl` and a summary with
  `environment_setup_failed` rather than silently skipping or counting it as a
  model failure.
- Added environment-failure trial metadata for the intended local execution
  path: agent version, `/responses` endpoint URL, Responses base URL, local host
  route, environment provider, local container runtime, task ID, trial ID, model
  ID, state, and reason.
- Added pinned Terminal-Bench 2 smoke configuration artifacts under
  `.scratch/glm52-local-serving/harbor/`: `configs/terminal-bench-2-smoke.yaml`
  and `datasets/terminal-bench-2.lock.yaml`.
- Added smoke-config validation and copying into run-scoped Harbor result
  directories. Classified missing-Harbor runs now preserve
  `harbor/configs/terminal-bench-2-smoke.yaml` and record its SHA-256 in both
  `summary.json` and `harbor/trials.jsonl`.
- Added focused tests in `python/tests/test_glm52_harbor_agent.py` and
  `python/tests/test_glm52_benchmark_verifier.py`.

This does not yet run a real Harbor Terminal-Bench 2 task. Remaining work:
install or pin Harbor, invoke Harbor local Docker with the pinned smoke config,
and copy real trial artifacts into the run-scoped result directory.

Verification evidence:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 8 passed

GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-smoke-20260815T220217Z
# exits 2 with classified setup failure:
# reason: harbor executable not found
# summary: glm52-benchmark-results/tbench2-smoke-20260815T220217Z/summary.json

scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 48 passed

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

git diff --check

GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-metadata-20260815T000000Z
# exits 2 with classified setup failure:
# reason: harbor executable not found
# summary: glm52-benchmark-results/tbench2-metadata-20260815T000000Z/summary.json
# trial artifact: glm52-benchmark-results/tbench2-metadata-20260815T000000Z/harbor/trials.jsonl
# trial metadata includes:
# agent_version=glm52-harbor-agent-v1
# endpoint=http://localhost:8080/v1/responses
# responses_base_url=http://localhost:8080/v1
# environment_provider=local_docker
# local_container_runtime=docker
# local_host_route=host.docker.internal

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_requires_pinned_tasks \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_rejects_unpinned_task_list \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_smoke_config_artifact_records_sha256 \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  -q
# 4 passed

GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-config-20260815T000000Z
# exits 2 with classified setup failure:
# reason: harbor executable not found
# summary: glm52-benchmark-results/tbench2-config-20260815T000000Z/summary.json
# copied smoke config:
# glm52-benchmark-results/tbench2-config-20260815T000000Z/harbor/configs/terminal-bench-2-smoke.yaml
# summary and trials.jsonl both record smoke_config_sha256

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 24 passed

scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 57 passed

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

git diff --check
```

2026-08-16 Harbor pass-path plumbing slice:

- Added the verifier branch that invokes `harbor terminal-bench` when both
  `harbor` and the selected local container runtime are present.
- Added run-scoped success artifact ingestion:
  - copy Harbor `trials.jsonl` into `harbor/trials.jsonl`;
  - copy Harbor `artifacts/` into `harbor/artifacts/`;
  - copy and hash the pinned smoke config under `harbor/configs/`;
  - write `summary.json` with `tasks_total`, `tasks_passed`,
    `model_failures`, `infrastructure_failures`, and `score`;
  - include all Harbor artifacts in `archive-manifest.json`.
- Added strict JSONL validation so missing, empty, malformed, or non-object
  Harbor trial records fail verifier processing instead of producing a proxy
  green status.
- Added a fake-Harbor pass-path regression test:
  `test_terminal_bench_smoke_invokes_harbor_and_archives_trials`.

This still does not prove a real Terminal-Bench 2 task has run. The host remains
blocked on `harbor executable not found`; the pass path is verified with a fake
Harbor executable that writes the expected Harbor contract artifacts.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# red before implementation:
# status=environment_setup_failed, reason="harbor terminal-bench-2 runner is not implemented yet"

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

GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-harbor-passpath-20260816T000000Z
# exits 2 with classified setup failure:
# reason: harbor executable not found
# summary: glm52-benchmark-results/tbench2-harbor-passpath-20260816T000000Z/summary.json
```

2026-08-16 Harbor run-state ledger slice:

- Extended the fake-Harbor pass-path regression so the fake Harbor subprocess
  asserts `benchmark-<run-id>.json` and `cleanup-<run-id>.json` already exist
  before `harbor terminal-bench` is invoked.
- Added pre-launch Harbor run-state writing:
  - `glm52-benchmark-results/<run-id>/run.json` starts as `status=running`;
  - `.scratch/glm52-local-serving/run/benchmark-<run-id>.json` starts as
    `status=running`;
  - `.scratch/glm52-local-serving/run/cleanup-<run-id>.json` is created before
    the external Harbor command runs.
- The Harbor success writer now finalizes the benchmark run state to
  `status=completed` and records the completed `terminal-bench-2` suite.

This closes a verifier-owned ledger gap for the Harbor pass path. Real
Terminal-Bench 2 execution remains blocked by the missing Harbor executable on
this host.

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

GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-harbor-ledger-20260816T000000Z
# exits 2 with classified setup failure:
# reason: harbor executable not found
# summary: glm52-benchmark-results/tbench2-harbor-ledger-20260816T000000Z/summary.json
```

2026-08-16 Harbor environment artifact slice:

- Added `environment.json` to the Harbor smoke pass path before
  `harbor terminal-bench` is invoked.
- The artifact records Python version, PID, `harbor_local_docker` backend,
  Responses base URL, local host route, local container runtime, and
  environment provider.
- The fake-Harbor pass-path regression now verifies `environment.json` content
  and requires it in `archive-manifest.json`.

This strengthens the pass-path contract layout. It does not change the real
host blocker: `harbor` is still unavailable.

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

2026-08-16 prelaunch Harbor failure artifact slice:

- Extended the classified missing-Harbor path to write result-local `run.json`
  and `environment.json`, matching the minimum benchmark result layout even
  when the run fails before invoking Harbor.
- The prelaunch failure archive now includes hashes for `run.json`,
  `environment.json`, `summary.json`, `benchmark-manifest.json`, the Harbor
  smoke config, and `harbor/trials.jsonl`.
- The fresh prompt command still exits `2` because `harbor` is not installed on
  this host; the improvement is that the classified failure now preserves the
  same run-scoped operational context as other Harbor result paths.

Verification:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-smoke-20260816T033801Z
# exit 2; status=environment_setup_failed; reason="harbor executable not found"
# red artifact check: environment.json and run.json were absent

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  -q
# red before implementation:
# FileNotFoundError: .../results/tbench2-smoke/run.json

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 61 passed

GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-smoke-20260816T034000Z
# exit 2; status=environment_setup_failed; reason="harbor executable not found"
# wrote summary.json, run.json, environment.json, benchmark-manifest.json,
# harbor/configs/terminal-bench-2-smoke.yaml, harbor/trials.jsonl, and
# archive-manifest.json under
# glm52-benchmark-results/tbench2-smoke-20260816T034000Z/
```

2026-08-16 Harbor post-launch failure classification slice:

- Covered the case where `harbor` and the selected local container runtime are
  present, the verifier launches `harbor terminal-bench`, and Harbor exits
  nonzero before usable trial artifacts exist.
- The verifier keeps the existing classified setup-failure summary behavior and
  now also finalizes both copies of benchmark run state to
  `environment_setup_failed` with the Harbor failure reason. This avoids stale
  `running` state after a post-launch Harbor crash.

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

2026-08-16 Harbor raw-output cleanup-ledger slice:

- The Harbor smoke path now records the run-scoped `harbor-raw` output
  directory in `.scratch/glm52-local-serving/run/cleanup-<run-id>.json` before
  invoking `harbor terminal-bench`.
- The host-side deployment cleanup helper now consumes benchmark cleanup-ledger
  `temp_dirs`, so the raw Harbor output directory is visible in dry-run cleanup
  and removable after a failed or completed run.

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

2026-08-16 Harbor trial metadata validation slice:

- Added verifier-side validation for required Harbor trial metadata before the
  pass path computes task counts or writes a summary.
- Required trial fields are `task_id`, `trial_id`, `model_id`, `endpoint`,
  `agent_version`, `environment_provider`, and `local_host_route`, matching the
  Phase 5 prompt contract.
- The fake-Harbor pass-path fixture now emits those fields, and
  `test_harbor_success_summary_rejects_trial_missing_required_metadata` proves
  missing metadata fails instead of producing a proxy pass.

This strengthens artifact integrity for copied Harbor outputs. It does not
change the live blocker: real Terminal-Bench 2 execution still requires an
installed `harbor` executable.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_harbor_success_summary_rejects_trial_missing_required_metadata \
  -q
# red before implementation:
# AssertionError: Harbor trials missing required metadata should fail

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_harbor_success_summary_rejects_trial_missing_required_metadata \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 37 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 77 passed

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

2026-08-16 Harbor classified-failure manifest artifact slice:

- Extended the classified Harbor environment-failure path to accept the same
  optional benchmark manifest as the pass path.
- When a manifest is supplied, the failure writer validates the selected
  `terminal-bench-2` suite, writes `benchmark-manifest.json`, and lets
  `archive-manifest.json` include it alongside the failure `summary.json`,
  Harbor preflight `trials.jsonl`, and smoke config artifact.
- The direct environment-failure regression now checks the copied manifest and
  archive entry.

This keeps the result layout complete even when the local host cannot launch
Harbor. It still does not prove real Harbor execution.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  -q
# red before implementation:
# TypeError: write_harbor_environment_failure() got an unexpected keyword argument 'manifest'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
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

2026-08-16 Harbor manifest artifact slice:

- Added `benchmark-manifest.json` to the Harbor smoke pass path when
  `smoke --suite terminal-bench-2 --manifest <path>` is used.
- The pass path validates the selected `terminal-bench-2` manifest suite before
  copying the full manifest into the run-scoped result directory.
- The fake-Harbor pass-path regression now verifies that the copied manifest has
  the expected suite and that `archive-manifest.json` lists
  `benchmark-manifest.json`.

This completes another verifier-owned piece of the minimum Harbor result layout.
It does not change the live blocker: real Terminal-Bench 2 execution still
requires an installed `harbor` executable.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  -q
# red before implementation:
# FileNotFoundError: .../benchmark-manifest.json

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

2026-08-16 real Harbor CLI contract slice:

- Installed Harbor 0.21.0 into a scratch host-side Python 3.12 virtualenv under
  `.scratch/glm52-local-serving/tmp/harbor-venv` with
  `uv pip install --python .scratch/glm52-local-serving/tmp/harbor-venv/bin/python harbor==0.21.0`.
  This is local environment repair only, not checked-in dependency policy.
- The installed Harbor CLI does not provide the fake-tested
  `harbor terminal-bench` subcommand. Its real execution entrypoint is
  `harbor run --config <JobConfig>`.
- Updated the verifier to generate a run-scoped Harbor JobConfig at
  `harbor-raw/job-config.yaml` and invoke `harbor run --config ... --yes`.
  The JobConfig records `job_name`, `jobs_dir`, Docker environment type,
  allowed host route, `GLM52HarborAgent` import path, Responses base URL,
  stream setting, model id, and the pinned smoke task list from the checked-in
  smoke config.
- Added red-green coverage in
  `test_terminal_bench_smoke_invokes_real_harbor_run_config`. The red failure
  showed the old command was `["/usr/bin/harbor", "terminal-bench", "--config"]`;
  the green path verifies `["/usr/bin/harbor", "run", "--config", <job-config>,
  "--yes"]` and inspects the generated JobConfig.
- A real host-side smoke with Harbor 0.21.0 and Docker present now reaches
  `harbor run --config`, proving the previous missing-subcommand blocker is
  fixed. First run failed inside Harbor because its resolver installed
  `supabase==3.0.0a1`, whose package lacks the `acreate_client` symbol Harbor
  imports. Pinning `supabase==2.18.1` in the scratch venv restored that symbol.
- After the scratch Supabase repair, the real Harbor smoke reaches registry
  dataset resolution and fails with:
  `ValueError: Dataset terminal-bench-2@d28711d0da2675d0bb1d56de45ae5df6082438a3 not found`.
  Probe evidence: `harbor download terminal-bench-2` reports the dataset is not
  found, while `harbor download terminal-bench` succeeds and downloads 89
  legacy Terminal-Bench tasks. The workstream still requires Terminal-Bench 2,
  so this is a real upstream registry/configuration blocker rather than a reason
  to downgrade the suite.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  -q
# red before implementation:
# command[:3] was ["/usr/bin/harbor", "terminal-bench", "--config"]
# green after implementation: 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_finalizes_state_after_harbor_failure \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_smoke_config_artifact_records_sha256 \
  -q
# 5 passed

PATH="$PWD/.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH" \
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-harbor-run-20260816T000000Z \
    --results-root .scratch/glm52-local-serving/tmp/tbench2-harbor-run-20260816T000000Z/results \
    --run-root .scratch/glm52-local-serving/tmp/tbench2-harbor-run-20260816T000000Z/run
# exit 2; generated harbor-raw/job-config.yaml; failed on missing
# supabase.acreate_client before trial artifacts

uv pip install --python .scratch/glm52-local-serving/tmp/harbor-venv/bin/python 'supabase==2.18.1'
# has_acreate_client=True

PATH="$PWD/.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH" \
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-harbor-supabase-20260816T000000Z \
    --results-root .scratch/glm52-local-serving/tmp/tbench2-harbor-supabase-20260816T000000Z/results \
    --run-root .scratch/glm52-local-serving/tmp/tbench2-harbor-supabase-20260816T000000Z/run
# exit 2; generated harbor-raw/job-config.yaml; failed with:
# Dataset terminal-bench-2@d28711d0da2675d0bb1d56de45ae5df6082438a3 not found

.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor download terminal-bench-2 \
  --output-dir .scratch/glm52-local-serving/tmp/harbor-download-probe --overwrite
# Error: Dataset 'terminal-bench-2' (version: 'None') not found

.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor download terminal-bench \
  --output-dir .scratch/glm52-local-serving/tmp/harbor-download-probe --overwrite
# Successfully downloaded 89 task(s)
```

2026-08-16 Terminal-Bench 2 Harbor registry preflight slice:

- Added verifier-side preflight classification for the checked-in
  Terminal-Bench 2 smoke config when it points at
  `terminal-bench-2@d28711d0da2675d0bb1d56de45ae5df6082438a3`, which the real
  Harbor 0.21.0 registry does not resolve. With Harbor and Docker present, the
  verifier now writes an `environment_setup_failed` summary before launching
  `harbor run`, with a reason that names the unresolved dataset/version and
  asks for a resolvable Harbor dataset version or local Harbor dataset path.
- The preflight is scoped to the repository's default checked-in smoke config.
  Synthetic resolvable configs in tests still reach the `harbor run --config`
  path, so pass-path coverage continues to verify the real CLI contract.
- A host-side wrapper probe with the scratch Harbor venv on `PATH` now exits
  before Harbor launch:
  `tbench2-registry-preflight-20260816T000001Z` records
  `terminal-bench-2@d28711d0da2675d0bb1d56de45ae5df6082438a3 is not available in Harbor registry`.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_unresolved_harbor_dataset_before_launch \
  -q
# red before implementation:
# AssertionError: unresolved Harbor dataset must fail before launch
# green after implementation: 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_finalizes_state_after_harbor_failure \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_environment_failure_records_classified_summary \
  python/tests/test_glm52_benchmark_verifier.py::test_write_harbor_smoke_config_artifact_records_sha256 \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_unresolved_harbor_dataset_before_launch \
  -q
# 6 passed

env PATH="$PWD/.scratch/glm52-local-serving/tmp/harbor-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/terminal-bench-2-smoke.yaml \
    --responses-base-url http://host.docker.internal:8080/v1 \
    --local-container-runtime docker \
    --run-id tbench2-registry-preflight-20260816T000001Z \
    --results-root .scratch/glm52-local-serving/tmp/results \
    --run-root .scratch/glm52-local-serving/tmp/run
# exit 2 before Harbor launch; reason names unresolved terminal-bench-2 registry binding
```

2026-08-16 Terminal-Bench 2 Harbor registry repair:

- Replaced the checked-in smoke binding with the Harbor-native dataset that the
  real registry exposes:
  `execution.dataset: terminal-bench`,
  `execution.dataset_version: "2.0"`, and
  `execution.repo: harbor-framework/harbor@9dd349f28b969268aef419e910e1998149b612a5`.
  The smoke task is now `adaptive-rejection-sampler`, a task observed in the
  downloaded dataset.
- Preserved `benchmark_source.revision:
  d28711d0da2675d0bb1d56de45ae5df6082438a3` as Terminal-Bench 2 source
  provenance, but stopped using it as the Harbor dataset version. The generated
  Harbor JobConfig now carries dataset `terminal-bench`, version `2.0`, the
  pinned Harbor repo, and `task_names` from the smoke config.
- Moved the unresolved legacy binding regression into smoke-config validation:
  a config that still names `execution.dataset: terminal-bench-2` fails with
  `terminal-bench-2 is not available in Harbor registry`. The previous
  default-config registry preflight was removed because the default config is
  now resolvable.
- Real Harbor registry probe evidence:
  `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor download
  terminal-bench@2.0 --repo
  harbor-framework/harbor@9dd349f28b969268aef419e910e1998149b612a5`
  exited zero and printed `Successfully downloaded 89 task(s)`.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_harbor_smoke_config_has_pinned_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_rejects_unresolved_legacy_harbor_dataset \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_requires_pinned_tasks \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  -q
# red before implementation: 4 failed for the old terminal-bench-2 binding,
# missing legacy rejection, and old JobConfig dataset/version fields
# green after implementation: 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 104 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 153 passed

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

.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor download \
  terminal-bench@2.0 \
  --repo harbor-framework/harbor@9dd349f28b969268aef419e910e1998149b612a5
# Successfully downloaded 89 task(s)
```

2026-08-16 Harbor-native execution boundary:

- The repaired Harbor-native config now reaches host-side Harbor execution
  against the registry-resolved Terminal-Bench 2 binding:
  `terminal-bench@2.0` from
  `harbor-framework/harbor@9dd349f28b969268aef419e910e1998149b612a5`,
  task `adaptive-rejection-sampler`.
- The verifier now normalizes Harbor 0.21's nested `result.json` layout into
  the run-scoped contract artifact `harbor/trials.jsonl`.
- Host run `tbench2-harbor-native-infra-20260816T000000Z` exits with
  `status=fail`, `tasks_total=1`, `tasks_passed=0`,
  `infrastructure_failures=1`, and `model_failures=0`. The normalized trial
  records `state=environment_crashed` and exception
  `AttributeError: 'GLM52HarborAgent' object has no attribute 'setup'`.
- This is the next real Harbor agent API boundary. The current blocker is not
  the registry binding, Python import path, or Harbor artifact layout: those
  now progress far enough to produce real native Harbor result artifacts.

Verification:

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 106 passed

scripts/run python -m pytest python/tests/test_glm52_harbor_agent.py -q
# 5 passed
```

2026-08-16 Harbor context hook and run-loop compatibility slices:

- Added `populate_context_post_run(context)` as the minimal no-op Harbor hook.
  The focused Harbor-agent test then passed:
  `scripts/run uv run pytest python/tests/test_glm52_harbor_agent.py -q`
  reported `7 passed` from the worker.
- Real host smoke run `tbench2-harbor-context-hook-20260816T000000Z`
  advanced past the missing context hook and cleanly exposed the next Harbor
  agent API boundary: `AttributeError: 'GLM52HarborAgent' object has no
  attribute 'run'`.
- That run's summary records `status=fail` for `terminal-bench-2` with
  `tasks_total=1`, `tasks_passed=0`, `model_failures=1`,
  `infrastructure_failures=0`, and `score=0.0`. It wrote
  `.scratch/glm52-local-serving/tmp/results/tbench2-harbor-context-hook-20260816T000000Z/summary.json`
  and
  `.scratch/glm52-local-serving/tmp/results/tbench2-harbor-context-hook-20260816T000000Z/harbor/trials.jsonl`.
- Added `run(...)` with fake Responses plus fake environment TDD. Parent
  verification passed:
  `scripts/run uv run pytest python/tests/test_glm52_harbor_agent.py -q &&
  scripts/run python -m py_compile scripts/glm52_harbor_agent.py
  python/tests/test_glm52_harbor_agent.py` reported `8 passed`, and
  `py_compile` exited zero.
- Real host smoke run `tbench2-harbor-run-loop-20260816T000000Z` advanced past
  the missing `run(...)` boundary and failed when the host Harbor agent process
  called `http://host.docker.internal:8080/v1/responses`.
- That run's trial records `URLError: <urlopen error [Errno -2] Name or service
  not known>`, and its summary records `status=fail` for `terminal-bench-2` with
  `tasks_total=1`, `tasks_passed=0`, `model_failures=1`,
  `infrastructure_failures=0`, and `score=0.0`. It wrote
  `.scratch/glm52-local-serving/tmp/results/tbench2-harbor-run-loop-20260816T000000Z/summary.json`
  and
  `.scratch/glm52-local-serving/tmp/results/tbench2-harbor-run-loop-20260816T000000Z/harbor/trials.jsonl`.
- Host probing showed the current blocker: `host.docker.internal` does not
  resolve from the host process, while `localhost:8080` and `127.0.0.1:8080`
  return SearXNG HTML, not the GLM Responses adapter. This is the current
  compatibility boundary for real Harbor execution; no completion claim is made.

2026-08-16 Responses endpoint preflight slice:

- Added a Harbor-smoke-only strict Responses `/models` preflight before
  `harbor run`. The preflight requires JSON with a non-empty `data` list and
  classifies DNS, connection, HTTP, non-JSON, and empty-model responses as
  `environment_setup_failed` before Harbor launch.
- This protects the real Harbor path from spending a Terminal-Bench 2 run against
  an HTML service, a dead host route, or an endpoint that is not the GLM
  Responses adapter.
- Worker test evidence:
  `scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q`
  reported `107 passed`. The focused bad-endpoint regression
  `python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_bad_responses_models_endpoint_before_harbor`
  passed, as did the Harbor-related subset including
  `test_terminal_bench_smoke_invokes_real_harbor_run_config`.
- Parent host evidence used bad endpoint
  `http://host.docker.internal:8080/v1` with run id
  `tbench2-responses-preflight-20260816T000000Z` and exited `2` before Harbor
  launch. The run-scoped `summary.json`, `run.json`, and `harbor/trials.jsonl`
  record `status=environment_setup_failed` with reason:
  `Responses /models preflight failed for
  http://host.docker.internal:8080/v1/models: <urlopen error [Errno -2] Name or
  service not known>`.
- The trial artifact preserves the intended route metadata:
  `responses_base_url=http://host.docker.internal:8080/v1`,
  `endpoint=http://host.docker.internal:8080/v1/responses`,
  `local_host_route=host.docker.internal`, `environment_provider=local_docker`,
  and `local_container_runtime=docker`.
- Current real blocker: no GLM Responses adapter/upstream is running at a valid
  host URL. `localhost:8080` and `127.0.0.1:8080` serve SearXNG HTML, and
  `localhost:8000/v1/models` returns HTML 404. A real pass requires starting the
  GLM chat backend and adapter on free ports, then using a host-resolvable
  `--responses-base-url` while leaving `--local-host-route host.docker.internal`
  for Docker.
