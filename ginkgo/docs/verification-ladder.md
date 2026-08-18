# Verification Ladder

The Ginkgo ladder separates contract readiness from GLM completion evidence.

1. **Schema:** declared YAML rejects unknown fields, fallback flags, default
   ports, shell command strings, and concrete host paths in portable configs.
2. **Materialization:** materialized configs derive every port, URL, argv, env,
   mount, and artifact path from schema inputs.
3. **Rootfs plan:** `enter_rootfs.sh` emits a resolved plan that matches the
   materialized sandbox config.
4. **Dependency environment:** rootfs-projected `uv` venvs contain the declared
   packages, imports, tools, and help surfaces.
5. **CPU serving smoke:** Qwen3 CPU SGLang serving proves the bwrap-rootfs
   serving path, model identity, real chat inference, logs, artifacts, process
   ownership, port closure, teardown, and absence of CUDA env/GPU projection.
6. **CUDA-kernel:** PyTorch CUDA and declared optimized kernels run real
   capability probes on the declared device class.
7. **Dense serving smoke:** Qwen3 dense SGLang serving proves model identity,
   `/generate`, `/v1/completions`, `/v1/chat/completions`, logs, artifacts,
   process ownership, port closure, and teardown.
   If the declared CUDA device is occupied, the operator wait is no-fallback:
   it records `gpu_wait` and `blocked_gpus` blocker evidence and stops instead
   of selecting a different GPU or switching device class.
8. **MoE serving smoke:** Qwen3 MoE SGLang serving proves MoE and larger-kernel
   paths when host budget allows.
9. **GLM SGLang live:** GLM-5.2 SGLang starts and passes real inference probes.
10. **Dynamo live:** Dynamo starts against the materialized GLM SGLang component
   and passes readiness probes.
11. **Responses live:** the adapter starts against the materialized Dynamo
    component and passes model, non-streaming, streaming, and tool-call probes.
12. **Repeatability:** at least three launch/probe/teardown cycles pass from
    the same declared config.
13. **Benchmark readiness:** benchmark harnesses run only against a GLM-backed
    Responses URL from a completed parent run.

Passing a lower gate does not imply a higher gate. In particular, Qwen3 smoke
success does not imply GLM-5.2 completion.
