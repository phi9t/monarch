#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
REPO_MOUNT = "/workspace/monarch"
ROOTFS_CACHE_MOUNT = f"{REPO_MOUNT}/scripts/rootfs/cache"


class SandboxConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RootfsExport:
    rootfs: Path
    recipe_sha256: str


@dataclass(frozen=True)
class HostLayout:
    repo_root: Path
    cache_root: Path
    cargo_target_root: Path


@dataclass(frozen=True)
class SandboxLayout:
    repo_root: str
    cache_root: str
    cargo_target_dir: str
    home: str
    nvidia_host: str


@dataclass(frozen=True)
class Mount:
    host_path: Path
    sandbox_path: str
    mode: str
    purpose: str


@dataclass(frozen=True)
class BwrapSandboxPlan:
    schema_version: int
    rootfs: RootfsExport
    host_layout: HostLayout
    sandbox_layout: SandboxLayout
    cwd: str
    repo_projection_mode: str
    mounts: list[Mount]
    env: dict[str, str]
    network: str
    gpu: str
    inner_argv: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["rootfs"]["rootfs"] = str(self.rootfs.rootfs)
        data["host_layout"] = {
            "repo_root": str(self.host_layout.repo_root),
            "cache_root": str(self.host_layout.cache_root),
            "cargo_target_root": str(self.host_layout.cargo_target_root),
        }
        data["mounts"] = [
            {
                "host_path": str(mount.host_path),
                "sandbox_path": mount.sandbox_path,
                "mode": mount.mode,
                "purpose": mount.purpose,
            }
            for mount in self.mounts
        ]
        return data


def _require_absolute(path: Path, name: str) -> Path:
    if not path.is_absolute():
        raise SandboxConfigError(f"{name} must be absolute: {path}")
    return path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def materialize_sandbox_plan(
    *,
    rootfs: Path,
    repo_root: Path,
    recipe_sha256: str,
    cache_root: Path,
    cwd: str,
    repo_projection_mode: str,
    inner_argv: list[str],
    extra_mounts: list[Mount] | None = None,
    extra_env: dict[str, str] | None = None,
) -> BwrapSandboxPlan:
    rootfs = _require_absolute(rootfs, "rootfs")
    repo_root = _require_absolute(repo_root, "repo_root")
    cache_root = _require_absolute(cache_root, "cache_root")
    if _is_relative_to(cache_root, rootfs):
        raise SandboxConfigError(f"cache_root must not live inside rootfs: {cache_root}")
    if repo_projection_mode not in {"rw", "ro"}:
        raise SandboxConfigError(f"repo_projection_mode must be rw or ro: {repo_projection_mode}")
    if not cwd.startswith(REPO_MOUNT):
        raise SandboxConfigError(f"cwd must be inside {REPO_MOUNT}: {cwd}")
    if not inner_argv:
        raise SandboxConfigError("inner_argv must not be empty")

    cargo_target_root = cache_root / "target" / "bwrap" / recipe_sha256
    sandbox_target = f"{REPO_MOUNT}/target/bwrap/{recipe_sha256}"
    mounts = [
        Mount(rootfs, "/", "ro", "rootfs"),
        Mount(repo_root, REPO_MOUNT, repo_projection_mode, "repo"),
        Mount(cache_root, ROOTFS_CACHE_MOUNT, "rw", "cache"),
        Mount(cargo_target_root, sandbox_target, "rw", "cargo-target"),
    ]
    if extra_mounts:
        mounts.extend(extra_mounts)

    env = {
        "HOME": "/home/monarch",
        "PATH": "/opt/cuda-synth/bin:/opt/cargo/bin:/usr/local/bin:/usr/bin:/bin:/run/nvidia-host",
        "UV_PROJECT_ENVIRONMENT": f"{REPO_MOUNT}/.venv-rootfs",
        "UV_CACHE_DIR": f"{ROOTFS_CACHE_MOUNT}/uv",
        "CARGO_HOME": f"{ROOTFS_CACHE_MOUNT}/cargo",
        "CARGO_TARGET_DIR": sandbox_target,
        "npm_config_cache": f"{ROOTFS_CACHE_MOUNT}/npm",
        "XDG_CACHE_HOME": f"{ROOTFS_CACHE_MOUNT}/xdg",
        "RUSTUP_HOME": "/opt/rustup",
        "CUDA_HOME": "/opt/cuda-synth",
        "CUDA_PATH": "/opt/cuda-synth",
        "MONARCH_IN_ROOTFS": "1",
        "MONARCH_ROOTFS_RECIPE_SHA256": recipe_sha256,
    }
    if extra_env:
        env.update(extra_env)

    return BwrapSandboxPlan(
        schema_version=SCHEMA_VERSION,
        rootfs=RootfsExport(rootfs=rootfs, recipe_sha256=recipe_sha256),
        host_layout=HostLayout(
            repo_root=repo_root,
            cache_root=cache_root,
            cargo_target_root=cargo_target_root,
        ),
        sandbox_layout=SandboxLayout(
            repo_root=REPO_MOUNT,
            cache_root=ROOTFS_CACHE_MOUNT,
            cargo_target_dir=sandbox_target,
            home="/home/monarch",
            nvidia_host="/run/nvidia-host",
        ),
        cwd=cwd,
        repo_projection_mode=repo_projection_mode,
        mounts=mounts,
        env=dict(sorted(env.items())),
        network="share-net",
        gpu="dev-bind-nvidia-when-present",
        inner_argv=inner_argv,
    )


