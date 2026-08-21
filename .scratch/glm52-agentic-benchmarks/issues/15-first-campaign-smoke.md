# First Campaign Smoke

Type: task
Status: ready-for-agent
Blocked by: 12 13 14

## Objective

Add a first campaign smoke command that runs a small representative GLM52
agentic benchmark campaign and emits a valid campaign summary.

## Context

The resolved first campaign includes smoke, reportable-score-capable, and pilot
evidence classes. This ticket ties together manifest loading, endpoint
readiness, adapters, artifact normalization, and campaign reporting for a
small local run.

## Requirements

- Add or update a sample campaign manifest under
  `.scratch/glm52-agentic-benchmarks/`.
- Include at least:
  - `needle-smoke`
  - `gsm8k`
  - `humaneval`
  - one Harbor pilot suite when the local Harbor prerequisites are available.
- Require the local GLM-5.2 Responses endpoint through
  `component://responses_adapter/openai_base_url`.
- Write `campaign-summary.json`.
- Record each suite evidence class.
- Separate model, infrastructure, scorer, skipped, unsupported, and
  non-comparable denominator counts.
- Fail loudly if endpoint readiness artifacts do not match the same run and
  endpoint condition as the campaign.
- Document which parts of the smoke can run without live GLM-5.2 and which
  require live serving.

## Files

- Create: `.scratch/glm52-agentic-benchmarks/campaign-manifest.yaml`
- Modify: `scripts/glm52_benchmark_verifier.py`
- Modify: `ginkgo/eval/orchestrator.py`
- Modify: `ginkgo/eval/artifacts.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`

## Exclusions

- Do not run a large full-suite campaign without explicit user authorization.
- Do not add stateful-tool or GDPval proxy pilots here.
- Do not claim reportable score evidence from fixture or smoke data.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
scripts/run_glm52_benchmark_verifier.sh smoke ...
```

## Done When

- The smoke command produces campaign-level artifacts for the selected suites.
- `campaign-summary.json` validates denominator separation and evidence
  classes.
- The command fails loudly when readiness artifacts are missing, stale, or from
  a different endpoint condition.
