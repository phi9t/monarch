#!/usr/bin/env bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Shared execution-contract validator for Monarch local development.
#
# Source this file to reach its pure validation helpers, or run it as a narrow
# CLI. It defines the single source of truth for what a valid hermetic bwrap
# rootfs, GitHub Linux CI, and native Darwin execution look like, and it emits
# one common diagnostic that always points at `scripts/run`.
#
# A bare `MONARCH_IN_ROOTFS=1` marker never proves rootfs entry: entry is proven
# by a matching contract file, a checkout mounted at /workspace/monarch, a
# single-id user-namespace uid map, and controlled tool paths. `CI=true` alone
# never grants the GitHub Linux exemption.
#
# CLI:
#   execution_contract.sh recipe-sha256
#   execution_contract.sh rootfs-current ROOTFS
#   execution_contract.sh require-rootfs [TOOLS...]
#   execution_contract.sh require-github-linux
#   execution_contract.sh require-darwin
#   execution_contract.sh require-controlled [TOOLS...]
#   execution_contract.sh identify-controlled

# Derive REPO_ROOT from the script location so worktree placement is irrelevant.
MONARCH_CONTRACT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MONARCH_REPO_ROOT="$(cd -- "$MONARCH_CONTRACT_DIR/../.." && pwd)"

# The checkout mount and rootfs contract path are fixed by the rootfs image.
MONARCH_CHECKOUT_MOUNT=/workspace/monarch
MONARCH_ROOTFS_CONTRACT_PATH=/etc/monarch-rootfs-contract

# Recipe identity: hash the reviewed contract data, the builder, and the pinned
# toolchain by *relative* name so the digest is location-independent.
monarch_rootfs_recipe_sha256() {
  local repo_root="$1"
  (
    cd "$repo_root" || return 1
    sha256sum scripts/rootfs/contract.env scripts/rootfs/build_rootfs.sh rust-toolchain
  ) | sha256sum | awk '{print $1}'
}

# Two contract files match when their recipe digest lines are identical.
monarch_contract_files_match() {
  local expected="$1" actual="$2"
  local expected_line actual_line
  expected_line="$(grep '^MONARCH_ROOTFS_RECIPE_SHA256=' "$expected" 2>/dev/null)" || return 1
  actual_line="$(grep '^MONARCH_ROOTFS_RECIPE_SHA256=' "$actual" 2>/dev/null)" || return 1
  [[ -n "$expected_line" && "$expected_line" == "$actual_line" ]]
}

# The checkout must be mounted at exactly /workspace/monarch.
monarch_checkout_matches() {
  [[ "$1" == "$2" ]]
}

# A hermetic rootfs runs in an unprivileged user namespace whose uid map is a
# single identity mapping of length one. A nested unprivileged user namespace
# created for test isolation inside the rootfs (e.g. the crash-recovery worker)
# writes no mapping, so its uid map is empty; that is still controlled. A broad
# host map (length 2^32) or any multi-line map is not.
monarch_uid_map_is_controlled() {
  awk '
    { lines++; count = $3 }
    NF != 3 { exit 1 }
    END { if (lines == 0) exit 0; exit !(lines == 1 && count == 1) }
  ' "$1"
}

# GitHub Linux exemption: the complete identity, never CI=true alone.
monarch_is_github_linux_ci() {
  [[ "${GITHUB_ACTIONS:-}" == "true" &&
     "${RUNNER_OS:-}" == "Linux" &&
     "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ &&
     -n "${GITHUB_WORKFLOW_REF:-}" ]]
}

monarch_is_darwin() {
  [[ "${OSTYPE:-}" == darwin* ]] || [[ "$(uname -s 2>/dev/null)" == Darwin ]]
}

# Map a requested tool to its controlled rootfs path. Python is special: it is
# valid before activation at /usr/bin/python and after activation at the
# rootfs venv only when it resolves to the rootfs interpreter.
monarch_controlled_tool_path_ok() {
  local tool="$1" resolved
  case "$tool" in
    uv) [[ "$(command -v uv 2>/dev/null)" == /usr/local/bin/uv ]] ;;
    node) [[ "$(command -v node 2>/dev/null)" == /usr/local/bin/node ]] ;;
    npm) [[ "$(command -v npm 2>/dev/null)" == /usr/local/bin/npm ]] ;;
    cargo) [[ "$(command -v cargo 2>/dev/null)" == /opt/cargo/bin/cargo ]] ;;
    mdbook) [[ "$(command -v mdbook 2>/dev/null)" == /opt/cargo/bin/mdbook ]] ;;
    python)
      resolved="$(command -v python 2>/dev/null)" || return 1
      case "$resolved" in
        /usr/bin/python) return 0 ;;
        "$MONARCH_CHECKOUT_MOUNT/.venv-rootfs/bin/python")
          [[ "$(readlink -f "$resolved" 2>/dev/null)" == /usr/bin/python3.12 ]]
          ;;
        *) return 1 ;;
      esac
      ;;
    *) return 1 ;;
  esac
}

