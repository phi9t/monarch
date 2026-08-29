# Split GLM-5.3-Flash Cold-Start and Steady-State Verification

Type: task
Status: ready-for-agent
Blocked by: 04, 08
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Extend the GLM-5.3-Flash verifier to record cold-start, first-request, and
  steady-state request phases separately.
- Record startup timings from SGLang logs: weight load, KV cache allocation,
  scheduler end-to-end time, tokenizer end-to-end time, CUDA graph capture, and
  any serving-time compilation warnings.
- Add a first-request probe that is allowed to be slow but must record
  first-token latency, end-to-end latency, finish reason, usage, and whether the
  response ended in `reasoning_content` without final `content`.
- Add a steady-state probe set after first-request compilation settles. The
  first concrete probe set is three bounded GSM8K-style arithmetic samples with
  expected final integers and per-sample latency/usage records.
- Preserve the distinction between HTTP readiness, decode readiness, and
  task-level reasoning readiness in the summary artifact.
- Add stable failure classes for `http_ready_decode_failed`,
  `first_request_compile_timeout`, `reasoning_content_budget_exhausted`,
  `steady_state_probe_failed`, and `steady_state_latency_missing`.

## Exclusions

- Do not treat `/v1/models` alone as serving readiness.
- Do not treat a first request that returns only `reasoning_content` as a failed
  server if a larger bounded request succeeds. Classify it as a budget/profile
  issue.
- Do not compare steady-state pilot accuracy to published benchmark scores.
- Do not run broad benchmark suites from this verifier ticket.

## Acceptance Criteria

- The verifier summary contains separate sections for `startup`,
  `http_readiness`, `first_request`, and `steady_state`.
- The first-request artifact records whether forced thinking consumed the whole
  output-token budget before final content.
- The steady-state artifact records at least three direct SGLang arithmetic
  probes with request id, elapsed seconds, prompt tokens, completion tokens,
  reasoning tokens, finish reason, content digest, and final-answer verdict.
- A synthetic test can force serving-time compilation logs and prove they are
  classified under first-request overhead rather than startup failure.
- A synthetic test can force a `/v1/models` success followed by decode failure
  and prove the verifier exits nonzero.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_serving_verifier.py -q
scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q
```

Add fake-server tests first. Live verification should reuse an already-running
SGLang endpoint when available and record the endpoint, profile name, and
artifact directory instead of relaunching implicitly.
