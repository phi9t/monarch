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
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_AUDITOR = REPO_ROOT / "scripts" / "rootfs" / "audit_entrypoints.py"


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
