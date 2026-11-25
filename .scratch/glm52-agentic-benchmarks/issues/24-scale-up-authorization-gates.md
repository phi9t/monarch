# Scale-Up Authorization Gates

Type: task
Status: ready-for-agent
Blocked by: 23

## Objective

Define the authorization, resource, and artifact gates for running benchmark
loads beyond the representative local pilot.

## Context

Full Terminal-Bench, SWE-bench, stateful-tool, browser, desktop, hosted-judge,
and GPU-heavy research runs can consume substantial local GPU time, host
storage, cloud spend, or sandbox capacity. They must not be launched by
accident or from stale prompt context. The user must explicitly authorize the
specific large run.

## Requirements

- Define which run classes require explicit user authorization:
  - local GPU occupancy longer than one hour;
  - Terminal-Bench or SWE-bench beyond the pinned smoke subset;
  - hosted APIs, paid sandboxes, cloud workers, or external judges;
  - untrusted code or browser/open-web tasks outside the existing local sandbox
    policy;
  - reportable score runs;
  - any suite that needs secrets, credentials, or private datasets.
- Define the required launch record for an authorized run:
  - suite list;
  - task count and trial count;
  - expected wall time;
  - GPU, CPU, RAM, disk, Docker, and network requirements;
  - endpoint and judge endpoints;
  - artifact root;
  - cleanup ledger path;
  - abort and cleanup commands;
  - comparability label.
- Add a prelaunch check that fails if the run is large and lacks an
  authorization token or explicit trusted user instruction.
- Keep local-only semantics: do not push, upload, or use cloud execution unless
  that is part of the explicit authorization.
- Define the final report requirements for scaled runs.

## Files

- Create or modify: `.scratch/glm52-agentic-benchmarks/runbooks/scale-up-gates.md`
- Modify if needed: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`

## Exclusions

- Do not launch a large run in this ticket.
- Do not add Kubernetes, KubeRay, Temporal, or cloud-provider implementation.
- Do not weaken local cleanup or owned-process restrictions.

## Verification

Run focused tests after code changes:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
```

Verify the prelaunch gate rejects a synthetic large run without explicit
authorization and accepts a small local smoke run.

## Done When

- The gate makes accidental large benchmark launches impossible through the
  normal CLI path.
- The runbook states exactly what the user must authorize.
- The final report requirements are clear enough to compare future runs without
  recovering context from chat.
