#!/usr/bin/env bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Cargo RUSTC_WRAPPER guard. Cargo runs it as `rustc-wrapper.sh <rustc> <args>`,
# so it refuses to invoke any compiler outside a controlled execution domain,
# then execs the real compiler unchanged.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
"$repo_root/scripts/rootfs/execution_contract.sh" require-controlled
[[ $# -ge 1 ]] || { echo "error: rustc wrapper requires a compiler" >&2; exit 2; }
exec "$@"
