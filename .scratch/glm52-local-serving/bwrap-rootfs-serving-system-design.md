# GLM-5.2 Bwrap Rootfs Serving System Design

Status: draft

Created: 2026-08-17

## Purpose

This document describes the current Monarch-local GLM-5.2 serving machinery and
the design it is converging on. It covers the schema-owned bwrap-rootfs SGLang
runtime, the parent SGLang -> Dynamo -> Responses inference lifecycle, and the
supporting benchmark/verifier infrastructure.

The design goal is repeatable local inference evidence: launch GLM-5.2 from a
governed rootfs, connect Dynamo to that exact SGLang instance, connect the
Responses adapter to that exact Dynamo frontend, prove real inference through
each public API, and tear the run down cleanly. The system must never turn
fixture evidence, default-port probes, fake adapters, or placeholder benchmark
results into completion evidence.

## First Principle

No fallback. Fail fast, fail loud.

The serving stack must not use ambient services, default ports, host Python
packages, implicit model IDs, fixture endpoints, fake Responses routing, or
alternate URLs after a failure. Every executable value must come from a
validated schema or a materialized config derived from that schema. Any drift
must fail before launch when possible, and otherwise fail with a concrete
Contract Artifact.

## Current State

The durable implementation is split across these files:

- `scripts/glm52_sglang_runtime.py`: schema-owned SGLang runtime,
  preparation, launch, probe, repeat, and teardown.
- `scripts/glm52_inference_runtime.py`: parent inference runtime for SGLang,
  Dynamo, and the Responses adapter.
- `scripts/rootfs/enter_rootfs.sh`: bwrap entrypoint and resolved mount-plan
  emitter.
- `.scratch/glm52-local-serving/config/sglang-local.yaml`: portable declared
  SGLang config.
- `.scratch/glm52-local-serving/config/inference-local.yaml`: portable declared
  parent inference config.
- `scripts/glm52_responses_adapter.py`: OpenAI Responses adapter over a Chat
  Completions upstream.
- `scripts/glm52_serving_verifier.py`: Chat and Responses health/tool-call
  verifier.
- `scripts/glm52_benchmark_verifier.py` and
  `scripts/glm52_bwrap_task_runner.py`: local benchmark and code-sandbox
  infrastructure.

The SGLang runtime is the most hardened piece. It validates declared YAML,
materializes concrete launch YAML, emits and validates the bwrap/rootfs plan,
prepares an in-rootfs SGLang venv, prepares the Hugging Face model cache,
probes `/v1/models`, `/generate`, `/v1/completions`, and
`/v1/chat/completions`, writes process records, emits crash diagnostics, and
tears down by owned process group.

The parent inference runtime now encodes the intended lifecycle and dependency
contract. It materializes SGLang, Dynamo, and Responses component URLs, ports,
commands, process-record paths, and artifact paths. It also encodes the current
understanding that `dynamo.sglang` is an integrated worker path, not an HTTP
bridge to an already-running SGLang OpenAI endpoint.

Live completion evidence is still not present. A successful run needs real
SGLang model inference, Dynamo readiness against that SGLang instance,
Responses non-streaming and streaming inference, tool-call verification, and
clean teardown evidence from the same parent run.

## Project Home

The bwrap-rootfs SGLang/Dynamo serving infrastructure should become a material
repo project named `ginkgo/`. That directory is the durable home for portable
declared configs, local-environment templates, schema documentation, launch
manifests, operator workflow docs, and verification specs for the GLM-5.2 local
serving stack.

`ginkgo/` should not own generated run state. Contract Artifacts still belong
under `glm52-serving-results/<run-id>/`, and mutable host state still belongs
under ignored run, temp, and cache roots. The project directory describes and
validates those roots; it does not become the cache.

Reusable launcher and verifier entrypoints may remain under `scripts/` while
they are shared with existing Monarch tooling. In that model, `scripts/` owns
executable entrypoints and `ginkgo/` owns the serving project contract those
entrypoints implement. The current `.scratch/glm52-local-serving/` specs and
configs are the incubation location; durable material should move into
`ginkgo/` as part of the next cleanup.

The project directory should make ownership visible:

