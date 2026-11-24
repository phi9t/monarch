# GLM-5.2 Local Serving, Codex Compatibility, and Benchmark Verification

Status: ready-for-human

Created: 2026-08-15T18:20:12Z
Updated: 2026-08-16T18:00:00Z

Current execution state, 2026-08-16: local verifier, adapter, deployment,
benchmark, Harbor-agent, and manifest guardrail slices are implemented and
tracked in `completion-audit-2026-08-16.md`. Remaining work is no longer a
clean local agent slice: it needs a live Dynamo/SGLang GLM-5.2 endpoint, a
GLM-backed Responses adapter, host-control Harbor/local Docker evidence, and
comparable primary-source conformance metadata. The issue tracker and the
audit's issue status map are authoritative for the current blocker state.

## Problem Statement

The user wants to run GLM-5.2 locally and use it confidently with Codex. The
local serving stack must bridge a protocol mismatch: current Codex custom
providers use the OpenAI Responses API, while NVIDIA's GLM-5.2 Dynamo/SGLang
recipe exposes Chat Completions. A plain `/v1/chat/completions` health check is
not enough, because Codex needs streaming Responses events, function-call
items, tool-output continuations, stable conversation state, and predictable
structured output.

The user also wants enough verification to distinguish a deployable coding-agent
provider from a model that merely returns text. The system must prove tool
calling, terminal-style coding behavior, cleanup after launcher crashes, local
benchmark execution, and benchmark artifact quality. Monarch should support the
Local Run and monitoring story around this deployment without replacing Dynamo's
inference path or SGLang's model serving.

## Solution

Build a local serving and verification path with this topology:

```text
Codex or verifier
  -> Responses-compatible adapter
  -> Dynamo frontend
  -> SGLang GLM-5.2
```

The Responses adapter is the Codex compatibility boundary. It exposes
`GET /v1/models` and `POST /v1/responses`, translates Responses requests into
OpenAI-style Chat Completions, disables GLM thinking by default for structured
tool use, translates Chat streaming deltas back into Responses SSE events, and
keeps process-local `previous_response_id` state for tool-call continuations.

The serving verifier proves raw Chat health, Responses compatibility, streaming
tool calls, function-call outputs, and complex tool-loop behavior. The terminal
bench smoke requires the model to run a test command, inspect a file, write a
fix, rerun tests, and report the result without receiving host shell access.

The deployment helper records host-observable components and supports status
and cleanup after the launcher, adapter, or control plane crashes. Cleanup is
idempotent and guarded by command matching before killing host PIDs.

The benchmark verifier extends confidence beyond protocol acceptance. It runs a
no-Kubernetes local evaluation platform with file-backed run state, Contract
Artifacts, Harbor-backed agent benchmarks where official containers matter, and
Hermetic Rootfs bwrap task sandboxes where the verifier owns the execution
contract. Conformance against published scores is allowed only when the
published source, model identity, prompt template, decoding settings, benchmark
revision, and execution backend match.

## User Stories

1. As a Codex user, I want GLM-5.2 to appear as a Responses-compatible provider,
   so that I can use it through Codex's current custom-provider path.
2. As a Codex user, I want streaming output to follow Responses SSE event
   shapes, so that Codex can reconstruct assistant text and function calls.
3. As a Codex user, I want GLM-5.2 tool calls to survive a full call-output-call
   continuation loop, so that agent tasks can progress beyond the first tool.
4. As a Codex user, I want malformed tool-call arguments to fail explicitly, so
   that protocol bugs are diagnosable instead of silently becoming wrong tool
   actions.
5. As a Codex user, I want GLM thinking disabled for the initial tool-calling
   profile, so that tool calls use predictable structured output channels.
6. As a Codex user, I want the adapter to advertise `zai-org/GLM-5.2`, so that
   Codex configuration can use the same model name across environments.
7. As a Codex user, I want adapter state requirements documented, so that I know
   whether a deployment needs a single adapter process or sticky routing.
8. As a local operator, I want a raw Chat health check, so that I can separate
   Dynamo/SGLang serving failures from Responses adapter failures.
9. As a local operator, I want a Responses compatibility check, so that I can
   know whether Codex can talk to the local model.
10. As a local operator, I want a multi-turn tool verifier, so that a passing
    deployment proves agent behavior rather than only text generation.
