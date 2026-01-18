# Technical Deep Dive: Monarch Architecture

## High-Level Architecture
Monarch layers a high-performance Rust actor runtime under a Python-first API for distributed PyTorch. The stack is organized into three planes:

- **Control plane**: process and actor lifecycle (spawn, supervision, faults) powered by Hyperactor.
- **Data plane**: message passing for actor endpoints plus optional tensor/RDMA transfers.
- **Integration plane**: PyO3 bindings that expose Rust primitives into `python/monarch/`.

At a glance:

```
python/monarch (user API)
  -> monarch_extension / monarch_hyperactor (PyO3 bindings)
    -> hyperactor + hyperactor_mesh (Rust runtime)
    -> monarch_rdma + torch-sys* (tensor engine + RDMA)
```

## Component Deep Dive

### 1) Hyperactor Runtime (Rust)
- **Location**: `hyperactor/`, `hyperactor_mesh/`, `hyperactor_macros/`.
- **Dependencies (Rust crates)**: `hyperactor` <- `hyperactor_macros`, `hyperactor_config`, `hyperactor_telemetry`; consumed by `hyperactor_mesh`, `monarch_hyperactor`, `monarch_extension`.
- **Role**: Implements the actor model, mailboxes, routing, and supervision trees. Actors are addressed by typed references and communicate via message endpoints.
- **Why it matters**: The runtime enforces isolation, backpressure, and fault handling, enabling resilient multi-process execution.

### 2) Meshes and Supervision
- **Location**: `hyperactor_mesh/`, `python/monarch/actor/`.
- **Dependencies (Rust crates)**: `hyperactor_mesh` uses `hyperactor`, `hyperactor_macros`, `hyperactor_mesh_macros`, `hyperactor_config`, `hyperactor_telemetry`.
- **Key types**: `HostMesh` (local host), `ProcMesh` (process collection), `ActorMesh` (actors across processes).
- **Flow**: `this_host()` -> `spawn_procs()` -> `spawn()` -> `ActorMesh` with broadcast endpoints.
- **Supervision**: Failures propagate up the tree so callers can decide whether to restart or fail-fast.

### 3) Control Plane Design (Actors + Hyperactor)
- **Scope**: Process allocation, actor lifecycle, supervision, and routing decisions.
- **Core responsibilities**:
  - **Spawn orchestration**: `HostMesh` allocates processes and boots runtime agents; `ProcMesh` materializes actors on each process.
 - **Lifecycle tracking**: Actor instances register endpoints and expose typed handles that map onto mailbox routes.
 - **Supervision tree**: Parent actors/processes observe failures and decide to restart, escalate, or terminate.
 - **Fault boundaries**: Isolates crashes to individual actors or processes rather than the whole job.
- **Control path outline**:
  1. `this_host()` builds the host mesh and runtime context.
  2. `spawn_procs()` allocates worker processes and installs mesh supervision.
  3. `spawn()` creates actors, binds endpoints, and returns an `ActorMesh` handle.
  4. Endpoint calls are routed through mailboxes with backpressure and retry semantics.

### 4) Python API and Bindings
- **Location**: `python/monarch/`, `monarch_extension/`, `monarch_hyperactor/`.
- **Dependencies (Rust crates)**: `monarch_extension` wraps `monarch_hyperactor`, `hyperactor_mesh`, `hyperactor_mesh_macros`, `monarch_messages`, `monarch_types`, and optionally tensor/RDMA crates.
- **Bindings**: PyO3 bridges Rust actor handles, message types, and runtime control into Python.
- **Public API**: `Actor`, `@endpoint`, `this_host()`, `ProcMesh`, `ActorMesh` are the top-level building blocks.

