# GLM-5.2 GPU Workload

This is the canonical Ginkgo workload contract for local GLM-5.2 GPU
completion evidence. It supersedes older execution plans for the end-to-end
operator path, but it does not supersede
`.scratch/glm52-local-serving/bwrap-rootfs-serving-system-design.md`, which
remains the broader system design.

The workload launches and verifies this chain:

```text
Ginkgo parent run -> Insula bwrap rootfs -> SGLang GLM-5.2 GPU backend -> Dynamo -> Responses adapter -> verifiers/benchmarks
```

See `ginkgo/docs/evidence-boundary.md` for evidence scope and
`ginkgo/docs/verification-ladder.md` for the ordered validation ladder.

## Evidence Levels

- **blocker**: a failed preflight or launch boundary that explains why the run
  did not proceed. Blocker artifacts never count as completion evidence.
- **readiness**: schema, dependency, rootfs, or lower-profile evidence that a
  boundary is prepared. `/v1/models` without inference is readiness evidence at
  most.
- **completion**: live GLM-backed inference for the component, with request and
  response artifacts from the same parent run.
- **benchmark-ready**: completion evidence plus repeated clean teardown and a
  completed GLM-backed Responses URL from the same parent run.

## Schema Ownership

`ginkgo/configs/inference-glm52.yaml` is the portable parent workload config.
It contains no absolute host paths. Host rootfs, cache, temp, result, and run
paths resolve only through `ginkgo/local-env/*` and the Insula local environment
resolver. Materialization must produce concrete ports, URLs, argv, env, mount
plans, artifact paths, dependency records, probe records, and teardown records
before any process spawns.

Ports are run-owned and allocated from `19000-19200`. Ports `8000`, `8080`, and
`18080` are permanently rejected. A component cannot launch until its concrete
port appears in the materialized parent config.

## Insula Boundary

Insula is the only bwrap/rootfs authority for this workload. Human wrappers,
automation, parent runtime code, and legacy rootfs entrypoints must route
through the Insula schema-to-command path. Before launch, the runtime emits the
resolved bwrap, mount, env, cwd, GPU, and argv plan, validates it against the
materialized workload schema, and fails before spawning if any field drifts.

## Live Gates

SGLang is the first live gate. It uses model id `zai-org/GLM-5.2`, serves that
same model name externally, uses the prepared model snapshot recorded by the
model-cache preparation artifact, and runs on CUDA devices `0,1,2,3,4,5,6,7`
with tensor parallel size `8` and bf16. There is no fallback device route.
Completion requires `/v1/models` and real chat output; `/v1/models` alone is
not completion evidence.

Dynamo uses the `local_frontend_worker` topology. Its dependency record must
prove the declared rootfs-owned venv, `dynamo.frontend` and `dynamo.sglang`
imports, and the required help flags before launch. The materialized schema
records the actual frontend and worker argv. The contract is an integrated
Dynamo/SGLang executable contract, not a proxy to an already-running SGLang HTTP
endpoint.

The Responses adapter launches only after the upstream GLM-backed path is
proven. It binds to a run-owned port and verifies model listing, non-streaming
Responses inference, streaming Responses inference, and tool-call behavior.
Payloads, upstream URL, model name, timings, and logs are contract artifacts.

## Parent Manifest

The parent run writes a manifest that classifies contract artifacts:

- materialized config and local-env digest;
- Insula plans and validation records;
- dependency records;
- process records and launch commands;
- SGLang, Dynamo, and Responses probes with inference outputs;
- logs and traces;
- teardown summaries, port closure proof, orphan scan, and GPU process audit.

Benchmark execution must reject missing, incomplete, fake, or mismatched parent
manifests. A benchmark can claim GLM-backed evidence only when the manifest
identifies a `benchmark-ready` GLM parent run and a completed Responses base URL
from that same run.

## Repeatability and Teardown

The default parent workload runs three cycles. Each cycle receives a unique run
id and fresh concrete ports. Launch order is SGLang, Dynamo, Responses.
Teardown order is Responses, Dynamo, SGLang. On failure, the parent stops
further cycles, runs guarded best-effort teardown for owned process records,
and writes failed evidence.

Teardown refuses stale or tampered process records. It proves owned ports are
closed, no owned process group remains, and selected GPU devices have no owned
process residue before a cycle can pass.

## Operator Entry

`scripts/run_glm52_inference_runtime.sh` is the thin operator wrapper. Parsing,
validation, materialization, launch, probe, teardown, repeatability, and
manifest audit live in `scripts/glm52_inference_runtime.py`. Linux-local
commands still run through `scripts/run` unless they are explicitly in the
host-bootstrap/rootfs execution domain.
