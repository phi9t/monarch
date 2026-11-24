# Artifact Normalization And Report Taxonomy

Type: task
Status: ready-for-agent
Blocked by: 08 09 10

## Objective

Normalize current verifier outputs into the campaign Contract Artifact tree and
add the campaign result taxonomy without breaking existing artifacts.

## Context

The current verifier writes `run.json`, `environment.json`,
`benchmark-manifest.json`, `summary.json`, and per-suite `samples.jsonl`,
`metrics.json`, and `failures.jsonl`. The campaign platform needs per-trial
artifacts and separate denominators for model score, infrastructure failures,
scorer failures, skipped tasks, unsupported tasks, and non-comparable suites.

## Requirements

- Add artifact helpers under `ginkgo/eval/`.
- Normalize or alias existing verifier artifacts into:
  - `campaign-manifest.json`
  - `endpoint-readiness.json`
  - `serving-summary.json`
  - `run-state.json`
  - `suite/<suite-id>/prepared-suite.json`
  - `suite/<suite-id>/tasks/<task-id>/trial-<n>/prediction.json`
  - `suite/<suite-id>/tasks/<task-id>/trial-<n>/trajectory.jsonl`
  - `suite/<suite-id>/tasks/<task-id>/trial-<n>/environment-final-state.json`
  - `suite/<suite-id>/tasks/<task-id>/trial-<n>/score.json`
  - `suite/<suite-id>/suite-summary.json`
  - `campaign-summary.json`
- Preserve compatibility with existing `samples.jsonl`, `metrics.json`, and
  `failures.jsonl`.
- Map current status/failure fields into canonical states:
  - `passed`
  - `task_failed`
  - `model_timeout`
  - `model_protocol_error`
  - `environment_setup_failed`
  - `environment_crashed`
  - `grader_failed`
  - `cancelled`
  - `invalid_artifact`
  - `unsupported`
  - `skipped`
- Report separate denominators for:
  - model score;
  - infrastructure failures;
  - judge or scorer failures;
  - skipped tasks;
  - unsupported tasks;
  - non-comparable suites.
- Preserve raw prediction or final environment state before grading for every
  reportable trial.
- Record scorer revision, scorer inputs, judge endpoint ID when used, and
  manifest hash in every score artifact.

## Files

- Create: `ginkgo/eval/artifacts.py`
- Modify: `ginkgo/eval/orchestrator.py`
- Modify only if needed: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`

## Exclusions

- Do not change official suite scoring semantics.
- Do not silently drop existing verifier artifacts.
- Do not count environment setup failures in the model score denominator.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

## Done When

- Compatibility artifacts remain readable.
- Campaign summary denominators are deterministic and tested.
- Regrading can be represented from immutable generation artifacts without
  rerunning generation.
