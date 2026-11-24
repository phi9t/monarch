# Static Eval Adapter Migration

Type: task
Status: ready-for-agent
Blocked by: 08 09 11

## Objective

Move the first static benchmark family behind a `static_eval` adapter while
preserving the existing verifier behavior and artifacts.

## Context

The current `scripts/glm52_benchmark_verifier.py` contains static suite writers:
`write_needle_smoke_responses_run`, `write_gsm8k_responses_run`,
`write_aime_responses_run`, and `write_ruler_responses_run`. These become the
first `static_eval` adapter implementation instead of more suite-specific logic
living in the CLI file.

## Requirements

- Create `ginkgo/eval/adapters/` and the `static_eval` adapter module.
- Provide adapter operations:
  - `prepare_suite(manifest, run_context)`
  - `run_trial(prepared_suite, task_id, trial_index, endpoints)`
  - `grade_trial(trial_artifact, scorer_config)`
  - `summarize_suite(score_artifacts)`
- Preserve current behavior for:
  - `needle-smoke`
  - `gsm8k`
  - `aime`
  - `ruler`
- Route GLM-5.2 calls through the resolved Responses endpoint.
- Preserve current deterministic metrics and failure categories while emitting
  the normalized campaign artifacts from ticket 11.
- Keep `scripts/glm52_benchmark_verifier.py` as a CLI facade and compatibility
  dispatcher.

## Files

- Create: `ginkgo/eval/adapters/__init__.py`
- Create: `ginkgo/eval/adapters/static_eval.py`
- Modify: `ginkgo/eval/orchestrator.py`
- Modify: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`

## Exclusions

- Do not migrate HumanEval or MBPP here.
- Do not add hosted judge endpoints.
- Do not change prompt templates, decoding profiles, or scoring semantics.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

## Done When

- Static suites can run through the adapter interface.
- Existing verifier tests still pass.
- Normalized campaign artifacts exist for static suite samples.
