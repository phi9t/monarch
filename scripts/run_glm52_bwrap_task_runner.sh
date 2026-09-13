#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Host-side launcher for strict GLM-5.2 benchmark bwrap tasks.
#
# This intentionally does not enter `scripts/run`: it must launch bwrap itself
# and record host-visible task PIDs in the cleanup ledger.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -d "$REPO_ROOT/scripts/rootfs/rootfs" ]]; then
  "$REPO_ROOT/scripts/rootfs/build_rootfs.sh"
fi

python_bin="${PYTHON:-python3}"
exec "$python_bin" "$REPO_ROOT/scripts/glm52_bwrap_task_runner.py" "$@"
