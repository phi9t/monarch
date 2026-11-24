# Future Cluster Control Plane ADR

Type: task
Status: ready-for-agent
Blocked by: 15

## Objective

Record the deferred v2 control-plane architecture as an ADR without authorizing
cluster-native implementation in v1.

## Context

The resolved v1 platform is machine-local and file-backed. The future
architecture may map the same manifest, EvalRun, Trial, Grade, runner, and
artifact concepts onto Temporal, KubeRay, native Kubernetes Jobs, and object
storage, but only after v1 semantics are stable.

## Requirements

- Add an ADR under `docs/adr/`.
- State explicitly that v1 remains local and this ADR does not authorize
  Kubernetes, KubeRay, Kueue, Temporal, cloud workers, or object-storage
  metadata services in v1.
- Map v1 concepts to future infrastructure:
  - EvalRun to Temporal workflow;
  - Shard to Temporal child workflow or activity group;
  - Trial to Temporal activity submitted to KubeRay or native Kubernetes Job;
  - Grade to separate activity over immutable generation artifacts;
  - Artifact to S3/MinIO object plus metadata row;
  - TaskRunner to local, KubeRay, Kubernetes Job, KVM, Modal, Daytona, or AWS
    adapter.
- Explain why Temporal owns durability and Ray owns placement/fan-out only.
- Preserve direct vLLM or SGLang serving services outside Ray Serve unless a
  later ADR proves that Ray Serve belongs in the inference data path.
- Define promotion gates from v1 to v2:
  - at least one representative v1 campaign can run and resume locally;
  - campaign artifacts separate all required denominators;
  - runner adapters pass the same contract tests locally;
  - security and operational cost boundaries are accepted.

## Files

- Create: `docs/adr/NNNN-glm52-agentic-benchmark-cluster-control-plane.md`
- Modify: `.scratch/glm52-agentic-benchmarks/spec.md`
- Modify: `.scratch/glm52-agentic-benchmarks/map.md`

## Exclusions

- Do not implement any cluster runner.
- Do not add Kubernetes manifests, Ray configs, Temporal workflows, or object
  storage clients.
- Do not change the v1 local campaign contract.

## Verification

```sh
rg -n "Temporal|KubeRay|Kubernetes|v1 remains|does not authorize" docs/adr .scratch/glm52-agentic-benchmarks
```

## Done When

- The ADR records the future mapping and the v1 boundary.
- The spec points to the ADR as deferred architecture only.
- No v1 implementation ticket depends on cluster infrastructure.