```text
ginkgo/
  README.md
  configs/
    sglang-glm52.yaml
    inference-glm52.yaml
    smoke-qwen3-dense.yaml
    smoke-qwen3-moe.yaml
  local-env/
    template.yaml
  schemas/
    sglang-runtime.md
    inference-runtime.md
    sandbox-runtime.md
  profiles/
    sandbox-only.yaml
    cuda-kernel.yaml
    serving-smoke-dense.yaml
    serving-smoke-moe.yaml
    glm52.yaml
  manifests/
    dependency-contract.yaml
    optimized-kernels.yaml
    model-cache-contract.yaml
  docs/
    operator-workflow.md
    verification-ladder.md
    evidence-boundary.md
```

This layout is descriptive, not a requirement to split files exactly this way.
The important rule is ownership: portable configs, profile definitions,
dependency manifests, sandbox contracts, verification ladders, and operator
docs belong under `ginkgo/`. Machine-local resolver files, generated
materialized YAML, logs, process records, cache contents, venv contents, and
model snapshots do not.

Ginkgo execution plans generated from this design supersede earlier execution
plans for GLM-related workstreams. They do not supersede this document:
`.scratch/glm52-local-serving/bwrap-rootfs-serving-system-design.md` remains the
source design that those plans are generated from. If an older GLM execution
plan conflicts with a Ginkgo plan, follow the Ginkgo plan and update it from
this design rather than reviving the older plan.

## Engineering Components

The system is a set of explicit engineering components, not a pile of launch
helpers:

- **Project contract:** `ginkgo/` owns the durable declared configs,
  local-environment templates, schema docs, launch manifests, operator
  workflow, and verification specs.
- **Schema and materialization layer:** Python schema code validates declared
  YAML, rejects fallback behavior, resolves logical refs through the local
  environment config, allocates run-owned ports, and writes materialized run
  YAML. Materialized YAML is the launch source of truth.
- **Local environment resolver:** machine-local config maps repo, run, temp,
  cache, and rootfs refs to concrete host paths. Portable configs never encode
  absolute host paths.
- **Sandbox layer:** the bwrap rootfs, package/tool environment, host directory
  layout, and rootfs projection form one contract. This layer translates the
  materialized sandbox schema into a concrete bwrap command and emits a
  resolved plan before execution.
- **Dependency environments:** governed rootfs-projected venvs provide SGLang,
  Dynamo, and required helper tools through `uv`-managed package contracts.
- **SGLang backend runtime:** launches GLM-5.2 inside the sandbox on a strict
  run-owned custom port and proves model identity plus real inference.
- **Dynamo integration runtime:** launches only after SGLang probes pass and
  binds to the materialized SGLang component contract.
- **Responses adapter runtime:** launches only after Dynamo probes pass and
  exposes the Responses API over the materialized Dynamo upstream.
- **Process and port ownership layer:** records process identity, validates
  ownership before signals, tears down owned process groups, and proves ports
  are closed after every cycle.
- **Verification and artifact layer:** writes Contract Artifacts under
  `glm52-serving-results/<run-id>/` and separates blocker evidence from
  completion evidence.
- **Benchmark harness layer:** runs Terminal-Bench, SWE-bench, EvalPlus, and
  bwrap task-runner evidence only against a GLM-backed Responses URL from a
  completed parent run.

## Architecture

The system has three lifecycle layers:

```text
host-control parent runner
  -> bwrap-rootfs SGLang backend
  -> local Dynamo frontend + integrated SGLang worker contract
  -> local Responses adapter
  -> verifiers and benchmark adapters
```

The host-control parent owns orchestration. It allocates ports, resolves
machine-local roots, writes materialized configs, starts components in order,
probes each surface, and tears components down in reverse order. Component
scripts may still be runnable independently for focused diagnosis, but
end-to-end inference evidence is valid only when the parent summary proves the
same run ID, ports, model identity, and process ownership.

SGLang runs inside the Monarch bwrap rootfs through the sandbox layer. The repo
is projected read-only, while run, temp, and cache roots are projected
read-write into governed sandbox paths. The launch command uses
`/cache/glm52/venvs/sglang/bin/python -m sglang.launch_server`, never host
Python.

Dynamo and the Responses adapter are host-controlled local processes today.
That is an execution-domain choice, not a fallback. Their command lines,
upstream URLs, model names, ports, logs, and process records must still come
from `materialized-inference.yaml`.

## Configuration Model

There are three different configuration scopes.

The declared config is human-authored and portable. It may use logical refs:
`repo://`, `cache://`, `temp://`, `run://`, `rootfs://`, and `component://`.
It must not encode workstation-specific absolute host paths.

