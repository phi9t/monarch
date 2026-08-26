# GLM52 Agentic Benchmark Platform Spec

Status: resolved-for-implementation-ticketing

## Purpose

Ginkgo should evaluate GLM-5.2 as an agentic model provider, not as a group of
unrelated benchmark scripts. The platform separates model inference, harnesses,
task environments, scoring, and durable orchestration so benchmark evidence is
repeatable, resumable, and auditable.

The first deployable version is local and file-backed. It runs on one
developer-controlled machine using the existing Ginkgo serving stack,
`bwrap_rootfs`, and `harbor_local_docker`. A later version may map the same
concepts onto Temporal, KubeRay, native Kubernetes Jobs, and object storage, but
cluster-native execution is outside v1 scope.

## Source Context

This spec extends:

- `ginkgo/README.md`;
- `.scratch/glm52-local-serving/bwrap-rootfs-serving-system-design.md`;
- `.scratch/glm52-local-serving/benchmark-spec.md`;
- `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`;
- `scripts/glm52_benchmark_verifier.py`;
- `scripts/glm52_bwrap_task_runner.py`.

If this spec conflicts with the existing GLM52 local-serving design, preserve
the stricter Ginkgo rule: no fallback, fail fast, fail loud.

## Resolved Decisions

- The first campaign is a representative machine-local pilot. It includes the
  existing verifier suites, one stateful-tool pilot, and one GDPval proxy lane.
- V1 does not claim official GDPval. It may run `gdpval-proxy-local` only as a
  labelled pilot unless public official reproduction conditions are pinned.
- Suite adapters call a small TaskRunner contract. Current
  `scripts/glm52_bwrap_task_runner.py` behavior may be wrapped for compatibility
  but should migrate behind an Insula-compatible runner adapter.
- Endpoint URLs come from materialized serving config or component refs, with
  `component://responses_adapter/openai_base_url` as the local GLM-5.2 model
  endpoint source.
- Campaign reports separate model-score, infrastructure, scorer, skipped, and
  unsupported denominators.
- Temporal, KubeRay, Kubernetes Jobs, Kueue, and cloud execution are deferred to
  v2 and require a separate ADR.

## Non-Goals

- Do not introduce Kubernetes, KubeRay, Kueue, Temporal, or cluster-native Jobs
  into v1.
- Do not claim official GDPval, FrontierMath, or other private/partly public
  benchmark parity unless public reproduction conditions are pinned.
- Do not run arbitrary model-authored code on the host.
- Do not mount the host Docker socket into a model-controlled task container.
- Do not treat fixture, smoke, or calibration evidence as a reportable score.
- Do not bypass the Responses adapter for GLM-5.2 agentic benchmark traffic.

## Terms

**EvalRun**: one campaign execution against a pinned campaign manifest, endpoint
registry, suite set, runner configuration, and artifact root.

**SuiteAdapter**: a module that prepares a benchmark suite, runs trials through
an endpoint and task runner, grades immutable outputs, and summarizes results.

**TaskRunner**: a module that creates and executes the task environment for one
trial. It may be `bwrap_rootfs`, `harbor_local_docker`, `scripts_run`, or
trusted `host_subprocess` in v1.

**Endpoint Registry**: the campaign manifest section that declares
model-under-test, judge, reader, controller, embedding, and tool-service
endpoints.

**Contract Artifact**: an artifact whose presence and contents determine
whether a run, suite, trial, or score is valid.

**Evidence Ref**: a portable artifact reference resolved during materialization.
`results://` resolves under the serving or benchmark results root, while
`run://` resolves under the mutable run root. Readiness summaries produced under
`glm52-serving-results/` are `results://` artifacts, not `run://` artifacts.

## Architecture

```text
campaign manifest
  -> local EvalRun orchestrator
      -> endpoint readiness gate
      -> suite preparation and dependency prefetch
      -> oracle or gold-path validation where supported
      -> pilot shard
      -> full task x trial matrix
      -> immutable prediction or final-state artifacts
      -> separate grading stage
      -> suite and campaign summaries
```

