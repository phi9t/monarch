# Representative Pilot Runbook

Type: task
Status: ready-for-agent
Blocked by: 19 20 21 22

## Objective

Create and validate the first representative GLM52 agentic benchmark pilot
runbook after the current Terminal-Bench, AIME, SWE-bench, and host preflight
blockers are resolved or explicitly deferred with evidence.

## Context

The platform spec selects a representative v1-local pilot rather than a full
benchmark matrix. This ticket turns that decision into an operator sequence
with explicit suite inclusion, skip/defer handling, cleanup, and artifact
checks.

## Requirements

- Define the exact pilot suite list:
  - `needle-smoke`;
  - `gsm8k`;
  - `humaneval`;
  - `mbpp`;
  - `ruler` smoke or small pilot;
  - `aime` only if ticket 20 produced a scorable bounded profile;
  - `terminal-bench-2` only if ticket 19 is not deferred;
  - `swe-bench-verified` only if ticket 21 is not deferred.
- Define the command sequence from clean preflight through cleanup.
- Record required live services:
  - SGLang/Dynamo serving;
  - Responses adapter;
  - Harbor host-control path when Harbor suites are included.
- Require every included suite to emit summary, raw-generation or trajectory
  artifacts, failure denominators, and cleanup artifacts.
- Represent deferred suites as `skipped` or `unsupported` with reasons.
- Add a final artifact inspection command that checks summary status,
  denominator separation, and per-suite artifact presence.

## Files

- Create or modify: `.scratch/glm52-agentic-benchmarks/runbooks/representative-pilot.md`
- Modify if needed: `.scratch/glm52-agentic-benchmarks/campaign-manifest.yaml`
- Modify if needed: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`

## Exclusions

- Do not launch a large full-suite campaign in this ticket.
- Do not include hosted APIs, paid sandboxes, cloud workers, or external judges.
- Do not claim reportable score evidence for smoke, fixture, deferred, or
  non-comparable suites.

## Verification

Run focused tests after code changes:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
```

Then run the smallest representative pilot approved by the prerequisite
tickets and inspect the final summary artifacts.

## Done When

- The runbook is complete enough for a fresh operator to execute without chat
  context.
- The pilot produces a campaign or suite summary that separates model,
  infrastructure, scorer, skipped, unsupported, and non-comparable counts.
- Cleanup is verified and recorded.
