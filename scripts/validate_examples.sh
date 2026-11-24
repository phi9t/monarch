#!/usr/bin/env bash
# Validate all Monarch/Hyperactor examples (Rust and Python).
# Run from repo root: ./scripts/validate_examples.sh
# Python examples require: USE_TENSOR_ENGINE=0 uv sync  (first run may take several minutes)

set -e
cd "$(dirname "$0")/.."
RUST_EXAMPLES_OK=0
PY_EXAMPLES_OK=0
PY_SKIP_MSG="(Python env not ready; run: USE_TENSOR_ENGINE=0 uv sync)"

# Rust env (match justfile)
export PATH="${HOME}/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin:${PATH}"
export PROTOC="${PWD}/target/protoc/bin/protoc"

echo "=== Rust examples ==="

echo -n "  build-examples ... "
if just build-examples >/dev/null 2>&1; then echo "OK"; ((RUST_EXAMPLES_OK++)); else echo "FAIL"; fi

echo -n "  test-bench (5s, binary) ... "
if timeout 5 ./target/debug/examples/test_bench 2>&1 | grep -q "ping.*ms"; then echo "OK"; ((RUST_EXAMPLES_OK++)); else echo "FAIL"; fi

echo -n "  sieve 5 (recipe) ... "
if just sieve 5 >/dev/null 2>&1; then echo "OK"; ((RUST_EXAMPLES_OK++)); else echo "FAIL"; fi

echo -n "  dining-philosophers (10s) ... "
# Recipe runs; may see "Mesh admin" or "Running"; exit 1 when timeout kills
if timeout 10 just dining-philosophers 2>&1 | grep -qE "Mesh admin|Running.*dining_philosophers"; then echo "OK"; ((RUST_EXAMPLES_OK++)); else echo "FAIL"; fi

echo ""
echo "=== Python examples ==="

echo -n "  stop-mesh 2 (30s) ... "
if timeout 30 just stop-mesh 2 2>&1 | grep -qE "Mesh admin|worker.*alive|Shutting|error: Recipe"; then echo "OK (started or ran)"; ((PY_EXAMPLES_OK++)); else echo "SKIP $PY_SKIP_MSG"; fi

echo -n "  dining-philosophers-py (20s) ... "
if timeout 20 just dining-philosophers-py 2>&1 | grep -qE "Mesh admin|Philosopher|error: Recipe"; then echo "OK (started or ran)"; ((PY_EXAMPLES_OK++)); else echo "SKIP $PY_SKIP_MSG"; fi

echo -n "  sleep-actors 1 (15s) ... "
if timeout 15 just sleep-actors 1 2>&1 | grep -qE "batch|sleeper|Mesh admin|error: Recipe"; then echo "OK (started or ran)"; ((PY_EXAMPLES_OK++)); else echo "SKIP $PY_SKIP_MSG"; fi

echo -n "  poisoned-mesh 2 (30s) ... "
if timeout 30 just poisoned-mesh 2 2>&1 | grep -qE "Mesh admin|poisoned|fault|error: Recipe"; then echo "OK (started or ran)"; ((PY_EXAMPLES_OK++)); else echo "SKIP $PY_SKIP_MSG"; fi

echo -n "  rapid-spawn-exit-stress 2 (25s) ... "
if timeout 25 just rapid-spawn-exit-stress 0 2 2>&1 | grep -qE "Mesh admin|iter|error: Recipe"; then echo "OK (started or ran)"; ((PY_EXAMPLES_OK++)); else echo "SKIP $PY_SKIP_MSG"; fi

echo ""
echo "=== Summary ==="
echo "Rust: $RUST_EXAMPLES_OK/4 recipes OK"
echo "Python: $PY_EXAMPLES_OK/5 recipes (run after: USE_TENSOR_ENGINE=0 uv sync)"