11. As a local operator, I want a terminal-shaped coding smoke, so that the
    model must read, edit, and test code through tools before I connect Codex.
12. As a local operator, I want terminal tools to be virtual and allowlisted, so
    that the verifier does not expose arbitrary host shell access.
13. As a local operator, I want JSON Contract Artifacts for each verifier stage,
    so that a deployment decision can be audited after the run.
14. As a local operator, I want a summary artifact that records pass, fail, and
    warning states, so that automation can gate promotion without parsing logs.
15. As a local operator, I want host-side status and cleanup commands, so that I
    can recover resources after a launcher crash.
16. As a local operator, I want cleanup to refuse PID kills when command guards
    do not match, so that stale PID files do not terminate unrelated processes.
17. As a local operator, I want deployment state recorded before resources are
    launched, so that cleanup remains possible after partial startup.
18. As a local operator, I want cleanup to run outside the Hermetic Rootfs, so
    that it can see host PIDs, ports, containers, and task roots.
19. As a Monarch maintainer, I want GLM-5.2 verification to follow the Local Run
    Ladder vocabulary, so that it fits existing Monarch operational practice.
20. As a Monarch maintainer, I want trusted verifier code to run through the
    Hermetic Rootfs, so that local Python and toolchain behavior are
    reproducible.
21. As a Monarch maintainer, I want bwrap task sandboxes to be stricter than
    `scripts/run`, so that model-authored code cannot write to the checkout.
22. As a Monarch maintainer, I want bwrap task sandboxes to default to no
    network and no GPU, so that generated code has the smallest useful
    authority.
23. As a Monarch maintainer, I want Docker or Harbor only when an official
    benchmark contract requires it, so that local benchmarks do not take an
    unnecessary dependency on containers.
24. As a benchmark operator, I want Harbor integrated for Terminal-Bench 2, so
    that terminal-agent behavior uses the benchmark's native task abstraction.
25. As a benchmark operator, I want SWE-bench Verified to preserve official
    per-instance Docker images, so that conformance scores remain meaningful.
26. As a benchmark operator, I want HumanEval and MBPP to run in bwrap by
    default, so that generated code is isolated without requiring Docker when
    the harness does not require it.
27. As a benchmark operator, I want GSM8K and AIME profiles separated from
    Codex tool-calling profiles, so that reasoning benchmarks are not confused
    with coding-agent readiness.
28. As a benchmark operator, I want thinking-enabled and thinking-disabled math
    runs separated, so that published-score comparisons are not misleading.
29. As a benchmark operator, I want RULER and needle-smoke long-context checks,
    so that the advertised context window is validated before expensive runs.
30. As a benchmark operator, I want a prepare stage, so that datasets, harnesses,
    image digests, endpoint availability, and gold paths are validated before
    scoring.
31. As a benchmark operator, I want gold-path checks for official harnesses, so
    that a failed model run is not confused with a broken benchmark setup.
32. As a benchmark operator, I want benchmark failures classified separately
    from infrastructure failures, so that model quality metrics are not polluted
    by environment outages.
33. As a benchmark operator, I want conformance mode to be manifest-driven, so
    that command-line overrides cannot change the execution condition being
    compared to a published score.
34. As a benchmark operator, I want every scored sample to include prompt hash,
    dataset revision, harness revision, endpoint, decoding profile, latency,
    usage, and result state, so that results can be reproduced and audited.
35. As a benchmark operator, I want a no-Kubernetes local architecture, so that
    the first deployable system can run on one developer-controlled machine.
36. As a benchmark operator, I want optional Docker validation only for
    Docker-backed suites, so that bwrap-backed calibration is not blocked by a
    missing container runtime.
37. As a benchmark operator, I want Harbor task containers to use an explicit
    local host route to reach the adapter, so that container networking is
    recorded and reproducible.
38. As a benchmark operator, I want local benchmark run state to be resumable, so
    that long runs can skip already completed task results when manifests still
    match.
39. As a benchmark operator, I want local benchmark cleanup to track bwrap task
    processes and task roots, so that interrupted runs do not leave stale
    sandboxes.
40. As a benchmark operator, I want bwrap sandbox smoke tests, so that isolation
    properties are proven before generated code is executed.
41. As an evaluator, I want published-score manifests to cite primary sources,
    so that conformance claims are tied to authoritative score definitions.
