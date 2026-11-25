# Code Eval Adapter Migration

Type: task
Status: ready-for-agent
Blocked by: 10 11 12

## Objective

Move generated-code benchmark suites behind a `code_eval` adapter that uses the
TaskRunner contract for isolated execution.

## Context

The current verifier contains generated-code suite writers:
`write_humaneval_responses_run`, `write_mbpp_responses_run`, and bwrap codegen
smoke paths. The agentic platform needs raw predictions preserved before
execution and scoring, with environment failures separated from model failures.

## Requirements

- Create a `code_eval` adapter module.
- Preserve behavior for:
  - `humaneval`
  - `mbpp`
  - bwrap generated-code smoke where used as a platform check.
- Generate model predictions through the Responses endpoint before execution.
- Persist raw prediction artifacts before invoking the task runner.
- Execute generated code through `TaskRunner`, defaulting to `bwrap_rootfs`.
- Preserve existing generated-code scoring semantics.
- Separate model failures, execution/environment failures, and scorer failures
  in normalized artifacts.
- Keep repository checkout writes unavailable to model-controlled code.

## Files

- Create: `ginkgo/eval/adapters/code_eval.py`
- Modify: `ginkgo/eval/runners.py`
- Modify: `ginkgo/eval/artifacts.py`
- Modify: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_bwrap_task_runner.py`

## Exclusions

- Do not implement LiveCodeBench, BigCodeBench, or SciCode in this ticket.
- Do not change HumanEval or MBPP scoring semantics.
- Do not allow generated code to use host Docker or write to the repository.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
scripts/run python -m pytest python/tests/test_glm52_bwrap_task_runner.py -q
```

## Done When

- HumanEval and MBPP can emit raw prediction, task-runner execution, and score
  artifacts through the adapter path.
- Environment failures do not enter the model score denominator.
- Existing generated-code verifier coverage remains green.
