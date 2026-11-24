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
7. Run three dense smoke launch/probe/teardown cycles before treating the
   sandbox as repeatable.
8. Run the MoE smoke only when the host satisfies its explicit disk, GPU, and
   timeout budget.
9. Run the GLM profile only after the sandbox, CUDA-kernel, dense smoke, and
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