The local environment config is machine-local resolver input. It maps logical
roots to concrete host paths and rootfs locations. Tracked examples are
copy-and-fill templates; operators provide concrete absolute paths outside the
portable declared runtime config.

The materialized config is machine-written for one run. It contains concrete
ports, URLs, argv arrays, environment maps, process-record paths, artifact
paths, and resolved local evidence. It is the only launch source for a live
run.

All commands are structured argv arrays. Shell strings are invalid at the
schema boundary.

## Port Ownership

Every live component uses `strict_run_owned_range` allocation from the declared
range. The current portable configs use custom ports in the `19000` range and
explicitly disallow `8000`, `8080`, and `18080`.

Those disallowed ports are not arbitrary. Earlier blocker evidence showed
`127.0.0.1:8000` refusing Chat connections and `127.0.0.1:8080` serving
SearXNG rather than a GLM-backed Responses adapter. The system may mention
those ports in historical evidence, but it must not use them as active serving
defaults.

Port proof has two halves:

- pre-launch: allocated ports are outside the disallowed set and currently
  free;
- post-teardown: every allocated port is closed before a cycle can pass.

## Rootfs and Bwrap Contract

The sandbox layer contains four coupled pieces:

- **rootfs image:** the concrete root filesystem selected by `rootfs://` and
  validated before launch;
- **environment:** system packages, Python, Rust, CUDA user-space bindings,
  `uv`, SGLang, Dynamo, and helper tools that the runtime is allowed to use;
- **host directory structure:** machine-local repo, run, temp, cache, model,
  venv, and results roots resolved from local environment config;
- **rootfs projection:** the exact sandbox paths, mount modes, cwd, device
  bindings, and environment values visible to the launched process.

These pieces are one contract. A launch is invalid if the materialized config
names one host/rootfs/cache structure but the emitted bwrap plan projects a
different one.

`scripts/rootfs/enter_rootfs.sh` owns the bwrap translation boundary. It
supports an `--emit-plan` mode controlled by `MONARCH_ROOTFS_EMIT_PLAN_ONLY=1`.
In that mode it resolves the rootfs path, mounts, cwd, environment, device
projection, and inner argv without executing the payload.

The host directory structure should be explicit and boring:

- a repo checkout root, projected read-only to `/workspace/monarch`;
- a run root, projected read-write to `/run/glm52`;
- a temp root, projected read-write to `/tmp/glm52`;
- a cache root, projected read-write to `/cache/glm52`;
- venv roots below `/cache/glm52/venvs/`;
- Hugging Face cache below `/cache/glm52/hf-home`;
- SGLang cache below `/cache/glm52/sglang`;
- result artifacts under `glm52-serving-results/<run-id>/`.

The portable project config describes those logical roots. The local
environment config resolves them to host paths. The materialized config records
the resolved host paths for one run and the expected sandbox projection.

The SGLang runtime validates the emitted plan before launch. Validation checks
at least:

- the resolved rootfs path matches `rootfs://monarch-default`;
- the repo projection is read-only;
- the sandbox cwd is `/workspace/monarch`;
- the emitted inner argv equals the materialized SGLang inner argv;
- required environment values match, including `CUDA_VISIBLE_DEVICES`;
- `HF_HOME` and `SGLANG_CACHE_DIR` are projected into the governed cache paths;
- required mounts exist for `/run/glm52`, `/tmp/glm52`, `/cache/glm52`,
  `/cache/glm52/venvs/sglang`, `/cache/glm52/hf-home`, and
  `/cache/glm52/sglang`;
- mount modes match the materialized sandbox model.

The rootfs entrypoint also preserves SGLang and Transformers cache variables
through the sandbox and de-duplicates repeated sandbox directory and NVIDIA
device bindings. These are part of the serving contract because SGLang startup
and model-cache reuse depend on stable cache projection.

The sandbox environment must be dependency-complete. Missing tools or packages
are not repaired by host fallback. If SGLang, Dynamo, `uv`, CUDA bindings,
model-cache tooling, or diagnostic helpers are absent from the rootfs-projected
environment, preparation fails and records the missing contract item. The
verifier should include a dependency-specific check so failures identify the
tool or package boundary that drifted.

## Contract Materialization Actions

