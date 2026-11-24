#!/usr/bin/env bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Create and activate the rootfs virtual environment after validated entry.
#
# Source this file (do not execute it) from inside the rootfs. It requires a
# valid rootfs with the full tool set, creates .venv-rootfs with the rootfs
# Python and inherited system site-packages, and exports VIRTUAL_ENV and PATH so
# the venv interpreter takes precedence. It never resolves or installs project
# dependencies; that is the caller's job.

MONARCH_ACTIVATE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MONARCH_ACTIVATE_REPO_ROOT="$(cd -- "$MONARCH_ACTIVATE_DIR/../.." && pwd)"

# shellcheck source=scripts/rootfs/execution_contract.sh
source "$MONARCH_ACTIVATE_DIR/execution_contract.sh"

monarch_require_rootfs "$MONARCH_ACTIVATE_REPO_ROOT" python uv cargo node npm mdbook || return $?

VIRTUAL_ENV="$MONARCH_ACTIVATE_REPO_ROOT/.venv-rootfs"
if [[ ! -x "$VIRTUAL_ENV/bin/python" ]]; then
  uv venv --python 3.12 --system-site-packages "$VIRTUAL_ENV" >&2
fi

export VIRTUAL_ENV
export PATH="$VIRTUAL_ENV/bin:$PATH"
unset PYTHONHOME
