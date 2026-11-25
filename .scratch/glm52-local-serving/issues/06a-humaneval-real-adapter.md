# Add HumanEval Real Benchmark Adapter

Type: task
Status: ready-for-human
Blocked by: live GLM-5.2 Responses endpoint
Parent: 06-real-benchmark-adapters.md

## Current Status

Local fake-Responses adapter routing, fixture-harness scoring, and official
EvalPlus missing-prerequisite artifacts are implemented and tested. The
remaining work needs either a live GLM-5.2 Responses endpoint or an official
EvalPlus-capable environment, so this ticket is not currently ready for another
local agent slice. Do not mark it resolved until live GLM output and official
HumanEval pass@1 evidence exist, and do not use fixture-harness results as
published conformance.

## Requirements

- Replace the HumanEval fixture path with a real HumanEval adapter.
- Materialize HumanEval inputs from the checked-in benchmark manifest source
  pins.
- Drive completions only through the Responses adapter.
- Emit run-scoped Contract Artifacts for samples, metrics, failures,
  environment, benchmark manifest, run state, and archive hashes.
- Preserve per-sample profile, dataset revision, harness revision, prompt
  template hash, decoding profile, execution backend, endpoint, latency, and
  usage.
- Separate model failures from infrastructure failures.

## Exclusions

- Do not treat `endpoint=fixture` as HumanEval model-inference evidence.
- Do not claim published conformance from smoke or calibration output.
- Do not bypass the Responses adapter by calling SGLang Chat directly.

## Acceptance Criteria

- Focused tests fail before the HumanEval adapter exists and pass after it is
  implemented.
- HumanEval smoke writes complete Contract Artifacts and does not record
  `endpoint=fixture`.
- HumanEval calibration records model/infrastructure failure counts separately.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite humaneval \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id humaneval-real-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

```sh
scripts/run_glm52_benchmark_verifier.sh calibration \
  --suite humaneval \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id humaneval-real-calibration-$(date -u +%Y%m%dT%H%M%SZ)
```

## Comments

### 2026-08-16 bounded fake Responses adapter slice

- Added exact single-suite fake `/v1/responses` adapter coverage for
  `smoke --suite humaneval` and `calibration --suite humaneval`.
- Red evidence: `scripts/run python -m pytest
  python/tests/test_glm52_benchmark_verifier.py -q -k
  'humaneval_single_suite_real_adapter_uses_responses_endpoint or
  humaneval_real_adapter_classifies_responses_failure'` failed 4 tests because
  smoke routed to the bwrap codegen runner and calibration stayed on
  `endpoint=fixture`.
- Green evidence: the same focused command passed 4 tests after adding the
  HumanEval Responses path.
- Regression evidence: `scripts/run python -m pytest
  python/tests/test_glm52_benchmark_verifier.py -q -k 'bwrap_codegen_smoke or
  mixed'` passed 10 tests, preserving mixed/code-sandbox bwrap behavior.
- Full-file evidence: `scripts/run python -m pytest
  python/tests/test_glm52_benchmark_verifier.py -q` passed 149 tests.
- Hygiene evidence: `scripts/run python -m py_compile
  scripts/glm52_benchmark_verifier.py
  python/tests/test_glm52_benchmark_verifier.py` and `git diff --check --
  scripts/glm52_benchmark_verifier.py
  python/tests/test_glm52_benchmark_verifier.py` passed.
- Scope note: this was fake-server adapter-path evidence only and did not claim
  HumanEval pass@1, published conformance, or live GLM validation. The current
  fixture-harness scoring state is recorded below.

### 2026-08-16 fixture-harness completion scoring update

- Current exact single-suite HumanEval Responses runs pass the Responses
  completion into the bwrap fixture scorer and archive the returned codegen
  artifact under the run-scoped Contract Artifacts.
- Samples and metrics record `benchmark_scoring=fixture_harness`,
  `pass_at_1=null`, and fixture-harness `score` values of `1.0` for fixture
  pass or `0.0` for fixture failure. This is only fixture-harness scoring; it is
  not official HumanEval pass@1, not the official HumanEval harness, and not
  published conformance.
- Responses endpoint/request failures remain infrastructure failures. Wrong
  generated code that reaches the fixture scorer and fails is classified as
  `failure_category=model` with `model_failures=1`, not as infrastructure.
