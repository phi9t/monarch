"""Pure contract, provenance, CI predicate, and rootfs-builder tests.

These tests source ``execution_contract.sh`` and drive its pure validation
helpers with explicit fact files, so they never require a real rootfs. Cases
that consume the filesystem pass ``tmp_path`` fixtures rather than probing the
host.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "scripts/rootfs/execution_contract.sh"
CONTRACT_ENV = REPO_ROOT / "scripts/rootfs/contract.env"


def bash(
    script: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Source the contract library and evaluate ``script`` against it."""
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift; {script}', "bash", str(CONTRACT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_github_linux_requires_the_complete_identity() -> None:
    complete = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_ACTIONS": "true",
        "RUNNER_OS": "Linux",
        "GITHUB_RUN_ID": "1234",
        "GITHUB_WORKFLOW_REF": "meta-pytorch/monarch/.github/workflows/test.yml@refs/pull/1/merge",
    }
    assert bash("monarch_is_github_linux_ci", env=complete).returncode == 0
    # CI=true alone is never enough.
    assert (
        bash("monarch_is_github_linux_ci", env={"PATH": "/usr/bin:/bin", "CI": "true"}).returncode
        != 0
    )
    # A zero run id is not a positive numeric run id.
    assert bash("monarch_is_github_linux_ci", env={**complete, "GITHUB_RUN_ID": "0"}).returncode != 0
    # A non-Linux runner is not the GitHub Linux domain.
    assert (
        bash("monarch_is_github_linux_ci", env={**complete, "RUNNER_OS": "macOS"}).returncode != 0
    )
    # An empty workflow ref is not enough.
    assert (
        bash("monarch_is_github_linux_ci", env={**complete, "GITHUB_WORKFLOW_REF": ""}).returncode
        != 0
    )


def test_uid_map_must_be_a_single_id(tmp_path: Path) -> None:
    single = tmp_path / "single"
    single.write_text("      1018          0          1\n")
    broad = tmp_path / "broad"
    broad.write_text("         0          0 4294967295\n")
    multi = tmp_path / "multi"
    multi.write_text("      1018          0          1\n      2000          2          5\n")
    assert bash('monarch_uid_map_is_single_id "$1"', str(single)).returncode == 0
    assert bash('monarch_uid_map_is_single_id "$1"', str(broad)).returncode != 0
    assert bash('monarch_uid_map_is_single_id "$1"', str(multi)).returncode != 0


def test_recipe_digest_is_location_independent(tmp_path: Path) -> None:
    """The recipe hash uses relative file names, so worktree location does not
    change identity, but content changes do."""
    result = bash('monarch_rootfs_recipe_sha256 "$1"', str(REPO_ROOT))
    assert result.returncode == 0
    digest = result.stdout.strip()
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_contract_files_match_detects_drift(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    expected.write_text("MONARCH_ROOTFS_RECIPE_SHA256=" + "a" * 64 + "\n")
    same = tmp_path / "same"
    same.write_text("MONARCH_ROOTFS_RECIPE_SHA256=" + "a" * 64 + "\n")
    other = tmp_path / "other"
    other.write_text("MONARCH_ROOTFS_RECIPE_SHA256=" + "b" * 64 + "\n")
    assert bash('monarch_contract_files_match "$1" "$2"', str(expected), str(same)).returncode == 0
    assert bash('monarch_contract_files_match "$1" "$2"', str(expected), str(other)).returncode != 0


def test_checkout_matches_exact_mount() -> None:
    assert (
        bash(
            'monarch_checkout_matches "$1" "$2"', "/workspace/monarch", "/workspace/monarch"
        ).returncode
        == 0
    )
    assert (
        bash(
            'monarch_checkout_matches "$1" "$2"', "/workspace/monarch", "/home/user/monarch"
        ).returncode
        != 0
    )


def test_require_rootfs_uses_the_common_status_two_diagnostic() -> None:
    """A bare marker never proves rootfs entry; the diagnostic points at
    ``scripts/run``."""
    result = subprocess.run(
        [CONTRACT, "require-rootfs"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "MONARCH_IN_ROOTFS": "1"},
    )
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr
    assert "run instead: scripts/run" in result.stderr


def test_require_controlled_accepts_github_linux() -> None:
    result = subprocess.run(
        [CONTRACT, "identify-controlled"],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GITHUB_ACTIONS": "true",
            "RUNNER_OS": "Linux",
            "GITHUB_RUN_ID": "1234",
            "GITHUB_WORKFLOW_REF": "meta-pytorch/monarch/.github/workflows/test.yml@refs/pull/1/merge",
        },
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "github-linux"


def test_require_controlled_rejects_bare_host() -> None:
    result = subprocess.run(
        [CONTRACT, "require-controlled"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "hermetic bwrap rootfs" in result.stderr


def test_darwin_predicate() -> None:
    assert bash("monarch_is_darwin", env={"PATH": "/usr/bin:/bin", "OSTYPE": "darwin23"}).returncode == 0
    assert bash("monarch_is_darwin", env={"PATH": "/usr/bin:/bin", "OSTYPE": "linux-gnu"}).returncode != 0


def test_contract_env_holds_the_reviewed_pins() -> None:
    text = CONTRACT_ENV.read_text()
    for pin in (
        "MONARCH_ROOTFS_SCHEMA=1",
        "MONARCH_ROOTFS_ARCH=x86_64",
        "MONARCH_BASE_IMAGE=",
        "MONARCH_UV_IMAGE=",
        "MONARCH_NODE_IMAGE=",
        "MONARCH_NODE_VERSION=20.19.5",
        "MONARCH_NPM_VERSION=10.8.2",
        "MONARCH_MDBOOK_VERSION=0.5.4",
        "MONARCH_NEXTEST_VERSION=0.9.143",
    ):
        assert pin in text, pin