### 5) Tensor Engine and RDMA
- **Location**: `monarch_rdma/`, `monarch_tensor_worker/`, `torch-sys2/`, `torch-sys-cuda/`.
- **Dependencies (Rust crates)**: `monarch_tensor_worker` -> `monarch_hyperactor`, `monarch_messages`, `monarch_types`, `torch-sys2`, `torch-sys-cuda` (optional), `nccl-sys` (optional); `monarch_rdma` -> `rdmaxcel-sys`.
- **Role**: Optional accelerator path for distributed tensors and point-to-point transfers.
- **Behavior**: When `USE_TENSOR_ENGINE=1` (default), Monarch can register CPU/GPU buffers for one-sided RDMA and move shards efficiently across processes. With `USE_TENSOR_ENGINE=0`, the system runs actors only.

### 6) Tooling and Workflow
- **Location**: `python/monarch/tools/`, `monarch.tools.cli` entrypoint.
- **Purpose**: Workspace configuration, code sync, cluster job orchestration, and testing utilities.

## Core Code Walkthrough (Pointers + Detail)
- **Hyperactor runtime (`hyperactor/src/`)**: Entry `hyperactor/src/lib.rs` wires actor traits, refs, and message envelopes. Mailbox design in `hyperactor/src/mailbox/` (client/server, multiplexing, delivery). Routing/backpressure in `hyperactor/src/router/` and `hyperactor/src/backpressure/`. Supervision logic in `hyperactor/src/supervision/` governs restart/abort. Channel implementations live under `hyperactor/src/channel/` (TCP/unix/loopback), with endpoint dispatch in `hyperactor/src/handler/`.
- **Mesh orchestration (`hyperactor_mesh/src/`)**: `hyperactor_mesh/src/lib.rs` exposes `HostMesh`, `ProcMesh`, `ActorMesh`. Process allocation path in `hyperactor_mesh/src/process_allocator/` (bootstrap, cleanup, remote alloc). Membership and routing state in `hyperactor_mesh/src/mesh/` and `hyperactor_mesh/src/router/`. Tests/bootstraps show end-to-end flows in `hyperactor_mesh/test/`.
- **Macros**: Actor proc-macros in `hyperactor_macros/src/lib.rs` generate handlers, typed refs, and endpoint glue. Mesh macros in `hyperactor_mesh_macros/src/lib.rs` derive typed RPC surfaces and mesh-specific routing helpers.
- **Config & telemetry**: Runtime/config schemas in `hyperactor_config/src/lib.rs` (CLI/env parsing, cfg structs). Tracing/metrics wiring in `hyperactor_telemetry/src/lib.rs` (tracing layers, otel exporters, span fields).
- **Monarch bridge (`monarch_hyperactor/src/`)**: `monarch_hyperactor/src/lib.rs` adapts Hyperactor types to Monarch conventions, exposes Python-safe entrypoints, and provides bootstrap helpers for process start/test harnesses.
- **Python bindings (`monarch_extension/src/lib.rs`)**: PyO3 layer exporting Rust handles into Python, toggling optional tensor/RDMA features. Python API surface in `python/monarch/` with internal impls in `python/monarch/_src/` (actor runtime glue, controller, simulator, worker).
- **Tensor engine/RDMA**: Tensor worker orchestration in `monarch_tensor_worker/src/lib.rs` (sharded tensor actors, stream mgmt). RDMA transport in `monarch_rdma/src/lib.rs` with lower-level bindings in `rdmaxcel-sys/` and optional CUDA/NCCL shims via `torch-sys-cuda/`, `nccl-sys/`. Torch C FFI in `torch-sys2/` shared by tensor engine and bindings.
- **Examples**: Deployment and API usage in `examples/` (Kubernetes flows, Slurm Torchtitan notebook `examples/slurm_titan.ipynb`).

