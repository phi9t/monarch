# GLM-5.2 SGLang Rootfs Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hardened, schema-backed bwrap rootfs contract for local GLM-5.2 SGLang that can prepare dependencies, verify model cache readiness, launch on custom run-owned ports, probe real inference, and tear down repeatedly with no fallback.

**Architecture:** Extend the existing `scripts/glm52_sglang_runtime.py` path with a SGLang-specific rootfs overlay that consumes `scripts/rootfs/rootfs_sandbox_config.py` for bwrap translation and validation. Keep preparation, launch, probe, and teardown as explicit commands with materialized YAML and machine-readable artifacts. Use the existing rootfs entrypoint to emit resolved bwrap plans and reject any drift between schema, plan, argv, env, mounts, and process records.

**Tech Stack:** Python 3.12, dataclasses, `yaml.safe_load`/`yaml.safe_dump`, `subprocess`, `urllib.request`, pytest, bash, Monarch `scripts/run`, bwrap rootfs.

**Spec:** `.scratch/glm52-rootfs-sglang-hardening/spec.md`

## Global Constraints

- No fallback. Fail fast, fail loud.
- Do not use ambient/default GLM serving ports `8000`, `8080`, or `18080`.
- Use strict run-owned port allocation from the declared range.
- Launch commands are generated from materialized YAML only.
- Portable config must not encode absolute host paths in host-layout fields.
- Machine-local absolute host paths are allowed only in local resolver config and resolved evidence.
- Absolute sandbox paths are allowed because the sandbox layout is a rootfs protocol.
- SGLang venv path is `/cache/glm52/venvs/sglang`.
- Hugging Face cache path is `/cache/glm52/hf-home`.
- Do not start SGLang as an implicit downloader; prepare and validate model cache first.
- Do not use `--disable-custom-all-reduce` as a broad first fix.
- Rootfs plan validation must compare concrete host paths, sandbox paths, mode, env, cwd, inner argv, and outer argv.
- Every post-launch failure tears down when `debug_mode=false`.

---

## File Structure

- Modify `scripts/glm52_sglang_runtime.py`
  - Owns GLM-5.2 SGLang schema, local resolver parsing, materialization,
    preparation commands, launch/probe/teardown orchestration, and CLI.
  - Imports the generic bwrap plan module rather than duplicating mount
    translation.
- Modify `scripts/run_glm52_sglang_runtime.sh`
  - Stays a thin host wrapper.
  - Dispatches preparation and live lifecycle commands without hiding host/rootfs
    boundaries.
- Create or modify `python/tests/test_glm52_sglang_runtime.py`
  - Adds red-green unit coverage for schema, preparation records, rootfs overlay
    validation, command drift, probe parsing, and teardown behavior.
- Modify `.scratch/glm52-local-serving/config/sglang-local.yaml`
  - Adds explicit SGLang rootfs overlay fields while keeping host paths logical.
- Modify `.scratch/glm52-local-serving/config/local-environment.example.yaml`
  - Documents machine-local roots and rootfs refs only.
- Use `.scratch/glm52-rootfs-sglang-hardening/issues/*.md`
  - One issue per implementation ticket.

## Public Interfaces

Add or extend these interfaces in `scripts/glm52_sglang_runtime.py`:

```python
@dataclass(frozen=True)
class SglangRootfsOverlaySpec:
    venv_path: str
    hf_home: str
    sglang_cache: str
    telemetry_root: str

@dataclass(frozen=True)
class SglangVenvSpec:
    sandbox_path: str
    packages: list[str]
    python: str

@dataclass(frozen=True)
class ModelCacheSpec:
    hf_home: str
    model_id: str
    revision: str | None
    require_prepared_snapshot: bool

def validate_sglang_rootfs_overlay(
    *,
    config: MaterializedSglangRuntimeConfig,
    plan: dict[str, Any],
) -> None:
    """Reject mount/env/path drift in the SGLang-specific rootfs overlay."""

def prepare_sglang_venv(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Create or update the rootfs-managed SGLang venv and write evidence."""

def prepare_model_cache(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Prepare and validate the rootfs-managed GLM-5.2 model cache."""

def validate_preparation_records(
    *,
    config: MaterializedSglangRuntimeConfig,
) -> None:
    """Reject launch if required SGLang venv or model-cache evidence is absent or stale."""

def run_repeatability_cycles(
    *,
    declared_path: Path,
    local_environment_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Run launch/probe/teardown cycles and return the final summary."""
```

