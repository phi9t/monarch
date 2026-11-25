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
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ENV = REPO_ROOT / "scripts" / "rootfs" / "contract.env"

REQUIRED_EXECUTABLES = (
    "bin/bash",
    "usr/bin/bwrap",
    "usr/bin/python",
    "usr/local/bin/uv",
    "usr/local/bin/node",
    "usr/local/bin/npm",
    "opt/cargo/bin/cargo",
    "opt/cargo/bin/rustc",
    "opt/cargo/bin/mdbook",
    "opt/cargo/bin/cargo-nextest",
    "opt/cuda-synth/bin/nvcc",
    "opt/cuda-synth/bin/cuobjdump",
    "opt/cuda-synth/bin/nvdisasm",
)
REQUIRED_MOUNTPOINTS = ("cache", "workspace/monarch", "run/nvidia-host")
REQUIRED_CUDA_FILES = (
    "opt/cuda-synth/include/cuda_runtime.h",
    "opt/cuda-synth/include/cuda_runtime_api.h",
    "opt/cuda-synth/lib/libcudart.so.13",
    "opt/cuda-synth/lib/libcudart.so",
)


@dataclass
class RootfsVerificationReport:
    rootfs: Path
    ok: bool
    recipe_sha256: str | None = None
    cache_root: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "rootfs": str(self.rootfs),
            "recipe_sha256": self.recipe_sha256,
            "cache_root": str(self.cache_root) if self.cache_root is not None else None,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def parse_contract_env(path: Path = CONTRACT_ENV) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def parse_rootfs_contract(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"malformed contract line: {raw_line}")
        key, value = line.split("=", 1)
        values[key] = value
    return values


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def rootfs_path(rootfs: Path, rel: str) -> Path:
    path = rootfs / rel
    parts = Path(rel).parts
    current = rootfs
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            target = Path(os.readlink(current))
            remainder = Path(*parts[index + 1 :])
            if target.is_absolute():
                current = rootfs / str(target).lstrip("/")
            else:
                current = current.parent / target
            if str(remainder) != ".":
                current = current / remainder
            return current
    return path


def run_command(command: list[str], rootfs: Path) -> str:
    env = {
        **os.environ,
        "PATH": (
            f"{rootfs / 'opt/cuda-synth/bin'}:"
            f"{rootfs / 'opt/cargo/bin'}:"
            f"{rootfs / 'usr/local/bin'}:"
            f"{rootfs / 'usr/bin'}:"
            f"{rootfs / 'bin'}"
        ),
    }
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(command)} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip() or result.stderr.strip()


def cudart_minor_from_header(header: Path) -> str | None:
    match = re.search(r"^#define\s+CUDART_VERSION\s+(\d+)", header.read_text(), re.M)
    if match is None:
        return None
    version = int(match.group(1))
    return f"{version // 1000}.{version % 1000 // 10}"


def nvcc_minor_from_output(output: str) -> str | None:
    match = re.search(r"release\s+([0-9]+\.[0-9]+),", output)
    return match.group(1) if match else None


def check_required_paths(rootfs: Path, errors: list[str]) -> None:
    for rel in REQUIRED_EXECUTABLES:
        path = rootfs_path(rootfs, rel)
        if not path.is_file() or not os.access(path, os.X_OK):
            errors.append(f"missing executable: /{rel}")
    for rel in REQUIRED_MOUNTPOINTS:
        if not rootfs_path(rootfs, rel).is_dir():
            errors.append(f"missing required mountpoint: /{rel}")
    for rel in REQUIRED_CUDA_FILES:
        path = rootfs_path(rootfs, rel)
        if rel.endswith("libcudart.so") and not path.exists():
            errors.append(f"missing cuda runtime linker name: /{rel}")
        elif not path.exists():
            errors.append(f"missing cuda file: /{rel}")
    lib64 = rootfs_path(rootfs, "opt/cuda-synth/lib64")
    if not lib64.exists():
        errors.append("missing cuda lib64 path: /opt/cuda-synth/lib64")


def check_cache_root(rootfs: Path, cache_root: Path | None, errors: list[str]) -> Path | None:
    if cache_root is None:
        return None
    if not cache_root.is_absolute():
        errors.append(f"cache root must be absolute: {cache_root}")
        return cache_root
    cache_root.mkdir(parents=True, exist_ok=True)
    if is_relative_to(cache_root, rootfs):
        errors.append(f"cache root must not live inside rootfs: {cache_root}")
    if not os.access(cache_root, os.W_OK):
        errors.append(f"cache root is not writable: {cache_root}")
    return cache_root


