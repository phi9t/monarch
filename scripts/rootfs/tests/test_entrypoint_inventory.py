# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Execution-domain inventory tests.

The auditor in ``scripts/rootfs/audit_entrypoints.py`` discovers every
repository entrypoint and requires each to match exactly one reviewed domain
rule, with no dead (zero-match) rule. These tests pin that end-to-end contract
and the classifier's core behaviors so a new entrypoint or a stale rule fails
the suite rather than drifting silently.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_AUDITOR = REPO_ROOT / "scripts" / "rootfs" / "audit_entrypoints.py"

# Documentation whose checkout-development instructions must route every local
# uv/cargo/pytest/make/npm/checkout-python command through the scripts/run
# gateway rather than advertising direct host execution.
_AUDITED_DOCS = (
    "AGENTS.md",
    "MONARCH_INFO.md",
    "README.md",
    "docs/DOCUMENTATION_GUIDE.md",
    "docs/source/monarch-dashboard.md",
    "docs/source/admin-tui.md",
    "python/monarch/monarch_dashboard/README.md",
    "python/monarch/monarch_dashboard/frontend/README.md",
)

# Command prefixes that name a local development tool. Inside an audited doc's
# shell block they must be reached through scripts/run.
_LOCAL_DEV_COMMAND = re.compile(
    r"^(uv|cargo|pytest|npm|mdbook)\b|^python\b.*\bmonarch\b|^make\s+-C\s+docs\b"
)


def _shell_command_lines(markdown: str) -> list[str]:
    """Command lines inside fenced shell blocks, prompts stripped.

    Only blocks whose fence names a shell language are scanned; unlabeled fences
    (used for command output and error transcripts) are ignored.
    """
    shell_langs = {"sh", "bash", "console", "shell", "shell-session"}
    lines: list[str] = []
    fence_lang: str | None = None
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            if fence_lang is None:
                fence_lang = stripped[3:].strip().lower()
            else:
                fence_lang = None
            continue
        if fence_lang not in shell_langs:
            continue
        line = stripped
        if line.startswith("$ "):
            line = line[2:]
        lines.append(line)
    return lines



def _load_auditor():
    spec = importlib.util.spec_from_file_location("_audit_entrypoints", _AUDITOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execution_inventory_is_complete() -> None:
    result = subprocess.run(
        [sys.executable, str(_AUDITOR), "--check"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_discovery_covers_the_required_categories() -> None:
    audit = _load_auditor()
    entries = audit.discover_entrypoints()
    # Host bootstrap and rootfs-development gateways.
    assert "scripts/run" in entries
    assert "scripts/rootfs/execution_contract.sh" in entries
    # Both setup backends and both real Makefiles.
    assert "setup.py" in entries
    assert "monarch_mini/python/setup.py" in entries
    assert "monarch_mini/Makefile" in entries
    assert "docs/Makefile" in entries
    # The frontend package and a GitHub workflow.
    assert "python/monarch/monarch_dashboard/frontend/package.json" in entries
    assert any(e.startswith(".github/workflows/") for e in entries)
    # A non-executable (mode 644) Python CLI and its sibling.
    assert "scripts/local_8gpu_capacity.py" in entries
    assert "scripts/fetch_disabled_tests.py" in entries
    # Cargo targets from cargo metadata, including the odd bin/ and tests/ paths.
    assert "hyperactor_mesh_admin_tui/bin/admin_tui.rs" in entries
    assert "ndslice/tests/fuzz_reshape_selection.rs" in entries


def test_every_entrypoint_matches_exactly_one_domain() -> None:
    audit = _load_auditor()
    rules = audit._load_rules()
    for path in sorted(audit.discover_entrypoints()):
        domains = audit._match(path, rules)
        assert len(domains) == 1, f"{path}: {domains}"


def test_no_rule_is_dead() -> None:
    audit = _load_auditor()
    assert not [line for line in audit.audit() if line.startswith("zero-match:")]


def test_glob_double_star_crosses_segments_but_star_does_not() -> None:
    audit = _load_auditor()
    assert audit._glob_match("a/b/c/x.rs", "**/x.rs")
    assert audit._glob_match("x.rs", "**/x.rs")
    assert not audit._glob_match("a/b/c.rs", "a/*.rs")
    assert audit._glob_match("a/c.rs", "a/*.rs")


def test_development_docs_route_local_commands_through_scripts_run() -> None:
    offenders: list[str] = []
    for rel in _AUDITED_DOCS:
        path = REPO_ROOT / rel
        for line in _shell_command_lines(path.read_text()):
            if line.startswith("scripts/run"):
                continue
            if _LOCAL_DEV_COMMAND.search(line):
                offenders.append(f"{rel}: {line}")
    assert not offenders, "direct local commands must use scripts/run:\n" + "\n".join(
        offenders
    )

