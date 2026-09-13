# Add AIME Real Benchmark Adapter

Type: task
Status: ready-for-human
Blocked by: live GLM-5.2 Responses endpoint
Parent: 06-real-benchmark-adapters.md

## Current Status

Local fake-Responses adapter routing and static-answer scoring over model output
are implemented and tested for exact single-suite smoke and calibration. The
remaining work needs a live GLM-5.2 Responses endpoint and any official AIME
scoring/reporting environment required for non-smoke evidence, so this ticket
is not currently ready for another local agent slice. Do not mark it resolved
until live GLM output exists, and do not use fake-Responses smoke/calibration
results as published conformance.

## Requirements

- Replace the AIME static fixture path with a real AIME adapter.
- Materialize AIME inputs from the checked-in benchmark manifest source pins.
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

- Do not treat `endpoint=fixture` or static answers as AIME model-inference
  evidence.
- Do not claim published conformance from smoke or calibration output.
- Do not bypass the Responses adapter by calling SGLang Chat directly.

## Acceptance Criteria

- Focused tests fail before the AIME adapter exists and pass after it is
  implemented.
- AIME smoke writes complete Contract Artifacts and does not record
  `endpoint=fixture`.
- AIME calibration records model/infrastructure failure counts separately.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite aime \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id aime-real-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

```sh
scripts/run_glm52_benchmark_verifier.sh calibration \
  --suite aime \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id aime-real-calibration-$(date -u +%Y%m%dT%H%M%SZ)
```

## 2026-08-16 Bounded TDD Slice

- Added exact single-suite AIME smoke/calibration routing through the Responses
  adapter path. Mixed-suite AIME runs still use the fixture/static path.
- Added local AIME cache loading for JSONL samples with `problem`, `question`,
  or `prompt` text plus `answer`.
- AIME Responses samples now score only the model output with
  `extract_static_final_answer("aime", raw_response)`, record the provided
  Responses base URL as `endpoint`, and preserve run-scoped Contract Artifacts.
- Missing AIME cache samples raise `BenchmarkVerifierError` instead of falling
  back to fixture evidence for exact single-suite AIME runs.

Evidence:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k 'aime_single_suite_real_adapter or aime_calibration_real_adapter or aime_mixed_calibration_preserves_fixture_path'
```

Red before implementation: 5 failed, 1 passed.

Green after implementation: 6 passed.

### 2026-08-16 evidence closeout

- The completed local slice covers exact single-suite `smoke --suite aime` and
  `calibration --suite aime` only.
- Test evidence uses a fake in-test `/v1/responses` server. This proves the
  adapter path, metadata, and failure taxonomy; it is not live GLM-5.2
  validation.
- The adapter scores only model output with
  `extract_static_final_answer("aime", raw_response)` and records the provided
  Responses base URL as `endpoint`.
- Bad endpoint behavior is classified as infrastructure failure. Malformed or
  wrong model output is classified as model failure.
- Full local verification for the slice reported `139 passed` for
  `python/tests/test_glm52_benchmark_verifier.py`; `py_compile` for
  `scripts/glm52_benchmark_verifier.py` and the benchmark verifier test file
  passed; scoped `git diff --check` passed; and the scoped trailing-whitespace
  search found no matches.
- Remaining blockers are live GLM validation for AIME, official/non-smoke
  scoring evidence over a live endpoint, and any published-conformance source
  metadata. Fake-Responses smoke/calibration output is not published
  conformance.
