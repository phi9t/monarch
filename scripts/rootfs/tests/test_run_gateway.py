"""Argument, CWD, environment, exit, namespace, and mount tests for scripts/run.

These tests run the real gateway, so they enter the rootfs. They assert that
scripts/run preserves arguments and exit status, maps a checkout-relative CWD,
does not nest the user namespace, activates the rootfs venv, and strips host
compiler variables.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN = REPO_ROOT / "scripts/run"


def test_inner_run_preserves_arguments_and_exit_status() -> None:
    result = subprocess.run(
        [
            RUN,
            "python",
            "-c",
            "import sys; print(sys.argv[1:]); raise SystemExit(37)",
            "a b",
            "$HOME",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 37
    assert "['a b', '$HOME']" in result.stdout


def test_inner_run_does_not_nest_the_user_namespace() -> None:
    before = os.readlink("/proc/self/ns/user")
    result = subprocess.run(
        [RUN, "python", "-c", "import os; print(os.readlink('/proc/self/ns/user'))"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == before


def test_inner_run_forwards_signals() -> None:
    process = subprocess.Popen(
        [
            RUN,
            "python",
            "-c",
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, lambda *_: sys.exit(42))\n"
            "print('ready', flush=True)\n"
            "time.sleep(30)\n",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    process.terminate()
    assert process.wait(timeout=15) == 42


def test_run_activates_the_rootfs_venv() -> None:
    result = subprocess.run(
        [RUN, "python", "-c", "import os,sys; print(os.environ['VIRTUAL_ENV']); print(sys.executable)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == [
        "/workspace/monarch/.venv-rootfs",
        "/workspace/monarch/.venv-rootfs/bin/python",
    ]


def test_run_strips_host_compiler_variables() -> None:
    env = {**os.environ, "CC": "/host/cc", "CXX": "/host/cxx", "PYTHONPATH": "/host/py"}
    result = subprocess.run(
        [
            RUN,
            "python",
            "-c",
            "import os; print('CC' in os.environ, 'CXX' in os.environ, 'PYTHONPATH' in os.environ)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.stdout.strip() == "False False False"


def test_run_maps_a_checkout_subdirectory() -> None:
    result = subprocess.run(
        ["../scripts/run", "python", "-c", "import os; print(os.getcwd())"],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT / "docs"),
    )
    assert result.stdout.strip() == "/workspace/monarch/docs"