The local EvalRun orchestrator may remain in `scripts/glm52_benchmark_verifier.py`
while the interface hardens. It owns run state, sharding, retry policy,
cancellation checks, resume, cleanup ledger, and artifact collection.

Suite adapters must call a small TaskRunner interface rather than shelling out
directly to arbitrary execution domains. The interface should hide task-root
layout, network policy, GPU policy, timeout handling, cleanup ledger updates,
and result collection.

The model endpoint remains outside the task environment. Benchmark code calls
the declared OpenAI-compatible endpoint; generated code and benchmark tasks do
not receive direct access to host secrets, host Docker control, or repository
write mounts.

## Modules and Interfaces

### EvalRun Orchestrator

The orchestrator interface is:

```text
materialize_campaign(manifest_path, run_id, local_environment) -> EvalRun
prepare_suite(eval_run, suite_id) -> PreparedSuite
run_trial(prepared_suite, task_id, trial_index) -> TrialArtifact
grade_trial(trial_artifact) -> ScoreArtifact
summarize_suite(score_artifacts) -> SuiteSummary
summarize_campaign(suite_summaries) -> CampaignSummary
```

The implementation writes run state before starting work and updates it after
each artifact-bearing transition. Resume skips completed trial or grade records
only when their input manifest hash still matches.

### Endpoint Registry

Every endpoint record declares:

```yaml
id: glm52-responses-local
role: model_under_test
protocol: openai_responses
base_url_ref: component://responses_adapter/openai_base_url
model: zai-org/GLM-5.2
serving_engine: sglang+dynamo+responses-adapter
readiness_artifacts:
  sglang_repeat_summary: results://<repeat-id>/loop-summary.json
  serving_verifier_summary: results://<run-id>/summary.json
```

Allowed roles are:

```text
model_under_test
judge
reader
controller
embedding
tool_service
```

The readiness gate records model discovery and a minimal live request for every
endpoint role that needs one. Judge and helper endpoint failures are classified
separately from model-under-test failures.

### Suite Adapters

The first adapter families are:

- `static_eval`: GSM8K, AIME, GPQA, Humanity's Last Exam, RULER, LongBench, and
  similar request/score suites.
- `code_eval`: HumanEval, MBPP, LiveCodeBench, BigCodeBench, SciCode, and other
  generate-then-execute suites.
- `harbor_agent`: Terminal-Bench, SWE-bench Verified, SkillsBench, and other
  Harbor-compatible terminal agents.
- `stateful_tool`: MCP Atlas, tau-bench, AppWorld, BFCL, ToolSandbox, and other
  stateful environment suites.
- `browser`: GAIA, BrowseComp, WebArena, VisualWebArena, and browser/search
  suites.
- `professional_artifact`: GDPval, PaperBench, and research/artifact
  production suites.

Adapters expose the same four operations:

```text
prepare_suite(manifest, run_context) -> PreparedSuite
run_trial(prepared_suite, task_id, trial_index, endpoints) -> TrialArtifact
grade_trial(trial_artifact, scorer_config) -> ScoreArtifact
summarize_suite(score_artifacts) -> SuiteSummary
```

Adapters preserve upstream scoring semantics. They do not reinterpret a suite's
official evaluator as a convenience metric.

### Task Runners

The v1 runners are:

- `bwrap_rootfs`: verifier-owned static, reasoning, generated-code, and custom
  tasks that do not require an official container.
- `harbor_local_docker`: Terminal-Bench, SWE-bench, SkillsBench, and other
  official Harbor or Docker-bound suites.
- `scripts_run`: trusted in-rootfs preparation, scoring, and collation.
- `host_subprocess`: trusted host-only discovery, Docker/Harbor orchestration,
  cleanup, and diagnostics.

The TaskRunner input includes:

```text
run_id
suite_id
task_id
trial_index
input_dir
work_dir
output_dir
tmp_dir
timeout_seconds
network
gpu
resource_limits
command
environment_allowlist
artifact_globs
```

The TaskRunner output includes:

```text
status
exit_code
start_time
end_time
duration_seconds
stdout_path
stderr_path
output_artifacts
cleanup_ledger_entries
failure_category
```

The runner never writes to the repository checkout on behalf of generated code.
Network and GPU access are disabled unless the suite manifest requires them.

