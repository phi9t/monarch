# A/B GLM-5.3-Flash SGLang Backend Profiles

Type: task
Status: ready-for-agent
Blocked by: 08, 09
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add an A/B runner that executes the same GLM-5.3-Flash probe corpus against
  `proven-direct-triton` and `official-b200-deepgemm-candidate`.
- Treat `proven-direct-triton` as the local correctness baseline because it has
  already loaded all 62 checkpoint shards and completed the direct
  three-sample GSM8K-style pilot.
- Treat `official-b200-deepgemm-candidate` as experimental until it passes the
  same load, health, first-request, steady-state, and pilot gates.
- Preserve all profile-specific launch metadata in the comparison artifact:
  image digest, SGLang version, Transformers version, argv, argv digest,
  checkpoint digest, selected MoE backend, `tp_size`, `ep_size`, KV cache dtype,
  quantization, shared-expert fusion state, and DSA backend flags.
- Compare startup, first-request, and steady-state phases separately. The
  comparison must record time-to-HTTP-ready, time-to-first-successful-decode,
  first-token latency, end-to-end latency, tokens per second, GPU memory
  snapshot when available, and final-answer verdict.
- Preserve backend-specific failure signatures, including the previously
  observed `IndexError: index 288 is out of bounds for dimension 1 with size
  288`, without rewriting them into generic launch failures.
- Add stable failure classes for `ab_baseline_failed`,
  `ab_candidate_load_failed`, `ab_candidate_decode_failed`,
  `ab_candidate_regressed_correctness`, `ab_candidate_missing_metrics`, and
  `ab_profiles_not_comparable`.

## Exclusions

- Do not compare profiles across different checkpoints, prompts, image digests,
  or decoding settings unless the artifact explicitly marks the run as
  non-comparable.
- Do not promote `official-b200-deepgemm-candidate` to the default profile from
  startup success alone. It must pass the steady-state pilot and produce the
  required metrics.
- Do not run broad public benchmark suites in this ticket. The first comparison
  scope is the bounded local pilot that already exists in the GLM-5.3 spec.
- Do not mutate either profile during A/B execution. Profile tuning must happen
  in a follow-up ticket with a new profile name or explicit revision.

## Acceptance Criteria

- The runner refuses to compare runs unless both profiles use the same
  checkpoint manifest digest, prompt corpus digest, decoding settings, and
  request timeout budget.
- The summary artifact reports one row per profile for startup, health,
  first-request, and steady-state phases, plus one row per probe result.
- A passing comparison shows that `proven-direct-triton` remains green and
  records whether `official-b200-deepgemm-candidate` is green, lossy, failed, or
  non-comparable.
- If the candidate hits the expert-index failure, the artifact records
  `ab_candidate_load_failed`, includes the traceback excerpt, and keeps the
  baseline result intact.
- If both profiles pass, the artifact records the candidate-to-baseline ratios
  for startup time, first-token latency, end-to-end latency, and tokens per
  second without automatically changing the default profile.
- Synthetic tests cover non-comparable prompt digests, baseline failure,
  candidate launch failure, and missing metric classification.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_backend_ab.py -q
scripts/run python -m pytest python/tests/test_glm53_flash_sglang_runtime.py -q
scripts/run python -m pytest python/tests/test_glm53_flash_serving_verifier.py -q
```

Use synthetic artifacts for unit tests. Live acceptance requires a fresh
baseline run and a candidate run on the same GPU allocation, with artifacts
stored under a single comparison directory.
