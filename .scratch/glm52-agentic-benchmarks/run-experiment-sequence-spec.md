# GLM52 Agentic Benchmark Run Sequence Spec

Status: draft-for-review

## Purpose

This spec scopes the next execution phase for GLM-5.2 agentic benchmarks. The
serving stack is already fortified enough to support benchmark work: the
3-cycle SGLang GPU repeat passed, the Responses adapter preserves streaming, and
Harbor can reach GLM-5.2 through the local Responses path. The next phase is not
more platform design. It is a blockers-first run sequence that turns the current
benchmark failures into diagnosed, reproducible, and eventually passing pilots.

This spec extends `.scratch/glm52-agentic-benchmarks/spec.md` and uses the
existing local GLM52 serving tracker as source evidence. It does not replace the
longer-term campaign-platform tickets.

## Current Baseline

The baseline for this phase is:

- Local GLM52 SGLang repeat run:
  `glm52-serving-results/glm52-sglang-local-repeat-20260822T210036Z-e7623385/loop-summary.json`.
- Repeat status: `passed`.
- Three cycles launched and tore down SGLang across eight GPUs.
- Each cycle recorded `prepare_heal.status: already_valid`.
- The warm throughput probe completed 128 generated tokens in each cycle.
- Benchmark verifier and Harbor/Responses hardening are landed on local `main`
  in commit `f92e34164`.

The phase starts from three known benchmark blockers:

- Terminal-Bench reaches Harbor, the Responses adapter, and GLM52 streaming, but
  the model/tool loop times out after 1800 seconds. This is a model or
  harness-interaction failure, not a host bootstrap failure.
- AIME through local Responses serving times out with an empty response. This
  remains an infrastructure/local-serving blocker until the endpoint returns a
  scorable answer.
- SWE-bench Verified fails before trial execution because Harbor cannot resolve
  dataset `swe-bench-verified`.

## Scope

The phase owns the sequence from the fortified local serving baseline to a
small, evidence-backed benchmark campaign. It includes:

- diagnosing and fixing the three current benchmark blockers;
- preserving streaming for GLM52 inference and Harbor traffic;
- keeping all GLM52 benchmark traffic on the Responses adapter unless a task is
  explicitly isolating a lower-level serving bug;
- turning successful smoke runs into a repeatable pilot run sequence;
- recording benchmark status in durable tracker issues;
- defining scale-up gates and explicit authorization boundaries before larger
  runs.

The phase does not include:

- Kubernetes, KubeRay, Kueue, Temporal, cloud workers, or object storage;
- official leaderboard claims for Terminal-Bench, SWE-bench, GDPval, or
  private/partly public benchmarks;
- disabling streaming to make a harness pass;
- increasing timeouts as the primary mitigation;
- killing GPU processes not owned by this user;
- staging generated benchmark caches, downloaded harnesses, or run logs.

## Execution Principles

Work blockers-first. A large benchmark run is valid only after the smaller
diagnostic run for the same path can complete with interpretable artifacts.

Use the existing result taxonomy:

- `environment_setup_failed` for missing Harbor, Docker, datasets, images, or
  credentials before trial execution;
- `environment_failed` for serving, adapter, scheduler, sandbox, or timeout
  failures that prevent a scorable model output;
- `fail` with `model_failures > 0` only after the task environment and model
  protocol path completed enough to make a model attempt count;
- `passed` only when the suite's smoke or pilot acceptance criteria are met.

Preserve raw artifacts before grading. For agentic suites, keep the full Harbor
trajectory or the richest available transcript before summarizing the result.

## Sequence

### Stage 0: Preflight

Run only checks that should be cheap and fail early:

- confirm the local `main` contains `f92e34164` or a descendant;
- confirm no owned SGLang, Responses adapter, Harbor, or benchmark process from
  an earlier run is still active;
- confirm GPU availability before launching SGLang;
- confirm the pinned Harbor executable is discoverable by the benchmark wrapper
  or by the explicit scratch venv path;
- confirm generated caches and run logs are untracked and not staged.

Acceptance:

- no stale owned process can interfere with a new run;
- the chosen host-control path for Harbor is explicit in the command and
  captured in artifacts.

### Stage 1: Terminal-Bench Model/Tool-Loop Diagnosis

Start with Terminal-Bench because it exercises the highest-risk agentic path:
Responses streaming, tool calls, Harbor, Docker, and long-running task state.

The diagnostic loop is:

1. Reproduce the one-task timeout with the current pinned task
   `adaptive-rejection-sampler`.
2. Extract the Harbor trajectory, Responses request/response stream shape,
   model messages, tool calls, and final timeout point.
3. Classify the root cause as one of:
   - model never emits the needed tool action;
   - inline tool-call repair creates an invalid continuation;
   - Harbor state or tool result is not being fed back correctly;
   - the task prompt is too large or too hard for the current GLM52 profile;
   - serving throughput makes the 1800 second budget unrealistic;
   - another concrete protocol or environment failure.
