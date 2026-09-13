#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Compatibility shim for the pre-gateway control-plane workflow.
#
# The canonical Linux-local gateway is scripts/run, which enters the hermetic
# bwrap rootfs and activates .venv-rootfs. This shim preserves the old
# entrypoint by routing through that gateway and delegating to the control-plane
# runner. It works both from the host bootstrap shell and from inside the
# rootfs.
#
# Usage:
#   scripts/rootfs/run_in_rootfs.sh [args passed to run_local_control_plane.sh]

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

exec "$REPO_ROOT/scripts/run" /workspace/monarch/scripts/run_local_control_plane.sh "$@"
