# Monarch Control Plane Schema

This document defines the target seam for using Monarch as the high-level
control plane for Ginkgo inference runs. It does not replace Insula. Insula owns
rootfs selection, bwrap projection, environment isolation, argv generation, and
plan validation. Monarch owns orchestration: phase ordering, supervision,
structured status, cancellation, and multi-process coordination.

No fallback. Fail fast, fail loud.

## Interface

`MonarchControlPlaneRun` is the portable parent run contract:

- `schema_version`: currently `1`.
- `run_id`: run-owned identifier shared by every child process record.
- `profile`: one Ginkgo profile, such as `serving-smoke-cpu`, `serving-smoke-dense`, or `glm52`.
- `declared_config_ref`: repo-local config ref consumed by the workload adapter.
- `local_environment_ref`: machine-local resolver file path supplied by the operator.
- `execution_mode`: `host-control adapter` or `monarch-actor-control`.
- `components`: ordered component names and dependencies.
- `artifacts`: run-owned manifest, process records, Insula plans, logs, and probe outputs.

The initial production path remains the host-control adapter used by the human
scripts. A Monarch-backed path must materialize the same contract before it
launches anything.

`ginkgo/control_plane.py` is the current schema-backed implementation of this
parent-run contract. It validates ordering, dependency refs, no-fallback failure
policy, parent-run component ref resolution, and adapter-backed prepare, launch,
probe, teardown, status, and cancellation ordering. `GinkgoControlPlaneActor`
exposes those operations as real Monarch `@endpoint` methods over the same
adapter seam and is covered by a local proc-mesh smoke with a fake adapter. This
still does not launch Ginkgo serving processes or bwrap commands.

`GinkgoHostControlAdapter` is the first bridge from the actor/coordinator seam
to the existing Ginkgo host-control SGLang local-run path. It resolves
`repo://` and `local-env://` refs into concrete paths, requires an explicit
SGLang local runner, returns `openai_base_url`, `run_id`, port, generated text,
and evidence manifest state, and rejects unsupported component kinds such as
Dynamo until their executable contracts exist. Current tests use a fake local
runner; they prove the adapter contract but are not live SGLang evidence.

`create_qwen3_host_control_adapter` is the concrete Qwen3 factory for that
bridge. It builds `GinkgoHostControlAdapter` with the real `SglangLocalRun` and
`Qwen3SglangWorkload` stack while allowing runtime injection for tests. The
covered path proves Monarch coordinator orchestration can drive the same
host-control Qwen3 local-run code used by the human wrapper. It still uses a
fake runtime in tests, so it is not live serving evidence.

`Qwen3HostControlPlaneActor` is the first concrete actor entrypoint. It accepts
the parent run, repo root, and optional runtime injection, constructs the Qwen3
host-control adapter inside the actor process, and exposes the same inherited
prepare, launch, probe, teardown, status, and cancellation endpoints. Current
coverage exercises this actor with a fake runtime; a live actor smoke remains a
separate verification gate.

`run_qwen3_monarch_control_plane_smoke.py` is the scriptable Qwen3 control-plane
smoke. It writes a parent `monarch-control-plane-manifest.json` with run refs,
component state, execution-domain metadata, an `execution_mode`, and an
`evidence_boundary` label. Fake-runtime test manifests use
`fake_runtime_contract`; live child-process runs use
`live_qwen3_host_child_smoke` with `execution_mode: host-control adapter`. That
boundary is deliberately not actor evidence: it proves the parent contract can
delegate to the existing host-control child runner and validate its child
manifest. The explicit `--mode in-process-actor` route writes
`execution_mode: monarch-actor-control`, uses
`live_qwen3_in_process_actor_smoke`, and preflights that the machine-local
environment's repo, cache, temp, and rootfs paths are reachable from the current
rootfs namespace before it launches anything. Both successful and failed
attempts write the parent manifest, and failure manifests include the phase,
exception type, and message before the original exception is re-raised.
Host-child parent success is gated by the standalone Qwen3 SGLang verifier
before the parent writes passed evidence. That gate validates the child
manifest contract, pins the expected child device, and probes that the serving
port is closed after teardown. The CPU control-plane route defaults to
`expected_child_device: cpu`; CUDA variants must opt in with an explicit `cuda`
expectation rather than reusing CPU proof. `--verify-artifact` then performs an
additional parent-manifest audit after the parent artifact has been written.