The existing `scripts/glm52_bwrap_task_runner.py` is the compatibility source
for the first `bwrap_rootfs` adapter. New work should not create a second
independent bwrap argv builder. Before a second bwrap-backed adapter lands, the
bwrap-specific behavior must move behind an Insula-compatible adapter so Ginkgo
keeps one owner for sandbox construction, path binding, and cleanup.

## Campaign Manifest

The campaign manifest extends the existing benchmark manifest:

```yaml
schema_version: 1
campaign:
  id: glm52-agentic-benchmarks-v1
  execution_mode: machine_local
  artifact_root: glm52-benchmark-results

model_under_test:
  endpoint_ref: glm52-responses-local
  required_serving_summary_ref: results://<run-id>/summary.json

endpoints:
  - id: glm52-responses-local
    role: model_under_test
    protocol: openai_responses
    base_url_ref: component://responses_adapter/openai_base_url
    model: zai-org/GLM-5.2

defaults:
  pilot:
    tasks: 5
    trials: 1
    concurrency: 1
  full:
    retries: 1
    timeout_seconds: 7200

suites:
  - id: gsm8k
    profile: math-reasoning-thinking-disabled
    dataset_revision: openai/gsm8k@740312add88f781978c0658806c59bc2815b9866
    harness_revision: lm-evaluation-harness@8a07e1110d060de48cfc7a9a7987b7659060b60b
    prompt_template: gsm8k-v1
    execution_backend: bwrap_rootfs
    decoding_profile:
      temperature: 0
      top_p: 1
      max_output_tokens: 2048
      glm_thinking: disabled
    metric: exact_match
    dataset_source:
      type: huggingface
      repo_id: openai/gsm8k
      repo_type: dataset
      revision: 740312add88f781978c0658806c59bc2815b9866
    harness_source:
      type: git
      url: https://github.com/EleutherAI/lm-evaluation-harness.git
      revision: 8a07e1110d060de48cfc7a9a7987b7659060b60b
    family: static_eval
    adapter: static_eval
    evidence_class: pilot
    scoring:
      mode: deterministic_exact_match
```

The campaign schema wraps and augments the existing benchmark manifest; it does
not rename existing fields. `execution_backend` remains the runner selector
accepted by `scripts/glm52_benchmark_verifier.py`. New fields such as `family`,
`adapter`, `evidence_class`, and `scoring` are additive campaign metadata. The
benchmark-manifest validator must continue to tolerate those additive campaign
fields, or the campaign manifest must become a separate wrapper that references
the unchanged benchmark manifest.

Every suite pins:

- dataset source and revision;
- harness source and revision;
- prompt template and hash;
- decoding profile;
- execution backend;
- metric;
- evidence class;
- scoring mode;
- unsupported or non-comparable conditions.

## First Campaign

The first campaign validates platform breadth without claiming every benchmark
surface is solved:

- `needle-smoke`: smoke evidence for long-context and platform sanity.
- `gsm8k`: reportable score when dataset, prompt, decoding, and exact-match
  scorer revisions are pinned.
- `aime`: pilot evidence for reasoning profile validation.
- `humaneval`: reportable score when generated code runs in an isolated task
  environment and raw predictions are preserved before scoring.
- `mbpp`: reportable score under the same generated-code isolation contract as
  `humaneval`.
- `ruler`: pilot evidence for long-context scoring beyond the smoke path.
- `terminal-bench-2`: pilot evidence through Harbor or local Docker; not a full
  leaderboard run in v1.
- `swe-bench-verified`: pilot evidence through Harbor or local Docker; larger
  runs require explicit authorization.
- one stateful-tool pilot, likely MCP Atlas or tau-bench after endpoint and
  sandbox needs are pinned.
- `gdpval-proxy-local`: pilot/proxy evidence if public artifacts support a
  meaningful local professional-artifact workflow. It must not be labelled as
  official GDPval.

Deferred suites and reasons:

- Browser/open-web suites are deferred until frozen browser/search environment
  contracts and live-web comparability policy exist.
- Desktop suites are deferred until KVM/VM lifecycle and release-image coupling
  are designed.
