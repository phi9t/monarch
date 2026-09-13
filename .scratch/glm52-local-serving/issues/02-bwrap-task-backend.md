# Add bwrap Task Backend for GLM-5.2 Benchmarks

Type: task
Status: resolved
Blocked by:

## Requirements

- Add a host-side bwrap task backend for verifier-owned benchmark execution.
- Reuse Monarch's Hermetic Rootfs userland and toolchain.
- Create one fresh task root per benchmark task with read-only input and
  writable work, output, and temporary directories.
- Disable network and GPU visibility by default for generated-code execution.
- Record bwrap task PIDs and task roots in the cleanup ledger.
- Refuse to give model-authored code write access to the repository checkout.
- Provide a bwrap sandbox smoke that proves write isolation and no-network
  behavior.

## Exclusions

- Do not replace official Docker-backed Terminal-Bench 2 or SWE-bench
  conformance environments.
- Do not run cleanup through the Hermetic Rootfs; cleanup must see host PIDs.
- Do not expose host Docker control from inside a bwrap task.

## Verification Evidence

- Focused tests for task-root creation, cleanup-ledger recording, command
  guarding, network-disabled behavior, and checkout write denial.
- A smoke command that runs a trusted fixture inside the bwrap task backend and
  emits a Contract Artifact.

## Answer

Implemented the first host-side bwrap task backend slice:

- Added `scripts/glm52_bwrap_task_runner.py` and
  `scripts/run_glm52_bwrap_task_runner.sh`.
- Added per-task roots under
  `.scratch/glm52-local-serving/run/bwrap/<run-id>/<task-id>/` with `input/`,
  `work/`, `output/`, `tmp/`, and `task.json`.
- Mounted the Monarch rootfs read-only, the checkout read-only, task `input/`
  read-only, and task `work/`, `output/`, and `tmp/` writable under a task tmpfs.
- Disabled network and GPU visibility by default; network and GPU are explicit
  task spec choices.
- Recorded host-visible bwrap task PIDs and task roots in the cleanup ledger
  with the `glm52_bwrap_task_runner` command guard.
- Added `scripts/glm52_benchmark_verifier.py` and
  `scripts/run_glm52_benchmark_verifier.sh` for the public
  `bwrap-sandbox-smoke` smoke interface.
- Added focused tests in `python/tests/test_glm52_bwrap_task_runner.py` and
  `python/tests/test_glm52_benchmark_verifier.py`.
- Added `glm52-benchmark-results/` to `.gitignore`.
- Extended the code-generation smoke summary to include `duration_seconds`
  from the underlying bwrap task result. The benchmark verifier records that
  value as per-sample `latency_seconds` for HumanEval/MBPP-style bwrap smoke
  artifacts.

Verification evidence:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 28 passed

python3 -m py_compile \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_deployment.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_benchmark_verifier.py

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

git diff --check
```

2026-08-16 cleanup-ledger container and port visibility slice:

- Extended host-side deployment cleanup-ledger status to report recorded
  `containers` and `ports` alongside bwrap task roots.
- Extended cleanup dry-run output to surface recorded ports first as
  `manual-review` with the detail
  `port ownership must be confirmed before cleanup`.
- Extended cleanup dry-run output to surface recorded containers as
  `would-remove`.
- Non-dry-run cleanup remains conservative for resources that need host
  ownership proof: ports and containers report `manual-review` instead of
  killing port owners or removing containers.

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_deployment.py::test_cleanup_ledger_reports_containers_and_ports_in_dry_run \
  -q
# red before implementation:
# KeyError: 'containers'

scripts/run python -m pytest \
  python/tests/test_glm52_deployment.py::test_cleanup_ledger_reports_containers_and_ports_in_dry_run \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_deployment.py -q
# 11 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 91 passed

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

2026-08-16 task-spec directory artifact slice:

- Extended per-task `task.json` to record the task-local `task_input_dir`,
  `work_dir`, `output_dir`, and `tmp_dir` in addition to the original source
  `input_dir`.
- This makes the persisted task artifact match the execution prompt's task-spec
  directory contract closely enough to reproduce or inspect a generated-code
  sandbox from the task root alone.

```sh
scripts/run python -m pytest python/tests/test_glm52_bwrap_task_runner.py -q
# red: KeyError: 'task_input_dir'

scripts/run python -m pytest python/tests/test_glm52_bwrap_task_runner.py -q
# 5 passed

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

2026-08-16 code-generation smoke timing coverage:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_bwrap_task_runner.py::test_codegen_smoke_summary_includes_duration \
  -q
# 1 passed

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

2026-08-16 task-root identifier path-safety coverage:

- `prepare_task_root()` now rejects path-like `run_id` and `task_id` values
  before creating the task root or writing `task.json`.
- Rejected identifiers include slash traversal (`../escape`) and special path
  components (`.` and `..`).

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_bwrap_task_runner.py::test_prepare_task_root_rejects_path_like_task_identifiers \
  -q
# red before implementation:
# Failed: DID NOT RAISE <class 'glm52_bwrap_task_runner.BwrapTaskError'>

scripts/run python -m pytest \
  python/tests/test_glm52_bwrap_task_runner.py::test_prepare_task_root_rejects_path_like_task_identifiers \
  -q
# 6 passed

scripts/run python -m pytest python/tests/test_glm52_bwrap_task_runner.py -q
# 12 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 118 passed

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

2026-08-16 cleanup-ledger removal coverage:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_deployment.py::test_cleanup_ledger_removes_bwrap_task_root \
  -q
# 1 passed; verifies non-dry-run cleanup removes a recorded bwrap task root and
# reports cleanup=removed.

scripts/run_glm52_deployment.sh status --state "$state"
# reports the throwaway task root as exists=true, status=recorded.

scripts/run_glm52_deployment.sh cleanup --state "$state"
# exits 0, reports status=clean and cleanup=removed, and the task root no
# longer exists.

scripts/run python -m pytest python/tests/test_glm52_deployment.py -q
# 9 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 65 passed

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
