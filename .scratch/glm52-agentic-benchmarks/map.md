# GLM52 Agentic Benchmarks Wayfinder

Status: resolved-for-spec

## Purpose

Build Ginkgo into a local evaluation platform for GLM-5.2 agentic benchmarks.
The first deployable version stays machine-local and file-backed, while the
interfaces leave room for a later Temporal/KubeRay control plane.

The platform must separate model inference, agent harnesses, task
environments, scoring, and durable orchestration. A benchmark result is valid
only when its Contract Artifacts prove the endpoint, manifest pins, task
environment, raw prediction or final state, grader, denominator, and
infrastructure-failure accounting.

## Fixed Decisions

- Ginkgo remains the project home for local GLM-5.2 serving and benchmark
  contracts.
- The v1 benchmark platform is machine-local. It must not introduce
  Kubernetes, KubeRay, Kueue, or cluster-native jobs.
- The first execution runners are `bwrap_rootfs`, `harbor_local_docker`,
  `scripts_run`, and narrowly trusted `host_subprocess`.
- GLM-5.2 benchmark traffic goes through the Responses adapter unless a suite
  is explicitly a lower-level serving verifier.
- Generation and grading are separate stages.
- Fixture, smoke, calibration, and reportable-score evidence are distinct
  artifact classes.
- GDPval-like evidence is labelled as a proxy until public reproduction
  conditions are pinned.

## Decisions So Far

- 01 benchmark scope and priority: resolved. First campaign is a representative
  v1-local pilot across existing suites plus one stateful-tool pilot and one
  GDPval proxy.
- 02 GDPval availability and proxy boundary: resolved. V1 permits only
  `gdpval-proxy-local` unless official public reproduction conditions are
  later pinned.
- 03 runner and task-environment contracts: resolved. Suite adapters call a
  small `TaskRunner` contract; current `glm52_bwrap_task_runner.py` is a
  compatibility source to wrap or migrate behind an Insula-compatible adapter.
- 04 endpoint roles and readiness: resolved. Campaign materialization resolves
  `component://responses_adapter/openai_base_url` from the parent inference
  config and validates concrete readiness artifacts.
- 05 scoring, denominators, and report format: resolved. The campaign report
  separates model, infrastructure, scorer, skipped, and unsupported
  denominators while preserving current verifier artifact compatibility.
- 06 cluster control-plane deferral: resolved. Temporal/KubeRay/Kubernetes stay
  future v2 and require a separate ADR.
- Implementation tickets 07 through 18 are created as the `ready-for-agent`
  queue. Work them blockers-first and keep each implementation slice in a fresh
  context.

## Remaining Fog

- Which large-suite runs require explicit user authorization because of cost,
  runtime, or GPU occupancy?
- Which stateful-tool suite, MCP Atlas or tau-bench, should be the first v1
  pilot after endpoint and sandbox contracts exist?

## Implementation Queue

- `issues/07-campaign-manifest-schema.md`
- `issues/08-file-backed-evalrun-state.md`
- `issues/09-endpoint-registry-readiness.md`
- `issues/10-taskrunner-contract-and-bwrap-adapter.md`
- `issues/11-artifact-normalization-and-report-taxonomy.md`
- `issues/12-static-eval-adapter-migration.md`
- `issues/13-code-eval-adapter-migration.md`
- `issues/14-harbor-agent-pilot.md`
- `issues/15-first-campaign-smoke.md`
- `issues/16-stateful-tool-pilot-selection.md`
- `issues/17-gdpval-proxy-local-pilot.md`
- `issues/18-future-cluster-control-plane-adr.md`

## Desired End State

An operator can launch a pinned GLM-5.2 benchmark campaign from a single
manifest, resume or inspect it after interruption, and receive a campaign
summary that separates model score from infrastructure failures. The same
manifest vocabulary should later map onto Temporal workflows and cluster
workers without changing suite semantics.
