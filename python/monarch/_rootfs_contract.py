# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Stdlib adapter for the shared execution contract.

This module is the Python edge of the single validator in
``scripts/rootfs/execution_contract.sh``. It exists so that every Python
entrypoint into a standalone Monarch source checkout -- importing the package,
running either setup backend, collecting the test suite -- refuses to do real
work unless it runs inside a controlled domain (the hermetic bwrap rootfs, exact
GitHub Linux CI, or native Darwin). It also owns the native-artifact provenance
manifest so an editable install cannot silently reuse a ``.so`` built under a
different rootfs recipe.

It uses only the standard library so it can run before setuptools, Torch, CUDA,
npm, or Cargo are importable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_MANIFEST_NAME = ".native-artifacts.json"
_MANIFEST_SCHEMA = 1


@dataclass(frozen=True)
class ContractIdentity:
    """The controlled domain a checkout is executing in.

    ``recipe_digest`` is the rootfs recipe sha256 for a real rootfs identity and
    a sentinel for the exempt controlled domains (GitHub Linux, Darwin), which
    have no rootfs recipe.
    """

    schema: int
    recipe_digest: str


# Sentinels for the exempt controlled domains. They are not rootfs recipe
# digests, so the native-artifact manifest is not required for them.
_GITHUB_LINUX = ContractIdentity(schema=_MANIFEST_SCHEMA, recipe_digest="github-linux")
_DARWIN = ContractIdentity(schema=_MANIFEST_SCHEMA, recipe_digest="darwin")


def _is_rootfs_identity(identity: ContractIdentity) -> bool:
    """True when the identity is a real rootfs recipe digest (64 lowercase hex)."""
    digest = identity.recipe_digest
    return len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def _repo_root_of(module_or_repo: Path) -> Path:
    """Resolve the repository root for a file, or return the path unchanged.

    ``require_checkout`` receives a repo root directly; ``require_source_import``
    receives ``python/monarch/__init__.py`` and must climb to the checkout root.
    """
    path = module_or_repo.resolve()
    if path.is_file():
        # python/monarch/<file> -> repo root is three parents up.
        return path.parents[2]
    return path


def _is_guarded_checkout(repo_root: Path) -> bool:
    """A guarded standalone source checkout has both markers at its root.

    Installed wheels and the internal fbsource tree lack the shell validator, so
    they are not guarded and the adapter is a no-op for them.
    """
    return (repo_root / ".git").exists() and (
        repo_root / "scripts" / "rootfs" / "execution_contract.sh"
    ).is_file()


