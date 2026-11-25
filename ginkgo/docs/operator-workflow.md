# Operator Workflow

Run all substantive checks through `scripts/run` so commands execute inside the
Monarch bwrap rootfs. Use a machine-local environment file derived from
`ginkgo/local-env/template.yaml`; do not put concrete host paths into portable
Ginkgo configs.

## Sequence

1. Fill a local environment file with repo, rootfs, run, temp, cache, results,
   shared-memory, and GPU settings for this host.
2. Run the sandbox-only profile to validate rootfs selection, directory
   projection, tools, imports, and bwrap plan translation.
3. Run the CUDA-kernel profile on GPU hosts to validate PyTorch CUDA visibility
   and declared optimized-kernel capability.
4. Prepare the SGLang venv under `/cache/glm52/venvs/sglang`.
5. Prepare the dense Qwen3 smoke model cache under `/cache/glm52/hf-home`.
6. Run the dense serving smoke from `ginkgo/configs/smoke-qwen3-dense.yaml`.
   The operator command is:

   ```sh
   ginkgo/scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh --port 19007
   ```

   The wrapper is a host-control entrypoint: it materializes host-local paths
   and delegates to the Python implementation, which validates and launches the
   resolved bwrap command. It defaults to
   `ginkgo/local-env/qwen3-sglang.yaml` for machine-local paths; set
   `GINKGO_QWEN3_LOCAL_ENVIRONMENT` or pass `--local-environment <path>` to use
   another file. It materializes the schema, launches SGLang inside the governed
   rootfs, sends a real chat request, prints each bringup/inference/teardown
   stage, prints SGLang log tails and the final model output, then writes
   `qwen3-sglang-smoke-evidence.json` in the run-owned results directory.
   In-process actor mode may generate projected local environment files under
   `ginkgo/local-env/.generated/`; those files are run artifacts and must be
   regenerated from the operator local environment instead of edited as source.
   When the configured CUDA device is occupied, operators may wait for that
   exact device before launch:

   ```sh
   ginkgo/scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh \
     --port 19007 \
     --wait-for-gpu-free-seconds 600 \
     --gpu-free-stable-seconds 10
   ```

   The wait is no-fallback: it watches only the device declared by the
   materialized config, for example `CUDA_VISIBLE_DEVICES=0` from the dense
   smoke config. It does not choose another GPU, does not switch to CPU, and
   fails loudly when the declared device remains occupied. Failed waits write
   `gpu_wait` and `failure.blocked_gpus` evidence in the run manifest so the
   blocker is inspectable without treating the run as serving success.
   For a CPU-only route that validates the SGLang serving path without GPU
   projection, use:

   ```sh
   ginkgo/scripts/run_qwen3_sglang_inference_in_bwrap_rootfs.sh --device cpu --port 19007
   ```

   This selects `ginkgo/configs/smoke-qwen3-cpu.yaml`, keeps
   `sandbox.gpu: none`, and omits `CUDA_VISIBLE_DEVICES` from the materialized
   launch contract. Passing an explicit `--declared-spec` keeps that declared
   spec authoritative.
7. Run three dense smoke launch/probe/teardown cycles before treating the
   sandbox as repeatable.
8. Run the MoE smoke only when the host satisfies its explicit disk, GPU, and
   timeout budget.
9. For the Monarch parent control-plane route, run the CPU actor smoke inside
   the rootfs and require artifact verification before accepting the run:

   ```sh
   scripts/run python ginkgo/scripts/run_qwen3_monarch_control_plane_smoke.py \
     --mode in-process-actor \
     --run-id qwen3-monarch-cpu-actor-$(date -u +%Y%m%dT%H%M%SZ) \
     --expected-child-device cpu \
     --verify-artifact
   ```

   The smoke writes a parent `monarch-control-plane-manifest.json`, launches the
   Qwen3 SGLang child through the same Local Run path, sends real model and
   inference probes, and tears the child down. A host-child parent pass is gated
   by the standalone Qwen3 child verifier before passed parent evidence is
   written; that gate validates the child manifest, child device, OpenAI URL,
   generated text, teardown status, and closed serving port. `--verify-artifact`
   then verifies the saved parent and child artifacts, including parent status,
   execution mode, evidence boundary, actor status, and component state. The CPU
   route defaults to `--expected-child-device cpu`; CUDA variants must pass
   `--expected-child-device cuda` explicitly and must not reuse CPU artifact
   proof. To audit an existing run, use:

   ```sh
   scripts/run python ginkgo/scripts/verify_qwen3_monarch_control_plane_smoke.py \
     --expected-child-device cpu \
     glm52-serving-results/<run-id>/monarch-control-plane-manifest.json
   ```

   This verifier proves the Qwen3 CPU Monarch actor smoke artifact only. It is
   not CUDA readiness, GLM-5.2 readiness, Dynamo readiness, Responses readiness,
   or benchmark/eval completion evidence.
10. Run the GLM profile only after the sandbox, CUDA-kernel, dense smoke, and
   any required MoE checks pass.

## Contract

Every launch uses run-owned custom ports. Default ports `8000`, `8080`, and
`18080` are disallowed as active serving defaults. Every process must have an
owned process record before teardown signals are sent.

## Local Run Module

`ginkgo.local_run` is the module seam for bwrap-rootfs SGLang workloads. It owns
stage logging, materialization, preparation refresh, launch, effective-config
reload, probes, teardown, failure reporting, and evidence manifests. Workload
adapters, such as `Qwen3SglangWorkload`, own workload-specific declared-spec
validation, materialized-config validation, generated-text extraction, and
manifest metadata.

Shell entrypoints stay host-control adapters. They may resolve machine-local
paths and print wrapper stages for humans, but the Local Run module owns the
bringup, inference, teardown, and Contract Artifact flow.
