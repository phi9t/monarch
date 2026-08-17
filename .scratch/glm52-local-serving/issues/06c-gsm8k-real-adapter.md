# Add GSM8K Real Benchmark Adapter

Type: task
Status: resolved
Blocked by: live GLM-5.2 Responses endpoint
Parent: 06-real-benchmark-adapters.md

## Requirements

- Replace the GSM8K static fixture path with a real GSM8K adapter.
- Materialize GSM8K inputs from the checked-in benchmark manifest source pins.
- Drive reasoning requests only through the Responses adapter.
- Extract and score final math answers from model output without using static
  fixture answers as evidence.
- Emit run-scoped Contract Artifacts for samples, metrics, failures,
  environment, benchmark manifest, run state, and archive hashes.
- Preserve per-sample profile, dataset revision, harness revision, prompt
  template hash, decoding profile, execution backend, endpoint, latency, and
  usage.
- Separate model failures from infrastructure failures.

## Exclusions

- Do not treat `endpoint=fixture` or static answers as GSM8K model-inference
  evidence.
- Do not claim published conformance from smoke or calibration output.
- Do not bypass the Responses adapter by calling SGLang Chat directly.

## Acceptance Criteria

- Focused tests fail before the GSM8K adapter exists and pass after it is
  implemented.
- GSM8K smoke writes complete Contract Artifacts and does not record
  `endpoint=fixture`.
- GSM8K calibration records model/infrastructure failure counts separately.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite gsm8k \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id gsm8k-real-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

```sh
scripts/run_glm52_benchmark_verifier.sh calibration \
  --suite gsm8k \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id gsm8k-real-calibration-$(date -u +%Y%m%dT%H%M%SZ)
```

## Answer

Implemented the bounded local slice for exact single-suite GSM8K smoke and
calibration runs. The verifier now loads one materialized GSM8K JSONL sample,
posts its question through the configured Responses endpoint, extracts the final
answer from model output with the existing GSM8K final-answer parser, and writes
run-scoped samples, metrics, failures, environment, manifest, run state, and
archive hash artifacts. Mixed-suite GSM8K runs remain on the existing
fixture/static path.

Red evidence:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k 'gsm8k_single_suite_real_adapter_uses_responses_endpoint or gsm8k_calibration_real_adapter_classifies_responses_failure or gsm8k_mixed_calibration_preserves_fixture_path'
```

Result: `3 failed, 1 passed`. The exact GSM8K smoke/calibration tests failed
because no `/v1/responses` requests were made, and the bad-endpoint
calibration test returned success through fixture evidence.

Additional red evidence:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py::test_gsm8k_calibration_real_adapter_classifies_bad_model_answer -q
```

Result: `1 failed`. Malformed model output was incorrectly classified as
`environment_failed` instead of a model failure.

Green evidence:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k 'gsm8k_single_suite_real_adapter_uses_responses_endpoint or gsm8k_calibration_real_adapter_classifies_responses_failure or gsm8k_calibration_real_adapter_classifies_bad_model_answer or gsm8k_mixed_calibration_preserves_fixture_path'
```

Result: `5 passed, 127 deselected`.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q
```

Result: `132 passed`.

```sh
scripts/run python -m py_compile scripts/glm52_benchmark_verifier.py python/tests/test_glm52_benchmark_verifier.py
```

Result: passed with no output.

No published conformance claim is made by this smoke/calibration path. Live
GLM-5.2 endpoint validation remains blocked by the live Responses endpoint and
is outside this local fake-Responses-backed slice.