def check_contract(
    rootfs: Path,
    expected_recipe: str | None,
    errors: list[str],
) -> str | None:
    contract_path = rootfs / "etc/monarch-rootfs-contract"
    if not contract_path.is_file():
        errors.append(f"missing rootfs contract: {contract_path}")
        return None
    try:
        contract = parse_rootfs_contract(contract_path)
    except ValueError as exc:
        errors.append(str(exc))
        return None

    recipe = contract.get("MONARCH_ROOTFS_RECIPE_SHA256")
    if recipe is None:
        errors.append("rootfs contract missing MONARCH_ROOTFS_RECIPE_SHA256")
    elif not re.fullmatch(r"[0-9a-f]{64}", recipe):
        errors.append(f"invalid rootfs recipe digest: {recipe}")
    if expected_recipe is not None and recipe != expected_recipe:
        errors.append(f"recipe mismatch: expected {expected_recipe}, found {recipe}")

    expected_values = parse_contract_env()
    for key in (
        "MONARCH_ROOTFS_SCHEMA",
        "MONARCH_ROOTFS_ARCH",
        "MONARCH_PYTHON_VERSION",
        "MONARCH_UV_VERSION",
        "MONARCH_NODE_VERSION",
        "MONARCH_NPM_VERSION",
        "MONARCH_MDBOOK_VERSION",
        "MONARCH_NEXTEST_VERSION",
        "MONARCH_CUDA_NVCC_VERSION",
        "MONARCH_CUDA_CCCL_VERSION",
        "MONARCH_CUDA_CRT_VERSION",
        "MONARCH_NVIDIA_NVVM_VERSION",
        "MONARCH_CUDA_CUOBJDUMP_VERSION",
        "MONARCH_CUDA_NVDISASM_VERSION",
    ):
        expected = expected_values.get(key)
        actual = contract.get(key)
        if expected is not None and actual != expected:
            errors.append(f"contract {key} mismatch: expected {expected}, found {actual}")
    return recipe


def check_cuda_version_coherence(
    rootfs: Path, errors: list[str], run_commands: bool
) -> None:
    header_minor = cudart_minor_from_header(
        rootfs_path(rootfs, "opt/cuda-synth/include/cuda_runtime_api.h")
    )
    if header_minor is None:
        errors.append("missing CUDART_VERSION in /opt/cuda-synth/include/cuda_runtime_api.h")
        return
    if not run_commands:
        return
    nvcc = rootfs_path(rootfs, "opt/cuda-synth/bin/nvcc")
    try:
        output = run_command([str(nvcc), "--version"], rootfs)
    except RuntimeError as exc:
        errors.append(str(exc))
        return
    nvcc_minor = nvcc_minor_from_output(output)
    if nvcc_minor is None:
        errors.append("could not parse nvcc release version")
    elif nvcc_minor != header_minor:
        errors.append(
            f"cuda compiler/header mismatch: nvcc {nvcc_minor} vs CUDART_VERSION {header_minor}"
        )


def check_tool_versions(rootfs: Path, errors: list[str], run_commands: bool) -> None:
    if not run_commands:
        return
    expected = parse_contract_env()
    commands: Iterable[tuple[str, list[str], str]] = (
        ("MONARCH_UV_VERSION", [str(rootfs / "usr/local/bin/uv"), "--version"], r"uv ([^\s]+)"),
        ("MONARCH_NODE_VERSION", [str(rootfs / "usr/local/bin/node"), "--version"], r"v([^\s]+)"),
        ("MONARCH_NPM_VERSION", [str(rootfs / "usr/local/bin/npm"), "--version"], r"([^\s]+)"),
        ("MONARCH_MDBOOK_VERSION", [str(rootfs / "opt/cargo/bin/mdbook"), "--version"], r"mdbook v([^\s]+)"),
    )
    for key, command, pattern in commands:
        try:
            output = run_command(command, rootfs)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        match = re.search(pattern, output)
        if match is None:
            errors.append(f"could not parse {key} from: {output}")
            continue
        actual = match.group(1)
        if actual != expected[key]:
            errors.append(f"{key} mismatch: expected {expected[key]}, found {actual}")


def verify_rootfs(
    rootfs: Path,
    *,
    expected_recipe: str | None = None,
    cache_root: Path | None = None,
    run_commands: bool = True,
) -> RootfsVerificationReport:
    errors: list[str] = []
    warnings: list[str] = []
    if not rootfs.is_absolute():
        errors.append(f"rootfs path must be absolute: {rootfs}")
    rootfs = rootfs.resolve()
    if not rootfs.exists():
        errors.append(f"rootfs does not exist: {rootfs}")
    elif not rootfs.is_dir():
        errors.append(f"rootfs is not a directory: {rootfs}")

    recipe = None
    if rootfs.is_dir():
        recipe = check_contract(rootfs, expected_recipe, errors)
        check_required_paths(rootfs, errors)
        check_cuda_version_coherence(rootfs, errors, run_commands)
        check_tool_versions(rootfs, errors, run_commands)

    resolved_cache_root = check_cache_root(rootfs, cache_root, errors)
    return RootfsVerificationReport(
        rootfs=rootfs,
        ok=not errors,
        recipe_sha256=recipe,
        cache_root=resolved_cache_root,
        errors=errors,
        warnings=warnings,
    )


def recipe_from_execution_contract() -> str:
    result = subprocess.run(
        [str(REPO_ROOT / "scripts/rootfs/execution_contract.sh"), "recipe-sha256"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="verify a Monarch bwrap rootfs export")
    parser.add_argument("--rootfs", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--expected-recipe")
    parser.add_argument("--skip-command-checks", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    expected_recipe = args.expected_recipe or recipe_from_execution_contract()
    report = verify_rootfs(
        args.rootfs,
        expected_recipe=expected_recipe,
        cache_root=args.cache_root,
        run_commands=not args.skip_command_checks,
    )
    if args.json_output:
        print(json.dumps(report.to_json_dict(), indent=2, sort_keys=True))
    elif report.ok:
        print(f"rootfs ok: {report.rootfs}")
    else:
        for error in report.errors:
            print(f"error: {error}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