The live Qwen3 smoke uses an explicit parent/child execution-domain split. The
parent may run in the Monarch rootfs-controlled domain so Monarch imports remain
valid. The child process is the existing host-control
`run_qwen3_sglang_inference_in_bwrap_rootfs.sh` wrapper, which owns
machine-local `ginkgo/local-env/*` host paths and then enters Insula for the
serving process. The parent passes the run-owned child ID, requires a concrete
child Qwen evidence manifest, validates that manifest with the standalone child
verifier including closed-port proof, parses its port, generated text, and
status, and then records those fields in the parent manifest. A zero child exit
without a valid passed child manifest and closed serving port is a failed parent
run, not completion evidence.

## Actor Shape

A Monarch control-plane implementation should expose a small Actor interface:

- `prepare(run)`: validate schema, local environment, model cache, and dependency records.
- `launch(component)`: launch exactly one component through its existing Ginkgo adapter.
- `probe(component)`: run readiness and inference probes for that component.
- `teardown(component)`: validate ProcessRecord ownership, signal only owned process groups, and verify closed ports.
- `status()`: return structured state, artifact paths, and failure context.

Every method should be an `endpoint`. The actor implementation may call existing
Ginkgo modules, but it must not construct bwrap argv directly. Any bwrap-rootfs
execution crosses Insula.

## Component Graph

The graph is strict:

1. `sglang_backend` launches from the materialized SGLang config.
2. `dynamo_frontend` starts only after SGLang model and inference probes pass.
3. `responses_adapter` starts only after Dynamo probes pass.
4. Benchmark and eval runners start only against the completed Responses URL
   from the same parent run.

Component refs such as `component://sglang_backend/openai_base_url` must be
resolved from the parent run state, not from operator-provided URLs.

## Failure Semantics

- Missing config, missing local environment, schema drift, plan drift, occupied
  ports, missing dependency records, and failed probes are terminal for the
  current run.
- Teardown is best-effort only after a ProcessRecord exists. It must still fail
  loudly when ownership cannot be proven.
- A failed child component prevents dependent components from starting.
- Status uses `phase` for the terminal state, such as `failed` or `cancelled`,
  and `failed_phase` for the exact lifecycle phase that raised, such as
  `probing:dynamo_frontend` or `launch:sglang_backend`.
- Cleanup failures never replace the primary failure. They are reported under
  `teardown_errors` with component names and messages so operators see both the
  root cause and any cleanup damage.
- The parent manifest's `failure` block records the exact failed phase as
  `phase`, the terminal actor/coordinator state as `terminal_phase`, the
  `failed_component`, cleanup errors as `teardown_errors`, and artifact paths.

## Verification Path

Before using Monarch as the default launcher, implement these gates:

1. Unit tests for `MonarchControlPlaneRun` schema validation and component ref resolution.
2. Actor tests that use fake Ginkgo adapters and prove prepare, launch, probe,
   teardown, status, and cancellation ordering.
3. A CPU SGLang actor smoke that launches the existing `serving-smoke-cpu`
   route through `--mode in-process-actor` and compares artifacts with the
   host-control adapter. A host-child smoke is useful evidence for the child
   runner, but it does not satisfy this actor gate.
4. A CUDA dense smoke using one GPU.
5. The GLM SGLang -> Dynamo -> Responses parent run after the CPU and dense
   paths are repeatable.

Passing host-control tests is not enough to claim Monarch control-plane
readiness. The actor path must produce its own parent run manifest and prove it
uses the same materialized Insula plan and ProcessRecord contracts.
