# Monarch Control Plane Schema

This document describes how Monarch should orchestrate Ginkgo inference runs. It
does not replace Insula. Insula chooses the rootfs, projects it with bwrap,
isolates the environment, builds argv, and validates the plan. Monarch orders
phases, supervises processes, reports structured status, handles cancellation,
and coordinates multiple processes.

No fallback. Fail fast, fail loud.

## Interface

`MonarchControlPlaneRun` is the parent-run record that every launcher must fill
in before starting work:

- `schema_version`: currently `1`.
- `run_id`: identifier owned by this run and copied into every child process
  record.
- `profile`: one Ginkgo profile, such as `serving-smoke-cpu`,
  `serving-smoke-dense`, or `glm52`.
- `declared_config_ref`: repo-local config path used by the workload adapter.
- `local_environment_ref`: machine-local resolver file supplied by the operator.
- `execution_mode`: `host-control adapter` or `monarch-actor-control`.
- `components`: ordered component names and their dependencies.
- `artifacts`: this run's manifest, process records, Insula plans, logs, and
  probe outputs.

The production path today is still the host-control adapter used by the human
scripts. A Monarch-backed path must write the same parent-run record before it
launches anything.

`ginkgo/control_plane.py` implements that parent-run record. It checks phase
order, dependency refs, the no-fallback failure policy, parent-run
component-ref resolution, and the adapter sequence: prepare, launch, probe,
teardown, status, and cancellation. `GinkgoControlPlaneActor` exposes those
operations as Monarch `@endpoint` methods on the same adapter surface. A local
proc-mesh test with a fake adapter covers it. This still does not launch Ginkgo
serving processes or bwrap commands.

`GinkgoHostControlAdapter` connects the actor and coordinator to the existing
Ginkgo host-control SGLang local-run path. It resolves `repo://` and
`local-env://` refs to real paths, requires an explicit SGLang local runner,
returns `openai_base_url`, `run_id`, port, generated text, and the
evidence-manifest state, and rejects unsupported component kinds such as Dynamo
until those kinds have a real runnable path. Current tests use a fake local
runner; they check the adapter's required fields and return values, not live
SGLang serving.

`create_qwen3_host_control_adapter` builds `GinkgoHostControlAdapter` for Qwen3
with the real `SglangLocalRun` and `Qwen3SglangWorkload` stack, and still allows
a test to inject a runtime. Tests show that Monarch coordinator orchestration
can drive the same host-control Qwen3 local-run code used by the human wrapper.
Tests still inject a fake runtime, so this is not live serving proof.

`Qwen3HostControlPlaneActor` is the first concrete actor entrypoint. It accepts
the parent run, repo root, and optional runtime injection, builds the Qwen3
host-control adapter inside the actor process, and exposes the inherited
prepare, launch, probe, teardown, status, and cancellation endpoints. Current
tests drive this actor with a fake runtime. A live actor run is a separate
required check.

`run_qwen3_monarch_control_plane_smoke.py` is the scriptable Qwen3 control-plane
check. It writes a parent `monarch-control-plane-manifest.json` with run refs,
component state, execution-domain metadata, an `execution_mode`, and an
`evidence_boundary` label. Fake-runtime test manifests use
`fake_runtime_contract`. Live child-process runs use
`live_qwen3_host_child_smoke` with `execution_mode: host-control adapter`. That
label is not actor proof: it shows the parent can hand off to the existing
host-control child runner and check that child's manifest. The
`--mode in-process-actor` route writes `execution_mode: monarch-actor-control`,
uses `live_qwen3_in_process_actor_smoke`, and checks that the machine-local
environment's repo, cache, temp, and rootfs paths are reachable from the current
rootfs namespace before it launches anything. Both successful and failed
attempts write the parent manifest. Failure manifests include the phase,
exception type, and message before the original exception is re-raised.

Host-child parent success requires the standalone Qwen3 SGLang verifier to pass
before the parent writes passed evidence. That verifier checks the child
manifest's required fields, pins the expected child device, and confirms the
serving port is closed after teardown. The CPU control-plane route defaults to
`expected_child_device: cpu`. CUDA variants must set an explicit `cuda`
expectation; they must not reuse CPU proof. `--verify-artifact` then audits the
parent manifest after it has been written.

The live Qwen3 check splits parent and child execution domains. The parent may
run in the Monarch rootfs so Monarch imports remain valid. The child process is
the existing host-control wrapper
`run_qwen3_sglang_inference_in_bwrap_rootfs.sh`, which owns machine-local
`ginkgo/local-env/*` host paths and then enters Insula for the serving process.
The parent passes the run-owned child ID, requires a concrete child Qwen
evidence manifest, runs the standalone child verifier including closed-port
proof, parses port, generated text, and status, and records those fields in the
parent manifest. A zero child exit without a valid passed child manifest and a
closed serving port is a failed parent run, not completion proof.

## Actor Shape

A Monarch control-plane implementation should expose a small Actor interface:

- `prepare(run)`: validate schema, local environment, model cache, and
  dependency records.
- `launch(component)`: launch exactly one component through its existing Ginkgo
  adapter.
- `probe(component)`: run readiness and inference probes for that component.
- `teardown(component)`: validate ProcessRecord ownership, signal only owned
  process groups, and verify closed ports.
- `status()`: return structured state, artifact paths, and failure context.

Every method should be an `endpoint`. The actor implementation may call existing
Ginkgo modules, but it must not construct bwrap argv directly. Any bwrap-rootfs
execution goes through Insula.

## Component Graph

The graph is strict:

1. `sglang_backend` launches from the written-out SGLang config.
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

## Required Checks

Before using Monarch as the default launcher, complete these checks:

1. Unit tests for `MonarchControlPlaneRun` schema validation and component-ref
   resolution.
2. Actor tests that use fake Ginkgo adapters and prove prepare, launch, probe,
   teardown, status, and cancellation ordering.
3. A CPU SGLang actor run that launches the existing `serving-smoke-cpu` profile
   through `--mode in-process-actor` and compares artifacts with the host-control
   adapter. A host-child run is useful proof of the child runner, but it does
   not satisfy this actor check.
4. A CUDA dense run using one GPU.
5. The GLM SGLang -> Dynamo -> Responses parent run after the CPU and dense
   paths are repeatable.

Passing host-control tests is not enough to claim Monarch control-plane
readiness. The actor path must write its own parent-run manifest and show it
uses the same Insula plan and ProcessRecord fields as the host-control path.
