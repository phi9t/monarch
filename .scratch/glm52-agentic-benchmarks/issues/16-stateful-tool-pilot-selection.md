# Stateful Tool Pilot Selection

Type: research
Status: ready-for-agent
Blocked by: 09 10 11

## Objective

Select and pin the first v1 stateful-tool pilot suite, preferring MCP Atlas or
tau-bench, and produce the implementation ticket needed to add it.

## Context

Stateful-tool suites need an isolated environment or database snapshot per
trial, endpoint role declarations, and task affinity across the full trajectory.
The first v1 campaign includes one stateful-tool pilot, but the suite must be
chosen from reproducible local conditions rather than convenience.

## Requirements

- Compare MCP Atlas and tau-bench against v1 constraints:
  - machine-local execution;
  - file-backed artifacts;
  - Responses-adapter model endpoint;
  - no host Docker socket in model-controlled containers;
  - reproducible task data and environment snapshots;
  - grader availability;
  - local resource footprint.
- Record primary source URLs, revisions, and license constraints.
- Choose exactly one first stateful-tool pilot or mark both deferred with a
  concrete blocker.
- Define the needed endpoint roles, including judge, user simulator, controller,
  embedding, or tool-service endpoints if required.
- Define the TaskRunner backend: `bwrap_rootfs`, `harbor_local_docker`,
  `scripts_run`, or trusted `host_subprocess`.
- Add a follow-up implementation ticket if one suite is selected.

## Files

- Modify: `.scratch/glm52-agentic-benchmarks/spec.md`
- Modify: `.scratch/glm52-agentic-benchmarks/map.md`
- Create if selected: `.scratch/glm52-agentic-benchmarks/issues/19-stateful-tool-pilot-implementation.md`

## Exclusions

- Do not implement the suite adapter in this ticket.
- Do not use live-web or unpinned hosted state.
- Do not introduce cluster, cloud, or Kubernetes execution.

## Verification

```sh
rg -n "stateful-tool|MCP Atlas|tau-bench|endpoint|TaskRunner" .scratch/glm52-agentic-benchmarks
```

## Done When

- The selected stateful-tool pilot has pinned sources and a valid v1 execution
  story.
- Any deferral is justified by a concrete missing dataset, harness, endpoint,
  grader, legal, or environment condition.
- A ready implementation ticket exists only if the selected suite is runnable
  under v1 constraints.
