#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Run the GLM-5.2 Responses-to-Chat adapter inside Monarch's hermetic rootfs.
#
# Usage:
#   GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
#     scripts/run_glm52_responses_adapter.sh --host 127.0.0.1 --port 8080

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Keep repo-local Python execution inside the canonical Monarch rootfs while
# proxying to the external Dynamo/SGLang Chat Completions deployment.
if ! "$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs >/dev/null 2>&1; then
  exec "$REPO_ROOT/scripts/run" /workspace/monarch/scripts/run_glm52_responses_adapter.sh "$@"
fi

python_bin="${PYTHON:-python3}"
exec "$python_bin" "$REPO_ROOT/scripts/glm52_responses_adapter.py" "$@"
