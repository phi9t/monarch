#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Execution-domain inventory auditor.

Every executable entrypoint in this repository runs in exactly one execution
domain (see scripts/rootfs/execution-domains.toml). This scanner discovers every
entrypoint -- git-tracked executables, both Makefiles, both setup backends, the
dashboard frontend package, Python examples and benches, Cargo bin/example/bench
targets, and GitHub workflows -- and requires each to match exactly one domain
rule.

`--check` exits 0 only when every discovered entrypoint is classified exactly
once, and 1 with one `unclassified: <path>` or `overlap: <path>: <domains>` line
per error. It is pure discovery plus matching and does no mutation, so it is
safe to import for unit tests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOMAINS_TOML = Path(__file__).resolve().parent / "execution-domains.toml"

# Directories never holding tracked entrypoints; skipped by the filesystem
# fallback used when git is unavailable (for example a linked worktree whose
# gitdir is outside the rootfs mount).
_PRUNE_DIRS = frozenset(
    {
        ".git",
        "target",
        "node_modules",
        "build",
        "__pycache__",
        ".venv",
        ".venv-rootfs",
        ".pytest_cache",
        "dist",
    }
)

# Repo-relative directories pruned by exact path: the Git-ignored host-side
# rootfs export and managed caches that live under scripts/rootfs/.
_PRUNE_RELPATHS = frozenset(
    {
        "scripts/rootfs/rootfs",
        "scripts/rootfs/cache",
    }
)

# Git-ignored build outputs the filesystem fallback must not mistake for
# tracked entrypoints (native extensions and the provenance manifest land in
# the source tree during an editable install).
_IGNORED_SUFFIXES = (".so", ".pyc", ".dylib", ".pyd")
_IGNORED_NAMES = frozenset({".native-artifacts.json"})

# Glob patterns for entrypoint categories discovered beyond git executable mode.
# scripts/*.py catches the non-executable (mode 644) CLI helpers such as
# local_8gpu_capacity.py, and scripts/rootfs/tests/*.py the test fixtures that
# drive them; both must be classified even though neither carries the exec bit.
_PYTHON_ENTRY_GLOBS = (
    "python/examples/**/*.py",
    "examples/**/*.py",
    "python/benches/**/*.py",
    "scripts/*.py",
    "scripts/rootfs/tests/*.py",
)


def _run(argv: list[str]) -> str:
    return subprocess.check_output(argv, cwd=_REPO_ROOT, text=True)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob to a regex, honoring `**` across segments.

    `**/` matches zero or more path segments; a bare `*` matches within a single
    segment and never crosses `/`. This is stricter and more predictable than
    fnmatch, whose `*` crosses `/`.
    """
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def _glob_match(path: str, pattern: str) -> bool:
    regex = _GLOB_CACHE.get(pattern)
    if regex is None:
        regex = _glob_to_regex(pattern)
        _GLOB_CACHE[pattern] = regex
    return bool(regex.match(path))


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _walk_relative_files() -> list[str]:
    """Every non-pruned regular file under the repo, repo-relative."""
    found: list[str] = []
    for root, dirs, files in os.walk(_REPO_ROOT):
        rel_root = os.path.relpath(root, _REPO_ROOT)
        dirs[:] = [
            d
            for d in dirs
            if d not in _PRUNE_DIRS
            and os.path.normpath(os.path.join(rel_root, d)) not in _PRUNE_RELPATHS
        ]
        for name in files:
            path = Path(root, name)
            if not path.is_file() or path.is_symlink():
                continue
            if name in _IGNORED_NAMES or name.endswith(_IGNORED_SUFFIXES):
                continue
            found.append(str(path.relative_to(_REPO_ROOT)))
    return found


def _git_executables() -> set[str]:
    """Every git-tracked file whose mode marks it executable.

    Falls back to a filesystem walk keyed on the executable bit when git is not
    usable, so the audit still runs inside a worktree-based rootfs.
    """
    if _git_available():
        out = _run(["git", "ls-files", "--stage"])
        paths: set[str] = set()
        for line in out.splitlines():
            if not line:
                continue
            mode, _rest = line.split(maxsplit=1)
            # git ls-files --stage: <mode> <sha> <stage>\t<path>
            if mode.endswith("755"):
                paths.add(line.split("\t", 1)[1])
        return paths
    return {
        rel
        for rel in _walk_relative_files()
        if os.stat(_REPO_ROOT / rel).st_mode & stat.S_IXUSR
    }


def _git_tracked(patterns: tuple[str, ...]) -> set[str]:
    if _git_available():
        out = _run(["git", "ls-files", *patterns])
        return {line for line in out.splitlines() if line}
    files = _walk_relative_files()
    return {rel for rel in files for pat in patterns if _glob_match(rel, pat)}


def _cargo_entrypoints() -> set[str]:
    """Bin, example, and bench target source paths from cargo metadata."""
    out = _run(
        ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
    )
    md = json.loads(out)
    root = Path(md["workspace_root"])
    kinds = {"bin", "example", "bench"}
    paths: set[str] = set()
    for pkg in md["packages"]:
        for target in pkg["targets"]:
            if kinds & set(target["kind"]):
                paths.add(str(Path(target["src_path"]).relative_to(root)))
    return paths


def discover_entrypoints() -> set[str]:
    """The complete set of repository entrypoints to classify."""
    entries: set[str] = set()
    entries |= _git_executables()
    entries |= _git_tracked(("Makefile", "**/Makefile"))
    entries |= _git_tracked(("setup.py", "**/setup.py"))
    entries |= _git_tracked(("python/monarch/monarch_dashboard/frontend/package.json",))
    entries |= _git_tracked(_PYTHON_ENTRY_GLOBS)
    entries |= _git_tracked((".github/workflows/*.yml", ".github/workflows/*.yaml"))
    # All tracked shell scripts, so sourced (non-executable) setup files such as
    # common-setup-macos.sh are classified alongside executable ones.
    entries |= _git_tracked(("**/*.sh",))
    entries |= _cargo_entrypoints()
    return entries


def _load_rules() -> dict[str, list[str]]:
    """Domain -> list of glob patterns, from the reviewed TOML."""
    with _DOMAINS_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    rules: dict[str, list[str]] = {}
    for domain, spec in data["domains"].items():
        rules[domain] = list(spec.get("patterns", []))
    return rules


def _match(path: str, rules: dict[str, list[str]]) -> list[str]:
    """Every domain whose patterns match the path."""
    return sorted(
        domain
        for domain, patterns in rules.items()
        if any(_glob_match(path, pat) for pat in patterns)
    )


def audit() -> list[str]:
    """Return one error line per unclassified, overlapping, or dead rule."""
    rules = _load_rules()
    entries = discover_entrypoints()
    errors: list[str] = []

    for path in sorted(entries):
        domains = _match(path, rules)
        if not domains:
            errors.append(f"unclassified: {path}")
        elif len(domains) > 1:
            errors.append(f"overlap: {path}: {', '.join(domains)}")

    # A pattern that matches nothing is dead classification and hides drift.
    for domain, patterns in rules.items():
        for pat in patterns:
            if not any(_glob_match(p, pat) for p in entries):
                errors.append(f"zero-match: {domain}: {pat}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if any entrypoint is unclassified or overlapping",
    )
    args = parser.parse_args(argv)

    errors = audit()
    if errors:
        for line in errors:
            print(line)
        return 1 if args.check else 0
    if not args.check:
        for path in sorted(discover_entrypoints()):
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
