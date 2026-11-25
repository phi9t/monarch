# Campaign Manifest Schema

Type: task
Status: resolved
Blocked by:

## Objective

Add a tested campaign manifest schema for the GLM52 agentic benchmark platform
while preserving compatibility with the existing benchmark manifest.

## Context

The resolved spec extends the current
`.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml` with campaign
metadata, endpoint registry records, evidence classes, adapter names, and
scoring metadata. Current verifier behavior must keep working; additive
campaign fields must either be accepted by the current manifest validator or
kept in a separate wrapper that references the unchanged benchmark manifest.

## Requirements

- Create the first `ginkgo/eval/` package files for manifest handling.
- Define typed structures or equivalent validation helpers for:
  - campaign ID, execution mode, and artifact root;
  - endpoint records;
  - suite records with existing fields plus additive campaign metadata;
  - defaults for pilot and full runs.
- Validate required existing suite fields without rejecting additive campaign
  fields.
- Reject unsupported `execution_mode` values.
- Reject unsupported endpoint roles and protocols.
- Preserve `execution_backend` as the runner selector.
- Keep v1 local only; no Kubernetes, KubeRay, Temporal, or cloud execution
  fields may imply implementation authority.

## Files

- Create: `ginkgo/eval/__init__.py`
- Create: `ginkgo/eval/manifest.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`
- Modify only if needed: `scripts/glm52_benchmark_verifier.py`

## Exclusions

- Do not move suite execution into `ginkgo/eval/` in this ticket.
- Do not add live endpoint readiness checks here.
- Do not generate campaign summaries here.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

## Done When

- A valid campaign manifest with additive metadata loads successfully.
- An invalid endpoint role, protocol, or execution mode fails loudly.
- Existing benchmark manifest validation behavior is preserved.

## Verification Evidence

- Red test:
  `scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q`
  failed during collection with
  `ModuleNotFoundError: No module named 'ginkgo.eval'`, proving the new package
  and manifest API did not exist yet.
- Green focused test:
  `scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q`
  passed (`6 passed`).
- Compatibility test:
  `scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q`
  passed (`163 passed`).
- Static compile:
  `scripts/run python -m py_compile ginkgo/eval/__init__.py ginkgo/eval/manifest.py python/tests/test_glm52_agentic_benchmark_platform.py`
  passed.