The sandbox contract needs a materialization ladder that works across different
host settings. The ladder should be light enough to run before GLM-5.2 scale
serving, but strong enough to prove that the rootfs, mount projection, package
environment, optimized kernels, SGLang server, and teardown path are ready for
real inference.

The ladder is a `ginkgo/` project contract. Each action should be represented
by tracked schema, profile, manifest, or operator documentation under
`ginkgo/`, with generated evidence written to the run's result directory. The
implementation entrypoints may live in `scripts/`, but their accepted inputs
and verification obligations are owned by `ginkgo/`.

The ladder has these actions.

1. **Host capability survey.** Detect and record the host facts that affect the
   bwrap runtime:
   - candidate locations for rootfs, cache, temp, run, model, and results
     roots;
   - free space and inode availability for each candidate root;
   - filesystem type and mount restrictions that affect large model caches,
     venvs, Unix sockets, file locks, and executable bits;
   - writable shared-memory options, including `/dev/shm` size and any declared
     alternate tmpfs or host directory used for sandbox shared memory;
   - user namespace and `bwrap` support;
   - local GPU count, NVIDIA driver visibility, CUDA device nodes, and driver
     library paths;
   - loopback networking policy and run-owned port availability;
   - host tools needed only to build or enter the rootfs, such as Docker when a
     rootfs build is requested.
2. **Local environment resolution.** Generate or validate a machine-local YAML
   file that maps logical roots to concrete host paths. This is the only config
   layer that may contain absolute host paths. The resolver should reject
   portable declared configs that encode those paths directly.
3. **Rootfs selection or build.** Resolve `rootfs://` to a concrete rootfs path,
   prove it exists or build it, and record the rootfs identity. Validation
   should include permissions, available space, Python and system toolchain
   availability, CUDA user-space compatibility, and whether the selected rootfs
   can see the declared host driver projection.
4. **Host directory creation.** Create the host run, temp, cache, venv,
   Hugging Face, SGLang, shared-memory, and results directories with explicit
   permissions. The action should be idempotent and should fail if an existing
   path has the wrong owner, mode, filesystem behavior, or free-space budget.
5. **Rootfs projection check.** Ask `enter_rootfs.sh` to emit the resolved
   bwrap plan and verify that every declared host path maps to the expected
   sandbox path and mode. This check covers `/workspace/monarch`, `/run/glm52`,
   `/tmp/glm52`, `/cache/glm52`, `/cache/glm52/venvs`,
   `/cache/glm52/hf-home`, `/cache/glm52/sglang`, the selected shared-memory
   projection, GPU device bindings, driver bindings, cwd, environment, and
   inner argv.
6. **Dependency environment preparation.** Create rootfs-projected `uv` venvs
   for serving dependencies. The SGLang venv owns SGLang, PyTorch-facing
   serving dependencies, Transformers, tokenizer libraries, Hugging Face
   tooling, diagnostics, and optimized kernel packages. The Dynamo venv owns
   Dynamo packages and any SGLang worker integration dependency it imports.
   Preparation runs inside the rootfs projection. Host Python and host site
   packages are never used as repair paths.
7. **Dependency contract verification.** Run import, version, help, and
   capability probes inside the rootfs venvs. The verifier should check at
   least:
   - `python`, `uv`, `torch`, `transformers`, `huggingface_hub`, `sglang`, and
     Dynamo package imports;
   - `torch.cuda.is_available()`, device count, device names, CUDA runtime
     version, and a small CUDA tensor operation when GPUs are declared;
   - SGLang launcher help, including schema-owned flags such as
     `--served-model-name`;
   - Dynamo module help for the configured frontend and SGLang worker path;
   - optimized-kernel imports and capability probes for the packages present in
     the declared profile, including Triton, FlashAttention, FlashInfer, and
     any SGLang-specific fused-kernel dependencies;
   - a tiny Triton kernel execution when Triton is installed and GPUs are
     declared;
   - a small attention-kernel smoke when FlashAttention or FlashInfer is
     installed and compatible with the current GPU architecture.
8. **Model-cache smoke preparation.** Prepare lightweight model snapshots
   through the governed Hugging Face cache and validate their index files,
   shard files, tokenizer files, config files, and local resolved paths. This
   proves the cache path, file-lock behavior, and snapshot integrity without
   downloading or launching GLM-5.2.