---

### Task 1: Rootfs Overlay Schema and Drift Validation

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `python/tests/test_glm52_sglang_runtime.py`
- Modify: `.scratch/glm52-local-serving/config/sglang-local.yaml`

**Interfaces:**
- Consumes: `MaterializedSglangRuntimeConfig`, `validate_resolved_rootfs_plan(...)`
- Produces: `SglangRootfsOverlaySpec`, `SglangVenvSpec`, `ModelCacheSpec`, `validate_sglang_rootfs_overlay(...)`

- [ ] **Step 1: Write failing tests for overlay schema acceptance**

Add a test that loads `.scratch/glm52-local-serving/config/sglang-local.yaml`,
materializes it with a temp local environment, and asserts the overlay paths are
explicit:

```python
def test_materialized_config_contains_sglang_rootfs_overlay(tmp_path: Path) -> None:
    declared_path = write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY)
    local_env_path = write_local_environment(tmp_path)

    declared = load_declared_spec(declared_path)
    local_env = load_local_environment(local_env_path)
    config = materialize_runtime_config(
        declared=declared,
        local_environment=local_env,
        run_id="overlay-test",
        port=19017,
    )

    assert config.sandbox["sglang"]["venv_path"] == "/cache/glm52/venvs/sglang"
    assert config.sandbox["sglang"]["hf_home"] == "/cache/glm52/hf-home"
    assert config.sandbox["sglang"]["cache"] == "/cache/glm52/sglang"
    assert config.launch["env"]["HF_HOME"] == "/cache/glm52/hf-home"
    assert config.launch["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"
```

- [ ] **Step 2: Write failing tests for overlay rejection**

Add parameterized tests that reject wrong venv path, wrong HF path, absolute host
paths in portable config, and missing overlay fields:

```python
@pytest.mark.parametrize(
    ("needle", "replacement", "match"),
    [
        ("/cache/glm52/venvs/sglang", "/workspace/monarch/.venv-rootfs", "venv_path must be /cache/glm52/venvs/sglang"),
        ("/cache/glm52/hf-home", "/workspace/monarch/.cache/huggingface", "hf_home must be /cache/glm52/hf-home"),
        ("cache_root: cache://glm52-local-serving", "cache_root: /tmp/glm52", "must use logical path refs"),
    ],
)
def test_declared_overlay_rejects_invalid_paths(
    tmp_path: Path,
    needle: str,
    replacement: str,
    match: str,
) -> None:
    declared_path = write_spec(
        tmp_path / "declared.yaml",
        VALID_DECLARED_WITH_OVERLAY.replace(needle, replacement),
    )

    with pytest.raises(RuntimeConfigError, match=match):
        load_declared_spec(declared_path)
```

- [ ] **Step 3: Run tests to verify red**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
```

Expected: fail because overlay fields and `validate_sglang_rootfs_overlay` do
not exist or are not validated yet.

- [ ] **Step 4: Add schema dataclasses and parser**

Add dataclasses and parse functions:

```python
@dataclass(frozen=True)
class SglangRootfsOverlaySpec:
    venv_path: str
    hf_home: str
    sglang_cache: str
    telemetry_root: str


def _parse_sglang_rootfs_overlay(data: Any) -> SglangRootfsOverlaySpec:
    mapping = _require_mapping(data, "sandbox.sglang")
    _reject_unknown(mapping, {"venv_path", "hf_home", "cache", "telemetry_root"}, "sandbox.sglang")
    overlay = SglangRootfsOverlaySpec(
        venv_path=_required_str(mapping, "venv_path", "sandbox.sglang"),
        hf_home=_required_str(mapping, "hf_home", "sandbox.sglang"),
        sglang_cache=_required_str(mapping, "cache", "sandbox.sglang"),
        telemetry_root=_required_str(mapping, "telemetry_root", "sandbox.sglang"),
    )
    if overlay.venv_path != SGLANG_VENV_SANDBOX_PATH:
        raise RuntimeConfigError("venv_path must be /cache/glm52/venvs/sglang")
    if overlay.hf_home != "/cache/glm52/hf-home":
        raise RuntimeConfigError("hf_home must be /cache/glm52/hf-home")
    if overlay.sglang_cache != "/cache/glm52/sglang":
        raise RuntimeConfigError("cache must be /cache/glm52/sglang")
    for name, value in {
        "venv_path": overlay.venv_path,
        "hf_home": overlay.hf_home,
        "cache": overlay.sglang_cache,
        "telemetry_root": overlay.telemetry_root,
    }.items():
        if not value.startswith("/"):
            raise RuntimeConfigError(f"sandbox.sglang.{name} must be an absolute sandbox path")
    return overlay
