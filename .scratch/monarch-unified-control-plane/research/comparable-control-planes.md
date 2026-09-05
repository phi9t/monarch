# Research: comparable control planes for training, serving, and data analysis

Feeds tickets 01 (plane seam), 04 (training fault tolerance), 05 (data analysis).
Sources are primary docs/source; URLs inline. Findings gathered 2026-09-05.

## The one architectural fact that anchors everything

Ray proves a single actor/task core can host training, serving, and analytics
as three *libraries* — each is a distinctive arrangement of actors plus control
logic, not a separate runtime. The shared core provides: actors + tasks, an
object store (bulk data plane), a durable global control store (GCS), one
scheduler with gang-scheduled placement groups, and per-actor restart. Each
library owns only its actor topology, health, and scaling policy.
(https://docs.ray.io/en/latest/ray-core/actors.html,
https://docs.ray.io/en/latest/ray-core/scheduling/index.html)

This maps directly onto Monarch's landed primitives: proc/actor/host meshes are
the actor core, RDMA + tensor-engine fetch is the bulk data plane, the
supervision tree is per-actor restart, and `JobTrait` is the placement/lifecycle
seam. What Monarch lacks is the *shared control store* and the *one scheduler*
that all three planes call. That is the plane-seam decision (ticket 01).

## Training plane (feeds ticket 04)

- Ray Train and torch-elastic **converge on the same fault model**: any worker
  failure -> stop the whole group -> (replace nodes) -> restart -> resume from
  the last checkpoint, bounded by a `max_failures`/`max_restarts` counter.
  (https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html,
  https://docs.pytorch.org/docs/2.14/elastic/run.html)
- **The control plane owns the restart *policy*, not the checkpoint *format*.**
  The application saves/restores; the platform detects failure, reallocates the
  mesh, and re-invokes. Ray Train recovers a whole run from just
  `(storage_path, run_name)`; torch-elastic from `rdzv_id` + checkpoint.
- **Rank and world size are unstable across restarts.** torch-elastic reassigns
  `RANK`/`WORLD_SIZE` on every restart; PyTorch DCP reshards on load, so a
  checkpoint saved under one topology loads under a different world size. A
  Monarch restart hook must re-derive rank/topology from *current* mesh
  membership, never a hardcoded world size.
  (https://docs.pytorch.org/docs/2.14/distributed.checkpoint.html)
- Recovery keys on a **stable run identity**, so a control-actor or head restart
  re-attaches rather than restarts from zero.

Direct consequence for Monarch: the existing `unhandled_fault_hook(MeshFailure)`
default of `sys.exit(1)` is exactly the wrong default for training; the seam is
to replace it with a bounded gang-restart-from-checkpoint policy driven off
`JobTrait.state()`, delegating state to torch DCP. The `MeshFailure` payload
already names the failed rank.

## Serving plane (feeds tickets 02, 03)

- **SGLang is single-model-per-server** (`--model-path` loads exactly one model;
  RadixAttention cache is per-replica). The multi-model / fleet concept is not
  in the worker.
  (https://docs.sglang.ai/advanced_features/server_arguments.html)
- The fleet layer is a **gateway/registry**: SGLang's Model Gateway
  (`--enable-igw`) lets workers register via `POST /workers` with
  `model_id`/`priority`/`labels` and exposes `/workers` management APIs; routing
  policies are `cache_aware`/`round_robin`/`power_of_two`.
  (https://docs.sglang.ai/advanced_features/sgl_model_gateway.html)
- **Dynamo is orchestration *above* the engine, not a replacement**: an
  OpenAI-compatible Frontend, a KV-aware Router (routes on load + prefix
  overlap), disaggregated prefill/decode pools, tiered KV offload (KVBM), and an
  SLA-driven Planner that right-sizes pools to hit TTFT/ITL targets. The Planner
  *is* the serving autoscaler. (https://github.com/ai-dynamo/dynamo)
- KV-aware routing needs only worker-reported signals SGLang already emits
  (`--kv-events-config`, `--enable-forward-pass-metrics`).
- **Ray Serve's minimal control surface** is the whole fleet API you need:
  deploy / scale (`num_replicas` int or autoscale min:max:target) / list /
  status / delete / ingress route, plus `user_config` hot-reconfigure to avoid
  replica restarts. It runs as a Controller actor over proxy actors over replica
  actors — a supervision tree.
  (https://docs.ray.io/en/latest/serve/architecture.html,
  https://docs.ray.io/en/latest/serve/configure-serve-deployment.html)
- Multi-tenant GPU allocation across SGLang Gateway, Dynamo, and vLLM's stack is
  uniformly **pool/process-level** — dedicate workers to a model and route
  across pools; none do in-GPU time-slicing at the control plane.
  (https://docs.vllm.ai/en/latest/deployment/integrations/production-stack.html)

Direct consequence for Monarch: the serving fleet is a controller actor over
worker meshes, each worker actor hosting one SGLang model and registering
`(model_id, labels)` — which is Monarch's supervision tree plus a registry. The
Dynamo Planner's job (profile load, size pools to SLA) is a Monarch scheduler
actor decision, so Monarch can subsume the autoscaler rather than depend on
Dynamo for it. This is why de-GLM-ing the runtime into a model-registered worker
(ticket 03) is the serving prerequisite.

## Data-analysis plane (feeds ticket 05)

- **DataFusion is single-node but partition-parallel and streaming.**
  `ExecutionPlan::execute(partition, ctx)` returns one `RecordBatchStream` per
  output partition; `Partitioning` is explicit (`Hash`/`RoundRobinBatch`);
  `RepartitionExec` is the local shuffle, `CoalescePartitionsExec` the gather.
  Distribution is *not* built in — you add a custom exchange `ExecutionPlan`.
  (https://docs.rs/datafusion/latest/datafusion/physical_plan/trait.ExecutionPlan.html)
- **Ballista shows the distributed pattern**: cut the plan at shuffle boundaries
  into stages, `ShuffleWriterExec` writes partitions, `ShuffleReaderExec` reads
  them (local FS or Arrow Flight `do_get`), and the scheduler rewrites
  `UnresolvedShuffleExec` -> `ShuffleReaderExec` with concrete partition
  locations once producers finish. The stage barrier enables partial
  re-execution on failure.
  (https://datafusion.apache.org/ballista/contributors-guide/shuffle.html)
- **Arrow Flight** models a partitioned result as `FlightInfo` -> list of
  `FlightEndpoint(ticket, locations)` — which maps cleanly onto "partition ->
  producing actor." But Flight is gRPC/TCP; Monarch's PortRef/RDMA can carry
  Arrow IPC buffers between actors directly, keeping Flight only as the external
  client boundary. (https://arrow.apache.org/docs/format/Flight.html)
- Ray Data / Spark / Ballista share one control structure: driver builds an
  operator DAG, cuts at shuffle boundaries, schedules map actors, materializes
  shuffle partitions, schedules reduce/aggregate actors that pull them.
  (https://docs.ray.io/en/latest/data/data-internals.html)

Direct consequence for Monarch: a distributed dataframe is
single-node DataFusion (already vendored, already used by
`monarch_distributed_telemetry`) + a custom exchange `ExecutionPlan` that pulls
remote partitions over the actor mesh + a coordinator that resolves
partition->actor placement. The hard parts (columnar SQL, streaming, Arrow
transfer) exist; the missing piece is the exchange operator + placement — the
same scheduler the other two planes need. Ballista's barrier model aligns with
Monarch's supervision tree (restart a failed stage's actors), so prefer it over
pipelined-fragile exchange.

## The convergent finding

All three planes need the **same two missing pieces**:

1. **One scheduler / placement decision over meshes** — Ray's placement group,
   Dynamo's Planner, and Ballista's partition->executor assignment are the same
   abstraction. Build it once; training gang-schedules a worker group, serving
   sizes replica pools to SLA, analytics places partitions.
2. **A restart/reallocation policy on the supervision tree** — training resumes
   from checkpoint, serving replaces a replica, analytics re-executes a stage.
   All three are `MeshFailure` -> policy -> reallocate, differing only in the
   policy callback.

Plus a durable control store (GCS-analog) for specs/placement so a control-actor
restart re-attaches. Everything else is plane-specific actor topology and a thin
per-plane API. This strongly favors the "shared core + three thin planes"
answer to ticket 01, with the scheduler + supervision-policy seam as the shared
substrate rather than three independent control planes.

## Caveats / to-verify-live

- The Dynamo Planner scaling formula (offline TTFT/ITL profiling + runtime
  signals) is inferred from the README + SGLang metrics hooks, not a fetched
  planner-guide page. Verify if the exact autoscaling math matters.
- All findings are doc-derived, not run locally. Monarch's RDMA-as-shuffle and
  DataFusion-exchange-over-mesh claims are architecturally sound but unproven in
  this checkout.
