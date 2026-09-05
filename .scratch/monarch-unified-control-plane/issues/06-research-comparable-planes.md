# Research: how comparable control planes structure the three planes

Type: research
Status: resolved
Blocked by:
Parent: ../map.md

## Question

Surface facts a decision waits on: how do comparable systems structure a shared
control plane across training, serving, and analytics, and what does Monarch's
own actor model already give for free?

Investigate against primary sources (docs, source, papers), capture as a cited
Markdown file on a throwaway `research/<name>` branch, and link it here:

- Ray's control-plane split (GCS, Ray Serve, Ray Train, Ray Data) and how one
  actor/task core hosts three workload libraries — what is shared vs library-
  specific. Relevant because Monarch's mesh+actor core is the closest analogue.
- Torchtitan / torch-elastic rendezvous + checkpoint-on-failure for fault-
  tolerant training (informs ticket 04). Note the local `torchtitan` checkout
  has prior robust-training work.
- SGLang + Dynamo + Responses production serving topologies and what a real
  fleet API (create/scale/list deployments) minimally needs (informs the
  serving API fog).
- DataFusion / Arrow Flight partitioned-query patterns for a distributed SQL /
  dataframe surface (informs ticket 05).

Deliver a findings doc structured by the three planes plus a "what Monarch's
mesh core already provides" section. This is AFK; fire it in parallel with the
charting session. It does not itself decide anything — it feeds tickets 01/04/05.

## Answer

Findings captured in `../research/comparable-control-planes.md` (primary-source
cited: Ray, torch-elastic/DCP, SGLang, Dynamo, DataFusion/Ballista, Arrow
Flight). The anchoring result: Ray proves one actor/task core hosts training,
serving, and analytics as three *libraries*, not three runtimes. All three
Monarch planes need the **same two** missing pieces on top of the landed
mesh+supervision core:

1. one scheduler/placement decision over meshes (Ray placement group ≈ Dynamo
   Planner ≈ Ballista partition→executor), and
2. a restart/reallocation policy on the supervision tree replacing the
   `unhandled_fault_hook` default `sys.exit(1)` — training resumes from
   checkpoint, serving replaces a replica, analytics re-executes a stage; all
   three are `MeshFailure → policy → reallocate`.

Plus a durable control store so a control-actor restart re-attaches. This
strongly favors the "shared core + three thin planes" answer to ticket 01.