```

- [ ] **Step 5: Extend materialization**

Materialized config must add:

```python
config.sandbox["sglang"] = {
    "venv_path": "/cache/glm52/venvs/sglang",
    "python": "/cache/glm52/venvs/sglang/bin/python",
    "hf_home": "/cache/glm52/hf-home",
    "cache": "/cache/glm52/sglang",
    "telemetry_root": "/workspace/monarch/.scratch/glm52-local-serving/run",
}
config.launch["env"]["HF_HOME"] = "/cache/glm52/hf-home"
config.launch["env"]["SGLANG_CACHE_DIR"] = "/cache/glm52/sglang"
```

- [ ] **Step 6: Implement overlay rootfs plan validation**

Implement:

```python
def validate_sglang_rootfs_overlay(
    *,
    config: MaterializedSglangRuntimeConfig,
    plan: dict[str, Any],
) -> None:
    validate_resolved_rootfs_plan(config=config, plan=plan)
    sandbox = _require_mapping(config.sandbox, "sandbox")
    sglang = _require_mapping(sandbox.get("sglang"), "sandbox.sglang")
    env = _require_mapping(plan.get("env"), "rootfs_plan.env")
    if env.get("HF_HOME") != sglang["hf_home"]:
        raise RuntimeConfigError("rootfs plan HF_HOME does not match materialized config")
    if env.get("SGLANG_CACHE_DIR") != sglang["cache"]:
        raise RuntimeConfigError("rootfs plan SGLANG_CACHE_DIR does not match materialized config")
    mounts = _mounts_by_sandbox_path(plan)
    for required in (sglang["venv_path"], sglang["hf_home"], sglang["cache"]):
        if required not in mounts:
            raise RuntimeConfigError(f"rootfs plan missing SGLang mount: {required}")
```

- [ ] **Step 7: Update declared example**

Add:

```yaml
sandbox:
  kind: bwrap_rootfs
  rootfs_ref: rootfs://monarch-default
  cwd: /workspace/monarch
  network: host_loopback_required
  gpu: required
  sglang:
    venv_path: /cache/glm52/venvs/sglang
    hf_home: /cache/glm52/hf-home
    cache: /cache/glm52/sglang
    telemetry_root: /workspace/monarch/.scratch/glm52-local-serving/run
```

- [ ] **Step 8: Run focused tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
scripts/run python -m pytest python/tests/test_rootfs_enter_plan.py python/tests/test_rootfs_sandbox_config.py -q
```

Expected: all pass.

- [ ] **Step 9: Review diff**

Run:

```sh
git diff -- scripts/glm52_sglang_runtime.py python/tests/test_glm52_sglang_runtime.py .scratch/glm52-local-serving/config/sglang-local.yaml
```

Confirm no absolute host paths were added to portable config.

---

### Task 2: Prepare and Verify SGLang Venv and Model Cache

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `scripts/run_glm52_sglang_runtime.sh`
- Modify: `python/tests/test_glm52_sglang_runtime.py`

**Interfaces:**
- Consumes: `validate_sglang_rootfs_overlay(...)`, `validate_model_snapshot(...)`
- Produces: `prepare_sglang_venv(...)`, `prepare_model_cache(...)`, `validate_preparation_records(...)`

- [ ] **Step 1: Write failing tests for venv preparation command construction**

Add a test with fake subprocess runner:

