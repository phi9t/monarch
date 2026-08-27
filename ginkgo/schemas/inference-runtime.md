# Inference Runtime Schema

The inference runtime schema owns the parent local-serving lifecycle. It
consumes the materialized SGLang backend contract and derives all component
URLs, ports, process records, logs, and artifact paths.

The first GLM profile may run SGLang -> Responses directly while Dynamo remains
profile-gated. A Dynamo-forwarded profile uses SGLang -> Dynamo -> Responses
and must prove that Dynamo preserves the backend protocol fields before the
topology is accepted for coding-agent or benchmark evidence.

## Components

- `sglang_backend`: launches from the declared SGLang config and must pass its
  model and inference probes before Dynamo starts.
- `dynamo_frontend`: launches only against
  `component://sglang_backend/openai_base_url` when the selected profile enables
  Dynamo, and must not accept a fallback upstream URL.
- `responses_adapter`: launches against the selected profile's component
  reference, either `component://sglang_backend/openai_base_url` for the direct
  SGLang profile or `component://dynamo_frontend/openai_base_url` for the
  Dynamo profile, and must not accept a fallback upstream URL.

## Required Contract

- `fail_fast` is `true`.
- `allow_fallback` is `false`.
- Port allocation uses `strict_run_owned_range`.
- Component upstreams are materialized from component refs, not operator URLs.
- Process records are validated before teardown.
- A parent run summary must prove the same run ID, ports, model identity, and
  process ownership across all components.

## Evidence Boundary

The parent inference runtime can produce GLM completion evidence only when the
selected GLM profile runs real SGLang inference, Responses non-streaming and
streaming inference, tool-call verification, and clean teardown in the same
parent run. Dynamo profiles additionally require Dynamo readiness, lossiness
proof, and any profile-declared long-running inference pilot in the same parent
run.
