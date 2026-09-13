# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "local_8gpu_capacity.py"
)
REPO_ROOT = Path(__file__).resolve().parents[2]
ROOTFS_BUILDER = REPO_ROOT / "scripts" / "rootfs" / "build_rootfs.sh"
CAPACITY_SCRIPT = REPO_ROOT / "scripts" / "run_local_8gpu_capacity.sh"
spec = importlib.util.spec_from_file_location("local_8gpu_capacity", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
local_8gpu_capacity = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = local_8gpu_capacity
spec.loader.exec_module(local_8gpu_capacity)

CudaVisibleDevicesError = local_8gpu_capacity.CudaVisibleDevicesError
failed_pytest_node_ids = local_8gpu_capacity.failed_pytest_node_ids
parse_nextest_junit = local_8gpu_capacity.parse_nextest_junit
validated_cuda_visible_devices = local_8gpu_capacity.validated_cuda_visible_devices


def write_xml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(text)
    return path


@pytest.mark.parametrize("value", [None, ""])
def test_cuda_visible_devices_defaults_to_eight_devices(value: str | None) -> None:
    devices, defaulted = validated_cuda_visible_devices(value)

    assert devices == "0,1,2,3,4,5,6,7"
    assert defaulted


def test_cuda_visible_devices_accepts_explicit_eight_devices() -> None:
    devices, defaulted = validated_cuda_visible_devices("7,6,5,4,3,2,1,0")

    assert devices == "7,6,5,4,3,2,1,0"
    assert not defaulted


@pytest.mark.parametrize(
    "value",
    [
        "0,1,2,3,4,5,6",
        "0,1,2,3,4,5,6,7,8",
        "0,1,,3,4,5,6,7",
        ",1,2,3,4,5,6,7",
        "0,1,2,3,4,5,6,",
    ],
)
def test_cuda_visible_devices_rejects_wrong_or_empty_entries(value: str) -> None:
    with pytest.raises(CudaVisibleDevicesError):
        validated_cuda_visible_devices(value)


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite tests="1" failures="0" errors="0"></testsuite>',
        (
            '<testsuites><testsuite tests="1" failures="0" errors="0" />'
            '<testsuite tests="2" failures="0" errors="0" /></testsuites>'
        ),
    ],
)
def test_nextest_junit_pass(tmp_path: Path, xml: str) -> None:
    assert parse_nextest_junit(write_xml(tmp_path, xml)) == "pass"


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite tests="1" failures="1" errors="0"></testsuite>',
        '<testsuite tests="1" failures="0" errors="1"></testsuite>',
        (
            '<testsuites><testsuite tests="1" failures="0" errors="0" />'
            '<testsuite tests="1" failures="1" errors="0" /></testsuites>'
        ),
    ],
)
def test_nextest_junit_fail(tmp_path: Path, xml: str) -> None:
    assert parse_nextest_junit(write_xml(tmp_path, xml)) == "fail"


def test_nextest_junit_unknown_for_unparseable_file(tmp_path: Path) -> None:
    assert parse_nextest_junit(write_xml(tmp_path, "<testsuite>")) == "unknown"


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite tests="0" failures="0" errors="0" />',
        '<testsuite failures="0" errors="0" />',
        "<testsuites />",
    ],
)
def test_nextest_junit_unknown_without_tests(tmp_path: Path, xml: str) -> None:
    assert parse_nextest_junit(write_xml(tmp_path, xml)) == "unknown"


def test_nextest_junit_unknown_for_stale_artifact(tmp_path: Path) -> None:
    path = write_xml(
        tmp_path, '<testsuite tests="1" failures="0" errors="0" />'
    )
    modified_ns = path.stat().st_mtime_ns

    assert parse_nextest_junit(path, not_before_ns=modified_ns + 1) == "unknown"


def test_pytest_junit_extracts_failures_and_errors(tmp_path: Path) -> None:
    path = write_xml(
        tmp_path,
        """\
<testsuites>
  <testsuite>
    <testcase classname="python.tests.test_actor_error" name="test_ok" />
    <testcase classname="python.tests.test_actor_error" name="test_crash[False-v1]">
      <failure message="failed" />
    </testcase>
    <testcase classname="python.tests._monarch.test_actor_mesh" name="test_mesh">
      <error message="errored" />
    </testcase>
  </testsuite>
</testsuites>
""",
    )

    assert failed_pytest_node_ids(path) == [
        "python/tests/test_actor_error.py::test_crash[False-v1]",
        "python/tests/_monarch/test_actor_mesh.py::test_mesh",
    ]


