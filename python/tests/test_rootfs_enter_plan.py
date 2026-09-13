import os
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ENTER_ROOTFS = REPO_ROOT / "scripts" / "rootfs" / "enter_rootfs.sh"
RUN = REPO_ROOT / "scripts" / "run"


def host_entry_env(**overrides: str) -> dict[str, str]:
    env = {**os.environ, **overrides}
    env.pop("MONARCH_IN_ROOTFS", None)
    return env


def test_enter_rootfs_emit_plan_writes_plan_without_bwrap(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-m",
            "sglang.launch_server",
            "--host",
            "127.0.0.1",
            "--port",
            "19017",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["rootfs_export"]["rootfs"] == str(REPO_ROOT / "scripts" / "rootfs" / "rootfs")
    assert plan["host_layout"]["repo_root"] == str(REPO_ROOT)
    assert plan["sandbox_layout"]["repo_root"] == "/workspace/monarch"
    assert plan["schema_translated_argv"][0] == "bwrap"
    assert plan["outer_argv"][0] == "bwrap"
    assert plan["schema_translated_argv"][-len(plan["inner_argv"]):] == plan["inner_argv"]
    assert plan["schema_version"] == 1
    assert plan["rootfs"].endswith("scripts/rootfs/rootfs")
    assert plan["cwd"] == "/workspace/monarch"
    assert plan["inner_argv"][:3] == ["python", "-m", "sglang.launch_server"]
    assert plan["repo_projection_mode"] == "rw"
    repo_mount = next(mount for mount in plan["mounts"] if mount["sandbox_path"] == "/workspace/monarch")
    assert repo_mount["mode"] == "rw"
    assert plan["network"] == "share-net"


def test_enter_rootfs_repo_readonly_emits_read_only_repo_mount(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--repo-readonly",
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-m",
            "sglang.launch_server",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["repo_projection_mode"] == "ro"
    repo_mount = next(mount for mount in plan["mounts"] if mount["sandbox_path"] == "/workspace/monarch")
    assert repo_mount["mode"] == "ro"


def test_enter_rootfs_emit_plan_has_unique_sandbox_mounts(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--repo-readonly",
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    sandbox_paths = [mount["sandbox_path"] for mount in plan["mounts"]]
    assert len(sandbox_paths) == len(set(sandbox_paths))


def test_enter_rootfs_emit_plan_preserves_hf_home(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--repo-readonly",
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={
            **os.environ,
            "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1",
            "HF_HOME": "/tmp/glm52/hf-home",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["env"]["HF_HOME"] == "/tmp/glm52/hf-home"


def test_enter_rootfs_emit_plan_preserves_sglang_cache_dir(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--repo-readonly",
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={
            **os.environ,
            "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1",
            "SGLANG_CACHE_DIR": "/cache/glm52/sglang",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["env"]["SGLANG_CACHE_DIR"] == "/cache/glm52/sglang"


def test_enter_rootfs_emit_plan_preserves_transformers_cache(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--repo-readonly",
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={
            **os.environ,
            "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1",
            "TRANSFORMERS_CACHE": "/cache/glm52/hf-home",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["env"]["TRANSFORMERS_CACHE"] == "/cache/glm52/hf-home"


def test_enter_rootfs_emit_plan_preserves_uv_cache_dir_override(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--repo-readonly",
            "--emit-plan",
            str(plan_path),
            "--",
            "uv",
            "venv",
            "/cache/glm52/venvs/sglang",
        ],
        env={
            **os.environ,
            "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1",
            "UV_CACHE_DIR": "/cache/glm52/uv",
            "XDG_CACHE_HOME": "/cache/glm52/xdg",
            "TORCHINDUCTOR_CACHE_DIR": "/cache/glm52/torchinductor",
            "TRITON_CACHE_DIR": "/cache/glm52/triton",
            "USER": "monarch",
            "LOGNAME": "monarch",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["env"]["UV_CACHE_DIR"] == "/cache/glm52/uv"
    assert plan["env"]["XDG_CACHE_HOME"] == "/cache/glm52/xdg"
    assert plan["env"]["TORCHINDUCTOR_CACHE_DIR"] == "/cache/glm52/torchinductor"
    assert plan["env"]["TRITON_CACHE_DIR"] == "/cache/glm52/triton"
    assert plan["env"]["USER"] == "monarch"
    assert plan["env"]["LOGNAME"] == "monarch"


def test_enter_rootfs_emit_plan_exposes_nvidia_link_path_when_present(tmp_path: Path) -> None:
    if not list(Path("/usr/lib/x86_64-linux-gnu").glob("libcuda.so*")):
        pytest.skip("host NVIDIA driver libraries are not present")
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["env"]["LD_LIBRARY_PATH"] == "/run/nvidia-host:/opt/cuda-synth/lib64"
    assert plan["env"]["LIBRARY_PATH"] == "/run/nvidia-host:/opt/cuda-synth/lib64"


def test_enter_rootfs_sets_nvidia_runtime_and_link_paths() -> None:
    text = ENTER_ROOTFS.read_text()

    assert '--setenv LD_LIBRARY_PATH "$NVIDIA_HOST_MNT:/opt/cuda-synth/lib64"' in text
    assert '--setenv LIBRARY_PATH "$NVIDIA_HOST_MNT:/opt/cuda-synth/lib64"' in text


def test_enter_rootfs_emit_plan_reports_extra_bind_mounts(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"
    rootfs_dir = tmp_path / "rootfs"
    run_dir = tmp_path / "run"
    cache_dir = tmp_path / "cache"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(rootfs_dir),
            "--bind-rw",
            f"{run_dir}:/run/glm52",
            "--bind-rw",
            f"{cache_dir}:/cache/glm52",
            "--emit-plan",
            str(plan_path),
            "--",
            "/cache/glm52/venvs/sglang/bin/python",
            "-m",
            "sglang.launch_server",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (rootfs_dir / "run").is_dir()
    assert (rootfs_dir / "cache").is_dir()
    plan = yaml.safe_load(plan_path.read_text())
    mounts = {mount["sandbox_path"]: mount for mount in plan["mounts"]}
    assert mounts["/run/glm52"] == {
        "host_path": str(run_dir),
        "sandbox_path": "/run/glm52",
        "mode": "rw",
        "purpose": "extra",
    }
    assert mounts["/cache/glm52"] == {
        "host_path": str(cache_dir),
        "sandbox_path": "/cache/glm52",
        "mode": "rw",
        "purpose": "extra",
    }
    outer_argv = plan["outer_argv"]
    dir_targets = [
        outer_argv[index + 1]
        for index, arg in enumerate(outer_argv)
        if arg == "--dir"
    ]
    tmpfs_targets = [
        outer_argv[index + 1]
        for index, arg in enumerate(outer_argv)
        if arg == "--tmpfs"
    ]
    assert "/run" in tmpfs_targets
    assert "/run/glm52" in dir_targets
    assert "/cache" in tmpfs_targets
    assert "/cache/glm52" in dir_targets
    assert plan["inner_argv"][:3] == [
        "/cache/glm52/venvs/sglang/bin/python",
        "-m",
        "sglang.launch_server",
    ]


def test_enter_rootfs_emit_plan_does_not_hide_nested_extra_binds(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"
    rootfs_dir = tmp_path / "rootfs"
    cache_dir = tmp_path / "cache"
    venv_dir = cache_dir / "venvs" / "sglang"
    hf_dir = cache_dir / "hf-home"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(rootfs_dir),
            "--bind-rw",
            f"{cache_dir}:/cache/glm52",
            "--bind-rw",
            f"{venv_dir}:/cache/glm52/venvs/sglang",
            "--bind-rw",
            f"{hf_dir}:/cache/glm52/hf-home",
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    outer_argv = plan["outer_argv"]
    tmpfs_targets = [
        outer_argv[index + 1]
        for index, arg in enumerate(outer_argv)
        if arg == "--tmpfs"
    ]
    assert tmpfs_targets.count("/cache") == 1
    bind_index = next(
        index
        for index, arg in enumerate(outer_argv)
        if arg == "--bind"
        and outer_argv[index + 1] == str(cache_dir)
        and outer_argv[index + 2] == "/cache/glm52"
    )
    assert outer_argv.index("/cache") < bind_index


def test_enter_rootfs_emit_plan_equals_form_preserves_chdir(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--chdir",
            "python",
            f"--emit-plan={plan_path}",
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["rootfs"] == str(REPO_ROOT / "scripts" / "rootfs" / "rootfs")
    assert plan["cwd"] == "/workspace/monarch/python"
    assert plan["inner_argv"] == ["python", "-c", "print(1)"]
    assert plan["repo_projection_mode"] == "rw"


def test_enter_rootfs_help_includes_emit_plan_and_rootfs_options() -> None:
    result = subprocess.run(
        [str(ENTER_ROOTFS), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--emit-plan PATH" in result.stdout
    assert "Write the resolved bwrap/rootfs plan before launch." in result.stdout
    assert "--rootfs DIR" in result.stdout
    assert "-h, --help" in result.stdout


def test_enter_rootfs_emit_plan_allows_separator_like_env_values(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={**os.environ, "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1", "TERM": "--"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["env"]["TERM"] == "--"
    assert plan["inner_argv"] == ["python", "-c", "print(1)"]


def test_scripts_run_forwards_explicit_rootfs_to_enter_rootfs_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"
    rootfs_dir = tmp_path / "rootfs"

    result = subprocess.run(
        [str(RUN), "python", "-c", "print(1)"],
        env=host_entry_env(
            MONARCH_ROOTFS=str(rootfs_dir),
            MONARCH_ROOTFS_EMIT_PLAN=str(plan_path),
            MONARCH_ROOTFS_EMIT_PLAN_ONLY="1",
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    assert plan["rootfs"] == str(rootfs_dir)
    assert plan["inner_argv"] == [
        "/workspace/monarch/scripts/run",
        "python",
        "-c",
        "print(1)",
    ]


def test_scripts_run_rejects_relative_explicit_rootfs(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(RUN), "python", "-c", "print(1)"],
        env=host_entry_env(
            MONARCH_ROOTFS="relative-rootfs",
            MONARCH_ROOTFS_EMIT_PLAN=str(tmp_path / "rootfs-plan.yaml"),
            MONARCH_ROOTFS_EMIT_PLAN_ONLY="1",
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "MONARCH_ROOTFS must be an absolute path" in result.stderr


def test_enter_rootfs_emit_plan_binds_external_cache_root(tmp_path: Path) -> None:
    plan_path = tmp_path / "rootfs-plan.yaml"
    cache_root = tmp_path / "cache-root"

    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--emit-plan",
            str(plan_path),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={
            **os.environ,
            "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1",
            "MONARCH_ROOTFS_CACHE_ROOT": str(cache_root),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load(plan_path.read_text())
    mounts = {mount["sandbox_path"]: mount for mount in plan["mounts"]}
    assert mounts["/workspace/monarch/scripts/rootfs/cache"] == {
        "host_path": str(cache_root),
        "sandbox_path": "/workspace/monarch/scripts/rootfs/cache",
        "mode": "rw",
        "purpose": "cache",
    }
    target_mount = mounts[plan["env"]["CARGO_TARGET_DIR"]]
    assert target_mount["host_path"].startswith(str(cache_root / "target" / "bwrap"))
    assert target_mount["mode"] == "rw"
    assert target_mount["purpose"] == "cargo-target"
    assert plan["host_layout"]["cache_root"] == str(cache_root)
    assert plan["sandbox_layout"]["cache_root"] == "/workspace/monarch/scripts/rootfs/cache"
    assert plan["env"]["UV_CACHE_DIR"] == "/workspace/monarch/scripts/rootfs/cache/uv"


def test_enter_rootfs_rejects_relative_external_cache_root(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(ENTER_ROOTFS),
            "--rootfs",
            str(REPO_ROOT / "scripts" / "rootfs" / "rootfs"),
            "--emit-plan",
            str(tmp_path / "rootfs-plan.yaml"),
            "--",
            "python",
            "-c",
            "print(1)",
        ],
        env={
            **os.environ,
            "MONARCH_ROOTFS_EMIT_PLAN_ONLY": "1",
            "MONARCH_ROOTFS_CACHE_ROOT": "relative-cache-root",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "MONARCH_ROOTFS_CACHE_ROOT must be absolute" in result.stderr
