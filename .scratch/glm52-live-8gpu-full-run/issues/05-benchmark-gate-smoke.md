# Benchmark Gate Smoke

Type: task
Status: ready-for-agent
Blocked by: 04

## Goal

Run the first benchmark smoke command only after the parent manifest proves a
completed GLM-backed Responses URL from the same parent run.

## Requirements

- Start only after ticket 04 records a passing parent-manifest audit.
- Use `scripts/glm52_benchmark_verifier.py` with `--parent-manifest` pointing
  at the audited manifest.
- Use the completed Responses base URL from the audited manifest.
- Record suite, mode, backend, manifest path, Responses URL, result directory,
  and exit code.
- Keep smoke, calibration, and conformance distinct. This ticket covers smoke
  only unless a human explicitly opens follow-up tickets.
- Preserve benchmark artifacts under `glm52-serving-results/`.

## Exclusions

- Do not run calibration or conformance before smoke evidence is reviewed.
- Do not override the Responses URL away from the audited parent run.
- Do not use fake benchmark results, fixture routing, or placeholder scores as
  GLM-backed benchmark evidence.
- Do not claim published conformance from smoke.

## Verification Evidence

- Benchmark verifier rejects a mismatched or missing parent manifest before the
  accepted smoke command is run.
- Accepted smoke command exits zero against the audited GLM-backed Responses
  URL, or exits nonzero with a blocker artifact that does not weaken the parent
  completion claim.
- Benchmark summary records the parent manifest path and completed Responses
  base URL.

## Comments
