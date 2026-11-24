# Clean 8-GPU Preflight

Type: task
Status: ready-for-agent
Blocked by:

## Goal

Prove that the local host, Hermetic Rootfs, declared parent config, dependency
records, ports, and GPU ownership are ready for one live GLM-5.2 parent
repeatability attempt.

## Requirements

- Work from the isolated GLM worktree unless a human explicitly names a newer
  execution checkout.
- Read `../spec.md` before running commands.
- Use `scripts/run` for Linux-local repository commands.
- Use host tools directly only for host-resource checks that must observe GPU
  and port state outside the Hermetic Rootfs.
- Verify the existing SGLang venv and model-cache records:
  `glm52-serving-results/prepare-venv/sglang-venv.json` and
  `glm52-serving-results/prepare-model/model-cache.json`.
- Prepare or refresh the Dynamo venv record through
  `scripts/glm52_inference_runtime.py prepare-dynamo-venv`.
- Materialize and validate the parent config from
  `ginkgo/configs/inference-glm52.yaml` and the selected
  `ginkgo/local-env/*.yaml`.
- Confirm materialized ports are concrete, inside `19000-19200`, and not
  `8000`, `8080`, or `18080`.
- Confirm materialized GPU devices are exactly `0,1,2,3,4,5,6,7`.
- Confirm no non-owned process occupies any of the eight GPUs immediately
  before handing off to the live run ticket.
- Preserve command output paths and blocker snapshots under
  `glm52-serving-results/<run-id>/`.

## Exclusions

- Do not launch SGLang, Dynamo, or the Responses adapter from this ticket.
- Do not kill or request killing non-owned GPU processes.
- Do not edit portable configs to point at absolute host paths.
- Do not accept an old clean GPU sample as a reservation for the later launch.

## Verification Evidence

- `scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q`
  passes.
- `scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py python/tests/test_rootfs_verifier.py scripts/rootfs/tests/test_execution_contract.py scripts/rootfs/tests/test_entrypoint_inventory.py -q`
  passes or a rootfs-space blocker is recorded with the alternate governed
  rootfs command used.
- Dynamo venv preparation writes an importable dependency record.
- Materialization and validation commands exit zero.
- Host GPU occupancy snapshot shows no non-owned compute process on devices
  `0,1,2,3,4,5,6,7`, or the ticket remains open with blocker evidence.
- Host port snapshot shows no occupied planned run-owned port, or the ticket
  remains open with blocker evidence.

## Comments
