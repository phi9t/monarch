# Ginkgo

Ginkgo is the repo-root project for Monarch-local GLM-5.2 serving through a
governed bwrap rootfs. It owns the portable serving contract for SGLang, Dynamo,
the Responses adapter, sandbox projection, dependency environments, lightweight
Qwen3 smokes, and GLM-5.2 completion evidence.

The source design is
`.scratch/glm52-local-serving/bwrap-rootfs-serving-system-design.md`. Execution
plans generated from that design supersede earlier GLM-related execution plans,
but they do not supersede the design.

## Ownership

Tracked Ginkgo files own:

- portable declared configs;
- local environment templates;
- schema documentation;
- sandbox and serving profiles;
- dependency, optimized-kernel, and model-cache manifests;
- operator workflow and verification docs.

The Monarch control-plane design lives in
`ginkgo/schemas/monarch-control-plane.md`. It keeps Insula as the sole bwrap
owner while describing how Monarch Actors can orchestrate Ginkgo prepare,
launch, probe, teardown, and status phases.

Ginkgo does not own generated state. Materialized configs, process records,
logs, venvs, caches, model snapshots, and per-run artifacts stay in the
declared run, temp, cache, and results roots.

## First Principle

No fallback. Fail fast, fail loud.

Every launch value must come from a declared config or from a materialized
config derived from it. Default ports, ambient services, host Python packages,
alternate URLs, and fixture endpoints are not recovery paths.
