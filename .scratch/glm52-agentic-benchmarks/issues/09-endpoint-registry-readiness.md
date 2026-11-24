# Endpoint Registry Readiness

Type: task
Status: ready-for-agent
Blocked by: 07

## Objective

Implement endpoint registry materialization and readiness artifacts for
machine-local GLM52 benchmark campaigns.

## Context

Benchmark traffic for GLM-5.2 must go through the Responses adapter. Endpoint
URLs come from materialized serving config or component refs, not invented
localhost defaults. The local model-under-test endpoint source is
`component://responses_adapter/openai_base_url`, resolved by the campaign
materializer from the parent inference materialized config.

## Requirements

- Add endpoint record validation for roles:
  - `model_under_test`
  - `judge`
  - `reader`
  - `controller`
  - `embedding`
  - `tool_service`
- Resolve `component://responses_adapter/openai_base_url` from a supplied
  parent inference materialized config.
- Reject unresolved `component://` refs with a clear error.
- Validate `results://<repeat-id>/loop-summary.json` and
  `results://<run-id>/summary.json` readiness artifact refs without inserting
  fictional path segments.
- Record endpoint readiness to `endpoint-readiness.json`.
- For OpenAI-compatible generation endpoints, record model discovery and a
  minimal live generation probe.
- For embedding endpoints, record a minimal embedding probe.
- Classify judge/helper endpoint failures separately from model-under-test
  failures.

## Files

- Create: `ginkgo/eval/refs.py`
- Modify: `ginkgo/eval/manifest.py`
- Modify: `ginkgo/eval/orchestrator.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`

## Exclusions

- Do not bypass the Responses adapter for reportable benchmark traffic.
- Do not invent fallback localhost ports.
- Do not add SGLang/Dynamo lower-level serving verification here.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q
```

## Done When

- Endpoint refs resolve only from declared materialized config or declared
  artifacts.
- `endpoint-readiness.json` is deterministic and includes role-specific probe
  results.
- Stale bad refs such as `results://serving/...`,
  `component://responses_adapter/base_url`, and fixed default ports are rejected
  or absent from generated artifacts.
