# Add Needle-Smoke Real Benchmark Adapter

Type: task
Status: ready-for-human
Blocked by: live GLM-5.2 Responses endpoint
Parent: 06-real-benchmark-adapters.md

## Current Status

Local fake-Responses adapter routing is implemented and tested for exact
single-suite smoke and calibration. The remaining work needs a live GLM-5.2
Responses endpoint and any official needle-smoke evidence needed for
non-fixture claims, so this ticket is not currently ready for another local
agent slice. Do not mark it resolved until live GLM output exists, and do not
use fake-Responses smoke/calibration results as published conformance.

## Requirements

- Replace the needle-smoke fixture path with a real needle-smoke adapter.
- Materialize needle-smoke inputs from the checked-in benchmark manifest source
  pins.
- Drive long-context retrieval requests only through the Responses adapter.
- Emit run-scoped Contract Artifacts for samples, metrics, failures,
  environment, benchmark manifest, run state, and archive hashes.
- Preserve per-sample profile, dataset revision, harness revision, prompt
  template hash, decoding profile, execution backend, endpoint, latency, and
  usage.
- Separate model failures from infrastructure failures.

## Exclusions

- Do not treat `endpoint=fixture` as needle-smoke model-inference evidence.
- Do not claim published conformance from smoke or calibration output.
- Do not bypass the Responses adapter by calling SGLang Chat directly.

## Acceptance Criteria

- Focused tests fail before the needle-smoke adapter exists and pass after it
  is implemented.
- Needle-smoke smoke writes complete Contract Artifacts and does not record
  `endpoint=fixture`.
- Needle-smoke calibration records model/infrastructure failure counts
  separately.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id needle-smoke-real-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

```sh
scripts/run_glm52_benchmark_verifier.sh calibration \
  --suite needle-smoke \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id needle-smoke-real-calibration-$(date -u +%Y%m%dT%H%M%SZ)
```

## 2026-08-16 bounded TDD slice

- Implemented the smoke-only adapter path for `smoke --suite needle-smoke`.
- The adapter posts the three needle-smoke prompts to the configured OpenAI
  Responses-compatible `--responses-base-url`, writes normal Contract
  Artifacts, records the provided endpoint instead of `fixture`, and separates
  model failures from infrastructure failures.
- Verification uses a fake in-test `/v1/responses` server; this slice does not
  use a live GLM endpoint and does not claim published conformance.
- Calibration adapter routing is covered by the later fake-Responses slice; live
  GLM validation remains a follow-up for this ticket.

## 2026-08-16 bounded TDD slice: calibration adapter routing

- Added calibration parser support for `--responses-base-url`, using the same
  `GLM52_RESPONSES_BASE_URL` / `http://localhost:8080/v1` default as smoke.
- Routed exactly `calibration --suite needle-smoke` through the Responses-backed
  needle-smoke writer in calibration mode.
- Preserved the existing fixture/static calibration path for mixed suites and
  non-needle suites.
- Verification uses the fake in-test `/v1/responses` server and records
  calibration Contract Artifacts without claiming published conformance.

### 2026-08-16 evidence closeout

- The completed local slice covers exact single-suite `smoke --suite
  needle-smoke` and `calibration --suite needle-smoke` routing only.
- Test evidence uses a fake in-test `/v1/responses` server. This proves the
  adapter path, endpoint metadata, run-scoped artifacts, and failure taxonomy;
  it is not live GLM-5.2 validation.
- Samples record the provided Responses base URL as `endpoint`, not `fixture`,
  and preserve the suite condition metadata needed for later comparison.
- Bad endpoint behavior is classified as infrastructure failure with
  `model_failures=0`.
- Focused calibration verification passed the two tests
  `test_needle_smoke_calibration_real_adapter_uses_responses_endpoint` and
  `test_needle_smoke_calibration_real_adapter_classifies_responses_failure`;
  the full benchmark verifier file reported `127 passed`; `py_compile` for
  `scripts/glm52_benchmark_verifier.py` and the benchmark verifier test file
  passed; scoped `git diff --check` passed; and the scoped trailing-whitespace
  search found no matches.
- Remaining blockers are live GLM validation for needle-smoke and any
  non-fixture evidence needed for published-conformance claims.
