# Decide the data-analysis plane's first surface

Type: grilling
Status: open
Blocked by: 01, 11
Parent: ../map.md

## Question

What is the first user-facing data-analysis capability, and should it be built
on the existing telemetry Arrow/DataFusion substrate or a new one?

Evidence: data analysis has almost no user-facing repo presence, but a
production-grade internal substrate exists:

- `monarch_distributed_telemetry` (`src/lib.rs:11`): `DatabaseScanner`,
  `TelemetryActor`, DataFusion `QueryEngine` returning
  `PyArrowType<RecordBatchReader>` (`query_engine.rs:421`), Arrow-IPC ingestion
  over Unix socket (`socket_ingest.rs:9`).
- Reusable Arrow derive: `monarch_record_batch` `#[derive(RecordBatchRow)]`
  (`src/lib.rs:11`), today used only for telemetry rows.
- Python surface: `QueryEngine.query(sql) -> pyarrow.Table`
  (`python/monarch/distributed_telemetry/engine.py:56`).
- Generic fan-out/fan-in: `ValueMesh` + `Accumulator` + `endpoint.call/stream`
  (`actor_mesh.py:835`, `endpoint.py:97`) is a map-reduce substrate; `BashActor`
  (`job.py:84`) runs arbitrary scripts across a mesh.
- What is MISSING: no `monarch.dataframe`, no partitioned dataset abstraction,
  no shuffle/exchange operators, no analytics job type in `job/`.

Decide:

- The first user-facing surface: a `QueryEngine`-over-user-tables SQL API, a
  partitioned dataset/dataframe, or an actor map-reduce job type.
- Whether to promote `monarch_record_batch` + DataFusion from telemetry-only to
  a user data path, or keep telemetry internal and build the analytics path on
  the generic actor map-reduce substrate.
- The first tracer bullet: a distributed SQL scan or map-reduce over a small
  partitioned dataset across a local proc-mesh.
- How this plane reuses the shared control-plane seam from ticket 01.

Data analysis is the biggest fog; this ticket turns it into a concrete first
decision.
