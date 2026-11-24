#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def survey_candidate_path(path: Path) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    stat = os.statvfs(path)
    probe = path / ".ginkgo-exec-probe"
    executable_bit_supported = False
    try:
        probe.write_text("#!/bin/sh\nexit 0\n")
        probe.chmod(0o755)
        executable_bit_supported = os.access(probe, os.X_OK)
    finally:
        probe.unlink(missing_ok=True)

    return {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "is_writable": os.access(path, os.W_OK),
        "executable_bit_supported": executable_bit_supported,
        "filesystem_id": stat.f_fsid,
        "free_bytes": stat.f_bavail * stat.f_frsize,
        "free_inodes": stat.f_favail,
    }


def detect_nvidia_devices() -> list[str]:
    dev = Path("/dev")
    if not dev.is_dir():
        return []
    return sorted(str(path) for path in dev.glob("nvidia*"))


def run_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def build_host_survey(
    *,
    repo_root: Path,
    rootfs_root: Path,
    cache_root: Path,
    temp_root: Path,
    run_root: Path,
    results_root: Path,
    shm_root: Path,
    ports: list[int],
) -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    driver_version = ""
    if nvidia_smi is not None:
        driver_version = run_command(
            [nvidia_smi, "--query-gpu=driver_version", "--format=csv,noheader"]
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paths": {
            "repo": survey_candidate_path(repo_root),
            "rootfs": survey_candidate_path(rootfs_root),
            "cache": survey_candidate_path(cache_root),
            "temp": survey_candidate_path(temp_root),
            "run": survey_candidate_path(run_root),
            "results": survey_candidate_path(results_root),
            "shared_memory": survey_candidate_path(shm_root),
        },
        "tools": {
            "bwrap": {"path": shutil.which("bwrap")},
            "docker": {"path": shutil.which("docker")},
            "nvidia-smi": {"path": nvidia_smi},
        },
        "gpu": {
            "nvidia_devices": detect_nvidia_devices(),
            "driver_version": driver_version,
        },
        "ports": {
            "bind_host": "127.0.0.1",
            "checked": ports,
            "results": [
                {
                    "port": port,
                    "available": port_available(port),
                }
                for port in ports
            ],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="survey host capabilities for Ginkgo")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--rootfs-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--shm-root", type=Path, required=True)
    parser.add_argument("--port", dest="ports", action="append", type=int, default=[])
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_host_survey(
        repo_root=args.repo_root,
        rootfs_root=args.rootfs_root,
        cache_root=args.cache_root,
        temp_root=args.temp_root,
        run_root=args.run_root,
        results_root=args.results_root,
        shm_root=args.shm_root,
        ports=args.ports,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
