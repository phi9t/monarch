# Diagnose AIME Local Serving Timeout

Type: task
Status: ready-for-agent
Blocked by: live GLM-5.2 SGLang endpoint
Parent: 06d-aime-real-adapter.md

## Problem

AIME live Responses smoke times out on the current local GLM-5.2 SGLang setup.
The failure persists across the canonical reasoning profile and a bounded short
profile with thinking disabled:

- `benchmark-live-aime-20260821T091428Z`: verifier timeout at 180s.
- `benchmark-live-aime-timeout360-20260821T093411Z`: adapter upstream timeout at
  300s.
- `benchmark-live-aime-promptfix-timeout600-20260821T094312Z`: adapter timeout at
  600s.
- `benchmark-live-aime-short-20260821T095413Z`: short profile timeout at 180s.

## Requirements

- Determine whether the timeout is caused by SGLang scheduling, context/KV
  pressure, GLM thinking behavior, adapter request shape, or benchmark prompt
  difficulty.
- Keep all test traffic through the Responses adapter unless isolating a lower
  level SGLang serving bug.
- Do not keep increasing timeouts as the primary mitigation.
- Preserve failure taxonomy: these timeouts remain infrastructure failures until
  the model returns a scorable answer.

## Acceptance Criteria

- Produce a bounded profile that returns a scorable AIME response within a
  declared timeout, or record a clear local-serving blocker with logs and
  resource evidence.
- Keep sample artifacts honest: no published AIME comparability claim from smoke
  or ad hoc profiles.

## Verification

Run the bounded AIME smoke and inspect `summary.json` plus `aime/samples.jsonl`.

## Comments

### 2026-08-22 bounded rerun

Current local Responses run still times out:

- Run: `benchmark-e2e-aime-bounded-20260822T024434Z`
- Summary:
  `glm52-benchmark-results/benchmark-e2e-aime-bounded-20260822T024434Z/summary.json`
- Status: `environment_failed`
- Evidence:
  `aime/failures.jsonl` records `error: "timed out"`,
  `latency_seconds: 240.03285859432071`, empty `raw_response`, empty
  `response`, and `failure_category: "infrastructure"`.

The retry confirms the blocker is still live GLM-5.2 serving latency or request
shape for the AIME sample, not scoring. Do not count this as a model failure or
published AIME evidence.

### 2026-08-22 status after streaming hardening

The Harbor/Responses streaming fixes do not close this AIME blocker. The latest
AIME evidence remains `benchmark-e2e-aime-bounded-20260822T024434Z`:

- Summary status: `environment_failed`.
- Infrastructure failures: `1`.
- Model failures: `0`.
- Endpoint: `http://127.0.0.1:18081/v1`.
- Responses timeout: `240.0` seconds.
- Failure evidence: `aime/failures.jsonl` records `error: "timed out"`,
  `latency_seconds: 240.03285859432071`, empty `raw_response`, and empty
  `response`.

The next diagnostic should isolate whether the AIME request shape triggers a
serving-side long-generation stall, scheduler/KV pressure, or GLM thinking
behavior. Keep the run classified as infrastructure until the endpoint returns a
scorable response.
