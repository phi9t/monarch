# Add RULER Real Benchmark Adapter

Type: task
Status: ready-for-human
Blocked by: live GLM-5.2 Responses endpoint
Parent: 06-real-benchmark-adapters.md

## Requirements

- Replace the RULER fixture path with a real RULER adapter.
- Materialize RULER inputs from the checked-in benchmark manifest source pins.
- Drive long-context requests only through the Responses adapter.
- Emit run-scoped Contract Artifacts for samples, metrics, failures,
  environment, benchmark manifest, run state, and archive hashes.
- Preserve per-sample profile, dataset revision, harness revision, prompt
  template hash, decoding profile, execution backend, endpoint, latency, and
  usage.
- Separate model failures from infrastructure failures.

## Exclusions

- Do not treat `endpoint=fixture` as RULER model-inference evidence.
- Do not claim published conformance from smoke or calibration output.
- Do not bypass the Responses adapter by calling SGLang Chat directly.

## Acceptance Criteria

- Focused tests fail before the RULER adapter exists and pass after it is
  implemented.
- RULER smoke writes complete Contract Artifacts and does not record
  `endpoint=fixture`.
- RULER calibration records model/infrastructure failure counts separately.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite ruler \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id ruler-real-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

```sh
scripts/run_glm52_benchmark_verifier.sh calibration \
  --suite ruler \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id ruler-real-calibration-$(date -u +%Y%m%dT%H%M%SZ)
```

## Implementation Notes

- Added the exact single-suite `ruler` smoke and calibration path through the
  Responses adapter.
- Kept mixed-suite `ruler` smoke/calibration on the existing fixture/static
  path.
- Added local RULER JSONL cache loading for prompt/context/question/input and
  expected_answer/answer/target fields.
- Missing RULER cache samples now fail loudly for exact single-suite RULER
  Responses runs.
- Samples record the provided Responses base URL as `endpoint`, preserve
  per-sample condition fields, and keep `conformance.claim` as `none`.

## Verification Evidence

Red:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k 'ruler_single_suite_real_adapter or ruler_mixed_smoke_stays_on_fixture_path'
```

Result: 5 failed, 1 passed. The failures showed exact `ruler` still using the
fixture path: no `/v1/responses` requests, endpoint failures returned pass, bad
model output returned pass, and missing cache did not raise.

Green:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k 'ruler_single_suite_real_adapter or ruler_mixed_smoke_stays_on_fixture_path'
```

Result: 6 passed, 139 deselected.

Full verifier file:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q
```

Result: 145 passed.

Compile:

```sh
scripts/run python -m py_compile scripts/glm52_benchmark_verifier.py python/tests/test_glm52_benchmark_verifier.py
```

Result: exit 0.
