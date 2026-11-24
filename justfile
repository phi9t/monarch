# Run Monarch / Hyperactor examples
# Usage: just <recipe>   e.g.  just dining-philosophers

# Toolchain and env (matches rust-toolchain)
rust_toolchain := env_var('HOME') + "/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin"
path_with_rust := rust_toolchain + ":" + env_var('PATH')
protoc_path := justfile_directory() + "/target/protoc/bin/protoc"

# Default: show available example commands
default:
    @just --list

# Build all hyperactor_mesh examples (use nightly + protoc)
build-examples:
    export PATH='{{ path_with_rust }}' && export PROTOC='{{ protoc_path }}' && cargo build -p hyperactor_mesh --examples

# --- Rust examples (hyperactor_mesh) ---

# Run dining philosophers (in-process); Ctrl+C to stop
dining-philosophers:
    export PATH='{{ path_with_rust }}' && export PROTOC='{{ protoc_path }}' && cargo run -p hyperactor_mesh --example dining_philosophers -- --in-process

# Run test_bench (mesh ping benchmark); Ctrl+C to stop
test-bench:
    export PATH='{{ path_with_rust }}' && export PROTOC='{{ protoc_path }}' && cargo run -p hyperactor_mesh --example test_bench

# Run sieve (finds primes; expects mesh bootstrap in multi-process mode)
# Standalone run may exit 1; recipe still succeeds so just sieve is usable
sieve num_primes="20":
    export PATH='{{ path_with_rust }}' && export PROTOC='{{ protoc_path }}' && cargo run -p hyperactor_mesh --example sieve -- --num-primes {{ num_primes }} || true

# Build examples and show runnable commands
examples: build-examples
    @echo "Rust examples ready. Run with: just dining-philosophers | just test-bench | just sieve"

# --- Python examples (optional; require uv + monarch) ---

# Run stop_mesh (spawns workers, coordinated stop)
stop-mesh procs="2":
    USE_TENSOR_ENGINE=0 uv run python python/examples/stop_mesh.py --procs {{ procs }}

# Run dining philosophers (Python)
dining-philosophers-py:
    USE_TENSOR_ENGINE=0 uv run python python/examples/dining_philosophers.py

# Run sleep_actors (continuous spawn/exit); Ctrl+C to stop
sleep-actors procs="2":
    USE_TENSOR_ENGINE=0 uv run python python/examples/sleep_actors.py --procs {{ procs }}

# Run poisoned_mesh (crash one worker, inspect post-mortem); Ctrl+C to stop
poisoned-mesh procs="3":
    USE_TENSOR_ENGINE=0 uv run python python/examples/poisoned_mesh.py --procs {{ procs }}

# Run rapid_spawn_exit_stress (spawn/exit stress test); Ctrl+C to stop
rapid-spawn-exit-stress sleep="0" iterations="100":
    USE_TENSOR_ENGINE=0 uv run python python/examples/rapid_spawn_exit_stress.py --sleep {{ sleep }} --iterations {{ iterations }}