- Safety suites are deferred until synthetic credentials, egress policy, and
  safety isolation are designed.
- PaperBench and broad research reproduction are deferred because they require
  multi-container boundaries, task-specific GPU access, and grader isolation.
- Official GDPval is deferred unless public reproduction conditions are pinned.
- FrontierMath private/held-out parity is out of v1 scope; public subset runs
  must be labelled by exact subset.

Large full-suite runs require explicit user authorization because they can hold
GPUs, Docker workers, hosted API quota, and local scratch space for a long time.

## Scoring and Result States

The platform maps the current verifier's coarse `FAILURE_STATES` and
`failure_category` fields into a richer campaign taxonomy. Existing artifacts
remain readable through this mapping:

```text
existing status=errored -> invalid_artifact when artifact validation failed,
  otherwise environment_crashed
failure_category=model -> task_failed, model_timeout, or model_protocol_error
failure_category=infrastructure -> environment_setup_failed or environment_crashed
status=passed/pass -> passed
```

The campaign taxonomy is:

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

Campaign summaries must separate:

- model score denominator;
- infrastructure failure denominator;
- judge or scorer failure denominator;
- skipped tasks;
- unsupported tasks;
- non-comparable suites.

Do not silently drop failed infrastructure trials. Do not include
environment setup failures in the model score denominator.

## Contract Artifacts

The existing verifier writes `run.json`, `environment.json`,
`benchmark-manifest.json`, `published-scores.json`, `summary.json`, and per-suite
`samples.jsonl`, `metrics.json`, and `failures.jsonl`. The campaign artifact tree
is a target shape layered over that current contract. Implementation must either
write compatibility aliases or keep the existing files as inputs while emitting
the new per-trial artifacts.

Each EvalRun writes or aliases:

```text
glm52-benchmark-results/<run-id>/
  campaign-manifest.json
  endpoint-readiness.json
  serving-summary.json
  run-state.json              # may alias existing run.json during migration
  suite/<suite-id>/prepared-suite.json
  suite/<suite-id>/tasks/<task-id>/trial-<n>/prediction.json
  suite/<suite-id>/tasks/<task-id>/trial-<n>/trajectory.jsonl
  suite/<suite-id>/tasks/<task-id>/trial-<n>/environment-final-state.json
  suite/<suite-id>/tasks/<task-id>/trial-<n>/score.json
  suite/<suite-id>/suite-summary.json
  campaign-summary.json
```

Logs may support diagnosis, but the files above decide validity.

Every reportable trial must preserve raw prediction or final environment state
before grading. Every score artifact records scorer revision, scorer inputs,
judge endpoint ID when used, and the manifest hash that makes the score valid.
Regrading is allowed only from immutable generation artifacts and an explicitly
new scorer revision.

## Migration from Current Verifier

The current benchmark verifier already has useful behavior that should be
extracted rather than replaced:

- `write_needle_smoke_responses_run`, `write_gsm8k_responses_run`,
  `write_aime_responses_run`, and `write_ruler_responses_run` become the first
  `static_eval` adapter implementation.
- `write_humaneval_responses_run` and `write_mbpp_responses_run` become the
  first `code_eval` adapter implementation.
- Harbor smoke paths become the first `harbor_agent` adapter implementation.
- Existing `manifest_sha256` resume checks remain the compatibility rule for
  skipping completed work until per-trial input hashes are introduced.
- Existing per-suite `samples.jsonl`, `metrics.json`, and `failures.jsonl`
  remain accepted input artifacts until per-trial `prediction.json`,
  `trajectory.jsonl`, and `score.json` are fully populated.

Do not continue growing `scripts/glm52_benchmark_verifier.py` as the permanent
home for every adapter. The first implementation slice may add an EvalRun facade
there for compatibility, but adapter and runner logic should move behind small
interfaces in separate modules once a second adapter family needs the same
orchestration behavior. The target is deep modules, not dozens of thin scripts:
one orchestrator interface, one runner interface, and one adapter module per
benchmark family.

Mirror the existing `ginkgo/insula/` shape for the target package:

```text
ginkgo/eval/
  refs.py
  manifest.py
  orchestrator.py
  artifacts.py
  runners.py
  adapters/
    static_eval.py
    code_eval.py
    harbor_agent.py
```

