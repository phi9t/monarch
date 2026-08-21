# File-Backed EvalRun State

Type: task
Status: resolved
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

## Resolution

- Added `ginkgo.eval.orchestrator`, a deterministic file-backed
  `evalrun-state.json` state module for campaign materialization, suite
  preparation, trial generation, grading, suite summary, and campaign summary.
- Wired active verifier artifact writers through the EvalRun state module,
  including fixture, prepare, conformance, Responses smoke/calibration, bwrap
  codegen smoke, and Harbor smoke/failure paths.
- Preserved the existing `run.json` `manifest_sha256` compatibility rule and
  tightened EvalRun resume validation to reject run id, mode, or suite-set
  mismatches before overwriting state.
- Kept `scripts/glm52_benchmark_verifier.py` as the CLI facade and left suite
  scoring behavior unchanged.

## Evidence

Red:

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
```

Failed at collection with:

```text
ModuleNotFoundError: No module named 'ginkgo.eval.orchestrator'
```

Verifier integration red:

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

Failed because `evalrun-state.json` was not emitted and corrupt state did not
block resume.

Green:

```sh
scripts/run python -m pyright ginkgo/eval/orchestrator.py ginkgo/eval/manifest.py python/tests/test_glm52_agentic_benchmark_platform.py
scripts/run python -m py_compile ginkgo/eval/orchestrator.py ginkgo/eval/manifest.py python/tests/test_glm52_agentic_benchmark_platform.py python/tests/test_glm52_benchmark_verifier.py scripts/glm52_benchmark_verifier.py
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py python/tests/test_glm52_benchmark_verifier.py -q
git diff --check
```

Result: pyright reported `0 errors`; pytest reported `186 passed`; diff check
passed.
