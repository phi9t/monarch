#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Thin compatibility adapter. Insula owns the governed local bwrap-rootfs
# protocol, including rootfs selection, bwrap plan emission, mount projection,
# environment construction, and command launch.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m ginkgo.insula.cli enter-rootfs-compat "$@"