- Verification evidence:
  `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
  no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
  'humaneval_responses_run_scores_completion_with_bwrap_fixture_harness or
  humaneval_responses_run_classifies_fixture_failure_as_model_failure or
  mbpp_responses_run_classifies_fixture_failure_as_model_failure'` passed 3
  tests; the runner-level fixture-failure test
	  `test_codegen_smoke_reports_fixture_failure_as_scoreable_result` passed;
  the full touched test files command passed with `170 passed`; `py_compile`
	  for `scripts/glm52_benchmark_verifier.py`,
	  `scripts/glm52_bwrap_task_runner.py`,
	  `python/tests/test_glm52_benchmark_verifier.py`, and
	  `python/tests/test_glm52_bwrap_task_runner.py` passed; and `git diff
	  --check` passed.

### 2026-08-16 official EvalPlus handoff artifact update

- Current exact single-suite HumanEval Responses runs write
  `humaneval/official-harness.json` and list it in `archive-manifest.json` as a
  run-scoped Contract Artifact.
- The handoff artifact records `official_harness=evalplus`, `status=not_run`,
  `metric=pass@1`, `pass_at_1=null`, the suite condition fields, the current
  `fixture_harness` scoring mode, the archived generated-code artifact path,
  and `conformance.claim=none`.
- This is an explicit not-run marker for the official EvalPlus harness, not
  official HumanEval pass@1 evidence and not published conformance.
- Verification evidence:
  `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
  no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
  'humaneval_responses_run_records_official_evalplus_handoff_artifact or
  mbpp_responses_run_records_official_evalplus_handoff_artifact'` passed 2
  tests; the full benchmark verifier file passed with `158 passed`;
  `py_compile` for `scripts/glm52_benchmark_verifier.py` and
  `python/tests/test_glm52_benchmark_verifier.py` passed; `git diff --check`
  for the same files passed; and the trailing-whitespace search found no
  matches.

### 2026-08-16 official EvalPlus missing-prerequisite classification

- The HumanEval `official-harness.json` artifact now classifies the local
  official EvalPlus attempt as `status=missing_prerequisite` when rootfs Python
  cannot import `evalplus`.
- The artifact keeps `metric=pass@1`, `pass_at_1=null`, current
  `fixture_harness` scoring, the archived generated-code artifact path, and
  `conformance.claim=none`, and records
  `prerequisite={type: python_import, name: evalplus, status: missing}` with
  reason `evalplus package is not installed`.
- This is still not official HumanEval pass@1 evidence. It records why the
  official harness was not executed in the current rootfs.
- Verification evidence:
  `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
  no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
  'missing_evalplus_official_harness_prerequisite'` passed 2 tests; the full
  benchmark verifier file passed with `160 passed`; `py_compile` for
  `scripts/glm52_benchmark_verifier.py` and
  `python/tests/test_glm52_benchmark_verifier.py` passed; `git diff --check`
  for the same files passed; and the trailing-whitespace search found no
  matches.

### 2026-08-16 official EvalPlus execution-attempt branch

- Exact single-suite HumanEval Responses runs now have an importable-`evalplus`
  branch that calls a small official-runner seam using the archived generated
  code artifact as input. The artifact still records `conformance.claim=none`
  and `pass_at_1=null`; it records local attempt evidence, not an official
  HumanEval pass@1 claim.
- The default runner writes an EvalPlus samples JSONL file next to the archived
  codegen artifact, runs `python -m evalplus.evaluate --dataset humaneval
  --samples <file> --base-only` with offline environment guards, and stores the
  command, return code, duration, stdout, stderr, samples path, and input
  artifact in `official_attempt_evidence`.
- Tests monkeypatch the import check and runner seam so the importable path is
  covered without network access or package installation. Missing-`evalplus`
  behavior remains covered explicitly.
- Verification evidence:
  `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
  no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
  'evalplus_official_harness or
  humaneval_responses_run_records_official_evalplus or
  mbpp_responses_run_records_official_evalplus'` reported `6 passed, 157
  deselected`; the full benchmark verifier file reported `163 passed`;
  `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m py_compile
  scripts/glm52_benchmark_verifier.py
  python/tests/test_glm52_benchmark_verifier.py` exited zero.

### 2026-08-16 official EvalPlus samples artifact coverage

- The importable-`evalplus` HumanEval test now verifies the generated
  EvalPlus samples JSONL file exists next to the archived codegen artifact,
  contains `task_id=HumanEval/0` and the generated solution text, and is listed
  in `archive-manifest.json` as
  `humaneval/artifacts/humaneval-001-codegen-artifact-evalplus-samples.jsonl`.
- This strengthens the official-harness attempt Contract Artifact trail. It is
  still fake-runner coverage only, not real EvalPlus execution, official
  HumanEval pass@1, or published conformance.
