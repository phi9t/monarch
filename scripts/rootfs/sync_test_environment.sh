#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Frozen uv operations must run inside the validated rootfs against the
# canonical rootfs virtual environment. Fail loudly rather than mutating a host
# or stray environment.
"$REPO_ROOT/scripts/rootfs/execution_contract.sh" require-rootfs python uv >/dev/null
[[ "${VIRTUAL_ENV:-}" == "/workspace/monarch/.venv-rootfs" ]] || {
  echo "error: activate the rootfs virtual environment (VIRTUAL_ENV=/workspace/monarch/.venv-rootfs) first" >&2
  exit 1
}
[[ -x "${VIRTUAL_ENV}/bin/python" ]] || {
  echo "error: ${VIRTUAL_ENV}/bin/python is missing; create .venv-rootfs first" >&2
  exit 1
}

# The Meta-generated lock preserves torchx-nightly 2021.10.28 on Linux, but
# that release cannot import on Python 3.12. Use the newer wheel that is already
# hash-recorded in uv.lock for non-Linux environments.
TORCHX_WHEEL="https://files.pythonhosted.org/packages/69/cf/a08330f1db8038c7de4484ccc0d1991bc520c21e56c3b1dc31e1bddd2bda/torchx_nightly-2026.7.27-py3-none-any.whl#sha256=d2bef6d3fb284b3015eec950dad16154419629e94100f8f49f36f85a2b3a6b92"

uv sync --frozen --extra test --no-dev --inexact \
  --no-install-project --active --no-build-isolation
uv pip install --no-deps "$TORCHX_WHEEL"
uv pip install --no-build-isolation --no-deps -e .
