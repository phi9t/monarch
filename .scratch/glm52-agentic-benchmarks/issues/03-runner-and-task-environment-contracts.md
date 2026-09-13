# Decide Runner and Task-Environment Contracts

Type: task
Status: resolved
Blocked by: 01

## Question

What is the stable interface between suite adapters and task-environment
runners?

## Context

The local v1 runner must stay machine-local and file-backed. Current valid
execution domains are:

- `bwrap_rootfs`
- `harbor_local_docker`
- `scripts_run`
- narrowly trusted `host_subprocess`

Future cluster runners may include Kubernetes Jobs, KubeRay workers, KVM
desktop workers, Modal, Daytona, and AWS providers, but those are not part of
v1 execution.

## Decision Needed

Define a runner interface that suite adapters can call without knowing whether
the implementation is local file-backed or future distributed orchestration.

Reconcile that target interface with the concrete runner that exists today:
`scripts/glm52_bwrap_task_runner.py` currently accepts `TaskSpec(run_id,
task_id, input_dir, timeout_seconds, network, gpu, command,
environment_allowlist)` and returns inline stdout/stderr plus return code and
duration. The target platform needs a trial dimension, structured status,
resource-limit policy, path-based stdout/stderr artifacts, and explicit output
artifact discovery.

The interface should cover:

- task root allocation;
- read-only input and writable work/output/tmp paths;
- network policy;
- GPU policy;
- timeout and resource limits;
- environment allowlist;
- cleanup ledger entries;
- immutable task result artifact.

The design must also settle ownership with Ginkgo's current Insula rule:
`ginkgo/README.md` says Insula is the sole bwrap owner. If
`glm52_bwrap_task_runner.py` remains as a direct bwrap argv builder, document
why that is compatible with Insula or make it an Insula adapter instead.

## Resolution

Adopt a small `TaskRunner` interface under the target `ginkgo/eval/` package.
Suite adapters call this interface and never build ad hoc shell commands for
task environments.

The request shape is:

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
network_policy
gpu_policy
resource_limits
command
environment_allowlist
artifact_globs
```

The result shape is:

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

Allowed v1 runner adapters:

- `bwrap_rootfs`: default for verifier-owned static, generated-code, and custom
  tasks that do not require an official container.
- `harbor_local_docker`: official Harbor or Docker-bound suites such as
  Terminal-Bench, SWE-bench, and SkillsBench.
- `scripts_run`: trusted in-rootfs preparation, scoring, and collation.
- `host_subprocess`: narrowly trusted host orchestration, Docker/Harbor setup,
  diagnostics, and cleanup. It is not available to model-authored commands.

`scripts/glm52_bwrap_task_runner.py` is the migration source, not the final
ownership boundary. The first implementation may wrap its current `TaskSpec`
and result shape for compatibility. Before adding a second independent bwrap
argv builder, move the bwrap-specific behavior behind an Insula-compatible
adapter so Ginkgo keeps one owner for sandbox construction and path binding.

Generated code and benchmark tasks never receive:

- host Docker socket access;
- write access to the repository checkout;
- unpinned host environment variables;
- network or GPU access unless the suite manifest explicitly declares it.

Future cluster runners must implement the same request/result contract, so
suite scoring does not change when execution moves from local files to a
distributed worker.

## Acceptance Criteria

- The interface is small enough for every suite adapter to use.
- `bwrap_rootfs` remains the default for verifier-owned generated-code and
  static tasks.
- `harbor_local_docker` remains the backend for official Harbor or
  Docker-bound suites.
- The model-controlled task environment never receives host Docker socket
  access or write access to the repository checkout.
- Future cluster runners can be added as adapters without changing suite
  scoring semantics.
