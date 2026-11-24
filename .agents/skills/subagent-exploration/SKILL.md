---
name: subagent-exploration
description: Use for broad Monarch codebase exploration, distributed-training design, or multi-area implementation planning that can split across independent subagents.
---

# Subagent Exploration

Use this skill only when the active agent runtime and user instructions permit
delegation. If delegation is unavailable or disallowed, apply the same expert
split locally as a checklist.

## Operating Model

Keep the main thread responsible for synthesis, tradeoffs, sequencing, and final
decisions. Delegate only bounded work that can proceed independently:

- read-heavy code mapping with file-grounded findings;
- design alternatives for one subsystem;
- verification of a specific runtime path or test surface;
- implementation slices with disjoint write scopes.

Before delegating, identify the immediate blocker that the main thread should
handle locally. Keep that blocker local unless the main thread has no useful
local work to do.

Each subagent prompt must include:

- exact repo path and subsystem scope;
- whether the task is read-only or may edit files;
- expected output shape, including file references or changed paths;
- boundaries: what to ignore, and what files the subagent may write if editing.

## Expert Lanes

For distributed-training design-space work, use these lanes when useful:

- **Mini Runtime Expert:** `monarch_mini/`, actor tree semantics, gateway
  routing, monitors, transports, shared memory, heartbeat delegation, and
  large-message paths.
- **Production Actor Expert:** `hyperactor/`, `hyperactor_mesh/`, and
  `python/monarch/_src/actor/`, including `HostMesh`, `ProcMesh`, `ActorMesh`,
  endpoint dispatch, supervision, and process lifecycle.
- **Tensor/Data Plane Expert:** `python/monarch/_src/tensor_engine/`,
  `python/monarch/tensor_engine/`, `python/monarch/_src/actor/tensor_engine_shim.py`,
  `monarch_rdma/`, `rdmaxcel-sys/`, and distributed tensor examples under
  `docs/source/examples/`.
- **Training-Orchestration Expert:** `examples/`, `python/examples/`,
  `docs/source/examples/`, `python/tests/job_train.py`,
  `python/tests/test_spmd.py`, `python/tests/test_device_mesh.py`, and workflow
  docs under `docs/source/`.
- **Verification Expert:** local run scripts, `python/tests/`, `docs/adr/`,
  `docs/superpowers/`, bwrap/rootfs flow, and failure artifacts. For execution
  details, use `.agents/skills/run-monarch-single-machine/SKILL.md`.

## Implementation Rules

Before any editing delegation, record the current dirty paths and assign an
explicit allowed write set. Tell each subagent that other agents may be editing
in parallel, that it must stay within its write set, and that it must not revert
unrelated work. If a needed edit falls outside the assigned write set, the
subagent should return to the main thread instead of editing it.

When a subagent returns, the main thread reviews the result, integrates any
patches, resolves overlaps, and runs the relevant verification. Completion
requires a synthesized answer or integrated patch set that names the evidence
used, changed paths, verification run, and remaining risks.
