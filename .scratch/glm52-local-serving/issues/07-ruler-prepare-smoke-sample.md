# Materialize RULER Smoke Sample During Prepare

Type: task
Status: resolved
Blocked by: none
Parent: 06e-ruler-real-adapter.md

## Problem

The live RULER smoke path requires a verifier-readable cached JSONL sample, but
`prepare --suite ruler` only materializes the pinned RULER source checkout. A
fresh prepared cache can therefore fail at smoke time with:

```text
RULER responses run requires a materialized dataset cache sample
```

## Requirements

- Make `prepare --suite ruler` leave a deterministic smoke sample at
  `benchmarks/datasets/ruler/samples.jsonl` when the pinned RULER checkout does
  not already contain a readable sample.
- Keep the sample clearly labeled as a Monarch smoke fixture, not official RULER
  conformance data.
- Accept RULER's native generated sample shape: `input` plus `outputs`.
- Record the smoke sample path in `prepare.json` cache preflight metadata.
- Preserve the existing fail-loud behavior when a RULER cache is neither a
  readable sample nor a recognizable RULER source checkout.

## Verification

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k 'prepare_command_materializes_ruler_smoke_sample'
```

Then run:

```sh
scripts/run python scripts/glm52_benchmark_verifier.py prepare --suite ruler --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --skip-endpoints --run-id <run-id>
scripts/run python scripts/glm52_benchmark_verifier.py smoke --suite ruler --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --execution-backend bwrap_rootfs --responses-base-url http://127.0.0.1:18081/v1 --responses-timeout-seconds 180 --run-id <run-id>
```

## Comments

## Answer

Implemented prepare-time RULER smoke sample materialization. When
`prepare --suite ruler` materializes a recognizable RULER source checkout that
does not already contain a verifier-readable JSONL sample, it writes
`benchmarks/datasets/ruler/samples.jsonl` with a deterministic Monarch smoke
fixture. The RULER adapter now also accepts RULER's native `outputs` answer
shape.

Evidence:

- Red test failed because `samples.jsonl` was missing.
- Green focused test:
  `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k 'prepare_command_materializes_ruler_smoke_sample'`
  -> 1 passed.
- Live prepare:
  `benchmark-prepare-ruler-smoke-sample-20260821T160421Z`.
- Live RULER smoke:
  `benchmark-live-ruler-after-prepare-20260821T160506Z` -> pass, 1/1,
  Responses endpoint `http://127.0.0.1:18081/v1`, sample latency ~6.63s.