`scripts/glm52_benchmark_verifier.py` remains the CLI facade. New shared logic
should move into `ginkgo/eval/` before the third adapter family lands, or before
the CLI facade grows beyond a thin compatibility layer for argument parsing,
dispatch, and exit-code translation. If an implementation slice cannot keep that
shape, it must create a design ticket instead of adding another suite-specific
path to the CLI file.

## Future Cluster Phase

The cluster phase maps local concepts onto durable infrastructure:

```text
Temporal EvalRun workflow
  -> same campaign manifest
  -> same suite adapters
  -> KubeRay or native Kubernetes runner adapters
  -> S3 or MinIO artifact store
  -> Postgres metadata index
```

Temporal owns durable workflow state, retries, timeout, cancellation, and
reconciliation. Ray owns placement and parallel fan-out for nonprivileged
workers. Native Kubernetes Jobs own privileged, KVM, nested-container, or
GPU-reproduction work. vLLM or SGLang should remain direct model-serving
services unless a later design proves that Ray Serve belongs in the inference
data path.

This phase requires a separate ADR before implementation.

## Resolved Decision Tickets

- `issues/01-benchmark-scope-and-priority.md`
- `issues/02-gdpval-availability-and-proxy.md`
- `issues/03-runner-and-task-environment-contracts.md`
- `issues/04-endpoint-roles-and-readiness.md`
- `issues/05-scoring-denominators-and-report-format.md`
- `issues/06-cluster-control-plane-deferral.md`

## Initial Implementation Order

The implementation queue is:

1. `issues/07-campaign-manifest-schema.md`
2. `issues/08-file-backed-evalrun-state.md`
3. `issues/09-endpoint-registry-readiness.md`
4. `issues/10-taskrunner-contract-and-bwrap-adapter.md`
5. `issues/11-artifact-normalization-and-report-taxonomy.md`
6. `issues/12-static-eval-adapter-migration.md`
7. `issues/13-code-eval-adapter-migration.md`
8. `issues/14-harbor-agent-pilot.md`
9. `issues/15-first-campaign-smoke.md`
10. `issues/16-stateful-tool-pilot-selection.md`
11. `issues/17-gdpval-proxy-local-pilot.md`
12. `issues/18-future-cluster-control-plane-adr.md`

Each ticket is `ready-for-agent` and carries blocker links, behavioral test
requirements, exclusions, and verification evidence. Work blockers-first. Do
not treat this ordered list as an implementation ticket by itself.

## Execution-Phase Scope

The current run-execution phase is specified in
`run-experiment-sequence-spec.md`. It starts from the fortified GLM52 serving
baseline and drives three known benchmark blockers before any larger run:

- Terminal-Bench 2 reaches Harbor and GLM52 streaming but times out in the
  model/tool loop after 1800 seconds.
- AIME times out through local Responses serving with no scorable response.
- SWE-bench Verified fails before trial execution because Harbor cannot resolve
  dataset `swe-bench-verified`.

The execution-phase ticket order is:

1. `issues/19-terminal-bench-loop-diagnosis.md`
2. `issues/20-aime-serving-timeout-diagnosis.md`
3. `issues/21-swebench-harbor-dataset-resolution.md`
4. `issues/22-host-orchestration-preflight.md`
5. `issues/23-representative-pilot-runbook.md`
6. `issues/24-scale-up-authorization-gates.md`

Tickets 19 through 22 may proceed independently. Ticket 23 may run only after
the blocker tickets are resolved or explicitly deferred with evidence. Ticket
24 defines the authorization boundary for larger benchmark loads.

## Verification Strategy

Implementation tickets must be test-first. Initial checks should include:

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
```

Campaign/orchestrator work should add focused coverage under
`python/tests/test_glm52_agentic_benchmark_platform.py` once the first concrete
module seam exists.

Then run smoke commands through:

```sh
scripts/run_glm52_benchmark_verifier.sh smoke ...
```

Live GLM-5.2 evidence is valid only when the serving summary, endpoint
readiness, run state, suite artifacts, and campaign summary all reference the
same run and endpoint condition.