```python
def test_prepare_sglang_venv_uses_rootfs_managed_python_and_uv(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='{"python": "/cache/glm52/venvs/sglang/bin/python"}', stderr="")

    record = prepare_sglang_venv(
        declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
        local_environment_path=write_local_environment(tmp_path),
        run_id="prepare-venv-test",
        run=fake_run,
    )

    flattened = " ".join(calls[0])
    assert "/cache/glm52/venvs/sglang" in flattened
    assert "sglang[all]" in flattened
    assert record["venv"]["python"] == "/cache/glm52/venvs/sglang/bin/python"
```

- [ ] **Step 2: Write failing tests for model preparation requiring HF_HOME**

Add:

```python
def test_prepare_model_cache_uses_rootfs_hf_home(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc"}',
            stderr="",
        )

    record = prepare_model_cache(
        declared_path=write_spec(tmp_path / "declared.yaml", VALID_DECLARED_WITH_OVERLAY),
        local_environment_path=write_local_environment(tmp_path),
        run_id="prepare-model-test",
        run=fake_run,
        snapshot_validator=lambda path: {"snapshot_path": str(path), "shard_count": 1, "missing_shard_count": 0},
    )

    assert any("HF_HOME=/cache/glm52/hf-home" in " ".join(call) for call in calls)
    assert record["model_cache"]["missing_shard_count"] == 0
```

- [ ] **Step 3: Write failing tests for stale or missing preparation records**

Add:

```python
def test_validate_preparation_records_rejects_missing_records(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19021)

    with pytest.raises(RuntimeConfigError, match="missing SGLang venv preparation record"):
        validate_preparation_records(config=config)
```

- [ ] **Step 4: Run tests to verify red**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
```

Expected: fail because preparation functions do not exist or do not write
records.

- [ ] **Step 5: Add preparation record paths to materialization**

Materialized config artifacts must include logical and resolved entries:

```python
config.artifacts["preparation"] = {
    "sglang_venv_record": "run://<run_id>/sglang-venv.json",
    "model_cache_record": "run://<run_id>/model-cache.json",
}
config.resolved_paths["preparation"] = {
    "sglang_venv_record": "<absolute host path>",
    "model_cache_record": "<absolute host path>",
}
```

- [ ] **Step 6: Implement `prepare_sglang_venv`**

Build the inner command as structured argv:

```python
inner_argv = [
    "uv",
    "venv",
    "/cache/glm52/venvs/sglang",
    "--python",
    "3.12",
]
install_argv = [
    "/cache/glm52/venvs/sglang/bin/python",
    "-m",
    "uv",
    "pip",
    "install",
    "sglang[all]",
]
help_argv = [
    "/cache/glm52/venvs/sglang/bin/python",
    "-m",
    "sglang.launch_server",
    "--help",
]
```

Run these through the rootfs gateway with emitted plan validation before the
heavy install command. Write a JSON record:

```json
{
  "schema_version": 1,
  "run_id": "prepare-venv-test",
  "venv": {
    "path": "/cache/glm52/venvs/sglang",
    "python": "/cache/glm52/venvs/sglang/bin/python",
    "packages": ["sglang[all]"]
  },
  "rootfs": {
    "recipe_sha256": "<digest>"
  },
  "checks": {
    "served_model_name_flag": true
  }
}
```

- [ ] **Step 7: Implement `prepare_model_cache`**

Use the SGLang venv Python and fixed HF cache env:

```python
inner_argv = [
    "/cache/glm52/venvs/sglang/bin/python",
    "-c",
    MODEL_CACHE_PREPARE_SCRIPT,
    config.model["path"],
]
env = {
    "HF_HOME": "/cache/glm52/hf-home",
    "TRANSFORMERS_CACHE": "/cache/glm52/hf-home",
}
```

Call `validate_model_snapshot(Path(snapshot_path))`. Write a JSON record:

```json
{
  "schema_version": 1,
  "run_id": "prepare-model-test",
  "model_cache": {
    "model_id": "zai-org/GLM-5.2",
    "snapshot_path": "/cache/glm52/hf-home/hub/models--zai-org--GLM-5.2/snapshots/abc",
    "shard_count": 1,
    "missing_shard_count": 0
  }
}
```

- [ ] **Step 8: Implement `validate_preparation_records`**

Reject if:

- record path is absent;
- record JSON is malformed;
- venv Python is not `/cache/glm52/venvs/sglang/bin/python`;
- package list does not include `sglang[all]`;
- `served_model_name_flag` is not true;
- model snapshot path is not under `/cache/glm52/hf-home`;
- `missing_shard_count` is not zero;
- rootfs recipe digest mismatches the materialized config.

- [ ] **Step 9: Extend wrapper CLI**

Add wrapper commands:

```sh
scripts/run_glm52_sglang_runtime.sh prepare-venv --declared .scratch/glm52-local-serving/config/sglang-local.yaml --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml
scripts/run_glm52_sglang_runtime.sh prepare-model --declared .scratch/glm52-local-serving/config/sglang-local.yaml --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml
```

The wrapper must pass arguments through without shell reconstruction.

- [ ] **Step 10: Run focused tests**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
bash -n scripts/run_glm52_sglang_runtime.sh
```

