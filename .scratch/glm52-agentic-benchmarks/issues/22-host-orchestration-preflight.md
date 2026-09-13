# Host Orchestration Preflight

Type: task
Status: ready-for-agent
Blocked by:

## Objective

Make host-control prerequisites explicit and reproducible before launching
Harbor-backed or GPU-bearing benchmark runs.

## Context

The benchmark verifier intentionally splits rootfs execution from host-control
work. Harbor, Docker, process cleanup, and GPU ownership checks are host-control
domains. Earlier runs advanced only when the scratch Harbor venv was prepended
to `PATH`; the default host path did not contain `harbor`.

The verifier must also avoid stale owned SGLang, Responses adapter, Harbor, or
benchmark processes before expensive runs. It must not kill non-owned GPU
processes.

## Requirements

- Add or document a preflight command that checks:
  - selected Harbor executable and version;
  - Docker or podman availability when required by the suite;
  - host route used by containers to reach the Responses adapter;
  - visible GPU count and currently owned GPU processes before GPU-bearing
    launches;
  - active owned GLM52 serving, adapter, Harbor, and benchmark processes;
  - untracked generated caches and run logs are not staged.
- Make the benchmark wrapper consistently discover the pinned scratch Harbor
  venv or fail with a precise message.
- Record the preflight result in benchmark artifacts when a run starts.
- Keep process cleanup scoped to owned processes.

## Files

- Modify if needed: `scripts/glm52_benchmark_verifier.py`
- Modify if needed: `scripts/run_glm52_benchmark_verifier.sh`
- Modify if needed: `.scratch/glm52-local-serving/issues/09-harbor-host-bootstrap.md`
- Test: `python/tests/test_glm52_benchmark_verifier.py`

## Exclusions

- Do not install global host packages.
- Do not kill root-owned or other-user GPU processes.
- Do not run Docker from inside the Monarch bwrap rootfs unless the existing
  docs explicitly classify that command as rootfs-safe.
- Do not stage generated benchmark datasets, harness caches, or run logs.

## Verification

Run focused tests after code changes:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
```

Run the host preflight command in dry-run or check-only mode if implemented.

## Done When

- A missing Harbor, Docker, host route, or GPU prerequisite fails before trial
  execution with a precise error.
- The chosen Harbor path is deterministic and captured in artifacts.
- Owned-process cleanup boundaries are explicit.
