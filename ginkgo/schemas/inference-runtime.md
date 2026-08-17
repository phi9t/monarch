# Inference Runtime Schema

The inference runtime schema owns the parent SGLang -> Dynamo -> Responses
lifecycle. It consumes the materialized SGLang backend contract and derives all
component URLs, ports, process records, logs, and artifact paths.

## Components

- `sglang_backend`: launches from the declared SGLang config and must pass its
  model and inference probes before Dynamo starts.
- `dynamo_frontend`: launches only against
  `component://sglang_backend/openai_base_url` and must not accept a fallback
  upstream URL.
- `responses_adapter`: launches only against
  `component://dynamo_frontend/openai_base_url` and must not accept a fallback
  upstream URL.

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
GLM profile runs real SGLang inference, Dynamo readiness, Responses
non-streaming and streaming inference, tool-call verification, and clean
teardown in the same parent run.
