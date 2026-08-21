# TaskRunner Contract And Bwrap Adapter

Type: task
Status: ready-for-agent
Blocked by: 07

## Objective

Introduce the `TaskRunner` request/result contract and adapt the existing
`scripts/glm52_bwrap_task_runner.py` behavior behind it.

## Context

Suite adapters must not build arbitrary execution-domain shell commands. The
first implementation may wrap the current bwrap task runner, but the target
shape belongs under `ginkgo/eval/` and must remain compatible with Ginkgo's
Insula ownership of bwrap construction.

## Requirements

- Add `TaskRunnerRequest` and `TaskRunnerResult` types under `ginkgo/eval/`.
- Include request fields:
  - `run_id`
  - `suite_id`
  - `task_id`
  - `trial_index`
  - `input_dir`
  - `work_dir`
  - `output_dir`
  - `tmp_dir`
  - `timeout_seconds`
  - `network`
  - `gpu`
  - `resource_limits`
  - `command`
  - `environment_allowlist`
  - `artifact_globs`
- Include result fields:
  - `status`
  - `exit_code`
  - `start_time`
  - `end_time`
  - `duration_seconds`
  - `stdout_path`
  - `stderr_path`
  - `output_artifacts`
  - `cleanup_ledger_entries`
  - `failure_category`
- Add a `bwrap_rootfs` adapter that can execute existing generated-code smoke
  tasks through the current task-runner behavior.
- Write stdout and stderr as path artifacts, not only inline strings.
- Discover declared output artifacts from `artifact_globs`.
- Deny repository checkout writes for model-controlled task execution.
- Deny network and GPU access unless the request explicitly enables them.
- Do not create a second independent bwrap argv builder; use the existing
  runner behavior as a compatibility source and keep the path open to Insula.

## Files

- Create: `ginkgo/eval/runners.py`
- Modify only if needed: `scripts/glm52_bwrap_task_runner.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`
- Test: `python/tests/test_glm52_bwrap_task_runner.py`

## Exclusions

- Do not implement `harbor_local_docker` in this ticket.
- Do not migrate all verifier suite code to the runner contract here.
- Do not add cluster runner adapters.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_bwrap_task_runner.py -q
```

## Done When

- A unit test can run a small task through the `TaskRunner` contract and produce
  path-based stdout, stderr, and output artifacts.
- Network/GPU/repository-write policy is explicit in request validation.
- Existing bwrap task-runner tests still pass.