42. As an evaluator, I want missing published-score manifest entries to fail
    conformance before inference starts, so that incomplete comparisons do not
    become accidental claims.
43. As an evaluator, I want smoke, calibration, and conformance modes separated,
    so that quick infrastructure checks do not masquerade as quality claims.
44. As an evaluator, I want Terminal-Bench 2 smoke before full calibration, so
    that Harbor integration failures are found cheaply.
45. As an evaluator, I want HumanEval, MBPP, GSM8K, AIME, and long-context
    suites configured independently, so that prompt, scoring, and extraction
    differences are preserved.
46. As an evaluator, I want usage and latency recorded for both model and tool
    calls, so that quality and operational cost can be analyzed together.
47. As an evaluator, I want benchmark archives to preserve run summaries and
    Contract Artifacts, so that a historical run can be inspected without live
    services.
48. As a future maintainer, I want docs to explain which components are in the
    inference hot path, so that Monarch is not accidentally inserted where
    Dynamo/SGLang should own serving.
49. As a future maintainer, I want docs to identify which pieces are verifier
    scaffolding, so that they are not mistaken for production Codex tools.
50. As a future maintainer, I want implementation tickets split by seam, so that
    agents can work independently without overwriting each other.

## Implementation Decisions

- The first deployable inference topology is Codex or verifier to Responses
  adapter to Dynamo frontend to SGLang GLM-5.2 workers.
- The Responses adapter is the only Codex-facing protocol boundary. Codex does
  not call Chat Completions directly.
- The adapter supports `GET /v1/models` and `POST /v1/responses`.
- The adapter translates Responses `instructions`, `input`, `tools`,
  `tool_choice`, and `max_output_tokens` into Chat Completions equivalents.
- The adapter translates Chat text deltas, tool-call deltas, finish reasons,
  and usage into a Responses-compatible result and SSE stream.
- The adapter injects `chat_template_kwargs.enable_thinking=false` by default
  for the Codex tool-calling profile.
- Explicit caller-provided chat-template arguments are preserved.
- Process-local `previous_response_id` state is acceptable for the first
  deployable adapter, with a documented single-process or sticky-routing
  requirement.
- Unknown previous response IDs fail explicitly.
- Mixed text and tool-call streaming must keep stable and unique output item
  indexes.
- The serving verifier is the highest test seam for Codex readiness. It checks
  the external Chat endpoint, the Responses adapter, and model/tool behavior
  through public HTTP interfaces.
- Synthetic verifier tools are the first tool runtime. They are typed,
  allowlisted, and produce structured success or error payloads.
- Terminal-style verifier tools are virtual. They emulate command execution,
  file reads, and file writes inside a synthetic workspace rather than exposing
  the host shell.
- The deployment helper owns host-side manifest, status, and cleanup behavior.
  It does not enter the Hermetic Rootfs because it must observe host resources.
- Cleanup records every host-observable resource needed to recover from partial
  startup or control-plane crashes.
- Monarch is not in the initial model-token hot path. Monarch's role is
  Local Run orchestration, monitoring, telemetry, supervision, and cleanup
  evidence around the serving path.
- The benchmark verifier is a local evaluation platform, not a pile of
  unrelated scripts.
- Kubernetes, KubeRay, Kueue, and cluster-native jobs are out of the local
  benchmark runner.
- Trusted benchmark verifier code runs through the Hermetic Rootfs.
- A stricter bwrap task backend is used for model-authored code when the
  verifier owns the execution contract.
- The bwrap backend creates a fresh task root with read-only input and separate
  writable work, output, and temporary directories.
- Bwrap task sandboxes hide GPUs by default and disable network by default for
  generated-code execution.
- Docker or Harbor remains the conformance backend when the benchmark's
  official scoring contract includes a specific container image or provider.
- Harbor is the preferred harness for Terminal-Bench 2 and agent-in-container
  suites.
- HumanEval and MBPP use bwrap by default unless a pinned harness revision
  requires Docker.
- GSM8K, AIME, RULER, needle-smoke, and lm-evaluation-harness-style static runs
  use Chat mode, not the Codex tool-calling profile.
- Codex readiness and published benchmark conformance are different profiles.
- Published conformance requires a manifest with primary-source scores,
  matching model identity, matching profile, matching benchmark revision,
  matching prompt template, matching decoding profile, and explicit tolerance.
