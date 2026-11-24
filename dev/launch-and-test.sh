#!/usr/bin/env bash
# Build monarch CPU dev image, start container, run tests.
# Run in tmux/screen or a long-lived terminal: ./dev/launch-and-test.sh
set -e
cd "$(dirname "$0")/.."
echo "=== Building monarch-dev (CPU) image ==="
docker compose -f dev/docker-compose.yml build
echo "=== Starting container ==="
docker compose -f dev/docker-compose.yml up -d
sleep 5
echo "=== Running tests ==="
docker compose -f dev/docker-compose.yml exec -T monarch-dev bash -c '
  set -e
  source /opt/conda/etc/profile.d/conda.sh && conda activate monarch
  cd /workspace
  python setup.py develop 2>/dev/null || true
  echo "--- Rust tests ---"
  cargo nextest run --workspace
  echo "--- Python tests ---"
  pytest python/tests/ -v -m "not oss_skip"
'
echo "=== Done ==="
