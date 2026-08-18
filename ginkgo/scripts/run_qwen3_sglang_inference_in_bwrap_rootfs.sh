#!/usr/bin/env bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

DEFAULT_LOCAL_ENV="${REPO_ROOT}/ginkgo/local-env/qwen3-sglang.yaml"
DEFAULT_DECLARED_SPEC="${REPO_ROOT}/ginkgo/configs/smoke-qwen3-dense.yaml"
DEFAULT_CACHE_ROOT="${REPO_ROOT}/.scratch/glm52-local-serving/cache/ginkgo"
DEFAULT_TEMP_ROOT="${REPO_ROOT}/.scratch/glm52-local-serving/tmp/ginkgo"

LOCAL_ENVIRONMENT="${GINKGO_QWEN3_LOCAL_ENVIRONMENT:-$DEFAULT_LOCAL_ENV}"
DECLARED_SPEC="${GINKGO_QWEN3_DECLARED_SPEC:-$DEFAULT_DECLARED_SPEC}"
LOCAL_ENVIRONMENT_EXPLICIT=0

log_stage() {
  printf '[ginkgo-wrapper] stage=%s' "$1"
  shift
  while [[ $# -gt 0 ]]; do
    printf ' %s' "$1"
    shift
  done
  printf '\n'
}

args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local-environment)
      if [[ $# -lt 2 ]]; then
        echo "error: --local-environment requires a path" >&2
        exit 2
      fi
      LOCAL_ENVIRONMENT="$2"
      LOCAL_ENVIRONMENT_EXPLICIT=1
      shift 2
      ;;
    --declared-spec)
      if [[ $# -lt 2 ]]; then
        echo "error: --declared-spec requires a path" >&2
        exit 2
      fi
      DECLARED_SPEC="$2"
      shift 2
      ;;
    -h|--help)
      args+=("$1")
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

for arg in "${args[@]}"; do
  if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
    exec "${REPO_ROOT}/ginkgo/scripts/run_qwen3_sglang_smoke.sh" "$arg"
  fi
done

materialize_default_local_environment() {
  local rootfs="${MONARCH_ROOTFS:-${REPO_ROOT}/scripts/rootfs/rootfs}"
  log_stage resolve_default_local_environment "path=${LOCAL_ENVIRONMENT}" "rootfs=${rootfs}"
  if [[ "$rootfs" != /* ]]; then
    echo "error: MONARCH_ROOTFS must be an absolute path: $rootfs" >&2
    exit 2
  fi

  mkdir -p \
    "$(dirname -- "$LOCAL_ENVIRONMENT")" \
    "$DEFAULT_CACHE_ROOT" \
    "$DEFAULT_TEMP_ROOT" \
    "${REPO_ROOT}/glm52-serving-results"

  cat > "$LOCAL_ENVIRONMENT" <<EOF
schema_version: 1
roots:
  repo: $REPO_ROOT
  cache: $DEFAULT_CACHE_ROOT
  temp: $DEFAULT_TEMP_ROOT
rootfs:
  monarch-default: $rootfs
EOF
  log_stage wrote_default_local_environment "path=${LOCAL_ENVIRONMENT}"
}

log_stage start "repo=${REPO_ROOT}" "declared_spec=${DECLARED_SPEC}" "local_environment=${LOCAL_ENVIRONMENT}"

if [[ ! -f "$LOCAL_ENVIRONMENT" ]]; then
  if [[ "$LOCAL_ENVIRONMENT_EXPLICIT" -eq 1 || -n "${GINKGO_QWEN3_LOCAL_ENVIRONMENT:-}" ]]; then
    cat >&2 <<EOF
error: missing Ginkgo Qwen3 local environment file: $LOCAL_ENVIRONMENT

Create it from ginkgo/local-env/template.yaml, or pass a valid
--local-environment <path>. The file owns host-specific rootfs, cache, temp, and
results paths.
EOF
    exit 2
  fi
  materialize_default_local_environment
else
  log_stage use_existing_local_environment "path=${LOCAL_ENVIRONMENT}"
fi

# This host-control script is intentionally not executed through scripts/run:
# it materializes host paths and the Python launcher validates the resolved
# bwrap command. SGLang itself still runs inside the governed rootfs.
log_stage delegate_to_python "python=${PYTHON:-python}" "runner=${REPO_ROOT}/ginkgo/scripts/run_qwen3_sglang_smoke.py"
exec "${PYTHON:-python}" "${REPO_ROOT}/ginkgo/scripts/run_qwen3_sglang_smoke.py" \
  --local-environment "$LOCAL_ENVIRONMENT" \
  --declared-spec "$DECLARED_SPEC" \
  "${args[@]}"