4. Add a regression fixture for the verified cause before changing behavior.
5. Fix only the verified cause.
6. Rerun the same one-task smoke.

Acceptance:

- the one-task Terminal-Bench smoke either completes, or the tracker records a
  concrete model-capability blocker with trajectory evidence;
- infrastructure failures remain zero if the endpoint, Harbor, Docker, and
  adapter path are healthy;
- streaming remains enabled.

### Stage 2: AIME Local-Serving Diagnosis

AIME is the reasoning-serving diagnostic. It should not be scaled until a
single bounded sample returns a scorable response.

The diagnostic loop is:

1. Reproduce the bounded AIME timeout through the Responses adapter.
2. Replay the exact prompt against the lowest useful layer:
   - Responses adapter;
   - Chat Completions endpoint if needed;
   - native SGLang `/generate` only to isolate serving behavior.
3. Compare request shape, timeout, generated token count, stop conditions,
   thinking mode, and SGLang scheduler/KV logs.
4. Decide whether the fix is prompt/profile, adapter request shape, serving
   config, or an accepted local-serving capacity blocker.
5. Add a regression fixture for the chosen request-shape or timeout behavior.
6. Rerun one bounded AIME smoke.

Acceptance:

- a bounded AIME profile returns a scorable answer within a declared timeout, or
  the blocker is documented with request, server-log, GPU, and timeout evidence;
- the result is labelled as smoke or pilot evidence, not published AIME
  conformance;
- timeout increases alone are not accepted as a fix.

### Stage 3: SWE-bench Harbor Dataset Resolution

SWE-bench is currently blocked before model execution. Fix that before any
model-quality work.

The diagnostic loop is:

1. Inspect Harbor 0.21.0's supported dataset identifiers and local/package
   dataset modes.
2. Determine whether `swe-bench-verified` should be represented as:
   - a Harbor registry dataset with a different name;
   - a local Harbor dataset generated from the pinned SWE-bench row;
   - a package dataset;
   - a direct SWE-bench evaluator path outside Harbor.
3. Add a preflight that fails with a precise message before launching Harbor
   when the configured dataset is unresolved.
4. Preserve the pinned smoke instance `astropy__astropy-12907` and its
   digest-pinned image metadata unless a primary-source review changes the
   selection.
5. Rerun the one-instance smoke to the first model call or a task-specific
   harness failure.

Acceptance:

- the SWE-bench smoke no longer fails with
  `ValueError: Dataset swe-bench-verified not found`;
- if a local/package dataset is used, its generated files and provenance are
  captured as contract artifacts;
- the smoke remains non-comparable to published SWE-bench Verified scores.

### Stage 4: Representative Pilot

After Stages 1 through 3 are resolved or explicitly deferred with evidence, run
a small campaign-like pilot:

- `needle-smoke`;
- `gsm8k`;
- `humaneval`;
- `mbpp`;
- `ruler` smoke or small pilot;
- `aime` bounded smoke if Stage 2 produced a scorable profile;
- `terminal-bench-2` one-task smoke if Stage 1 is not deferred;
- `swe-bench-verified` one-instance smoke if Stage 3 is not deferred.

Acceptance:

- every included suite writes summary, raw-generation or trajectory artifacts,
  and failure denominators;
- skipped or deferred suites appear as skipped or unsupported, not silently
  missing;
- the pilot summary distinguishes model failures from infrastructure failures.

### Stage 5: Scale-Up Gate

Do not run larger benchmark loads until the pilot has no unexplained
infrastructure failures.

A larger run requires explicit authorization when it:

- occupies local GPUs for more than one hour;
- runs Terminal-Bench or SWE-bench beyond the pinned smoke subset;
- uses hosted APIs, paid sandboxes, cloud providers, or external judges;
- runs untrusted code or browser/open-web tasks outside the existing local
  sandbox policy;
- claims reportable score evidence.

Acceptance:

- the requested run size, suite list, expected duration, GPU use, and artifact
  destination are written before launch;
- cleanup commands and owned-process boundaries are recorded;
- the final report includes score, denominator, infrastructure-failure rate,
  and artifact paths.

## Ticket Graph

This phase adds these tracker tickets:

- `issues/19-terminal-bench-loop-diagnosis.md`
- `issues/20-aime-serving-timeout-diagnosis.md`
- `issues/21-swebench-harbor-dataset-resolution.md`
- `issues/22-host-orchestration-preflight.md`
- `issues/23-representative-pilot-runbook.md`
- `issues/24-scale-up-authorization-gates.md`

Tickets 19, 20, 21, and 22 can proceed independently after preflight. Ticket 23
is blocked by their outcomes. Ticket 24 is blocked by ticket 23.

## Verification

The non-GPU verification suite for changes made under these tickets starts with:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_inference_runtime.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
scripts/run python -m pyright \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_inference_runtime.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_sglang_runtime.py
scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_inference_runtime.py \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_sglang_runtime.py
git diff --check
```

Live verification uses the existing GLM52 serving config and must run through
the repo-local rootfs gateway or host-control wrappers documented in
`AGENTS.md`.
