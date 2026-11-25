# Add GLM-5.3-Flash SGLang Launch and Preflight

Type: task
Status: ready-for-agent
Blocked by: 01
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add a GLM-5.3-Flash SGLang launch path using the `glm53_flash_` script/module
  prefix.
- Launch SGLang inside the Monarch bwrap rootfs unless this ticket records a
  separate Docker profile decision.
- Use `--model-path zai-org/GLM-5.3-Flash`, `--reasoning-parser glm45`, and
  `--tool-call-parser glm47`.
- Record backend package or image provenance, model cache evidence, GPU list,
  rootfs identity, parser settings, thinking settings, and multimodal processor
  availability.
- Preflight GLM-5.3-Flash-specific capability support: `glm5_next`, FP8
  checkpoint handling, hybrid attention, MoE expert shape, and KDA/MTP relevant
  settings. Image processor availability may be recorded as deferred until the
  multimodal profile is selected.
- Record observed KDA state-pool, MTP, and speculative-decoding settings in the
  environment artifact when the backend exposes them.
- Record direct SGLang raw Chat transcript digests for later Dynamo lossiness
  comparison.
- Emit failure artifacts with stable classes from the spec, including
  `environment_setup_failed`, `model_cache_failed`, and
  `backend_capability_failed`.

## Exclusions

- Do not claim the Responses path is compatible from direct SGLang Chat probes.
- Do not run benchmark suites in this ticket.
- Do not silently fall back to GLM-5.2, a hosted API, or a different model id.

## Acceptance Criteria

- A focused dry-run/materialization path produces structured argv, env, log,
  process-record, and artifact paths for a GLM-5.3-Flash SGLang component.
- Preflight fails before launch when required model metadata or parser settings
  are absent, and fails the multimodal profile when processor support is absent.
- Direct Chat health can be probed as a backend diagnostic and writes a
  run-scoped artifact.
- Direct Chat diagnostic output is labeled non-Codex evidence unless it is later
  mapped through the Responses adapter.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_sglang_runtime.py -q
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
```

Add GLM-5.3-Flash-focused tests before implementation. Keep the GLM-5.2 command
as regression coverage if the existing launch runtime is shared, and keep
live-launch evidence separate from unit/fake-process evidence.