- Conformance mode reads backend selection from the pinned manifest and rejects
  backend overrides that would change score conditions.
- Benchmark results are local files for the first deployment, with run-scoped
  result directories and file-backed cleanup ledgers.
- Optional local Temporal can be added later as an outer durable scheduler, but
  it must not move serving or sandbox execution into Kubernetes.

## Testing Decisions

- Tests should target external behavior and contract artifacts, not private
  implementation details.
- The serving adapter should be tested through request conversion, response
  conversion, streaming SSE event conversion, and continuation behavior.
- Adapter tests should include text-only responses, tool-call responses,
  streaming tool-call deltas, mixed text plus tool calls, usage mapping, and
  function-call-output continuation.
- The serving verifier should be tested through parser and acceptance behavior
  without requiring a live GLM-5.2 deployment.
- The terminal coding smoke should be tested as a behavior contract: initial
  test failure, file read, file write, successful later test run, and final
  answer.
- Tool errors should be conversation-level tool outputs rather than HTTP errors,
  so the model can recover inside the agent loop.
- The deployment helper should be tested for stale PID handling, command-guarded
  cleanup refusal, reverse-order cleanup, selector cleanup, and manifest
  writing.
- Rootfs environment passthrough should be tested for every documented adapter
  variable.
- Bwrap task sandbox tests should prove generated code can write inside the task
  workdir, cannot write to the checkout, and cannot access the network when
  network is disabled.
- Benchmark verifier tests should validate manifest loading, backend selection,
  conformance override rejection, failure taxonomy, artifact writing, and resume
  behavior.
- Harbor integration tests should use small pinned smoke tasks and assert that
  trial artifacts are copied into the run-scoped result directory.
- HumanEval and MBPP tests should use known-good and known-bad fixtures before
  model-generated code is scored.
- GSM8K and AIME tests should focus on prompt rendering, final-answer
  extraction, normalization, and scoring.
- Long-context tests should start with deterministic needle-smoke before RULER
  because it catches context plumbing failures cheaply.
- Published conformance tests should fail before inference when the published
  score manifest is missing a required field.
- A live GLM-5.2/Dynamo/SGLang deployment is not required for unit tests. Live
  endpoint runs are promotion evidence, not the only verification seam.
- Prior art in the repo includes the Local Run Ladder, Contract Artifacts,
  Hermetic Rootfs entrypoint, Capacity Verifier failure classification, and
  focused Python tests for GLM-5.2 verifier, adapter, and deployment helpers.

## Out of Scope

- Replacing Dynamo's KV-aware routing or SGLang inference engine.
- Putting Monarch in the initial SSE byte stream or model-token hot path.
- Building a full OpenAI Responses API implementation beyond Codex-compatible
  text, streaming, function-call, and continuation behavior.
- Exposing arbitrary host shell or filesystem tools to the model.
- Running a live GLM-5.2 cluster as part of unit tests.
- Claiming published benchmark conformance from smoke, partial, or
  profile-mismatched runs.
- Using Kubernetes, KubeRay, Kueue, or cluster-native jobs for the local
  benchmark runner.
- Treating Docker as mandatory for bwrap-capable local suites.
- Replacing official Docker-backed benchmark environments with bwrap when doing
  published conformance comparisons.
- Persisting adapter conversation state across adapter restarts in the first
  implementation.
- Implementing a distributed benchmark control plane before the local runner is
  proven.

## Further Notes

- Use `execution-prompt.md` as the main execution guidance for agents running
  this workstream end-to-end.
- The current local implementation already includes focused verifier, adapter,
  deployment, and test scaffolding. Remaining agent work should treat this spec
  as the canonical tracker summary and the detailed design documents as
  supporting material.
- The response adapter and verifier currently target `zai-org/GLM-5.2`.
- The initial Codex profile should use Responses streaming, tools enabled,
  temperature zero, and thinking disabled.
- Reasoning and published benchmark profiles may use Chat mode and
  thinking-enabled settings when the official GLM-5.2 source used that profile.
- The bwrap task backend should reuse Monarch's Hermetic Rootfs but must be
  task-scoped and stricter than the normal trusted `scripts/run` gateway.
- The highest useful test seam for this feature is the local serving verifier
  plus benchmark verifier command surfaces. Lower-level helper tests are useful
  only when they preserve those external contracts.