9. **Materialized command validation.** Materialize the smoke launch configs and
   compare final argv, environment, ports, paths, mounts, cwd, and rootfs plan
   against the materialized YAML before `Popen`. Any translation drift fails
   before launch.
10. **Lightweight serving smoke.** Launch SGLang on strict run-owned custom
    ports with lightweight Qwen3 profiles, run real inference requests, collect
    artifacts, and tear down by owned process group. This proves server
    startup, OpenAI-compatible surfaces, model identity, request handling,
    logs, crash diagnostics, port ownership, and teardown without bringing up
    the GLM-5.2 serving apparatus.
11. **Repeatability check.** Run several launch/probe/teardown cycles from the
    same declared smoke config. A cycle passes only when owned process groups
    are gone, allocated ports are closed, and generated artifacts are complete.

The smoke model matrix should have two SGLang profiles:

- **Dense smoke:** a small Qwen3 dense model, preferably `Qwen/Qwen3-0.6B` when
  it is available and supported by the installed SGLang version. This profile
  is the default low-cost proof of PyTorch CUDA visibility, Transformers model
  loading, tokenizer handling, SGLang OpenAI serving, and teardown.
- **MoE smoke:** the smallest Qwen3 MoE model supported by the installed
  SGLang version and available to the operator's Hugging Face credentials. The
  current expected family is the Qwen3 `30B-A3B` MoE line, which is larger on
  disk than the dense smoke but exercises routing, expert loading, and MoE code
  paths that dense models cannot cover. This profile is opt-in and should have
  explicit disk, memory, GPU, and timeout budgets.

The smoke profiles are readiness evidence for the sandbox and SGLang serving
machinery. They are not GLM-5.2 completion evidence. A successful Qwen3 smoke
means that the rootfs, venvs, CUDA/PyTorch path, optimized kernels, SGLang
launch, request surfaces, artifacts, and teardown are coherent. It does not
prove GLM model compatibility, GLM offloader behavior, GLM memory fit, Dynamo
GLM integration, Responses GLM behavior, or benchmark conformance.

The optimized-kernel checks should be capability-based, not optimistic import
checks. If a declared profile expects Triton, FlashAttention, FlashInfer, or an
SGLang fused kernel, the verifier should run a small operation that exercises
that package on the declared device class. If the package is absent,
incompatible with the GPU architecture, or silently falls back to an unowned
implementation, the profile fails and records the failing kernel boundary.
Profiles may declare that a kernel package is optional, but optional means
"not required for this profile," not "fallback after a required kernel fails."

The host profiles are:

- **Sandbox-only:** validates rootfs selection, directory projection, tools,
  package imports, PyTorch import, and bwrap plan translation without launching
  a serving process.
- **CUDA-kernel:** adds GPU visibility and optimized-kernel capability checks,
  but still does not launch a model server.
- **Dense serving smoke:** launches the Qwen3 dense smoke model through SGLang
  and proves real inference plus clean teardown.
- **MoE serving smoke:** launches the Qwen3 MoE smoke profile to exercise MoE
  and larger-kernel paths when the host has enough disk, memory, GPU capacity,
  and time budget.
- **GLM profile:** uses the same machinery with GLM-5.2 and is the only profile
  that can produce GLM serving completion evidence.

## SGLang Runtime Contract

The SGLang declared config owns:

- served model name: `zai-org/GLM-5.2`;
- model path;
- expected model IDs;
- CUDA visible devices;
- tensor parallelism;
- dtype and KV-cache dtype;
- context length;
- memory and request limits;
- CPU offload;
- SGLang extra args;
- crash dump folder;
- probe payloads;
- repeat count.

Schema-owned flags cannot be repeated in `runtime.extra_args`. The launcher
materializes those flags exactly once and then validates that the final argv
matches the materialized fields.

The preparation path is rootfs-owned:

1. create `/cache/glm52/venvs/sglang`;
2. install SGLang into that venv;
3. apply the GLM-5.2 offloader patch with
   `scripts/glm52_sglang_offloader_patch.py`;
4. probe installed package versions;
5. run `sglang.launch_server --help` and require `--served-model-name`;
6. write preparation records and bwrap plan digests.

The model-cache path downloads through `HF_HOME=/cache/glm52/hf-home` and then
validates that `model.safetensors.index.json` exists, is parseable, and
references present shard files. The live launch must not paper over an
incomplete model cache.

