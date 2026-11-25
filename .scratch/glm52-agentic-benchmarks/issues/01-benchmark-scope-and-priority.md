# Decide Benchmark Scope and Priority

Type: grilling
Status: resolved
Blocked by:

## Question

Which benchmark families belong in the first GLM-5.2 agentic benchmark
campaign, and which are deferred to later platform expansion?

## Context

The existing Ginkgo benchmark manifest already covers these first-party local
families:

- `needle-smoke`
- `gsm8k`
- `aime`
- `humaneval`
- `mbpp`
- `ruler`
- `terminal-bench-2`
- `swe-bench-verified`

The proposed broader platform also names reasoning, coding, engineering,
stateful-tool, browser, safety, desktop, and professional-artifact suites.
Running all of them at once would blur harness defects, endpoint defects,
resource limits, and benchmark-specific scoring issues.

## Decision Needed

Choose the first campaign shape:

- **Recommended:** representative pilot across families:
  `needle-smoke`, `gsm8k`, `aime`, `humaneval`, `mbpp`,
  `terminal-bench-2`, `swe-bench-verified`, one stateful-tool pilot, and one
  GDPval proxy pilot.
- **Narrow:** only the suites already represented in
  `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`.
- **Broad:** add browser, safety, desktop, and professional-artifact suites in
  the first campaign.

## Resolution

Use the representative pilot as the first campaign. The v1 campaign validates
platform breadth across the existing local verifier surface, one stateful-tool
pilot, and one professional-artifact proxy without turning every benchmark
family into first-release scope.

Selected suites and evidence classes:

- `needle-smoke`: smoke. This proves the endpoint, artifact plumbing, and
  long-context request path are usable; it is not reportable score evidence.
- `gsm8k`: reportable score when the dataset revision, prompt template,
  decoding profile, and deterministic exact-match scorer are pinned.
- `aime`: pilot. This is reasoning coverage with a smaller sample and profile
  sensitivity; promote only after prompt and decoding policy are fixed.
- `humaneval`: reportable score when generated code runs in an isolated
  task environment and raw predictions are preserved before scoring.
- `mbpp`: reportable score under the same generated-code isolation contract as
  `humaneval`.
- `ruler`: pilot. This validates long-context scoring beyond the smoke path.
- `terminal-bench-2`: pilot. Use Harbor or local Docker only; it is not a full
  leaderboard run in v1.
- `swe-bench-verified`: pilot. Run a small Harbor/local-Docker smoke first,
  then require explicit authorization for larger campaigns.
- `stateful-tool-pilot`: pilot. Prefer MCP Atlas or tau-bench after endpoint,
  sandbox, and snapshot contracts are pinned.
- `gdpval-proxy`: pilot/proxy. The report must label this as a proxy unless
  ticket 02 proves official reproducibility from public artifacts.

Deferred suites:

- Browser/open-web suites (`GAIA`, `BrowseComp`, `WebArena`,
  `VisualWebArena`, `DeepSearchQA`): defer for missing frozen search/browser
  environment contracts and live-web comparability policy.
- Desktop suites (`OSWorld`, OSWorld 2.0): defer for KVM/VM lifecycle and
  image-release coupling outside v1.
- Safety suites (`AgentDojo`, `AgentHarm`): defer until safety isolation,
  synthetic credential, and egress policy are designed.
- PaperBench and broad research reproduction: defer for multi-container,
  task-specific GPU, and grader isolation requirements.
- Official GDPval: defer unless ticket 02 proves public reproducibility.
- FrontierMath private/held-out parity: defer; public subset experiments must
  be labelled by the exact accessible subset.

Full runs of `terminal-bench-2`, `swe-bench-verified`, `stateful-tool-pilot`,
and any hosted-judge or GPU-heavy suite require explicit user authorization
before launch.

## Acceptance Criteria

- The selected suites are named explicitly.
- Every selected suite has a declared evidence class: smoke, pilot,
  calibration, or reportable score.
- Deferred suites have a reason: missing harness, missing dataset, missing
  judge, missing environment, cost boundary, or intentionally out of v1 scope.
- The decision states whether a full run requires explicit user authorization.
