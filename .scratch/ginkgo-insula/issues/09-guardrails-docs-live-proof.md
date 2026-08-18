# Insula Guardrails, Docs, And Live Proof

Status: ready-for-agent
Type: task
Blocked by: 08

## Objective

Prove Insula is the sole governed local bwrap-rootfs invocation path and
document the new ownership model.

## Requirements

- Add guardrail tests that reject raw bwrap or rootfs entry argv construction
  outside Insula and allowed rootfs build/test fixtures.
- Update Ginkgo docs to describe Insula.
- Run focused Insula, rootfs, Ginkgo, and SGLang tests.
- Run live `scripts/run` smoke.
- Run live legacy `enter_rootfs.sh --emit-plan` smoke.
- Run live Qwen3 SGLang bwrap smoke twice on run-owned custom ports.

## Files

- Modify `python/tests/test_ginkgo_project_contract.py`
- Modify `scripts/rootfs/tests/test_entrypoint_inventory.py`
- Modify `ginkgo/docs/operator-workflow.md`
- Modify `ginkgo/README.md`
- Modify `.scratch/ginkgo-insula/spec.md`

## Verification

```sh
scripts/run python -m pytest \
  python/tests/test_ginkgo_insula_schema.py \
  python/tests/test_ginkgo_insula_materialize.py \
  python/tests/test_ginkgo_insula_bwrap_plan.py \
  python/tests/test_ginkgo_insula_compatibility.py \
  python/tests/test_ginkgo_insula_runtime_integration.py \
  python/tests/test_ginkgo_qwen3_sglang_smoke.py \
  python/tests/test_ginkgo_project_contract.py \
  python/tests/test_glm52_sglang_runtime.py \
  scripts/rootfs/tests/test_entrypoint_inventory.py \
  scripts/rootfs/tests/test_execution_contract.py \
  scripts/rootfs/tests/test_guarded_entrypoints.py \
  scripts/rootfs/tests/test_run_gateway.py \
  -q

scripts/run python -c "print('insula-run-ok')"

tmp_plan="$(mktemp)"
scripts/rootfs/enter_rootfs.sh --emit-plan "$tmp_plan" -- python3 -c "print('insula-enter-ok')"
test -s "$tmp_plan"

./ginkgo/scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh --port 19017
./ginkgo/scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh --port 19018
```

## Notes

Follow Task 9 in `.scratch/ginkgo-insula/implementation-plan.md`.
