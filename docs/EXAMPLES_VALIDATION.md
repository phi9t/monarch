# Examples validation

All Monarch/Hyperactor examples are runnable via the **justfile** at the repo root. This document records how to run them and validation status.

## Rust examples (hyperactor_mesh)

| Example | Command | Validation |
|--------|---------|------------|
| **build-examples** | `just build-examples` | Builds `dining_philosophers`, `test_bench`, `sieve`. |
| **dining-philosophers** | `just dining-philosophers` | Starts in-process mesh, prints "Mesh admin server listening on ...". Long-running; Ctrl+C to stop. Exit 1 when terminated by signal. |
| **test-bench** | `just test-bench` | Prints "ping Xms" lines. Long-running; Ctrl+C to stop. Validated: output contains `ping 27ms`, `ping 48ms`, etc. |
| **sieve** | `just sieve [N]` e.g. `just sieve 20` | Runs sieve; standalone run may exit 1 (expects mesh bootstrap). Recipe exits 0. Validated: `just sieve 5` completes. |

**Requirements:** Rust nightly (`nightly-2025-12-05`), `protoc` at `target/protoc/bin/protoc` (see justfile). Run from repo root.

## Python examples

| Example | Command | Validation |
|--------|---------|------------|
| **stop-mesh** | `just stop-mesh [N]` e.g. `just stop-mesh 2` | Spawns workers, coordinated stop. Requires `USE_TENSOR_ENGINE=0 uv sync` (first run may take several minutes). |
| **dining-philosophers-py** | `just dining-philosophers-py` | Python dining philosophers. Same env as above. |
| **sleep-actors** | `just sleep-actors [N]` | Continuous spawn/exit; Ctrl+C to stop. |
| **poisoned-mesh** | `just poisoned-mesh [N]` e.g. `just poisoned-mesh 3` | Crashes one worker, inspect post-mortem. |
| **rapid-spawn-exit-stress** | `just rapid-spawn-exit-stress [sleep] [iterations]` | Spawn/exit stress test. May require tensor engine for `spawn_tensor_engine`. |

**Requirements:** `uv`, Python 3.10+. First run: `USE_TENSOR_ENGINE=0 uv sync` from repo root.

## Validation script

From repo root:

```bash
./scripts/validate_examples.sh
```

Runs each Rust recipe (and optionally Python if env is ready) and prints OK/FAIL/SKIP. Rust validation does not require a lock on the cargo cache (run when no other `cargo`/`just` builds are running).

## Evidence (Rust)

- **test_bench:** `timeout 5 ./target/debug/examples/test_bench` → output includes `ping 27ms`, `ping 48ms`, etc.; exit 124 (timeout).
- **sieve:** `./target/debug/examples/sieve --num-primes 5` → runs; exit 1 (expected when not under mesh bootstrap). `just sieve 5` → exit 0.
- **dining_philosophers:** `just dining-philosophers` (with sufficient timeout and no cargo lock contention) → "Mesh admin server listening on http://..."; long-running.
