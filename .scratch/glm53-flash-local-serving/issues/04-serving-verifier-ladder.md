# Add GLM-5.3-Flash Serving Verifier Ladder

Type: task
Status: ready-for-agent
Blocked by: 02, 03
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add a GLM-5.3-Flash serving verifier that proves backend Chat and Responses
  compatibility for one materialized run.
- Require `/v1/models` identity checks at backend and Responses surfaces.
- Require Chat health, reasoning separation, Chat tool loop, Responses
  non-streaming, Responses streaming, Responses tool loop, and
  `previous_response_id` continuation.
- Add a profile-gated Dynamo lossiness check that compares direct SGLang and
  Dynamo-forwarded transcripts for reasoning, content, tool calls, and streaming
  deltas before declaring the Dynamo topology Codex-ready.
- Add a profile-gated long-running inference pilot for the SGLang+Dynamo path.
  The first concrete pilot is bounded GSM8K-style static eval through
  Responses -> Dynamo -> SGLang after the Dynamo lossiness gate passes.
- Require the long-running pilot to checkpoint progress, resume only when the
  manifest still matches the materialized config and benchmark conditions, and
  record per-sample latency, usage, timeout, finish reason, partial outputs, and
  model-vs-infrastructure failure classification.
- Emit the Contract Artifacts named in the spec:
  `environment.json`, `sglang-models.json`, `sglang-health.json`,
  `sglang-reasoning.json`, `sglang-tool-loop.json`,
  `responses-models.json`, `responses-nonstream.json`,
  `responses-stream.json`, `responses-tool-loop.json`, `teardown.json`,
  `summary.json`, and `archive-manifest.json`. The multimodal and Dynamo
  profiles additionally emit `sglang-multimodal.json`, `dynamo-models.json`,
  `dynamo-chat.json`, `dynamo-lossiness.json`, and
  `dynamo-long-reasoning-pilot.json`.
- Hash every Contract Artifact in `archive-manifest.json`.
- Classify failures with the stable failure classes in the spec.

## Exclusions

- Do not run broad benchmark suites from the serving verifier; only the
  profile-declared bounded long-running pilot belongs in this ticket.
- Do not run a full GSM8K suite or claim benchmark-score conformance from the
  long-running pilot.
- Do not treat direct Chat-only evidence as Codex compatibility.
- Do not pass when teardown leaves allocated ports open or orphaned processes.

## Acceptance Criteria

- Unit tests cover successful fake-backend/fake-adapter runs and each required
  failure class.
- Tests cover lossiness detection for dropped `reasoning_content`, changed tool
  arguments, and reordered stream chunks in the Dynamo profile.
- Tests cover long-running pilot rejection for stale resume manifests, missing
  progress checkpoints, missing usage/latency fields, and per-sample timeout
  failures.
- A verifier run exits zero only when all stages required by the selected
  profile pass.
- Partial artifacts remain useful for diagnosis but do not mark the run as
  complete.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_serving_verifier.py -q
scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q
```

Add GLM-5.3-Flash verifier tests before implementation. Keep the GLM-5.2 command
as regression coverage if existing verifier code is shared. Live SGLang/Dynamo
evidence remains a separate final acceptance artifact.