Expected: all pass.

---

### Task 3: Repeatable Live Launch, Probe, and Teardown

**Files:**
- Modify: `scripts/glm52_sglang_runtime.py`
- Modify: `scripts/run_glm52_sglang_runtime.sh`
- Modify: `python/tests/test_glm52_sglang_runtime.py`
- May write runtime artifacts under: `.scratch/glm52-local-serving/run/`

**Interfaces:**
- Consumes: `validate_preparation_records(...)`, `parse_models_response(...)`, `should_teardown_after_failure(...)`
- Produces: `run_repeatability_cycles(...)`, cycle records, final summary

- [ ] **Step 1: Write failing tests for strict port allocation**

Add:

```python
def test_repeatability_rejects_default_ports(tmp_path: Path) -> None:
    declared_path = write_spec(
        tmp_path / "declared.yaml",
        VALID_DECLARED_WITH_OVERLAY.replace("range_start: 19000", "range_start: 8000").replace("range_end: 19100", "range_end: 8000"),
    )

    with pytest.raises(RuntimeConfigError, match="disallowed port"):
        run_repeatability_cycles(
            declared_path=declared_path,
            local_environment_path=write_local_environment(tmp_path),
            run_id="bad-port",
        )
```

- [ ] **Step 2: Write failing tests for launch command drift**

Add:

```python
def test_launch_cycle_rejects_inner_argv_drift(tmp_path: Path) -> None:
    config = materialized_config_for_test(tmp_path, port=19031)
    drifted = config.replace_launch_inner(config.launch["inner_argv"] + ["--port", "8000"])

    with pytest.raises(RuntimeConfigError, match="inner argv mismatch"):
        validate_materialized_config(drifted)
```

- [ ] **Step 3: Write failing tests for teardown after probe failure**

Add fake process and fake probe hooks:

```python
def test_launch_failure_tears_down_when_debug_disabled(tmp_path: Path) -> None:
    events: list[str] = []

    def fake_launch(config: MaterializedSglangRuntimeConfig) -> ProcessRecord:
        events.append("launch")
        return ProcessRecord(pid=1234, pgid=1234, argv=config.launch["inner_argv"], port=config.service["port"])

    def fake_probe(config: MaterializedSglangRuntimeConfig) -> None:
        events.append("probe")
        raise RuntimeLaunchError("probe failed")

    def fake_teardown(record: ProcessRecord) -> dict[str, Any]:
        events.append("teardown")
        return {"ok": True, "port_closed": True, "process_gone": True}

    with pytest.raises(RuntimeLaunchError, match="probe failed"):
        run_one_cycle(
            config=materialized_config_for_test(tmp_path, port=19032),
            launch=fake_launch,
            probe=fake_probe,
            teardown=fake_teardown,
        )

    assert events == ["launch", "probe", "teardown"]
```