## Core Rust Source Files (Roles)
- `hyperactor/src/lib.rs`: Runtime entry; defines actor traits, refs, envelopes, and wires mailboxes/routing/supervision.
- `hyperactor/src/mailbox/`: Mailbox server/client, multiplexing, delivery, and backpressure mechanics.
- `hyperactor/src/router/` & `hyperactor/src/backpressure/`: Routing decisions and flow-control policies for endpoint calls.
- `hyperactor/src/supervision/`: Failure detection and restart/abort strategies (supervision tree).
- `hyperactor/src/channel/` & `hyperactor/src/handler/`: Transport implementations (TCP/unix/loopback) and endpoint dispatch glue.
- `hyperactor_mesh/src/lib.rs`: Public mesh types (`HostMesh`, `ProcMesh`, `ActorMesh`) and spawn APIs over the runtime.
- `hyperactor_mesh/src/process_allocator/`: Process bootstrap, remote allocation, and cleanup for multi-host spawning.
- `hyperactor_mesh/src/mesh/` & `hyperactor_mesh/src/router/`: Mesh membership/state and cross-process routing of actor refs.
- `hyperactor_macros/src/lib.rs`: Proc-macros generating actor handlers, typed refs, endpoint plumbing.
- `hyperactor_mesh_macros/src/lib.rs`: Proc-macros generating typed mesh RPC surfaces and routing helpers.
- `hyperactor_config/src/lib.rs`: Config schemas and CLI/env parsing for runtime/mesh behavior.
- `hyperactor_telemetry/src/lib.rs`: Tracing/metrics setup (tracing layers, otel exporters, span fields).
- `monarch_hyperactor/src/lib.rs`: Monarch-specific bridge exposing Hyperactor constructs for Python bindings/bootstraps.
- `monarch_extension/src/lib.rs`: PyO3 entry that exports Rust handles to Python; gates tensor/RDMA features.
- `monarch_tensor_worker/src/lib.rs`: Tensor engine actors, sharded tensor orchestration, stream management (optional).
- `monarch_rdma/src/lib.rs`: RDMA transport and resource management for one-sided tensor moves (optional).
- `torch-sys2/src/lib.rs` & `torch-sys-cuda/src/lib.rs`: Torch C/CUDA FFI used by tensor engine and bindings.
- `monarch_messages/src/lib.rs` & `monarch_types/src/lib.rs`: Shared message/type definitions consumed across runtime, tensor engine, and bindings.

## Hyperactor Components (Major Pieces + Dependencies)
- **hyperactor**: Core runtime (actors, mailboxes, routing, supervision, backpressure). Depends on `hyperactor_config` (config flags), `hyperactor_telemetry` (tracing/metrics), `hyperactor_macros` (derive helpers), plus shared crates (`typeuri`, `wirevalue`, `ndslice`).
- **hyperactor_mesh**: Distributed mesh and process allocator; handles remote spawn, membership, routing across hosts. Uses `hyperactor`, `hyperactor_macros`, `hyperactor_mesh_macros`, `hyperactor_config`, `hyperactor_telemetry`, `serde_multipart`, `preempt_rwlock`.
- **hyperactor_macros**: Proc-macros for actor definitions, handlers, typed references.
- **hyperactor_mesh_macros**: Proc-macros for mesh RPC plumbing and typed endpoints.
- **hyperactor_config**: Config schemas/parsing for runtime flags and mesh settings.
- **hyperactor_telemetry**: Tracing/logging integration for runtime and mesh layers.
- **monarch_hyperactor**: Bridge crate adapting Hyperactor to Monarch conventions; re-exported to Python. Depends on `hyperactor_mesh`, `hyperactor`, `hyperactor_config`, `hyperactor_telemetry`, `ndslice`, `typeuri`, `wirevalue`.
- **monarch_extension**: PyO3 surface that wraps `monarch_hyperactor` + optional tensor/RDMA crates for Python users.

## Rust Crate Dependency Diagram (Simplified)
Major Rust crates and how they stack. Optional components are marked `(optional)`.

```
monarch_extension (PyO3)
  -> monarch_hyperactor
     -> hyperactor_mesh
        -> hyperactor
           -> hyperactor_config
           -> hyperactor_telemetry
           -> hyperactor_macros
     -> monarch_types
     -> monarch_messages
  -> hyperactor_mesh_macros
  -> monarch_tensor_worker (tensor engine)
     -> torch-sys2 -> torch-sys-cuda (optional)
     -> nccl-sys (optional)
  -> monarch_rdma_extension (optional)
     -> monarch_rdma -> rdmaxcel-sys
  -> monarch_cpp_static_libs (optional)

Shared utilities: typeuri, wirevalue, ndslice
```

