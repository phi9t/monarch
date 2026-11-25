# Issue 01: Rootfs Overlay Schema and Drift Validation

Status: ready-for-agent

Type: task

Blocked by:

Spec: `.scratch/glm52-rootfs-sglang-hardening/spec.md`

Plan: `.scratch/glm52-rootfs-sglang-hardening/implementation-plan.md`

## Outcome

Add a source-backed GLM-5.2 SGLang rootfs overlay schema and validate that the
resolved bwrap plan matches the materialized runtime config for SGLang-specific
paths, env values, and mounts.

## Requirements

- Portable config must not contain absolute host paths in host-layout fields.
- SGLang venv path must be `/cache/glm52/venvs/sglang`.
- HF cache path must be `/cache/glm52/hf-home`.
- SGLang cache path must be `/cache/glm52/sglang`.
- `HF_HOME` and `SGLANG_CACHE_DIR` in the rootfs plan must match the
  materialized config.
- Concrete host mounts must still be validated through the generic rootfs
  sandbox contract.

## Exclusions

- Do not install SGLang.
- Do not download model weights.
- Do not launch a live server.
- Do not modify Dynamo, Responses adapter, Harbor, or benchmark code.

## Verification

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
scripts/run python -m pytest python/tests/test_rootfs_enter_plan.py python/tests/test_rootfs_sandbox_config.py -q
```

## Comments
