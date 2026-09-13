# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Native-artifact provenance manifest tests.

These exercise the stdlib provenance helpers in isolation: a source-tree native
extension counts as current only when the manifest records its exact size and
mtime under the current recipe digest. They construct manifests directly and do
not enter the rootfs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADAPTER = _REPO_ROOT / "python" / "monarch" / "_rootfs_contract.py"

_spec = importlib.util.spec_from_file_location("_rootfs_contract_under_test", _ADAPTER)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

ContractIdentity = _mod.ContractIdentity
native_artifact_is_current = _mod.native_artifact_is_current
require_native_manifest = _mod.require_native_manifest
write_native_manifest = _mod.write_native_manifest

_DIGEST = "a" * 64


def _identity() -> "ContractIdentity":
    return ContractIdentity(schema=1, recipe_digest=_DIGEST)


def test_missing_manifest_is_not_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    assert not native_artifact_is_current(artifact, package, _identity())


def test_valid_manifest_is_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    write_native_manifest(package, _identity(), [artifact])
    assert native_artifact_is_current(artifact, package, _identity())


def test_wrong_recipe_is_not_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    write_native_manifest(package, _identity(), [artifact])
    other = ContractIdentity(schema=1, recipe_digest="b" * 64)
    assert not native_artifact_is_current(artifact, package, other)


def test_malformed_manifest_is_not_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    (package / ".native-artifacts.json").write_text("{ not json")
    assert not native_artifact_is_current(artifact, package, _identity())


def test_missing_artifact_entry_is_not_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    recorded = package / "_rust_bindings.so"
    recorded.write_bytes(b"first")
    write_native_manifest(package, _identity(), [recorded])
    other = package / "_gradient_generator.so"
    other.write_bytes(b"other")
    assert not native_artifact_is_current(other, package, _identity())


def test_changed_size_is_not_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    write_native_manifest(package, _identity(), [artifact])
    artifact.write_bytes(b"first-and-longer")
    assert not native_artifact_is_current(artifact, package, _identity())


def test_replaced_artifact_is_not_current(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    identity = ContractIdentity(schema=1, recipe_digest="a" * 64)
    write_native_manifest(package, identity, [artifact])
    assert native_artifact_is_current(artifact, package, identity)
    artifact.write_bytes(b"replacement")
    assert not native_artifact_is_current(artifact, package, identity)


def test_symlink_artifact_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    real = tmp_path / "real.so"
    real.write_bytes(b"first")
    link = package / "_rust_bindings.so"
    link.symlink_to(real)
    with pytest.raises(SystemExit):
        write_native_manifest(package, _identity(), [link])


def test_write_manifest_is_atomic(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    artifact = package / "_rust_bindings.so"
    artifact.write_bytes(b"first")
    write_native_manifest(package, _identity(), [artifact])
    manifest = package / ".native-artifacts.json"
    first_ino = manifest.stat().st_ino
    write_native_manifest(package, _identity(), [artifact])
    # os.replace swaps in a fresh inode rather than truncating in place.
    assert manifest.stat().st_ino != first_ino
    # No temporary file is left behind.
    leftovers = [p for p in package.iterdir() if p.name != ".native-artifacts.json"]
    assert leftovers == [artifact]


def test_require_native_manifest_rejects_unlisted_so(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    listed = package / "_rust_bindings.so"
    listed.write_bytes(b"first")
    write_native_manifest(package, _identity(), [listed])
    stray = package / "_stray.so"
    stray.write_bytes(b"stray")
    with pytest.raises(SystemExit):
        require_native_manifest(package, _identity())


def test_require_native_manifest_accepts_listed_only(tmp_path: Path) -> None:
    package = tmp_path / "monarch"
    package.mkdir()
    listed = package / "_rust_bindings.so"
    listed.write_bytes(b"first")
    write_native_manifest(package, _identity(), [listed])
    require_native_manifest(package, _identity())
