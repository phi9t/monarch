# Add GLM-5.3-Flash Benchmark Profile Wiring

Type: task
Status: ready-for-agent
Blocked by: 04
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add GLM-5.3-Flash benchmark profiles only after the serving verifier can pass
  for the same materialized config.
- Drive live benchmark requests only through the Responses adapter.
- Preserve per-sample condition metadata: model profile, endpoint, dataset
  revision, harness revision, prompt template hash, sampling settings,
  reasoning settings, parser settings, context length, output-token budget,
  timeout, execution backend, latency, and usage.
- Preserve comparison metadata for published-score checks: agent harness name
  and version, shell/container environment, wall-clock timeout, source suite
  revision, context budget, and mapping between benchmark `max_new_tokens` and
  Responses `max_output_tokens`.
- Record GLM-5.3-Flash-specific conditions: forced thinking, preserved-thinking
  history, multimodal input type, MTP/speculative decoding settings, KDA
  state-pool settings, and FP8 path.
- Keep smoke, calibration, and published-score conformance artifacts separate.
- Require host-controlled Harbor/Docker for suites whose benchmark contract
  requires that execution domain.

## Exclusions

- Do not treat fake Responses, static fixture answers, or `endpoint=fixture` as
  live model evidence.
- Do not bypass Responses by calling SGLang or Dynamo Chat directly.
- Do not claim published conformance without source score metadata and matching
  local run conditions.
- Do not launch Harbor/Docker from inside the bwrap rootfs.

## Acceptance Criteria

- Benchmark profiles refuse to run when the serving verifier has not passed for
  the same materialized config.
- Exact-suite smoke records the run-owned Responses endpoint and complete
  condition metadata.
- Calibration separates model failures from infrastructure failures.
- Published-score comparison remains disabled until benchmark source,
  conditions, tolerances, and local evidence are all recorded.
- Terminal-Bench-style profiles fail if Harbor/Docker is launched from inside
  the bwrap rootfs instead of the host-control domain.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_benchmark_verifier.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

Add GLM-5.3-Flash benchmark-profile tests before implementation. Keep the
GLM-5.2 command as regression coverage if benchmark wiring is shared. Live
benchmark completion evidence should cite run ids and Contract Artifact paths.
