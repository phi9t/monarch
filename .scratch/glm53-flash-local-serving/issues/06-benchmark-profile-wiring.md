# Add GLM-5.3-Flash Benchmark Profile Wiring

Type: task
Status: ready-for-agent
Blocked by: 04
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add GLM-5.3-Flash benchmark profiles only after the serving verifier can pass
  for the same materialized config.
- Drive live benchmark requests only through the Responses adapter.
- Require SGLang+Dynamo benchmark and coding-agent profiles to cite the passing
  Dynamo lossiness artifact and the passing long-running GSM8K-style pilot
  artifact for the same materialized config digest.
- Add `sglang-dynamo-gsm8k-pilot` as the first long-running inference bringup
  profile, using bounded sample counts before any full-suite attempt.
- Reuse the pinned GLM-5.2 GSM8K-style static-eval metadata unless a newer
  source-reviewed record replaces it: suite id `gsm8k`, dataset revision
  `openai/gsm8k@740312add88f781978c0658806c59bc2815b9866`, harness revision
  `lm-evaluation-harness@8a07e1110d060de48cfc7a9a7987b7659060b60b`, prompt
  template `gsm8k-v1`, family `static_eval`, adapter `static_eval`, execution
  backend `bwrap_rootfs`, and metric `exact_match`.
- Preserve per-sample condition metadata: model profile, endpoint, dataset
  revision, harness revision, prompt template hash, sampling settings,
  reasoning settings, parser settings, context length, output-token budget,
  timeout, execution backend, latency, and usage.
- Preserve run-state metadata for long-running profiles: selected sample ids,
  completed sample ids, progress checkpoints, partial-output paths, run-state
  path, run-state manifest digest, resume verdict, wall-clock timeout,
  per-sample timeout, HTTP status, finish reason, and failure class.
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
- Do not skip the long-running pilot when enabling an SGLang+Dynamo benchmark or
  coding-agent profile.
- Do not claim published conformance without source score metadata and matching
  local run conditions.
- Do not treat bounded GSM8K pilot exact-match results as published-score
  conformance.
- Do not launch Harbor/Docker from inside the bwrap rootfs.

## Acceptance Criteria

- Benchmark profiles refuse to run when the serving verifier has not passed for
  the same materialized config.
- SGLang+Dynamo profiles refuse to run when either `dynamo-lossiness.json` or
  `dynamo-long-reasoning-pilot.json` is absent, failed, or tied to a different
  materialized config digest.
- The GSM8K pilot records resumable run state and can restart without rerunning
  completed samples only when the manifest exactly matches the current model,
  endpoint, dataset, harness, prompt template, sampling, thinking,
  output-token, and timeout settings.
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
