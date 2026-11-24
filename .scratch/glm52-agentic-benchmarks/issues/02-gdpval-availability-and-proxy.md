# Decide GDPval Availability and Proxy Boundary

Type: research
Status: resolved
Blocked by: 01

## Question

What GDPval artifacts are available and reproducible enough to run locally, and
what must be labelled as a GDPval proxy instead of an official GDPval result?

## Context

The recommended architecture treats GDPval as a professional-artifact workflow:
agent workspace, artifact or reproduction execution, and independent grading.
The public GDPval release is not currently known to provide a single complete
command that recreates all published artifact-generation and expert-comparison
conditions.

## Decision Needed

Define the GDPval lane for v1:

- Official GDPval run, if all required task artifacts, rubrics, grader, and
  comparison conditions are reproducible.
- GDPval proxy pilot, if tasks or rubrics are available but published
  conditions are incomplete.
- Deferred, if legal, dataset, or grader availability blocks meaningful local
  evidence.

## Resolution

V1 supports a `gdpval-proxy` pilot only. It must not be reported as official
GDPval or compared to published GDPval results unless a later research update
pins every public condition needed for an official run.

The proxy lane is useful because it exercises the professional-artifact shape:

- one clean agent workspace per trial;
- immutable deliverable collection before grading;
- independent grading after generation;
- artifact and rubric provenance in the score record.

The proxy is blocked from reportable-score status until primary sources prove:

- the exact task set and release revision;
- legal local access to task assets and any private source material;
- the official or published rubric text;
- the official grader, expert-comparison, or judge protocol;
- sampling, trial, and denominator rules that make the result comparable.

Until then, the manifest and report must name the harness
`gdpval-proxy-local`, record the source URLs and revisions actually used, and
label the evidence class `pilot`. The grader may be a deterministic rubric,
an independent judge endpoint, pairwise comparison, or manual review, but the
chosen mode must be recorded in each score artifact.

If those public artifacts cannot be obtained, the proxy remains a platform
exercise and may not appear in a reportable score table.

## Acceptance Criteria

- Primary source URLs, revisions, and license constraints are recorded.
- The artifact workspace shape is specified.
- The grader type is specified: deterministic rubric, independent judge model,
  pairwise comparison, or manual review.
- Any score is labelled with the exact harness name and does not claim official
  GDPval parity unless official conditions are met.
