# Parent Manifest Audit

Type: task
Status: ready-for-agent
Blocked by: 02

## Goal

Audit a successful live parent run and classify its artifacts as
benchmark-ready completion evidence.

## Requirements

- Start only after ticket 02 records a zero-exit three-cycle parent run.
- Use the exact `parent-manifest.json` from the successful parent run.
- Run the audit CLI through `scripts/run`.
- Verify the manifest identifies the same GLM-backed Responses base URL that
  appears in the successful Responses adapter process/probe artifacts.
- Verify completion evidence exists for SGLang, Dynamo, and Responses from the
  same parent run.
- Verify teardown evidence exists for all three cycles.
- Verify benchmark readiness is not inferred from blocker, readiness-only, fake,
  fixture, or stale artifacts.
- Append audit output and artifact classification to this ticket.

## Command

```sh
scripts/run python scripts/glm52_inference_runtime.py audit-parent-manifest --manifest glm52-serving-results/<run-id>/parent-manifest.json
```

## Exclusions

- Do not run benchmarks from this ticket.
- Do not repair or edit a manifest by hand.
- Do not accept a manifest from a different run id than the live parent run.

## Verification Evidence

- Audit command exits zero and prints benchmark-ready classification.
- The audited manifest path is recorded.
- The completed Responses base URL is recorded.
- Artifact classifications are recorded as blocker, readiness, completion, or
  benchmark-ready.

## Comments
