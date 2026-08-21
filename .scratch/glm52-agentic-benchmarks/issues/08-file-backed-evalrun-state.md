# File-Backed EvalRun State

Type: task
Status: ready-for-agent
Blocked by: 07

## Objective

Add file-backed EvalRun state and resume validation around the existing GLM52
benchmark verifier without changing suite scoring behavior.

## Context

The current verifier already writes `run.json`, `environment.json`,
`benchmark-manifest.json`, `summary.json`, and per-suite artifacts. The new
platform needs a campaign-level state model that records artifact-bearing
transitions and resumes completed work only when the manifest input hash still
matches.

## Requirements

- Add an EvalRun state module under `ginkgo/eval/`.
- Define state records for:
  - campaign materialization;
  - suite preparation;
  - trial generation;
  - grading;
  - suite summary;
  - campaign summary.
- Write state before starting an artifact-bearing transition and update it
  after completion.
- Preserve the existing `manifest_sha256` compatibility rule for current
  verifier outputs.
- Reject resume when the stored manifest hash differs from the current
  materialized manifest hash.
- Treat missing or malformed state as `invalid_artifact`, not as a clean rerun.
- Keep `scripts/glm52_benchmark_verifier.py` as the CLI facade.

## Files

- Create: `ginkgo/eval/orchestrator.py`
- Modify: `ginkgo/eval/manifest.py`
- Modify only if needed: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`

## Exclusions

- Do not move static/code/Harbor adapters in this ticket.
- Do not add endpoint live probes here.
- Do not add cluster or object-storage state.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

## Done When

- EvalRun state is written and updated in deterministic JSON.
- Resume succeeds only for matching manifest hashes.
- Resume fails loudly for mismatched, missing, or malformed state.
- Existing benchmark verifier tests still pass.