def test_pytest_junit_rejects_unmapped_classname(tmp_path: Path) -> None:
    path = write_xml(
        tmp_path,
        """\
<testsuite>
  <testcase classname="tests.test_actor_error" name="test_crash">
    <failure message="failed" />
  </testcase>
</testsuite>
""",
    )

    with pytest.raises(ValueError, match="cannot map JUnit testcase"):
        failed_pytest_node_ids(path)


def test_pytest_junit_rejects_stale_artifact(tmp_path: Path) -> None:
    path = write_xml(
        tmp_path,
        """\
<testsuite>
  <testcase classname="python.tests.test_actor_error" name="test_crash">
    <failure message="failed" />
  </testcase>
</testsuite>
""",
    )
    modified_ns = path.stat().st_mtime_ns

    with pytest.raises(ValueError, match="stale artifact"):
        failed_pytest_node_ids(path, not_before_ns=modified_ns + 1)


@pytest.mark.parametrize(
    "dest",
    [
        "/",
        str(REPO_ROOT),
        str(REPO_ROOT / "scripts" / "rootfs" / "experiment"),
    ],
)
def test_rootfs_builder_rejects_destination_not_named_rootfs(dest: str) -> None:
    result = subprocess.run(
        [ROOTFS_BUILDER, "--dest", dest],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 2
    assert "--dest must be named rootfs or rootfs-*" in result.stderr


@pytest.mark.parametrize(
    "dest",
    [
        "/tmp/rootfs-experiment",
        str(REPO_ROOT / "scripts" / "rootfs"),
    ],
)
def test_rootfs_builder_dry_run_allows_rootfs_named_destinations(dest: str) -> None:
    result = subprocess.run(
        [ROOTFS_BUILDER, "--dest", dest, "--dry-run"],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"rootfs destination: {dest}" in result.stdout


def test_rootfs_builder_allows_absolute_external_rootfs_store(tmp_path: Path) -> None:
    dest = tmp_path / "rootfs-ca484a4d579b45c0"

    result = subprocess.run(
        [ROOTFS_BUILDER, "--dest", str(dest), "--dry-run"],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"rootfs destination: {dest}" in result.stdout


def test_rootfs_builder_rejects_symlink_destination(tmp_path: Path) -> None:
    target = tmp_path / "real-rootfs"
    target.mkdir()
    dest = tmp_path / "rootfs-link"
    dest.symlink_to(target)

    result = subprocess.run(
        [ROOTFS_BUILDER, "--dest", str(dest), "--dry-run"],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 2
    assert "--dest must not be a symbolic link" in result.stderr


def test_rootfs_entrypoint_uses_verify_rootfs_before_launch() -> None:
    entry = (REPO_ROOT / "scripts/rootfs/enter_rootfs.sh").read_text()

    verify_index = entry.index("verify_rootfs.py")
    bwrap_index = entry.index('exec bwrap "${bwrap_args[@]}"')
    assert verify_index < bwrap_index


def test_rootfs_builder_provides_cuda_runtime_linker_name() -> None:
    builder = ROOTFS_BUILDER.read_text()

    assert "libcudart.so.13" in builder
    assert "libcudart.so" in builder
    assert "test -e \"$cu/lib/libcudart.so\"" in builder


def test_rootfs_builder_rejects_cuda_compiler_header_mismatch() -> None:
    builder = ROOTFS_BUILDER.read_text()

    assert "nvidia-cuda-crt==${CUDA_CRT_VERSION}" in builder
    assert "nvidia-nvvm==${NVIDIA_NVVM_VERSION}" in builder
    assert "nvidia-cuda-cuobjdump==${CUDA_CUOBJDUMP_VERSION}" in builder
    assert "nvidia-cuda-nvdisasm==${CUDA_NVDISASM_VERSION}" in builder
    assert "cuobjdump missing" in builder
    assert "nvdisasm missing" in builder
    assert "CUDART_VERSION" in builder
    assert "nvcc_minor" in builder
    assert "cuda compiler/header mismatch" in builder


def test_capacity_script_delegates_before_python_or_cuda_work() -> None:
    text = CAPACITY_SCRIPT.read_text()
    delegation = text.index('exec "$REPO_ROOT/scripts/run"')
    for later in (
        "HOST_PYTHON=",
        "scripts/local_8gpu_capacity.py",
        "CUDA_VISIBLE_DEVICES",
    ):
        assert delegation < text.index(later), (
            f"scripts/run delegation must precede {later!r}"
        )
