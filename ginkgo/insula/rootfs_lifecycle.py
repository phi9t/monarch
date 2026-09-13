from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from ginkgo.insula.schema import InsulaConfigError


REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_ROOTFS = REPO_ROOT / "scripts" / "rootfs" / "build_rootfs.sh"
VERIFY_ROOTFS = REPO_ROOT / "scripts" / "rootfs" / "verify_rootfs.py"


def prepare_rootfs(
    *,
    rootfs: Path,
    expected_recipe: str | None,
    build: bool,
    verify: bool,
    run: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> dict[str, str | None]:
    if not rootfs.is_absolute():
        raise InsulaConfigError(f"rootfs must be an absolute path: {rootfs}")

    runner = run or subprocess.run
    recipe = _read_recipe(rootfs)
    stale = expected_recipe is not None and recipe != expected_recipe
    missing = not rootfs.exists()

    if (missing or stale) and build:
        runner([str(BUILD_ROOTFS), "--dest", str(rootfs)], check=True)
        recipe = _read_recipe(rootfs)
        stale = expected_recipe is not None and recipe != expected_recipe

    if missing and not rootfs.exists():
        raise InsulaConfigError(f"rootfs does not exist: {rootfs}")
    if stale:
        raise InsulaConfigError(
            f"rootfs recipe mismatch: expected {expected_recipe}, found {recipe}"
        )
    if not (rootfs / "bin" / "bash").is_file():
        raise InsulaConfigError(f"rootfs missing executable: {rootfs / 'bin' / 'bash'}")

    if verify:
        command = [sys.executable, str(VERIFY_ROOTFS), "--rootfs", str(rootfs)]
        if expected_recipe is not None:
            command.extend(["--expected-recipe", expected_recipe])
        runner(command, check=True)
        recipe = _read_recipe(rootfs)

    return {
        "status": "ready",
        "rootfs": str(rootfs),
        "recipe_sha256": recipe,
    }


def _read_recipe(rootfs: Path) -> str | None:
    contract = rootfs / "etc" / "monarch-rootfs-contract"
    if not contract.is_file():
        return None
    for line in contract.read_text().splitlines():
        if line.startswith("MONARCH_ROOTFS_RECIPE_SHA256="):
            return line.split("=", 1)[1]
    return None
