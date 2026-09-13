# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

#
# Build the minimonarch Python extension. Project metadata lives in
# pyproject.toml; this file only declares the C extension (and builds the Rust
# staticlib it links against) since setuptools needs ext_modules in setup.py.
#
#   uv run pytest        # builds + installs minimonarch, then runs the tests

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

HERE = os.path.dirname(os.path.abspath(__file__))
CRATE_DIR = os.path.dirname(HERE)  # monarch_mini/
WORKSPACE_DIR = os.path.dirname(CRATE_DIR)  # monarch/

# Guard the build backend before setuptools does real work or cargo runs. A
# standalone source checkout must build inside a controlled execution domain;
# installed/fbsource trees have no validator and pass through untouched.
_contract_spec = importlib.util.spec_from_file_location(
    "monarch._rootfs_contract",
    os.path.join(WORKSPACE_DIR, "python", "monarch", "_rootfs_contract.py"),
)
if _contract_spec is not None and _contract_spec.loader is not None:
    _contract = importlib.util.module_from_spec(_contract_spec)
    sys.modules[_contract_spec.name] = _contract
    _contract_spec.loader.exec_module(_contract)
    _contract.require_checkout(WORKSPACE_DIR)

# Default to an optimized build so benchmark numbers are meaningful; override
# with MINIMONARCH_PROFILE=debug for fast iterative builds.
PROFILE = os.environ.get("MINIMONARCH_PROFILE", "release")
# Honor CARGO_TARGET_DIR so a rootfs-overridden target tree is respected.
_target_dir = Path(os.environ.get("CARGO_TARGET_DIR", Path(WORKSPACE_DIR) / "target"))
if not _target_dir.is_absolute():
    _target_dir = Path(WORKSPACE_DIR, _target_dir)
STATIC_LIB = str(_target_dir / PROFILE / "libmonarch_mini.a")


class CargoBuildExt(build_ext):
    """Build the Rust staticlib before compiling the C extension."""

    def run(self):
        cargo = ["cargo", "build", "-p", "monarch_mini"]
        if PROFILE == "release":
            cargo.append("--release")
        elif PROFILE != "debug":
            cargo.append(f"--profile={PROFILE}")
        subprocess.check_call(cargo, cwd=WORKSPACE_DIR)
        super().run()


ext = Extension(
    name="minimonarch",
    sources=["minimonarch.c"],
    include_dirs=[CRATE_DIR],  # for minimonarch.h
    extra_objects=[STATIC_LIB],
    # System libraries the Rust standard library / tokio pull in.
    libraries=["pthread", "dl", "m"],
)

setup(
    ext_modules=[ext],
    cmdclass={"build_ext": CargoBuildExt},
)