def _identify_controlled(repo_root: Path) -> ContractIdentity:
    """Run the shell validator and translate its verdict into an identity.

    Forwards the validator's diagnostic and raises ``SystemExit(2)`` on failure
    so the caller aborts before any real work.
    """
    validator = repo_root / "scripts" / "rootfs" / "execution_contract.sh"
    result = subprocess.run(
        [str(validator), "identify-controlled"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(2)

    verdict = result.stdout.strip()
    if verdict.startswith("rootfs "):
        return ContractIdentity(
            schema=_MANIFEST_SCHEMA, recipe_digest=verdict.split(None, 1)[1]
        )
    if verdict == "github-linux":
        return _GITHUB_LINUX
    if verdict == "darwin":
        return _DARWIN
    sys.stderr.write(f"error: unexpected contract verdict: {verdict!r}\n")
    raise SystemExit(2)


def require_checkout(
    repo_root: Path, argv: Sequence[str] | None = None
) -> ContractIdentity | None:
    """Require a controlled domain for a standalone source checkout.

    Returns ``None`` for a non-guarded path (installed wheel, fbsource) without
    invoking the shell validator. Otherwise returns the controlled identity or
    raises ``SystemExit(2)``.
    """
    del argv  # reserved for future per-command policy
    root = _repo_root_of(Path(repo_root))
    if not _is_guarded_checkout(root):
        return None
    return _identify_controlled(root)


def require_source_import(module_file: Path) -> ContractIdentity | None:
    """Guard importing Monarch from a standalone source checkout.

    Beyond ``require_checkout``, a real rootfs identity must also present a valid
    native-artifact manifest so a stale ``.so`` from another recipe cannot load.
    The exempt controlled domains build their own artifacts with their
    controlled toolchains and need no manifest.
    """
    root = _repo_root_of(Path(module_file))
    identity = require_checkout(root)
    if identity is None:
        return None
    if _is_rootfs_identity(identity):
        require_native_manifest(Path(module_file).resolve().parent, identity)
    return identity


def _manifest_path(package_dir: Path) -> Path:
    return package_dir / _MANIFEST_NAME


def _resolve_below(package_dir: Path, artifact: Path) -> Path:
    """Resolve an artifact path and require it to live below ``package_dir``.

    Rejects symlinks and paths that escape the package tree so a manifest can
    only vouch for real files inside the checkout.
    """
    package_dir = package_dir.resolve()
    if artifact.is_symlink():
        sys.stderr.write(f"error: native artifact is a symlink: {artifact}\n")
        raise SystemExit(2)
    resolved = artifact.resolve()
    try:
        resolved.relative_to(package_dir)
    except ValueError:
        sys.stderr.write(
            f"error: native artifact escapes package dir: {artifact}\n"
        )
        raise SystemExit(2)
    return resolved


def write_native_manifest(
    package_dir: Path,
    identity: ContractIdentity,
    artifacts: Sequence[Path],
) -> None:
    """Record each artifact's size and mtime under the current recipe digest.

    Writes through a same-directory temporary file plus ``os.replace`` so the
    manifest is swapped atomically and never observed half-written.
    """
    package_dir = Path(package_dir).resolve()
    entries: dict = {}
    for artifact in artifacts:
        resolved = _resolve_below(package_dir, Path(artifact))
        stat = resolved.stat()
        entries[resolved.name] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

    payload = {
        "schema": identity.schema,
        "recipe_digest": identity.recipe_digest,
        "artifacts": entries,
    }
    manifest = _manifest_path(package_dir)
    tmp = manifest.with_name(manifest.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, manifest)


def _load_manifest(package_dir: Path, identity: ContractIdentity) -> dict | None:
    """Return the manifest artifacts map, or ``None`` if it cannot be trusted."""
    manifest = _manifest_path(Path(package_dir).resolve())
    try:
        payload = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != identity.schema:
        return None
    if payload.get("recipe_digest") != identity.recipe_digest:
        return None
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    return artifacts


def native_artifact_is_current(
    artifact: Path,
    package_dir: Path,
    identity: ContractIdentity,
) -> bool:
    """True when the manifest vouches for this artifact's exact bytes.

    An artifact is current only when a manifest for the current recipe records
    its name with a matching size and mtime.
    """
    artifacts = _load_manifest(package_dir, identity)
    if artifacts is None:
        return False
    resolved = _resolve_below(Path(package_dir).resolve(), Path(artifact))
    entry = artifacts.get(resolved.name)
    if not isinstance(entry, dict):
        return False
    stat = resolved.stat()
    return entry.get("size") == stat.st_size and entry.get("mtime_ns") == stat.st_mtime_ns


def require_native_manifest(package_dir: Path, identity: ContractIdentity) -> None:
    """Require every source-tree ``.so`` to be a current, listed native artifact.

    Rejects a missing or stale manifest and any unlisted or changed ``.so`` so a
    checkout cannot import native code that no controlled build produced.
    """
    package_dir = Path(package_dir).resolve()
    artifacts = _load_manifest(package_dir, identity)
    if artifacts is None:
        sys.stderr.write(
            "error: native artifacts have no valid provenance manifest for this "
            "rootfs recipe; rebuild with scripts/run\n"
        )
        raise SystemExit(2)
    for so in sorted(package_dir.glob("*.so")):
        if not native_artifact_is_current(so, package_dir, identity):
            sys.stderr.write(
                f"error: native artifact is unlisted or stale: {so.name}; "
                "rebuild with scripts/run\n"
            )
            raise SystemExit(2)
