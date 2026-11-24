#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Verify a local GLM-5.2 serving stack for coding-agent traffic.
#
# This is intentionally not a Monarch Local Run: it validates an external
# Dynamo/SGLang deployment and the Responses-compatible adapter that Codex needs.
#
# Usage:
#   GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
#   GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
#     scripts/run_glm52_serving_verifier.sh

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Keep repo-local Python execution inside the canonical Monarch rootfs while
# validating the external Dynamo/SGLang and Responses endpoints.
if ! "$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs >/dev/null 2>&1; then
  exec "$REPO_ROOT/scripts/run" /workspace/monarch/scripts/run_glm52_serving_verifier.sh "$@"
fi

python_bin="${PYTHON:-python3}"
exec "$python_bin" "$REPO_ROOT/scripts/glm52_serving_verifier.py" "$@"