Runtime readiness requires model identity and inference, not just an open port.
`/v1/models` must advertise the served model name and intersect expected model
IDs. Path identities or arbitrary aliases do not count. The runtime then probes
`/generate`, `/v1/completions`, and `/v1/chat/completions`.

On probe failure the runtime sends an owned diagnostic signal before teardown:
`SIGQUIT` to the owned process group, a short flush wait, crash-dump inventory,
and then normal teardown unless debug mode explicitly says to leave the process
running. `leave_running_on_failure` is valid only with debug mode.

## Parent Inference Contract

The parent inference config owns three components:

- `sglang_backend`;
- `dynamo_frontend`;
- `responses_adapter`.

The parent materialization allocates a port for each component and derives:

- SGLang OpenAI base URL;
- Dynamo OpenAI base URL;
- Responses OpenAI base URL;
- component process record paths;
- component log paths;
- component argv arrays;
- component environment maps;
- component artifact paths.

The SGLang component reuses the materialized SGLang slice. It must validate the
SGLang venv and model-cache preparation records before launch.

The Dynamo component launches only after SGLang probes pass. Its upstream is the
materialized SGLang component URL. It must not read an operator-supplied
fallback URL. The current Dynamo package contract is explicit:
`ai-dynamo==1.4.0`, `ai-dynamo-runtime==1.4.0`, `sglang==0.5.17`, and `blake3`.
The Dynamo venv is prepared through `uv` inside the rootfs-projected cache, and
module help contracts are checked for `dynamo.frontend` and `dynamo.sglang`.

The Responses adapter launches only after Dynamo probes pass. Its upstream is
the materialized Dynamo URL. It must prove `/v1/models`, non-streaming
`/v1/responses`, streaming `/v1/responses`, and a tool-call path through the
serving verifier.

Teardown runs in reverse component order. SGLang teardown delegates to the
SGLang runtime process-group validator. Dynamo and Responses teardown validate
owned process records before signaling. A cycle passes only after all owned
ports are closed and orphan checks pass.

## Responses Adapter Contract

The adapter translates the OpenAI Responses API to Chat Completions. It must
support:

- `GET /v1/models`;
- `POST /v1/responses`;
- streaming and non-streaming responses;
- `previous_response_id` continuation state;
- function-call outputs as tool messages;
- Chat Completions tool-call deltas and final responses.

The adapter disables hidden fallback through parent materialization. Active
end-to-end runs pass the upstream URL and served model name from
`materialized-inference.yaml`.

`chat_template_kwargs.enable_thinking` stays false for the current verifier
path. GLM reasoning channels can be modeled later, but the basic tool loop must
first be stable and unambiguous.

## Benchmark and Verification Infrastructure

The benchmark platform is adjacent to serving readiness. It is useful, but it
is not a substitute for live inference evidence.

There are two execution backends:

- `bwrap_rootfs` for local code-generation and fixture-harness execution;
- `harbor_local_docker` for Terminal-Bench 2 and SWE-bench style Docker
  suites.

The bwrap task runner creates fresh task roots, denies network by default,
restricts writable paths, and records task artifacts. The benchmark verifier
archives Contract Artifacts, distinguishes fixture scoring from official
harness attempts, and prevents published-score placeholders from being filled
from incompatible evidence.

Harbor/Docker smoke artifacts can prove Docker and Harbor setup. They do not
prove GLM readiness unless they run against a valid GLM-backed Responses URL
from the parent serving run.

## Artifact Model

Every serving run should write machine-readable Contract Artifacts under
`glm52-serving-results/<run-id>/`. The minimum parent run set is:

- declared config copy;
- materialized inference config;
- resolved local paths;
- per-component materialized config slices;
- resolved bwrap plan;
- preparation records;
- stdout and stderr logs;
- process records;
- readiness probes;
- inference probes;
- diagnostic summary;
- teardown summary;
- final parent summary.

Generated artifacts under `.scratch/glm52-local-serving/{run,tmp,cache}/` are
local scratch state and remain ignored. Durable specs, configs, manifests,
issues, and docs are tracked.

## Failure Model

The system should fail before launch for schema, path, port, command, rootfs
plan, preparation, or dependency drift. It should fail during launch for
process exit, readiness timeout, fatal startup logs, model identity mismatch,
or probe failure. It should fail during teardown for process-record mismatch,
unknown process ownership, uncleared process groups, or open ports.

