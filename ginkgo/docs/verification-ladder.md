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
5. **CUDA-kernel:** PyTorch CUDA and declared optimized kernels run real
   capability probes on the declared device class.
6. **Dense serving smoke:** Qwen3 dense SGLang serving proves model identity,
   `/generate`, `/v1/completions`, `/v1/chat/completions`, logs, artifacts,
   process ownership, port closure, and teardown.
7. **MoE serving smoke:** Qwen3 MoE SGLang serving proves MoE and larger-kernel
   paths when host budget allows.
8. **GLM SGLang live:** GLM-5.2 SGLang starts and passes real inference probes.
9. **Dynamo live:** Dynamo starts against the materialized GLM SGLang component
   and passes readiness probes.
10. **Responses live:** the adapter starts against the materialized Dynamo
    component and passes model, non-streaming, streaming, and tool-call probes.
11. **Repeatability:** at least three launch/probe/teardown cycles pass from
    the same declared config.
12. **Benchmark readiness:** benchmark harnesses run only against a GLM-backed
    Responses URL from a completed parent run.

Passing a lower gate does not imply a higher gate. In particular, Qwen3 smoke
success does not imply GLM-5.2 completion.
