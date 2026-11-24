# Decide Cluster Control-Plane Deferral

Type: task
Status: resolved
Blocked by: 03 04 05

## Question

What parts of the Temporal/KubeRay/Kubernetes architecture should be recorded
now, and what must be deferred until after the machine-local v1 platform is
stable?

## Context

The recommended evaluation architecture uses Temporal as the durable outer
control plane and Ray or native Kubernetes Jobs only for placement and fan-out.
That is a good long-term shape, but prior Monarch GLM52 guidance explicitly
keeps the first benchmark platform local and file-backed.

## Decision Needed

Record a future-control-plane ADR that:

- keeps v1 machine-local;
- maps v1 EvalRun, Shard, Trial, Grade, and Artifact concepts to future
  Temporal workflows;
- maps runner adapters to KubeRay, Kubernetes Jobs, KVM workers, Modal,
  Daytona, or AWS where appropriate;
- states when the project is allowed to introduce cluster-native execution.

## Resolution

V1 remains machine-local, file-backed, and rooted in the current Ginkgo serving
and benchmark verifier path. This decision does not authorize Temporal,
KubeRay, Kubernetes Jobs, Kueue, cloud workers, or object-storage metadata
services in v1.

Record the future cluster architecture as a deferred ADR after the v1 manifest,
runner, endpoint, artifact, and scoring contracts are stable enough to map
without semantic changes.

The future mapping is:

```text
EvalRun -> Temporal workflow
Shard -> Temporal child workflow or activity group
Trial -> Temporal activity submitted to KubeRay or a native Kubernetes Job
Grade -> separate Temporal activity over immutable generation artifacts
Artifact -> S3/MinIO object plus metadata row
TaskRunner -> local, KubeRay, Kubernetes Job, KVM, Modal, Daytona, or AWS adapter
```

Temporal owns durability, retry policy, timeout, cancellation, and
reconciliation. Ray owns placement and fan-out for nonprivileged workers only.
Native Kubernetes Jobs own privileged, nested-container, KVM, and exact-GPU
tasks. Direct vLLM or SGLang serving services remain outside Ray Serve unless a
later ADR proves that the inference data path needs Ray Serve.

Cluster execution may be introduced only after:

- v1 can run and resume at least one representative campaign locally;
- campaign artifacts separate model, infrastructure, scorer, skipped, and
  unsupported denominators;
- runner adapters pass the same contract tests locally;
- a reviewed ADR accepts the operational cost and security boundary.

## Acceptance Criteria

- The ADR does not authorize Kubernetes/KubeRay implementation in v1.
- The ADR explains why Temporal owns durability and Ray owns placement only.
- The ADR preserves direct vLLM/SGLang serving services outside Ray Serve unless
  a later need justifies changing the inference data path.
- The v1 manifest and artifact vocabulary is sufficient input for v2.
