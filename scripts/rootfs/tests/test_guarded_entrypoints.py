# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Guarded-entrypoint seam tests.

Each guarded Monarch entrypoint refuses to do real work outside a controlled
domain. These tests run inside the rootfs but strip the rootfs markers from the
child environment, so the child sees neither a valid rootfs nor GitHub Linux nor
Darwin, and must exit 2 before importing Monarch, probing Torch/CUDA/npm, or
invoking a compiler. They also assert the Cargo build wrapper is wired in
.cargo/config.toml.
"""

from __future__ import annotations

import os
import subprocess
import sys
import shutil
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Environment stripped of every controlled-domain proof. A child launched with
# this sees no valid rootfs, no GitHub Linux CI, and no Darwin, so every guard
# must funnel through the common contract error.
_UNCONTROLLED = {
    k: v
    for k, v in os.environ.items()
    if k
    not in {
        "MONARCH_IN_ROOTFS",
        "MONARCH_ROOTFS_RECIPE_SHA256",
        "GITHUB_ACTIONS",
        "RUNNER_OS",
        "GITHUB_RUN_ID",
        "GITHUB_WORKFLOW_REF",
    }
}


def _run_uncontrolled(argv: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        env=_UNCONTROLLED,
        **kwargs,
    )


def test_source_import_refuses_outside_controlled_domain() -> None:
    # Point at the source tree so `import monarch` reaches __init__.py's guard
    # rather than failing to import; the guard must abort before native loading.
    env = {**_UNCONTROLLED, "PYTHONPATH": str(REPO_ROOT / "python")}
    result = subprocess.run(
        [sys.executable, "-c", "import monarch"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr


def test_setup_backend_refuses_outside_controlled_domain() -> None:
    # Importing setup.py as a module runs its top-level guard before setuptools,
    # Torch, CUDA, npm, or Cargo probing.
    result = _run_uncontrolled(
        [sys.executable, str(REPO_ROOT / "setup.py"), "--version"],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr


def test_mini_setup_backend_refuses_outside_controlled_domain() -> None:
    setup = REPO_ROOT / "monarch_mini" / "python" / "setup.py"
    result = _run_uncontrolled(
        [sys.executable, str(setup), "--version"],
        cwd=setup.parent,
    )
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr


def test_pytest_collection_refuses_outside_controlled_domain() -> None:
    result = _run_uncontrolled(
        [sys.executable, "-m", "pytest", "--co", "-q", "python/tests/test_config.py"],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr


def test_rustc_wrapper_refuses_outside_controlled_domain() -> None:
    wrapper = REPO_ROOT / "scripts/rootfs/rustc-wrapper.sh"
    result = _run_uncontrolled([str(wrapper), "true"])
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr


def test_rustc_wrapper_rejects_marker_only_entry(tmp_path: Path) -> None:
    # A bare MONARCH_IN_ROOTFS=1 marker never proves rootfs entry. Copy the
    # contract scripts into a checkout outside the /workspace/monarch mount so
    # the checkout-match proof fails even though the marker is set; the wrapper
    # must exit 2 before running the compiler.
    fake_root = tmp_path / "fake-monarch"
    (fake_root / "scripts" / "rootfs").mkdir(parents=True)
    for name in ("execution_contract.sh", "contract.env", "build_rootfs.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / "rootfs" / name, fake_root / "scripts" / "rootfs" / name)
    shutil.copy2(REPO_ROOT / "scripts" / "rootfs" / "rustc-wrapper.sh", fake_root / "scripts" / "rootfs" / "rustc-wrapper.sh")
    shutil.copy2(REPO_ROOT / "rust-toolchain", fake_root / "rust-toolchain")

    compiler = tmp_path / "compiler"
    compiler.write_text('#!/bin/sh\necho executed > "$1"\n')
    compiler.chmod(0o755)
    sentinel = tmp_path / "sentinel"
    env = {**os.environ, "MONARCH_IN_ROOTFS": "1"}
    env.pop("MONARCH_ROOTFS_RECIPE_SHA256", None)
    result = subprocess.run(
        [fake_root / "scripts" / "rootfs" / "rustc-wrapper.sh", compiler, sentinel],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    assert not sentinel.exists()


def test_cargo_config_wires_the_build_wrapper() -> None:
    config = REPO_ROOT / ".cargo/config.toml"
    with config.open("rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["build"]["rustc-wrapper"] == "scripts/rootfs/rustc-wrapper.sh"