# Full rootfs validity: marker, checkout mount, matching contract, single-id uid
# map, and controlled paths for any requested tools.
monarch_in_valid_rootfs() {
  local repo_root="$1"
  shift
  [[ "${MONARCH_IN_ROOTFS:-}" == "1" ]] || return 1
  monarch_checkout_matches "$repo_root" "$MONARCH_CHECKOUT_MOUNT" || return 1
  [[ -r "$MONARCH_ROOTFS_CONTRACT_PATH" ]] || return 1
  local expected
  expected="$(monarch_rootfs_recipe_sha256 "$repo_root")" || return 1
  grep -qx "MONARCH_ROOTFS_RECIPE_SHA256=$expected" "$MONARCH_ROOTFS_CONTRACT_PATH" || return 1
  [[ -r /proc/self/uid_map ]] || return 1
  monarch_uid_map_is_controlled /proc/self/uid_map || return 1
  local tool
  for tool in "$@"; do
    monarch_controlled_tool_path_ok "$tool" || return 1
  done
}

# Compare a built rootfs directory's stamped contract against the current recipe.
monarch_rootfs_contract_current() {
  local rootfs="$1" repo_root="$2" expected
  [[ -r "$rootfs$MONARCH_ROOTFS_CONTRACT_PATH" ]] || return 1
  expected="$(monarch_rootfs_recipe_sha256 "$repo_root")" || return 1
  grep -qx "MONARCH_ROOTFS_RECIPE_SHA256=$expected" "$rootfs$MONARCH_ROOTFS_CONTRACT_PATH"
}

# The common diagnostic. Every guard funnels failure through here.
monarch_contract_error() {
  echo "error: Monarch development commands must run inside the hermetic bwrap rootfs" >&2
  echo "run instead: scripts/run ${MONARCH_ORIGINAL_COMMAND:-<command>}" >&2
  return 2
}

monarch_require_rootfs() {
  local repo_root="$1"
  shift
  monarch_in_valid_rootfs "$repo_root" "$@" && return 0
  monarch_contract_error
}

# Controlled execution is a valid rootfs, exact GitHub Linux CI, or Darwin.
monarch_require_controlled_execution() {
  local repo_root="$1"
  shift
  monarch_in_valid_rootfs "$repo_root" "$@" && return 0
  monarch_is_github_linux_ci && return 0
  monarch_is_darwin && return 0
  monarch_contract_error
}

# ---------------------------------------------------------------------------
# CLI. Only runs when executed, not when sourced.
# ---------------------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  # shellcheck source=/dev/null
  source "$MONARCH_CONTRACT_DIR/contract.env"

  cmd="${1:-}"
  [[ $# -gt 0 ]] && shift
  case "$cmd" in
    recipe-sha256)
      monarch_rootfs_recipe_sha256 "$MONARCH_REPO_ROOT"
      ;;
    rootfs-current)
      [[ $# -ge 1 ]] || { echo "error: rootfs-current requires a rootfs path" >&2; exit 2; }
      monarch_rootfs_contract_current "$1" "$MONARCH_REPO_ROOT"
      ;;
    require-rootfs)
      monarch_require_rootfs "$MONARCH_REPO_ROOT" "$@"
      ;;
    require-github-linux)
      monarch_is_github_linux_ci || monarch_contract_error
      ;;
    require-darwin)
      if ! monarch_is_darwin; then
        echo "error: this command runs only on native Darwin" >&2
        exit 2
      fi
      ;;
    require-controlled)
      monarch_require_controlled_execution "$MONARCH_REPO_ROOT" "$@"
      ;;
    identify-controlled)
      if monarch_in_valid_rootfs "$MONARCH_REPO_ROOT"; then
        echo "rootfs $(monarch_rootfs_recipe_sha256 "$MONARCH_REPO_ROOT")"
      elif monarch_is_github_linux_ci; then
        echo "github-linux"
      elif monarch_is_darwin; then
        echo "darwin"
      else
        monarch_contract_error
      fi
      ;;
    *)
      echo "error: unknown command: ${cmd:-<none>}" >&2
      echo "usage: execution_contract.sh {recipe-sha256|rootfs-current|require-rootfs|require-github-linux|require-darwin|require-controlled|identify-controlled}" >&2
      exit 2
      ;;
  esac
fi
