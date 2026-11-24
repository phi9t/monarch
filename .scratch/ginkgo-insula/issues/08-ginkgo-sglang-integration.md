# Insula Ginkgo SGLang Integration

Status: ready-for-agent
Type: task
Blocked by: 07

## Objective

Move Ginkgo SGLang launch onto Insula so the Qwen3 bwrap-rootfs run uses the
same rootfs invocation module as human and automation entrypoints.

## Requirements

- Add `build_insula_invocation_spec` to `scripts/glm52_sglang_runtime.py`.
- Replace raw `launch.outer_argv` execution with Insula execution.
- Preserve SGLang process records and teardown ownership checks.
- Add Insula artifact paths to SGLang launch summaries.
- Add Insula artifact paths to Ginkgo Local Run evidence manifests.
- Keep Qwen3 generated output and teardown behavior unchanged.

## Files

- Modify `scripts/glm52_sglang_runtime.py`
- Modify `ginkgo/local_run.py`
- Create `python/tests/test_ginkgo_insula_runtime_integration.py`
- Modify `python/tests/test_ginkgo_qwen3_sglang_smoke.py`
- Modify `python/tests/test_glm52_sglang_runtime.py`

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_runtime_integration.py python/tests/test_ginkgo_qwen3_sglang_smoke.py python/tests/test_glm52_sglang_runtime.py -q
```

## Notes

Follow Task 8 in `.scratch/ginkgo-insula/implementation-plan.md`.
