#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Deterministic dashboard-frontend builder.

Builds the React dashboard assets fail-closed so a source build can never
package stale or partial output. It refuses to run outside a controlled
execution domain, rejects a symlinked ``build`` tree, requires npm and the exact
esbuild outputs, relocates the CSS emitted next to the JS, and copies the shared
HTML template into the build directory.

``build_dashboard_frontend`` returns the three final asset paths so setuptools
can depend on their existence rather than on a best-effort side effect. Missing
tools and subprocess failures become concise ``RuntimeError`` messages.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_FRONTEND = (
    _REPO_ROOT / "python" / "monarch" / "monarch_dashboard" / "frontend"
)


def _require_controlled_domain() -> None:
    """Refuse to build the frontend outside a controlled execution domain.

    Loads the shared contract adapter by file path so this script has no import
    dependency on an installed Monarch.
    """
    spec = importlib.util.spec_from_file_location(
        "monarch._rootfs_contract",
        _REPO_ROOT / "python" / "monarch" / "_rootfs_contract.py",
    )
    if spec is None or spec.loader is None:
        return
    contract = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = contract
    spec.loader.exec_module(contract)
    contract.require_checkout(_REPO_ROOT)


def build_dashboard_frontend(
    frontend_dir: Path, *, npm: str = "npm"
) -> tuple[Path, Path, Path]:
    """Build the dashboard assets and return (index.html, main.js, main.css).

    Removes any prior ``build`` directory, runs ``npm ci`` and ``npm run build``,
    requires the esbuild JS and CSS outputs, moves the CSS under ``static/css``,
    and copies ``public/index.html`` into the build tree.
    """
    _require_controlled_domain()

    frontend_dir = Path(frontend_dir).resolve()
    if not frontend_dir.is_dir():
        raise RuntimeError(f"frontend directory not found: {frontend_dir}")

    build_dir = frontend_dir / "build"
    if build_dir.is_symlink():
        raise RuntimeError(f"frontend build path is a symlink: {build_dir}")

    npm_path = shutil.which(npm)
    if npm_path is None:
        raise RuntimeError(f"npm not found: {npm}")

    if build_dir.exists():
        shutil.rmtree(build_dir)

    try:
        subprocess.run([npm_path, "ci"], cwd=frontend_dir, check=True)
        subprocess.run([npm_path, "run", "build"], cwd=frontend_dir, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"frontend build failed: {e}") from e

    javascript = build_dir / "static" / "js" / "main.js"
    if not javascript.is_file():
        raise RuntimeError(f"frontend build produced no javascript: {javascript}")

    emitted_css = build_dir / "static" / "js" / "main.css"
    if not emitted_css.is_file():
        raise RuntimeError(f"frontend build produced no css: {emitted_css}")

    css = build_dir / "static" / "css" / "main.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(emitted_css), str(css))

    index = build_dir / "index.html"
    shutil.copy(frontend_dir / "public" / "index.html", index)

    return index, javascript, css


def main() -> int:
    index, javascript, css = build_dashboard_frontend(_DEFAULT_FRONTEND)
    print(f"built {index}")
    print(f"built {javascript}")
    print(f"built {css}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
