# Evidence Boundary

Ginkgo evidence is profile-scoped.

## Readiness Evidence

- Sandbox-only evidence proves rootfs selection, host directory resolution, and
  bwrap projection.
- CUDA-kernel evidence proves PyTorch CUDA visibility and required optimized
  kernels for the declared device class.
- Qwen3 smoke evidence proves SGLang serving mechanics, model identity,
  request handling, artifacts, and teardown for the smoke model.
- Qwen3 MoE smoke evidence proves MoE serving mechanics when host budget allows.

Qwen3 smoke is not GLM-5.2 completion evidence.

## Completion Evidence

Only the GLM profile can produce GLM-5.2 completion evidence. A completion
run must prove real GLM SGLang inference, Dynamo readiness against that exact
SGLang component, Responses non-streaming and streaming inference, tool-call
verification, repeated clean teardown, and benchmark runs only against the
GLM-backed Responses URL from the completed parent run.

## Non-Evidence

The following do not count as GLM-5.2 completion evidence:

- fixture harness scores;
- fake Responses routing;
- `/v1/models` without inference probes;
- default-port probes;
- placeholder benchmark manifests;
- published scores from incompatible model cards or secondary articles;
- blocker artifacts from failed endpoint attempts.
