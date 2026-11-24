# Prove GLM-5.3-Flash Dynamo Path Execution

Type: task
Status: ready-for-agent
Blocked by: 03, 04, 09
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add an explicit GLM-5.3-Flash execution path for
  `Responses adapter -> Dynamo frontend -> SGLang backend`.
- Preserve a direct SGLang control path for every Dynamo-backed run so protocol
  lossiness can be measured against the same model, checkpoint, profile, prompt
  set, and decoding settings.
- Record every field that crosses the Responses boundary: visible `content`,
  `reasoning_content`, tool-call fields, finish reason, usage, model id,
  request id, HTTP status, latency, and any backend error payload.
- Add a Dynamo lossiness artifact that compares direct SGLang responses with
  Dynamo responses for the same request corpus. The artifact must classify
  missing reasoning, missing final content, dropped tool-call data, changed
  finish reason, changed usage accounting, HTTP-level errors, and timeout
  behavior separately.
- Run the same bounded three-sample GSM8K-style pilot through the Dynamo path
  after the direct SGLang path is green.
- Add stable failure classes for `dynamo_launch_failed`,
  `dynamo_health_failed`, `dynamo_response_schema_mismatch`,
  `dynamo_reasoning_lossy`, `dynamo_tool_call_lossy`,
  `dynamo_usage_lossy`, and `dynamo_pilot_failed`.

## Exclusions

- Do not mark Dynamo support green from direct SGLang evidence alone.
- Do not hide direct-versus-Dynamo differences behind a single pass/fail field.
- Do not require exact token text equality between direct SGLang and Dynamo.
  Compare protocol fields, final-answer verdicts, and stable response metadata.
- Do not broaden this ticket into performance tuning. The Dynamo path only
  needs a bounded functional pilot and lossiness report.

## Acceptance Criteria

- A verifier run can launch or attach to a GLM-5.3-Flash SGLang endpoint and a
  Dynamo frontend, then record both endpoint URLs and selected backend profile
  names in the summary artifact.
- The direct control request and Dynamo request use the same prompt, model id,
  temperature, max token budget, reasoning parser expectation, and timeout
  budget.
- The lossiness artifact contains one row per request with direct fields,
  Dynamo fields, per-field verdicts, elapsed seconds, and final classification.
- The three-sample GSM8K-style pilot returns HTTP 200 from the Dynamo path for
  every sample and records final integer verdicts in a machine-readable summary.
- A synthetic test proves that dropped `reasoning_content` is classified as
  `dynamo_reasoning_lossy` even when visible final `content` remains correct.
- A synthetic test proves that a Dynamo HTTP 200 response with an incompatible
  schema exits nonzero as `dynamo_response_schema_mismatch`.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_dynamo_runtime.py -q
scripts/run python -m pytest python/tests/test_glm53_flash_serving_verifier.py -q
scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q
```

Use fake-server tests for schema and lossiness classification before live
execution. Live acceptance must include the Dynamo-backed GSM8K-style pilot
artifact and the matching direct SGLang control artifact from the same run.
