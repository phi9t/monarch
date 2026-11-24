#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Host-side helper for GLM-5.2 deployment state and crash cleanup.
#
# This script intentionally does not enter the Monarch rootfs. Cleanup must see
# host processes such as `kubectl port-forward` and local adapter services.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

python_bin="${PYTHON:-python3}"
exec "$python_bin" "$REPO_ROOT/scripts/glm52_deployment.py" "$@"
