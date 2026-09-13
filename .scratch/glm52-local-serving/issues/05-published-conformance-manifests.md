# Add Published-Score Conformance Manifests

Type: task
Status: ready-for-human
Blocked by: 03

## Current Status

Benchmark and published-score manifests, condition-field guardrails, and
pre-inference conformance rejection are implemented and tested locally. The
remaining work needs verified primary-source GLM-5.2 score metadata whose
profile, prompt template, decoding profile, benchmark revision, execution
backend, metric, and tolerance match the local manifest. Current placeholders
and known primary-source scores are intentionally non-comparable, so this ticket
is not ready for another local agent slice. Do not mark it resolved or use it
for conformance until comparable primary-source conditions are populated.

## Requirements

- Add benchmark and published-score manifests for GLM-5.2 conformance runs.
- Pin every benchmark suite by dataset revision, harness revision, prompt
  template, decoding profile, profile name, execution backend, and metric.
- Record primary-source URLs for every published GLM-5.2 score used for
  comparison.
- Separate Codex tool-calling readiness from reasoning and published
  conformance profiles.
- Keep thinking-enabled and thinking-disabled reasoning profiles separate.
- Require explicit tolerances per benchmark before a conformance pass/fail can
  be reported.
- Include GSM8K, AIME, HumanEval, MBPP, Terminal-Bench 2, RULER, and
  needle-smoke entries as separate suites.
- Mark benchmarks as non-comparable when the local profile does not match the
  published score condition.

## Exclusions

- Do not populate expected scores from secondary articles or unofficial tables.
- Do not compare bwrap-backed runs to published Docker-backed results when the
  execution backend is part of the published condition.
- Do not treat missing manifest values as warnings in conformance mode.

## Verification Evidence

- Manifest validation tests that fail on missing source, metric, tolerance,
  profile, prompt template, dataset revision, harness revision, or execution
  backend.
- A dry-run conformance command that fails before inference when required
  published-score fields are missing.

## Answer

Partial implementation completed for manifest coverage and conformance
guardrails:

- Added `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`.
- Added required suite entries for `gsm8k`, `aime`, `humaneval`, `mbpp`,
  `terminal-bench-2`, `ruler`, and `needle-smoke`.
- Kept Codex tool-calling, coding, terminal-agent, long-context, and math
  reasoning profiles separate.
- Kept thinking-disabled and thinking-enabled reasoning profiles separate for
  GSM8K and AIME.
- Added `.scratch/glm52-local-serving/benchmarks/published-scores.yaml` with
  explicit non-comparable placeholder entries rather than unverified secondary
  scores. Placeholder entries include the pinned local decoding profile so
  conformance can distinguish missing primary-source scores from profile
  mismatches.
- Added manifest coverage validation and conformance validation in
  `scripts/glm52_benchmark_verifier.py`.
- Conformance rejects missing or placeholder `source_url`, `score`, and
  `tolerance` fields before inference.
- Conformance rejects published-score entries whose profile or decoding profile
  does not match the suite manifest, preventing thinking-enabled and
  thinking-disabled comparisons from being conflated.

This does not yet pin primary-source GLM-5.2 published scores. The manifest
therefore cannot support a published conformance claim yet, by design.

Verification evidence:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 46 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_missing_published_score_fields \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_backend_override \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_profile_mismatch \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_decoding_profile_mismatch \
  -q
# 4 passed

scripts/run_glm52_benchmark_verifier.sh conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --suite humaneval \
  --run-id conformance-dry-run
# exits 2 before inference:
# error: published score for humaneval missing fields: score, source_url, tolerance
```

2026-08-15 primary-source score check:

- Added `.scratch/glm52-local-serving/published-score-source-check.md`.
- Checked the Hugging Face `zai-org/GLM-5.2` model card as a primary source:
  `https://huggingface.co/zai-org/GLM-5.2/raw/main/README.md`.
- The model card reports official GLM-5.2 scores including `AIME 2026=99.2`,
  `Terminal Bench 2.1 (Terminus-2)=81.0`, and
  `Terminal Bench 2.1 (Best Reported Harness)=82.7`.
- The same model card footnotes make those scores non-comparable to the
  current local manifest:
  - AIME/HMMT/IMOAnswerBench use `temperature=1.0`, `top_p=0.95`, maximum
    generation length `163,840`, a specific answer-format system prompt, and
    GPT-5.5 medium as judge.
  - Terminal-Bench 2.1 (Terminus-2) uses the Terminus-2 framework with
    `parser=json`, `timeout=4h`, `temperature=1.0`, `top_p=1.0`,
    `max_new_tokens=48k`, `max_episodes=500`, and a 256K context window.
  - The local `terminal-bench-2` profile is Harbor/Codex-readiness oriented:
    `temperature=0.2`, `top_p=0.95`, `max_output_tokens=4096`, and GLM
    thinking disabled.
  - The local `aime` profile is not pinned to `AIME 2026` and uses different
    decoding/judging conditions.
- Decision: keep `.scratch/glm52-local-serving/benchmarks/published-scores.yaml`
  placeholders for now so conformance continues to fail before inference rather
  than comparing incompatible conditions.

