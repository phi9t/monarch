# GDPval Proxy Local Pilot

Type: research
Status: ready-for-agent
Blocked by: 11 15

## Objective

Pin the `gdpval-proxy-local` pilot conditions and create an implementation
ticket only if the public artifacts support a meaningful local
professional-artifact workflow.

## Context

V1 must not claim official GDPval. The resolved decision permits only a proxy
lane unless every public official reproduction condition is pinned. The proxy is
still valuable because it exercises agent workspace creation, deliverable
collection, independent grading, and artifact provenance.

## Requirements

- Research primary sources for public GDPval task artifacts, rubrics, grader
  protocol, comparison conditions, and license constraints.
- Record exact source URLs and revisions in the tracker.
- Decide one of:
  - official GDPval remains deferred;
  - `gdpval-proxy-local` can run as a pilot;
  - GDPval-like evidence is deferred entirely.
- If proxy is selected, define:
  - workspace layout;
  - allowed tools and network policy;
  - deliverable collection format;
  - grader type: deterministic rubric, independent judge endpoint, pairwise
    comparison, or manual review;
  - score artifact fields;
  - non-comparable report labelling.
- Create a follow-up implementation ticket only if the proxy can run under v1
  local constraints.

## Files

- Modify: `.scratch/glm52-agentic-benchmarks/spec.md`
- Modify: `.scratch/glm52-agentic-benchmarks/map.md`
- Create if selected: `.scratch/glm52-agentic-benchmarks/issues/20-gdpval-proxy-implementation.md`

## Exclusions

- Do not claim official GDPval or published-result parity.
- Do not implement the proxy adapter in this ticket.
- Do not use private data, production credentials, or unpinned manual grading
  conditions.

## Verification

```sh
rg -n "gdpval-proxy-local|GDPval|professional-artifact|grader" .scratch/glm52-agentic-benchmarks
```

## Done When

- The tracker records whether GDPval is proxy-only or deferred.
- Any proxy result label is exact and non-comparable.
- A ready implementation ticket exists only if public artifacts and local
  execution constraints are sufficient.
