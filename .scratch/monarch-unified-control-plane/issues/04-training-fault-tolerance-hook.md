# Decide the training-plane fault-tolerance policy hook

Type: grilling
Status: open
Blocked by: 01, 11
Parent: ../map.md

## Question

How should Monarch turn fail-fast supervision into fault-tolerant, resumable
training — and what is the first tracer bullet?

Evidence of what exists vs what is missing:

- Failure detection is landed: `MeshMonitor` → `MeshFailure` naming the failed
  rank (`hyperactor_mesh/src/monitor.rs:9`), surfaced to Python as
  `unhandled_fault_hook(MeshFailure)` whose default is `sys.exit(1)`
  (`python/monarch/_src/actor/supervision.py:25,54`).
- The declarative job model is landed: `JobTrait.state()` polling hook
  (`python/monarch/_src/job/job.py:369,556`), `apply()`/`kill()`, pickle state
  cache. Docstring frames elasticity as "poll the state for changes."
- What is MISSING: no checkpoint/restart anywhere (grep `checkpoint|resume` in
  `_src/job`/`_src/spmd` is empty), no elastic reconfiguration (no mesh
  shrink/regrow/re-shard), `torchrun --max-restarts` is parsed but never acted
  on (`spmd.py:48`). Supervision is fail-fast, not fault-tolerant.
- Transport for checkpoints exists but is unused for it: RDMABuffer
  (`python/monarch/_src/rdma/rdma.py:440`), tensor-engine fetch
  (`mesh_controller.py:302`).

Decide:

- The policy seam: replace the default `unhandled_fault_hook` with a
  checkpoint-then-restart / shrink-regrow policy, driven off `JobTrait.state()`.
- Checkpoint transport: RDMA + tensor-engine fetch vs filesystem, and who owns
  checkpoint cadence (trainer vs control plane).
- The first tracer bullet: kill one rank in a local proc-mesh training loop and
  prove the control plane detects, checkpoints, and resumes.
- Whether Monarch owns the training step/optimizer loop or only the mesh
  lifecycle around a torch-elastic loop.

This is the biggest training-plane gap and gates the checkpoint/elasticity fog.