Verification:

```sh
python - <<'PY'
import urllib.request
text = urllib.request.urlopen(
    "https://huggingface.co/zai-org/GLM-5.2/raw/main/README.md",
    timeout=30,
).read().decode("utf-8", "replace")
for needle in [
    "AIME 2026|99.2",
    "Terminal Bench 2.1 (Terminus-2)|81.0",
    "temperature=1.0",
    "max_new_tokens=48k",
]:
    assert needle in text
PY

scripts/run_glm52_benchmark_verifier.sh conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --suite terminal-bench-2 \
  --run-id conformance-terminal-source-check
# exits 2 before inference because source_url, score, and tolerance remain
# placeholders for the intentionally non-comparable local profile
```

2026-08-16 default conformance dry-run coverage:

- Added `needle-smoke` to
  `.scratch/glm52-local-serving/benchmarks/published-scores.yaml` as a
  non-comparable placeholder so the published-score manifest covers every
  benchmark suite selected by the default conformance command.
- Added a checked-in manifest coverage regression test:
  `test_checked_in_published_scores_cover_default_conformance_suites`.
- Conformance now supports the execution prompt's documented command shape:
  omitting `--suite` selects all suites from
  `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`.
- The default dry-run still exits before inference because the placeholders are
  intentionally incomplete:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_scores_cover_default_conformance_suites \
  -q
# red before manifest coverage fix:
# AssertionError: ... 'needle-smoke' ... <= {'aime', 'gsm8k', 'humaneval', 'mbpp', 'ruler', 'terminal-bench-2'}

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_scores_cover_default_conformance_suites \
  -q
# 1 passed

scripts/run python scripts/glm52_benchmark_verifier.py conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --run-id conformance-default-suite-dry-run
# exits 2 before inference:
# error: published score for needle-smoke missing fields: score, source_url, tolerance

scripts/run_glm52_benchmark_verifier.sh conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --run-id conformance-default-suite-wrapper-dry-run
# exits 2 before inference:
# error: published score for needle-smoke missing fields: score, source_url, tolerance

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 33 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 73 passed

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

2026-08-16 fresh conformance dry-run command:

- Re-ran the execution prompt's conformance dry-run against the checked-in
  benchmark and published-score manifests.
- The command still fails before inference because the first default suite,
  `needle-smoke`, has placeholder `score`, `source_url`, and `tolerance`
  fields. This is the intended guardrail while published-score inputs remain
  incomplete and non-comparable.
- No result directory or run-state files were created for this invalid
  conformance input.

Verification:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh conformance \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
    --run-id conformance-dry-run-20260816T034900Z
# exit 2
# error: published score for needle-smoke missing fields: score, source_url, tolerance

find glm52-benchmark-results/conformance-dry-run-20260816T034900Z -maxdepth 3 -type f
# no files; result directory not created

find .scratch/glm52-local-serving/run -maxdepth 1 -type f -name '*conformance-dry-run-20260816T034900Z*'
# no run-state files
```

2026-08-16 prompt-named manifest validation slice:

- Added the exact Phase 6 prompt verification target
  `test_published_score_manifest_validation`.
- The test loads the checked-in benchmark manifest and published-score
  manifest, verifies every default conformance suite has a published-score
  entry, and asserts that current placeholder `needle-smoke` fields still fail
  before inference.
- This keeps the execution prompt's documented pytest command runnable without
  weakening the existing guardrail that placeholders cannot become conformance
  claims.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  -q
# red before implementation:
# ERROR: not found: ... test_published_score_manifest_validation

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 61 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 103 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 checked-in published-score condition consistency slice:

- Added
  `test_checked_in_published_score_conditions_match_benchmark_manifest`.
- The test loads the checked-in benchmark manifest and published-score manifest
  and compares conformance condition fields for every suite: `profile`,
  `metric`, `prompt_template`, `dataset_revision`, `harness_revision`,
  `execution_backend`, and `decoding_profile`.
- Red evidence: the new test failed on
  `swe-bench-verified.dataset_revision` because the published-score placeholder
  entry still used the SWE-bench harness commit in the dataset revision slot.
- Fixed only that metadata drift. The published-score SWE-bench Verified
  `dataset_revision` now matches the benchmark manifest's Hugging Face dataset
  revision:
  `SWE-bench/SWE-bench_Verified@78f471bf655a3137b2e8a75af1501690ec009ec3`.
- This does not populate primary-source scores, tolerances, or comparable
  conformance inputs. The published-score manifest still intentionally blocks
  conformance before inference.

Verification:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_score_conditions_match_benchmark_manifest \
  -q
# red: AssertionError: swe-bench-verified.dataset_revision

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_scores_cover_default_conformance_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_score_conditions_match_benchmark_manifest \
  -q
# 4 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 123 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

Fresh checked-in conformance dry-run after the condition consistency fix:

```sh
scripts/run python scripts/glm52_benchmark_verifier.py conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --run-id conformance-condition-guard-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/conformance-condition-guard-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/conformance-condition-guard-20260816T000000Z/run
# exit 2
# error: published score for needle-smoke missing fields: score, source_type, source_url, tolerance, tolerance_basis

