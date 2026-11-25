# Inference Run Schema

Status: ready-for-agent

Type: task

Blocked by:

## Goal

Define the source-backed declared and materialized schema for one complete
GLM-5.2 end-to-end inference Local Run.

## Requirements

- Add a portable declared config at
  `.scratch/glm52-local-serving/config/inference-local.yaml`.
- Reject unknown fields, nullable required fields, shell command strings, and
  absolute host paths in portable config.
- Use logical refs for host-side paths: `repo://`, `cache://`, `temp://`,
  `run://`, `rootfs://`, and `component://`.
- Allocate concrete SGLang, Dynamo, and Responses adapter ports from one strict
  run-owned range.
- Reject ports `8000`, `8080`, and `18080`.
- Materialize concrete component URLs, process record paths, artifact paths,
  argv arrays, env mappings, preparation record refs, and failure policy.
- Require `fail_fast: true` and `allow_fallback: false`.
- Fail if any component endpoint is provided as an ambient free-form URL instead
  of a materialized component ref.

## Exclusions

- Do not launch SGLang, Dynamo, or the Responses adapter.
- Do not run live probes.
- Do not change benchmark scoring.

## Verification Evidence

- Focused unit tests for declared schema acceptance and rejection.
- Focused unit tests for materialized config shape.
- Focused unit tests for strict multi-port allocation and disallowed ports.
- A sample materialized config artifact generated from the example declared
  config and a temp local environment.

## Comments