def bwrap_argv_from_plan(plan: BwrapSandboxPlan) -> list[str]:
    argv = [
        "bwrap",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--dev",
        "/dev",
        "--tmpfs",
        "/home",
        "--dir",
        "/home/monarch",
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--clearenv",
        "--chdir",
        plan.cwd,
    ]
    for mount in plan.mounts:
        if mount.sandbox_path == "/":
            flag = "--ro-bind"
        elif mount.mode == "ro":
            flag = "--ro-bind"
        elif mount.purpose.startswith("dev"):
            flag = "--dev-bind"
        else:
            flag = "--bind"
        argv.extend([flag, str(mount.host_path), mount.sandbox_path])
    for key, value in sorted(plan.env.items()):
        argv.extend(["--setenv", key, value])
    argv.extend(plan.inner_argv)
    return argv


def parse_bwrap_argv(argv: list[str]) -> tuple[list[Mount], dict[str, str], str]:
    if not argv or argv[0] != "bwrap":
        raise SandboxConfigError("bwrap argv must start with bwrap")
    mounts: list[Mount] = []
    env: dict[str, str] = {}
    cwd = ""
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg in {"--bind", "--ro-bind", "--dev-bind"}:
            if index + 2 >= len(argv):
                raise SandboxConfigError(f"{arg} requires host and sandbox paths")
            host_path = Path(argv[index + 1])
            sandbox_path = argv[index + 2]
            mode = "ro" if arg == "--ro-bind" else "rw"
            purpose = "dev" if arg == "--dev-bind" else "unknown"
            mounts.append(Mount(host_path, sandbox_path, mode, purpose))
            index += 3
        elif arg == "--setenv":
            if index + 2 >= len(argv):
                raise SandboxConfigError("--setenv requires a name and value")
            env[argv[index + 1]] = argv[index + 2]
            index += 3
        elif arg == "--chdir":
            if index + 1 >= len(argv):
                raise SandboxConfigError("--chdir requires a path")
            cwd = argv[index + 1]
            index += 2
        elif arg in {"--proc", "--tmpfs", "--dev", "--dir"}:
            if index + 1 >= len(argv):
                raise SandboxConfigError(f"{arg} requires a path")
            index += 2
        elif arg == "--":
            break
        elif arg.startswith("--"):
            index += 1
        else:
            break
    return mounts, env, cwd


def validate_bwrap_argv_matches_plan(plan: BwrapSandboxPlan, argv: list[str]) -> None:
    actual_mounts, actual_env, actual_cwd = parse_bwrap_argv(argv)
    if actual_cwd != plan.cwd:
        raise SandboxConfigError(f"cwd mismatch: expected {plan.cwd}, found {actual_cwd}")
    expected_mounts = {
        mount.sandbox_path: (mount.host_path, mount.mode) for mount in plan.mounts
    }
    actual_mount_map = {
        mount.sandbox_path: (mount.host_path, mount.mode) for mount in actual_mounts
    }
    for sandbox_path, expected in expected_mounts.items():
        actual = actual_mount_map.get(sandbox_path)
        if actual != expected:
            raise SandboxConfigError(
                f"mount mismatch for {sandbox_path}: expected {expected}, found {actual}"
            )
    for key, expected_value in plan.env.items():
        actual_value = actual_env.get(key)
        if actual_value != expected_value:
            raise SandboxConfigError(
                f"env mismatch for {key}: expected {expected_value}, found {actual_value}"
            )
