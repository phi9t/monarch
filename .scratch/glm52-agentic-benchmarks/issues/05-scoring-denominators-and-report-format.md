# Decide Scoring, Denominators, and Report Format

Type: task
Status: resolved
Blocked by: 01 03 04

## Question

What result states, denominators, and artifacts make a benchmark campaign
auditable?

## Context

The platform must not count infrastructure outages as model failures, but it
also must not silently discard them. Generation and grading are separate
stages, and published conformance requires pinned source conditions and
tolerances.

## Decision Needed

Define the campaign report schema and per-trial result taxonomy.

The new taxonomy must be mapped from the existing verifier artifacts instead of
silently replacing them. Current code records coarse `FAILURE_STATES`, per-sample
`failure_category` values, `model_failures`, `infrastructure_failures`, and
`infrastructure_failure_denominator`. Current artifacts include `run.json`,
`environment.json`, `benchmark-manifest.json`, `summary.json`, and per-suite
`samples.jsonl`, `metrics.json`, and `failures.jsonl`.

Required states should include at least:

```text
passed
task_failed
model_timeout
model_protocol_error
environment_setup_failed
environment_crashed
grader_failed
cancelled
invalid_artifact
```

## Resolution

Use a per-trial taxonomy and report schema that preserves the current verifier
artifacts while adding explicit denominators for campaign reporting.

Canonical trial states:

```text
passed
task_failed
model_timeout
model_protocol_error
environment_setup_failed
environment_crashed
grader_failed
cancelled
invalid_artifact
unsupported
skipped
```

Denominators:

- **Model score denominator:** trials whose task environment, model call, and
  scorer completed enough to judge model behavior.
- **Infrastructure failure denominator:** all attempted trials whose environment,
  runner, serving dependency, artifact validation, or orchestration failed.
- **Scorer failure denominator:** trials whose generation artifact exists but
  grading failed because of scorer, judge, or rubric infrastructure.
- **Skipped denominator:** intentionally unrun tasks, including pilot sample
  limits and user-deferred full runs.
- **Unsupported denominator:** manifest-selected tasks that the local v1
  platform cannot validly run.

Current verifier migration:

```text
status=passed or status=pass -> passed
failure_category=model + timeout evidence -> model_timeout
failure_category=model + protocol/http/schema evidence -> model_protocol_error
failure_category=model otherwise -> task_failed
failure_category=infrastructure + setup/preflight evidence -> environment_setup_failed
failure_category=infrastructure otherwise -> environment_crashed
artifact validation failure -> invalid_artifact
grader/scorer/judge failure -> grader_failed
explicit cancellation -> cancelled
explicit unsupported suite/task -> unsupported
manifest sample limit or user deferral -> skipped
```

Existing `run.json`, `environment.json`, `benchmark-manifest.json`,
`summary.json`, per-suite `samples.jsonl`, `metrics.json`, and `failures.jsonl`
remain accepted input artifacts during migration. New campaign artifacts may
alias those files, but report generation must state which compatibility source
was used.

Every reportable trial must preserve raw prediction or final environment state
before grading. Every score artifact records scorer revision, scorer inputs,
judge endpoint ID when used, and the manifest hash that made the score valid.
Regrading is allowed only from immutable generation artifacts and an explicitly
new scorer revision.

## Acceptance Criteria

- The report separates model score denominator, infrastructure failure
  denominator, judge/scorer failure denominator, skipped tasks, and unsupported
  tasks.
- Existing artifact names and failure categories have an explicit migration or
  aliasing rule.
- Per-trial artifacts include raw prediction or final environment state before
  grading.
- Grading artifacts record scorer revision and judge endpoint when used.
- Suite summaries can be regraded without rerunning generation.
- Campaign summary lists each suite's evidence class and whether it supports a
  reportable score.