Failure artifacts should say which gate failed and why. They must not mark the
run complete. A run can be useful blocker evidence without being completion
evidence.

## Security and Isolation

The SGLang serving process runs in the bwrap rootfs with:

- read-only repo projection;
- explicit read-write run, temp, and cache mounts;
- governed cache projection for venv and model assets;
- host loopback networking only as declared;
- GPU device and driver projection through the rootfs entrypoint.

The code-generation benchmark backend uses stricter task sandboxes than the
serving runtime. It should not inherit host checkout write access or network
unless a task explicitly declares that requirement and the runner validates it.

## Verification Ladder

The intended acceptance ladder is:

1. **Schema:** declared YAML and local environment YAML parse and reject unknown
   fields, fallback flags, disallowed ports, and absolute host paths in
   portable configs.
2. **Materialization:** materialized SGLang and parent inference configs derive
   every port, URL, argv, env, and artifact path from schema inputs.
3. **Rootfs Plan:** `enter_rootfs.sh` emits a resolved plan, and the launcher
   validates the plan against the materialized config.
4. **Preparation:** SGLang and Dynamo venv/package contracts are installed and
   verified in the governed rootfs/cache projection.
5. **SGLang Live:** SGLang starts on an owned custom port and passes model,
   generate, completions, and chat probes.
6. **Dynamo Live:** Dynamo launches against that exact SGLang instance and
   passes model and chat probes.
7. **Responses Live:** the adapter launches against that exact Dynamo frontend
   and passes model, non-streaming, streaming, and tool-call probes.
8. **Repeatability:** at least three launch/probe/teardown cycles pass from the
   same declared config.
9. **Teardown:** all owned process groups are gone, all allocated ports are
   closed, and orphan scans pass.
10. **Benchmark Readiness:** Harbor and bwrap benchmark paths run against the
    GLM-backed Responses URL when benchmark evidence is requested.

Gates 1-4 and much of the SGLang lifecycle around gate 5 are backed by local
unit and fake-process evidence today. That evidence proves the contract logic,
not live serving readiness. Gate 5 still depends on a real successful SGLang
GLM-5.2 process on this host. Gates 6-10 remain live evidence requirements.

## Open Design Risks

- Dynamo integration is the least proven live component. The design encodes
  the integrated `dynamo.sglang` worker contract, but a full successful local
  Dynamo run still needs live evidence.
- SGLang package and flag surfaces can drift. The help-contract checks are
  necessary, but the runtime should keep validating actual installed help text
  before every launch.
- The offloader patch is version-sensitive. The patch helper is idempotent and
  evidence-producing, but a future SGLang offloader change should fail loudly
  rather than silently applying the wrong patch.
- Large model cache preparation can leave partial snapshots. The snapshot
  validator must remain part of preflight.
- Debug mode can intentionally leave processes alive. That path must stay
  explicit, local-only, and clearly marked as not repeatability evidence.

## Non-Goals

- Do not fill published benchmark placeholders from model cards, articles,
  fixture harnesses, or incompatible local runs.
- Do not treat `/v1/models` alone as live readiness.
- Do not use default ports as active serving defaults.
- Do not convert the bwrap rootfs into a generic mutable host environment.
- Do not route around Dynamo by calling an already-running Chat endpoint in the
  parent end-to-end path.
- Do not claim benchmark conformance from bwrap fixture scoring.

## Operator Workflow

The intended operator flow is:

1. Copy a local environment template and fill concrete host paths.
2. Prepare the SGLang venv in the rootfs cache projection.
3. Prepare and validate the GLM-5.2 model cache.
4. Materialize the SGLang runtime and inspect the bwrap plan.
5. Run SGLang launch/probe/teardown repeatability on custom ports.
6. Prepare the Dynamo venv and validate module help contracts.
7. Materialize the parent inference config.
8. Run the parent SGLang -> Dynamo -> Responses lifecycle.
9. Run benchmark/verifier adapters only against the parent Responses URL.
10. Archive the parent summary and Contract Artifacts as completion evidence
    only if every required gate passes.

## Current Completion Boundary

The machinery is now a credible schema-owned local serving platform, but the
workstream is not complete. The remaining completion boundary is live evidence:
a real GLM-5.2 SGLang backend, a Dynamo frontend attached to it, a Responses
adapter attached to Dynamo, real inference probes through all surfaces, repeated
clean teardown, and benchmark runs against that GLM-backed Responses URL.
