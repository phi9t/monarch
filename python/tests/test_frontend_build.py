# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Deterministic dashboard-frontend build tests.

``scripts/build_dashboard_frontend.py`` builds the React dashboard assets
fail-closed: it removes stale output, rejects a symlinked build tree, requires
npm and the exact esbuild outputs, relocates CSS, and copies the HTML template.
A fake npm and a temporary frontend exercise every branch without a real
toolchain. The lifecycle tests pin the package scripts that guard install,
build, typecheck, and test.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "python/monarch/monarch_dashboard/frontend"
_HELPER = REPO_ROOT / "scripts" / "build_dashboard_frontend.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("_build_dashboard_frontend", _HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_dashboard_frontend = _load_helper().build_dashboard_frontend


def make_frontend(tmp_path: Path) -> Path:
    frontend = tmp_path / "frontend"
    (frontend / "public").mkdir(parents=True)
    (frontend / "public/index.html").write_text("fresh template")
    (frontend / "package.json").write_text(json.dumps({"name": "fixture"}))
    (frontend / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": {}})
    )
    return frontend


def make_fake_npm(tmp_path: Path, *, create_js: bool, create_css: bool) -> Path:
    npm = tmp_path / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'if [ "${1:-}" = ci ]; then exit 0; fi\n'
        "mkdir -p build/static/js\n"
        f"{'printf js > build/static/js/main.js' if create_js else ':'}\n"
        f"{'printf css > build/static/js/main.css' if create_css else ':'}\n"
    )
    npm.chmod(0o755)
    return npm


def test_success_replaces_stale_assets(tmp_path: Path) -> None:
    frontend = make_frontend(tmp_path)
    stale = frontend / "build/index.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale")
    npm = make_fake_npm(tmp_path, create_js=True, create_css=True)
    index, javascript, css = build_dashboard_frontend(frontend, npm=str(npm))
    assert index.read_text() == (frontend / "public/index.html").read_text()
    assert javascript == frontend / "build/static/js/main.js"
    assert css == frontend / "build/static/css/main.css"
    assert "stale" not in index.read_text()


def test_missing_frontend_directory_is_rejected(tmp_path: Path) -> None:
    npm = make_fake_npm(tmp_path, create_js=True, create_css=True)
    import pytest

    with pytest.raises(RuntimeError):
        build_dashboard_frontend(tmp_path / "absent", npm=str(npm))


def test_symlinked_build_is_rejected(tmp_path: Path) -> None:
    import pytest

    frontend = make_frontend(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (frontend / "build").symlink_to(target, target_is_directory=True)
    npm = make_fake_npm(tmp_path, create_js=True, create_css=True)
    with pytest.raises(RuntimeError):
        build_dashboard_frontend(frontend, npm=str(npm))


def test_missing_npm_is_rejected(tmp_path: Path) -> None:
    import pytest

    frontend = make_frontend(tmp_path)
    with pytest.raises(RuntimeError):
        build_dashboard_frontend(frontend, npm=str(tmp_path / "no-such-npm"))


def test_missing_js_output_is_rejected(tmp_path: Path) -> None:
    import pytest

    frontend = make_frontend(tmp_path)
    npm = make_fake_npm(tmp_path, create_js=False, create_css=True)
    with pytest.raises(RuntimeError):
        build_dashboard_frontend(frontend, npm=str(npm))


def test_missing_css_output_is_rejected(tmp_path: Path) -> None:
    import pytest

    frontend = make_frontend(tmp_path)
    npm = make_fake_npm(tmp_path, create_js=True, create_css=False)
    with pytest.raises(RuntimeError):
        build_dashboard_frontend(frontend, npm=str(npm))


def test_build_failure_is_reported(tmp_path: Path) -> None:
    import pytest

    frontend = make_frontend(tmp_path)
    npm = tmp_path / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = ci ]; then exit 0; fi\n'
        "exit 3\n"
    )
    npm.chmod(0o755)
    with pytest.raises(RuntimeError):
        build_dashboard_frontend(frontend, npm=str(npm))


def test_package_scripts_guard_lifecycle_and_type_check() -> None:
    pkg = json.loads((FRONTEND / "package.json").read_text())
    scripts = pkg["scripts"]
    guard = "npm run rootfs-check"
    assert scripts["preinstall"] == guard
    assert scripts["prebuild"] == guard
    assert scripts["pretypecheck"] == guard
    assert scripts["pretest"] == guard
    assert scripts["rootfs-check"].endswith(
        "scripts/rootfs/execution_contract.sh require-controlled"
    )
    assert scripts["typecheck"] == "tsc --noEmit"
    assert "no test runner configured" in scripts["test"]


def test_frontend_test_script_fails_honestly() -> None:
    result = subprocess.run(
        ["npm", "--prefix", str(FRONTEND), "test"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "no test runner configured" in result.stderr
