# Replace Fixture-Only Benchmark Paths with Real Adapters

Type: task
Status: tracking
Blocked by: live GLM-5.2 Responses endpoint

## Context

The current benchmark verifier can exercise local fixture and static paths for
HumanEval, MBPP, GSM8K, AIME, RULER, and needle-smoke. Those paths are useful
for artifact, scoring, failure-taxonomy, and cleanup validation, but they are
not model-inference benchmark evidence and cannot support published
conformance claims.

The completion audit keeps this as remaining work: replace fixture-only
benchmark paths with real adapters, or split that debt into follow-up tickets.
This ticket is the follow-up tracker for that debt.

## Child Tickets

- `06a-humaneval-real-adapter.md` — `ready-for-human`; local
  fake-Responses routing, fixture-harness scoring, and EvalPlus
  missing-prerequisite classification are done, but live GLM output and
  official HumanEval pass@1 remain blocked.
- `06b-mbpp-real-adapter.md` — `ready-for-human`; local fake-Responses
  routing, fixture-harness scoring, and EvalPlus missing-prerequisite
  classification are done, but live GLM output and official MBPP pass@1 remain
  blocked.
- `06c-gsm8k-real-adapter.md` — `resolved` for the bounded local adapter slice;
  live GLM validation remains blocked by the parent workstream.
- `06d-aime-real-adapter.md` — `ready-for-human`; local fake-Responses routing
  and static-answer scoring over model output are done, but live GLM output and
  non-smoke evidence remain blocked.
- `06e-ruler-real-adapter.md` — `ready-for-human`; local fake-Responses routing
  is done, but live GLM output and non-smoke evidence remain blocked.
- `06f-needle-smoke-real-adapter.md` — `ready-for-human`; local fake-Responses
  smoke and calibration routing are done, but live GLM output and non-fixture
  evidence remain blocked.

## Requirements

- Add real benchmark adapters for HumanEval, MBPP, GSM8K, AIME, RULER, and
  needle-smoke, or split each suite into a narrower child ticket before
  implementation.
- Materialize each suite's primary-source inputs from the checked-in benchmark
  manifest source pins.
- Drive the model only through the Responses adapter, preserving the local GLM
  profile declared in the benchmark manifest.
- Emit run-scoped Contract Artifacts for samples, metrics, failures,
  environment, benchmark manifest, run state, and archive hashes.
- Preserve per-sample condition metadata: profile, dataset revision, harness
  revision, prompt template hash, decoding profile, execution backend, endpoint,
  latency, and usage.
- Separate model failures from infrastructure failures with the existing
  benchmark failure taxonomy.
- Keep smoke and calibration evidence separate from published conformance.

## Exclusions

- Do not treat fixture responses or static answers as model-inference evidence.
- Do not claim published conformance until primary-source score metadata,
  tolerances, local conditions, and live model evidence all match.
- Do not replace official Docker or Harbor environments for suites whose
  benchmark contract requires them.
- Do not introduce Kubernetes, KubeRay, Kueue, or cluster-native jobs.

## Acceptance Criteria

- Each real adapter has focused tests that fail before the adapter exists and
  pass after implementation.
- A smoke run for each suite writes complete Contract Artifacts and records
  model/infrastructure failure counts.
- Calibration runs for HumanEval, MBPP, GSM8K, AIME, RULER, and needle-smoke no
  longer rely on `endpoint=fixture` or static fixture answers.
- The completion audit can replace the fixture-only limitation with concrete
  run IDs and artifact paths for the real adapters, or link to child tickets for
  any suite deliberately deferred.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

For each implemented suite:

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite <suite> \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend <declared-backend> \
  --run-id <suite>-real-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

```sh
scripts/run_glm52_benchmark_verifier.sh calibration \
  --suite <suite> \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend <declared-backend> \
  --run-id <suite>-real-calibration-$(date -u +%Y%m%dT%H%M%SZ)
```