## Execution Flow (End-to-End)
1. **Allocate processes**: `HostMesh.spawn_procs()` creates worker processes.
2. **Create actors**: `ProcMesh.spawn()` instantiates actor classes on each process.
3. **Call endpoints**: `ActorMesh.method.call()` dispatches requests and returns futures.
4. **Transfer tensors** (optional): Tensor engine routes sharded tensor transfers, using RDMA when available.

## Torchtitan Integration Example (Training Loop)
The example below sketches how Monarch components map onto a Torchtitan training job. It uses meshes for lifecycle, actors for orchestration, and the tensor engine for sharded tensors.

```python
from monarch.actor import Actor, endpoint, this_host
from torchtitan.train import Trainer
from torchtitan.config import ConfigManager, JobConfig

class TitanTrainer(Actor):
    def __init__(self, cfg: JobConfig):
        self.trainer = Trainer(cfg)

    @endpoint
    def train_step(self, step: int):
        # Runs on each process; tensors may be sharded if tensor engine is enabled.
        return self.trainer.train_step(step)

# 1) Control plane: allocate processes
procs = this_host().spawn_procs({"gpus": 8})

# 2) Integration plane: load Torchtitan config
cfg = ConfigManager().load("torchtitan/models/llama3/train_configs/debug_model.toml")

# 3) Data plane: spawn trainers and run steps
trainers = procs.spawn("titan_trainers", TitanTrainer, cfg)
trainers.train_step.call(step=0).get()
```

**How each component participates**:
- **Actor model**: `TitanTrainer` isolates training state per process and exposes a typed endpoint.
- **Meshes**: `ProcMesh` distributes trainers across GPUs, enabling broadcast RPCs.
- **PyTorch integration**: Torchtitan runs inside each actor process, using standard PyTorch modules.
- **Tensor engine/RDMA**: If enabled, sharded tensors can move across processes with low overhead.

For a concrete walkthrough, see `examples/slurm_titan.ipynb` and adapt it to your cluster runtime.

## Training Job Lifecycle (Control/Data Plane Walkthrough)
Using the `TitanTrainer` example above:
- **Control plane: process bootstrap** — `this_host().spawn_procs({"gpus": 8})` asks `hyperactor_mesh` to allocate 8 worker processes. The process allocator bootstraps each worker (via `hyperactor_mesh` boot bins), installs supervision hooks, and registers them in the mesh membership table.
- **Control plane: actor instantiation** — `procs.spawn("titan_trainers", TitanTrainer, cfg)` crosses into PyO3 (`monarch_extension`) and down to `hyperactor_mesh`, which constructs `TitanTrainer` in each process, registers its `train_step` endpoint in the mailbox registry, and returns an `ActorMesh` handle to Python.
- **Data plane: RPC dispatch** — `trainers.train_step.call(step=0)` creates a typed message envelope. It enters the mailbox client, is routed by `hyperactor_mesh` to each process, and delivered into the actor’s mailbox. Backpressure in `hyperactor` throttles if queues fill. A future is returned to Python.
- **Data plane: actor execution** — In each worker, the mailbox handler invokes `TitanTrainer.train_step`, running Torchtitan code on local GPU resources. Return values are serialized back through the mailbox path; exceptions propagate as failures to the caller.
- **Tensor path (optional)** — If tensors are sharded or transferred, `monarch_tensor_worker` and `monarch_rdma` handle buffer registration and one-sided moves; otherwise, pure message passing is used.
- **Supervision and teardown** — Any crash in a worker/actor is surfaced via the supervision tree; callers can restart or fail-fast. On completion, meshes can be torn down via process allocator cleanup.