- [ ] **Step 4: Run tests to verify red**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
```

Expected: fail because repeatability cycle orchestration is not implemented.

- [ ] **Step 5: Implement strict allocator**

Implement a helper that:

- iterates declared range in deterministic order;
- skips disallowed ports;
- checks bindability on `127.0.0.1`;
- returns one concrete port;
- raises `RuntimeConfigError("no free run-owned port in declared range")` when
  the range is exhausted.

It must never probe ambient ports outside the declared range.

- [ ] **Step 6: Implement launch process record**

Use `subprocess.Popen(..., start_new_session=True)` with structured argv. Write
a process record before readiness wait:

```json
{
  "schema_version": 1,
  "run_id": "cycle-1",
  "pid": 1234,
  "pgid": 1234,
  "port": 19031,
  "outer_argv": ["scripts/rootfs/enter_rootfs.sh", "..."],
  "inner_argv": ["/cache/glm52/venvs/sglang/bin/python", "-m", "sglang.launch_server", "..."],
  "env": {
    "HF_HOME": "/cache/glm52/hf-home",
    "SGLANG_CACHE_DIR": "/cache/glm52/sglang"
  }
}
```

- [ ] **Step 7: Implement live probes**

Implement:

```python
def probe_models(config: MaterializedSglangRuntimeConfig) -> dict[str, Any]:
    url = f"http://{config.service['bind_host']}:{config.service['port']}/v1/models"
    body = urllib.request.urlopen(url, timeout=10).read()
    return parse_models_response(
        body,
        expected_model_ids=config.model["expected_model_ids"],
        served_model_name=config.model["served_model_name"],
    )
```

Implement chat probe with JSON body:

```json
{
  "model": "zai-org/GLM-5.2",
  "messages": [
    {"role": "user", "content": "Reply with the exact string: monarch-sglang-ready"}
  ],
  "max_tokens": 32,
  "temperature": 0,
  "chat_template_kwargs": {"enable_thinking": false}
}
```

Require HTTP 200 and non-empty assistant content.

- [ ] **Step 8: Implement teardown**

Teardown must:

- read the process record;
- verify the live command still contains `sglang.launch_server` and the recorded
  port;
- send `SIGTERM` to the recorded process group;
- wait for exit;
- send `SIGKILL` only after timeout;
- check the port is closed;
- write `teardown.json`.

- [ ] **Step 9: Implement repeatability summary**

`run_repeatability_cycles(...)` must run `declared.repeatability.cycles` cycles
from the same declared spec. It writes:

```json
{
  "schema_version": 1,
  "run_id": "glm52-sglang-repeatability",
  "ok": true,
  "cycles": [
    {"cycle": 1, "ok": true, "port": 19031},
    {"cycle": 2, "ok": true, "port": 19032},
    {"cycle": 3, "ok": true, "port": 19033}
  ]
}
```

The summary is `ok: true` only if every cycle has successful launch, models
probe, chat probe, teardown, and post-teardown proof.

- [ ] **Step 10: Extend wrapper CLI**

Add:

```sh
scripts/run_glm52_sglang_runtime.sh repeatability --declared .scratch/glm52-local-serving/config/sglang-local.yaml --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml
```

The wrapper must exit with the Python command's status.

- [ ] **Step 11: Run unit verification**

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
bash -n scripts/run_glm52_sglang_runtime.sh
```

Expected: all pass.

- [ ] **Step 12: Run live verification when prerequisites exist**

Run:

```sh
scripts/run_glm52_sglang_runtime.sh prepare-venv \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml

scripts/run_glm52_sglang_runtime.sh prepare-model \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml

scripts/run_glm52_sglang_runtime.sh repeatability \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml
```

Expected:

- venv preparation writes a valid record;
- model preparation writes a valid record or fails before launch with a
  prepare-required blocker artifact;
- repeatability exits zero only if three live SGLang cycles pass;
- no command uses ports `8000`, `8080`, or `18080`.

---

## Self-Review

Spec coverage:

- Rootfs overlay schema is Task 1.
- Venv preparation is Task 2.
- Model cache preparation is Task 2.
- Command and bwrap drift validation begins in Task 1 and is enforced before
  launch in Task 3.
- Strict port allocation and no ambient ports are Task 3.
- Live models and chat probes are Task 3.
- Teardown and repeatability are Task 3.

Placeholder scan:

- No task contains open-ended placeholders. Each task has concrete files,
  interfaces, tests, commands, and acceptance checks.

Type consistency:

- Public function names match the spec.
- The plan keeps `scripts/glm52_sglang_runtime.py` as the public entrypoint and
  uses the existing rootfs schema module instead of introducing a second bwrap
  translator.
