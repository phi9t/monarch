import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "rootfs" / "verify_rootfs.py"

spec = importlib.util.spec_from_file_location("verify_rootfs", VERIFIER)
assert spec is not None and spec.loader is not None
verify_rootfs = importlib.util.module_from_spec(spec)
sys.modules["verify_rootfs"] = verify_rootfs
spec.loader.exec_module(verify_rootfs)


def write_executable(path: Path, text: str = "#!/bin/sh\nexit 0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def write_contract(rootfs: Path, recipe: str = "a" * 64) -> None:
    contract = rootfs / "etc" / "monarch-rootfs-contract"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        "\n".join(
            [
                "MONARCH_ROOTFS_SCHEMA=1",
                f"MONARCH_ROOTFS_RECIPE_SHA256={recipe}",
                "MONARCH_ROOTFS_ARCH=x86_64",
                "MONARCH_PYTHON_VERSION=3.12.3",
                "MONARCH_UV_VERSION=0.12.2",
                "MONARCH_NODE_VERSION=20.19.5",
                "MONARCH_NPM_VERSION=10.8.2",
                "MONARCH_MDBOOK_VERSION=0.5.4",
                "MONARCH_NEXTEST_VERSION=0.9.143",
                "MONARCH_CUDA_NVCC_VERSION=13.2.86",
                "MONARCH_CUDA_CCCL_VERSION=13.2.86",
                "MONARCH_CUDA_CRT_VERSION=13.2.86",
                "MONARCH_NVIDIA_NVVM_VERSION=13.2.86",
                "MONARCH_CUDA_CUOBJDUMP_VERSION=13.2.86",
                "MONARCH_CUDA_NVDISASM_VERSION=13.2.86",
                "",
            ]
        )
    )


def make_rootfs(tmp_path: Path, recipe: str = "a" * 64) -> Path:
    rootfs = tmp_path / "rootfs"
    write_contract(rootfs, recipe)
    for path in (
        "bin/bash",
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
    ):
        write_executable(rootfs / path)
    (rootfs / "opt/cuda-synth/include").mkdir(parents=True)
    (rootfs / "opt/cuda-synth/include/cuda_runtime.h").write_text("")
    (rootfs / "opt/cuda-synth/include/cuda_runtime_api.h").write_text(
        "#define CUDART_VERSION 13020\n"
    )
    (rootfs / "opt/cuda-synth/lib").mkdir(parents=True)
    (rootfs / "opt/cuda-synth/lib/libcudart.so.13").write_text("")
    (rootfs / "opt/cuda-synth/lib/libcudart.so").symlink_to("libcudart.so.13")
    (rootfs / "opt/cuda-synth/lib64").symlink_to("lib")
    (rootfs / "workspace/monarch").mkdir(parents=True)
    (rootfs / "run/nvidia-host").mkdir(parents=True)
    return rootfs


def test_verify_rootfs_handles_absolute_in_rootfs_cuda_symlink(tmp_path: Path) -> None:
    rootfs = make_rootfs(tmp_path)
    real_cuda = rootfs / "usr/local/lib/python3.12/dist-packages/nvidia/cu13"
    real_cuda.parent.mkdir(parents=True)
    shutil.rmtree(rootfs / "opt/cuda-synth")
    (rootfs / "opt/cuda-synth").symlink_to(
        "/usr/local/lib/python3.12/dist-packages/nvidia/cu13"
    )
    (real_cuda / "bin").mkdir(parents=True)
    for name in ("nvcc", "cuobjdump", "nvdisasm"):
        write_executable(real_cuda / "bin" / name)
    (real_cuda / "include").mkdir()
    (real_cuda / "include/cuda_runtime.h").write_text("")
    (real_cuda / "include/cuda_runtime_api.h").write_text(
        "#define CUDART_VERSION 13020\n"
    )
    (real_cuda / "lib").mkdir()
    (real_cuda / "lib/libcudart.so.13").write_text("")
    (real_cuda / "lib/libcudart.so").symlink_to("libcudart.so.13")
    (real_cuda / "lib64").symlink_to("lib")

    report = verify_rootfs.verify_rootfs(
        rootfs,
        expected_recipe="a" * 64,
        run_commands=False,
    )

    assert report.ok is True


def test_verify_rootfs_accepts_complete_export(tmp_path: Path) -> None:
    rootfs = make_rootfs(tmp_path)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    report = verify_rootfs.verify_rootfs(
        rootfs,
        expected_recipe="a" * 64,
        cache_root=cache_root,
        run_commands=False,
    )

    assert report.ok is True
    assert report.recipe_sha256 == "a" * 64
    assert report.cache_root == cache_root
    assert not report.errors


def test_verify_rootfs_rejects_missing_contract(tmp_path: Path) -> None:
    rootfs = make_rootfs(tmp_path)
    (rootfs / "etc/monarch-rootfs-contract").unlink()

    report = verify_rootfs.verify_rootfs(
        rootfs,
        expected_recipe="a" * 64,
        run_commands=False,
    )

    assert report.ok is False
    assert any("missing rootfs contract" in error for error in report.errors)


def test_verify_rootfs_rejects_stale_recipe(tmp_path: Path) -> None:
    rootfs = make_rootfs(tmp_path, recipe="b" * 64)

    report = verify_rootfs.verify_rootfs(
        rootfs,
        expected_recipe="a" * 64,
        run_commands=False,
    )

    assert report.ok is False
    assert any("recipe mismatch" in error for error in report.errors)


@pytest.mark.parametrize(
    "missing_path, message",
    [
        ("bin/bash", "missing executable"),
        ("workspace/monarch", "missing required mountpoint"),
        ("run/nvidia-host", "missing required mountpoint"),
        ("opt/cuda-synth/lib/libcudart.so", "missing cuda runtime linker name"),
    ],
)
def test_verify_rootfs_rejects_incomplete_export(
    tmp_path: Path, missing_path: str, message: str
) -> None:
    rootfs = make_rootfs(tmp_path)
    path = rootfs / missing_path
    if path.is_dir():
        path.rmdir()
    else:
        path.unlink()

    report = verify_rootfs.verify_rootfs(
        rootfs,
        expected_recipe="a" * 64,
        run_commands=False,
    )

    assert report.ok is False
    assert any(message in error for error in report.errors)


def test_verify_rootfs_rejects_relative_cache_root(tmp_path: Path) -> None:
    rootfs = make_rootfs(tmp_path)

    report = verify_rootfs.verify_rootfs(
        rootfs,
        expected_recipe="a" * 64,
        cache_root=Path("relative-cache"),
        run_commands=False,
    )

    assert report.ok is False
    assert any("cache root must be absolute" in error for error in report.errors)


def test_verify_rootfs_rejects_cache_root_inside_rootfs(tmp_path: Path) -> None:
    rootfs = make_rootfs(tmp_path)
    cache_root = rootfs / "cache"
    cache_root.mkdir()

    report = verify_rootfs.verify_rootfs(
        rootfs,
        expected_recipe="a" * 64,
        cache_root=cache_root,
        run_commands=False,
    )

    assert report.ok is False
    assert any("cache root must not live inside rootfs" in error for error in report.errors)


def test_verify_rootfs_cli_emits_json_and_nonzero_on_failure(tmp_path: Path) -> None:
    rootfs = make_rootfs(tmp_path)
    (rootfs / "bin/bash").unlink()

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--rootfs",
            str(rootfs),
            "--expected-recipe",
            "a" * 64,
            "--skip-command-checks",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert '"ok": false' in result.stdout
    assert "missing executable" in result.stdout
