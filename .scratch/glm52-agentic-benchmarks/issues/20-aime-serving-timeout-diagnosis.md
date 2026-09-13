# AIME Serving Timeout Diagnosis

Type: task
Status: ready-for-agent
Blocked by:

## Objective

Diagnose the bounded AIME local-serving timeout and either produce a scorable
bounded AIME smoke profile or record a precise local-serving blocker.

## Context

The latest bounded AIME run is
`benchmark-e2e-aime-bounded-20260822T024434Z`. It ended as
`environment_failed` with one infrastructure failure, zero model failures, a
240 second Responses timeout, empty raw response, and empty parsed response.

The AIME path remains infrastructure until the endpoint returns a scorable
answer. Do not count this as model-quality evidence.

## Requirements

- Reproduce the bounded AIME timeout through the Responses adapter.
- Preserve the exact prompt, request payload, timeout, response headers if any,
  adapter logs, server logs, and GPU memory evidence.
- Isolate the same prompt through lower layers only as a diagnostic:
  - Responses adapter;
  - Chat Completions endpoint;
  - native SGLang `/generate`.
- Compare thinking mode, max output tokens, stop conditions, temperature,
  prompt size, generated token count, and scheduler/KV pressure.
- Decide whether the fix belongs in the prompt/profile, Responses adapter
  request shape, SGLang runtime config, or the documented local capacity
  boundary.
- Add a regression test for any code-level request-shape or timeout fix.
- Do not keep increasing timeouts as the primary mitigation.

## Files

- Modify if needed: `scripts/glm52_benchmark_verifier.py`
- Modify if needed: `scripts/glm52_responses_adapter.py`
- Modify if needed: `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`
- Test: `python/tests/test_glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_responses_adapter.py`
- Update: `.scratch/glm52-local-serving/issues/08-aime-local-serving-timeout.md`

## Exclusions

- Do not claim published AIME comparability from smoke or bounded diagnostic
  profiles.
- Do not bypass the Responses adapter except for documented lower-layer
  isolation.
- Do not treat timeout-only runs as model failures.
- Do not launch a multi-sample AIME run until one bounded sample returns a
  scorable response.

## Verification

Run focused tests after code changes:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
```

Then rerun one bounded AIME smoke against the live Responses adapter:

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite aime \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --responses-base-url http://127.0.0.1:18081/v1 \
  --run-id benchmark-e2e-aime-diagnosis-<timestamp>
```

## Done When

- A bounded AIME smoke returns a scorable answer within its declared timeout, or
  the tracker records a precise serving-capacity or request-shape blocker with
  enough evidence to reproduce it.
- The run summary and failure artifacts preserve the distinction between
  infrastructure and model failures.
- Any code-level fix is covered by focused tests.
