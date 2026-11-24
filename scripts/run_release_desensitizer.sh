#!/usr/bin/env bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Thin gateway wrapper for the release desensitizer. Keeps the shell entrypoint
# small (repo convention) and runs the Python tool inside the hermetic rootfs so
# publication scrubbing uses the same environment as every other local command.
#
# Usage:
#   scripts/run_release_desensitizer.sh --root .scratch/production-release-readiness
#   scripts/run_release_desensitizer.sh --root .scratch/production-release-readiness --apply
#
# Defaults to --check (report + fail-loud, no mutation). All arguments pass
# through to scripts/release_desensitizer.py.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

exec "${REPO_ROOT}/scripts/run" python "${REPO_ROOT}/scripts/release_desensitizer.py" \
  --repo-root "${REPO_ROOT}" "$@"