find .scratch/glm52-local-serving/tmp/conformance-condition-guard-20260816T000000Z -maxdepth 4 -type f
find .scratch/glm52-local-serving/run -maxdepth 1 -type f -name '*conformance-condition-guard-20260816T000000Z*'
# no files
```

2026-08-16 checked-in benchmark source pin slice:

- Added
  `test_checked_in_benchmark_manifest_has_pinned_prepare_revisions`.
- The test loads `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`,
  verifies default suite coverage, and runs
  `validate_prepare_manifest_revisions()` against the checked-in manifest.
- Replaced checked-in `@pinned-placeholder` suite revisions with concrete
  upstream refs and verifier-supported `dataset_source` / `harness_source`
  metadata. The published-score placeholder manifest's condition fields now
  match those benchmark revisions, while `score`, `source_url`, `tolerance`,
  and `tolerance_basis` remain invalid placeholders so conformance still stops
  before inference.
- This does not claim official conformance. It only makes the benchmark
  manifest source pins explicit; real source materialization, Harbor execution,
  official container images, SWE-bench per-instance images, and comparable
  published scores remain open.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_benchmark_manifest_has_pinned_prepare_revisions \
  -q
# red before implementation:
# BenchmarkVerifierError: suite humaneval dataset_revision must be pinned

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_benchmark_manifest_has_pinned_prepare_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_scores_cover_default_conformance_suites \
  -q
# 3 passed

scripts/run python scripts/glm52_benchmark_verifier.py conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --run-id conformance-pinned-revisions-dry-run-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/conformance-pinned-revisions-dry-run-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/conformance-pinned-revisions-dry-run-20260816T000000Z/run
# exit 2
# error: published score for needle-smoke missing fields: score, source_type, source_url, tolerance, tolerance_basis

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 94 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 143 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

scripts/run python - <<'PY'
from pathlib import Path
import yaml
for path in [Path(".scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml"), Path(".scratch/glm52-local-serving/benchmarks/published-scores.yaml")]:
    payload = yaml.safe_load(path.read_text())
    print(path, len(payload.get("suites", payload.get("scores", []))))
PY
# .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml 8
# .scratch/glm52-local-serving/benchmarks/published-scores.yaml 8

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0
```

2026-08-16 Harbor smoke source pin slice:

- The checked-in Terminal-Bench 2 Harbor smoke config and dataset lock now use
  the same source revisions as the benchmark manifest:
  Harbor `9dd349f28b969268aef419e910e1998149b612a5` and Terminal-Bench
  `d28711d0da2675d0bb1d56de45ae5df6082438a3`.
- `load_harbor_smoke_config()` now rejects placeholder-style source revisions,
  so a checked-in or copied Harbor smoke config with `placeholder` in a source
  revision fails before Harbor execution.
- This still does not claim published conformance; score fields and tolerance
  metadata remain intentionally invalid placeholders until primary-source
  comparable scores are available.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_harbor_smoke_config_has_pinned_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_rejects_placeholder_source_revisions \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 97 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 146 passed
```

2026-08-16 manifest profile-required validation slice:

- Benchmark manifests must now pin `profile` for every suite before
  conformance validation can compare local conditions to published-score
  metadata.
- Added `test_manifest_suite_validation_requires_profile` and fixed fixture
  manifests to carry explicit profiles.
- The checked-in benchmark manifest already included suite profiles; this slice
  makes the verifier reject future omissions.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_suite_validation_requires_profile \
  -q
# red before implementation:
# AssertionError: suite profile should be required

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_manifest_suite_validation_requires_profile \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# intermediate fixture fallout after tightening the manifest contract:
# 22 failed, 19 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 41 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 82 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```

2026-08-16 non-comparable score guardrail slice:

- Conformance validation now rejects published-score entries marked
  `comparable: false` even when `source_url`, `score`, `tolerance`, and all
  matching condition metadata are present.
- This keeps the manifest's non-comparable marker authoritative and prevents a
  local profile that differs from the primary-source benchmark condition from
  becoming a conformance claim by filling in numeric fields.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_comparable_score \
  -q
# red before implementation:
# AssertionError: non-comparable published scores should fail conformance

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_comparable_score \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 40 passed
```

2026-08-16 conformance reproducibility artifact slice:

- Added result/run-root support to the `conformance` command.
- When conformance inputs are complete and comparable, the command now writes a
  run-scoped `conformance.json` artifact with selected suite IDs, matched
  published-score metadata, manifest hash, and published-score manifest hash.
- The conformance command also copies `benchmark-manifest.json` and
  `published-scores.json`, writes `archive-manifest.json`, and emits
  `benchmark-<run-id>.json` plus `cleanup-<run-id>.json` in the run ledger.
- Added `test_conformance_command_writes_reproducibility_artifact` for the
  complete-input path. The checked-in published-score manifest still contains
  placeholders and still fails before inference by design.

Verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# red before implementation:
# argparse rejected --results-root and --run-root for conformance

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 35 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 75 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py

bash -n \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh

git diff --check
# exit 0
```
