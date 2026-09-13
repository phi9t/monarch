# Codify GLM-5.3-Flash SGLang Launch Profiles

Type: task
Status: ready-for-agent
Blocked by: 02, 07
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add durable GLM-5.3-Flash SGLang profile definitions for the two known local
  launch shapes:
  - `proven-direct-triton`: direct SGLang profile proven on the local 8-GPU
    host with `--moe-runner-backend triton`, `tp_size=8`, `ep_size=1`,
    shared-expert fusion enabled, `context_length=32768`,
    `mem_fraction_static=0.80`, and `max_running_requests=1`.
  - `official-b200-deepgemm-candidate`: official-image B200 candidate with
    `--tp-size 8`, `--ep-size 8`, `--moe-runner-backend deep_gemm`,
    `--disable-shared-experts-fusion`, `--kv-cache-dtype fp8_e4m3`,
    `--reasoning-parser glm45`, and `--tool-call-parser glm47`.
- Record image provenance for each profile, including image name, digest,
  SGLang version, Transformers version, and whether the image contains GLM-5.3
  snippet docs for the selected profile.
- Preserve model-layout assumptions that affect launch flags: 288 routed
  experts, 1 shared expert, FP8 checkpoint, DSA/KDA attention, and forced
  thinking.
- Make profile selection explicit in materialized argv and artifacts. The
  runtime must never silently switch from one profile to another after a weight
  load failure.
- When a profile uses Docker rather than the rootfs venv, record the separate
  execution-domain decision in the artifact and include the mount map for the
  checkpoint and run-artifact directory.

## Exclusions

- Do not treat `proven-direct-triton` and `official-b200-deepgemm-candidate` as
  equivalent benchmark profiles until both pass the same live probes.
- Do not enable MTP or speculative decoding in either base profile. Add those
  as separate extensions only after the base profile is green.
- Do not use GLM-5.2 SGLang flags as defaults for GLM-5.3-Flash unless the
  profile explicitly revalidates them.

## Acceptance Criteria

- Materializing `proven-direct-triton` emits the exact working direct-SGLang
  settings observed in the live run and records shared-expert fusion as
  expected enabled state.
- Materializing `official-b200-deepgemm-candidate` emits the B200 candidate
  settings and records shared-expert fusion as disabled by explicit flag.
- Launch preflight rejects a profile when observed image or checkpoint metadata
  does not match the profile's required model layout.
- A weight-load failure records the selected profile name, argv digest, image
  digest, checkpoint digest, and the first traceback without mutating the
  materialized profile.
- Direct SGLang health artifacts include the selected profile name and can be
  compared across profiles by config digest.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_sglang_runtime.py -q
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
```

Add tests that inspect materialized argv and artifact contents. Live profile
execution is separate final evidence: first rerun `proven-direct-triton`, then
run `official-b200-deepgemm-candidate` only after the direct profile is green
and GPUs are available.
