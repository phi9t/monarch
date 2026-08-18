from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ginkgo.insula.bwrap_plan import build_bwrap_argv
from ginkgo.insula.bwrap_plan import emit_plan
from ginkgo.insula.bwrap_plan import validate_plan
from ginkgo.insula.local_environment import local_environment_from_mapping
from ginkgo.insula.materialize import materialize_invocation
from ginkgo.insula.schema import InsulaBindSpec
from ginkgo.insula.schema import InsulaCommandSpec
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import InsulaEnvironmentSpec
from ginkgo.insula.schema import InsulaInvocationSpec
from ginkgo.insula.schema import MaterializedInsulaInvocation


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOTFS_DIR = REPO_ROOT / "scripts" / "rootfs"
DEFAULT_ROOTFS = ROOTFS_DIR / "rootfs"
REPO_MOUNT = "/workspace/monarch"
ROOTFS_CONTRACT_PATH = "/etc/monarch-rootfs-contract"
CHECKOUT_TOOLS = ("python", "uv", "cargo")
HOST_ENV_ALLOWLIST = (
    "TERM",
    "COLORTERM",
    "http_proxy",
    "https_proxy",
    "ftp_proxy",
    "no_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "FTP_PROXY",
    "NO_PROXY",
    "NVIDIA_VISIBLE_DEVICES",
    "RUST_LOG",
    "RUST_BACKTRACE",
    "TORCHINDUCTOR_CACHE_DIR",
    "TRITON_CACHE_DIR",
    "SGLANG_CACHE_DIR",
    "TRANSFORMERS_CACHE",
    "USER",
    "LOGNAME",
    "USE_TENSOR_ENGINE",
    "MONARCH_GPU_PLATFORM",
    "MONARCH_PACKAGE_NAME",
    "MONARCH_VERSION",
    "ENABLE_MESSAGE_LOGGING",
    "GLM52_MODEL",
    "GLM52_CHAT_BASE_URL",
    "GLM52_RESPONSES_BASE_URL",
    "GLM52_RESPONSES_ADAPTER_HOST",
    "GLM52_RESPONSES_ADAPTER_PORT",
    "GLM52_API_KEY_ENV",
    "GLM52_ADAPTER_TIMEOUT_SECONDS",
    "GLM_API_KEY",
    "HF_HOME",
)
HOST_LEAK_VARS = (
    "CC",
    "CXX",
    "CPP",
    "LD",
    "CFLAGS",
    "CXXFLAGS",
    "CPPFLAGS",
    "LDFLAGS",
    "PYTHONPATH",
    "PYTHONHOME",
    "LIBCLANG_PATH",
    "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER",
)


@dataclass(frozen=True)
class EnterRootfsCompatArgs:
    rootfs: Path
    chdir: str
    repo_readonly: bool
    emit_plan: Path | None
    bind_rw: tuple[str, ...]
    payload: tuple[str, ...]


def monarch_run(argv: list[str]) -> int:
    payload = _strip_separator(argv)
    if _in_valid_rootfs(REPO_ROOT, CHECKOUT_TOOLS):
        _activate_rootfs_environment()
        if not payload:
            os.execv("/bin/bash", ["/bin/bash", "-l"])
        os.environ["MONARCH_ORIGINAL_COMMAND"] = " ".join(shlex.quote(arg) for arg in payload)
        os.execvp(payload[0], payload)

    _preflight_host()
    checkout_rel = _checkout_relative_cwd(Path.cwd())
    rootfs_args: list[str] = []
    if os.environ.get("MONARCH_ROOTFS"):
        rootfs = Path(os.environ["MONARCH_ROOTFS"])
        if not rootfs.is_absolute():
            raise InsulaConfigError(f"MONARCH_ROOTFS must be an absolute path: {rootfs}")
        rootfs_args = ["--rootfs", str(rootfs)]

    emit_plan_args: list[str] = []
    if os.environ.get("MONARCH_ROOTFS_EMIT_PLAN"):
        emit_plan = Path(os.environ["MONARCH_ROOTFS_EMIT_PLAN"])
        if not emit_plan.is_absolute():
            raise InsulaConfigError(f"MONARCH_ROOTFS_EMIT_PLAN must be an absolute path: {emit_plan}")
        emit_plan_args = ["--emit-plan", str(emit_plan)]

    command = [
        str(REPO_ROOT / "scripts" / "rootfs" / "enter_rootfs.sh"),
        *rootfs_args,
        *emit_plan_args,
        "--chdir",
        checkout_rel,
        "--",
        f"{REPO_MOUNT}/scripts/run",
        *payload,
    ]
    os.execv(command[0], command)
    raise AssertionError("unreachable")


def enter_rootfs_compat(args: EnterRootfsCompatArgs) -> int:
    _preflight_host()
    rootfs = args.rootfs if args.rootfs.is_absolute() else (Path.cwd() / args.rootfs)
    recipe_sha256 = _recipe_sha256()
    _ensure_rootfs(rootfs, recipe_sha256)
    _verify_rootfs(rootfs)

    plan = _materialize_legacy_plan(args=args, rootfs=rootfs, recipe_sha256=recipe_sha256)
    if args.emit_plan is not None:
        args.emit_plan.parent.mkdir(parents=True, exist_ok=True)
        args.emit_plan.write_text(yaml.safe_dump(plan, sort_keys=False))
        if os.environ.get("MONARCH_ROOTFS_EMIT_PLAN_ONLY") == "1":
            return 0

    outer_argv = plan["outer_argv"]
    os.execvp(outer_argv[0], outer_argv)
    raise AssertionError("unreachable")


def _materialize_legacy_plan(
    *, args: EnterRootfsCompatArgs, rootfs: Path, recipe_sha256: str
) -> dict[str, Any]:
    checkout_rel = _normalize_checkout_rel(args.chdir)
    cwd = f"{REPO_MOUNT}{('/' + checkout_rel) if checkout_rel else ''}"
    cache_host_root = _cache_host_root()
    cargo_target_host = cache_host_root / "target" / "bwrap" / recipe_sha256
    cache_mount = f"{REPO_MOUNT}/scripts/rootfs/cache"
    cargo_target_mount = f"{REPO_MOUNT}/target/bwrap/{recipe_sha256}"
    _ensure_cache_dirs(cache_host_root, cargo_target_host)

    mounts = [
        {"host_path": str(rootfs), "sandbox_path": "/", "mode": "ro", "purpose": "rootfs"},
        {
            "host_path": str(REPO_ROOT),
            "sandbox_path": REPO_MOUNT,
            "mode": "ro" if args.repo_readonly else "rw",
            "purpose": "repo",
        },
        {"host_path": str(cache_host_root), "sandbox_path": cache_mount, "mode": "rw", "purpose": "cache"},
        {
            "host_path": str(cargo_target_host),
            "sandbox_path": cargo_target_mount,
            "mode": "rw",
            "purpose": "cargo-target",
        },
    ]

    for bind_spec in args.bind_rw:
        host, sandbox = _parse_bind_rw(bind_spec)
        host.mkdir(parents=True, exist_ok=True)
        mounts.append(
            {
                "host_path": str(host),
                "sandbox_path": sandbox,
                "mode": "rw",
                "purpose": "extra",
            }
        )

    for host_path in (Path("/etc/resolv.conf"), Path("/etc/hosts")):
        if host_path.exists():
            mounts.append(
                {
                    "host_path": str(host_path),
                    "sandbox_path": str(host_path),
                    "mode": "ro",
                    "purpose": host_path.name,
                }
            )

    mounts, have_nvidia = _append_nvidia_projection(mounts)
    env = _rootfs_env(
        recipe_sha256=recipe_sha256,
        cache_mount=cache_mount,
        cargo_target_mount=cargo_target_mount,
        have_nvidia=have_nvidia,
    )

    inner_argv = list(args.payload) if args.payload else ["/bin/bash", "-l"]
    invocation = _legacy_insula_invocation(
        rootfs=rootfs,
        recipe_sha256=recipe_sha256,
        cwd=cwd,
        repo_readonly=args.repo_readonly,
        mounts=mounts,
        env=env,
        inner_argv=inner_argv,
    )
    insula_plan = emit_plan(invocation)
    validate_plan(invocation, insula_plan)
    outer_argv = build_bwrap_argv(invocation)
    return {
        "schema_version": 1,
        "rootfs": str(rootfs),
        "rootfs_export": {"rootfs": str(rootfs), "recipe_sha256": recipe_sha256},
        "host_layout": {
            "repo_root": str(REPO_ROOT),
            "cache_root": str(cache_host_root),
            "cargo_target_root": str(cargo_target_host),
        },
        "sandbox_layout": {
            "repo_root": REPO_MOUNT,
            "cache_root": cache_mount,
            "cargo_target_dir": cargo_target_mount,
            "home": "/home/monarch",
            "nvidia_host": "/run/nvidia-host",
        },
        "cwd": cwd,
        "repo_projection_mode": "ro" if args.repo_readonly else "rw",
        "mounts": mounts,
        "env": env,
        "env_allowlist": [],
        "network": "share-net",
        "gpu": "dev-bind-nvidia-when-present",
        "inner_argv": inner_argv,
        "outer_argv": outer_argv,
        "schema_translated_argv": outer_argv,
        "insula": {
            "invocation_id": invocation.invocation_id,
            "recipe_sha256": recipe_sha256,
            "bwrap_argv_sha256": insula_plan.bwrap_argv_sha256,
        },
    }


def _rootfs_env(
    *, recipe_sha256: str, cache_mount: str, cargo_target_mount: str, have_nvidia: bool
) -> dict[str, str]:
    env = {
        "HOME": "/home/monarch",
        "PATH": "/opt/cuda-synth/bin:/opt/cargo/bin:/usr/local/bin:/usr/bin:/bin:/run/nvidia-host",
        "UV_PROJECT_ENVIRONMENT": f"{REPO_MOUNT}/.venv-rootfs",
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", f"{cache_mount}/uv"),
        "CARGO_HOME": f"{cache_mount}/cargo",
        "CARGO_TARGET_DIR": cargo_target_mount,
        "npm_config_cache": f"{cache_mount}/npm",
        "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME", f"{cache_mount}/xdg"),
        "RUSTUP_HOME": "/opt/rustup",
        "CUDA_HOME": "/opt/cuda-synth",
        "CUDA_PATH": "/opt/cuda-synth",
        "MONARCH_IN_ROOTFS": "1",
        "MONARCH_ROOTFS_RECIPE_SHA256": recipe_sha256,
    }
    if have_nvidia:
        env["LD_LIBRARY_PATH"] = "/run/nvidia-host:/opt/cuda-synth/lib64"
        env["LIBRARY_PATH"] = "/run/nvidia-host:/opt/cuda-synth/lib64"
    for key in HOST_ENV_ALLOWLIST:
        if key in os.environ:
            env[key] = os.environ[key]
    if "CUDA_VISIBLE_DEVICES" in os.environ:
        env["CUDA_VISIBLE_DEVICES"] = os.environ["CUDA_VISIBLE_DEVICES"]
    env.setdefault("NVIDIA_VISIBLE_DEVICES", "all")
    return dict(sorted(env.items()))


def _legacy_insula_invocation(
    *,
    rootfs: Path,
    recipe_sha256: str,
    cwd: str,
    repo_readonly: bool,
    mounts: list[dict[str, str]],
    env: dict[str, str],
    inner_argv: list[str],
) -> MaterializedInsulaInvocation:
    rootfs_name = "monarch-default"
    spec = InsulaInvocationSpec(
        schema_version=1,
        name="monarch-rootfs-compat",
        rootfs_ref=f"rootfs://{rootfs_name}",
        repo=InsulaBindSpec(
            name="repo",
            host="repo://",
            sandbox=REPO_MOUNT,
            mode="ro" if repo_readonly else "rw",
            create=False,
            required=True,
        ),
        binds=[
            InsulaBindSpec(
                name=_bind_name(mount["sandbox_path"], index),
                host=_host_ref_for_mount(mount),
                sandbox=mount["sandbox_path"],
                mode=_insula_mount_mode(mount),
                create=False,
                required=True,
            )
            for index, mount in enumerate(mounts)
            if mount["sandbox_path"] not in {"/", REPO_MOUNT}
        ],
        environment=InsulaEnvironmentSpec(clear=True, values=env, inherit_allowlist=[]),
        command=InsulaCommandSpec(cwd=cwd, argv=inner_argv),
        artifacts={
            "root": "run://insula",
            "stdout": "run://insula/stdout.log",
            "stderr": "run://insula/stderr.log",
            "plan": "run://insula/plan.yaml",
            "result": "run://insula/result.json",
        },
        network="share-net",
        gpu="nvidia-if-present",
        die_with_parent=True,
        unshare_all=True,
    )
    local_environment = local_environment_from_mapping(
        {
            "schema_version": 1,
            "repo": str(REPO_ROOT),
            "rootfs": {rootfs_name: str(rootfs)},
            "cache": str(_cache_host_root()),
            "temp": str(ROOTFS_DIR / "tmp"),
            "run": str(ROOTFS_DIR / "run"),
            "results": str(REPO_ROOT / "rootfs-results"),
            "shared_memory": {},
            "gpu": {"mode": "nvidia-if-present"},
        }
    )
    invocation = materialize_invocation(
        spec=spec,
        local_environment=local_environment,
        invocation_id="monarch-rootfs-compat",
        compatibility={"adapter": "enter-rootfs-compat"},
    )
    return MaterializedInsulaInvocation(
        schema_version=invocation.schema_version,
        invocation_id=invocation.invocation_id,
        name=invocation.name,
        repo_root=invocation.repo_root,
        rootfs_path=invocation.rootfs_path,
        rootfs_recipe_sha256=recipe_sha256,
        cache_root=invocation.cache_root,
        command=invocation.command,
        binds=invocation.binds,
        environment=invocation.environment,
        bwrap_argv=invocation.bwrap_argv,
        artifacts=invocation.artifacts,
        compatibility=invocation.compatibility,
    )


def _host_ref_for_mount(mount: dict[str, str]) -> str:
    host_path = mount["host_path"]
    if host_path == str(_cache_host_root()):
        return "cache://"
    return f"host://{host_path}"


def _insula_mount_mode(mount: dict[str, str]) -> str:
    if mount.get("purpose", "").startswith("dev"):
        return "dev"
    return mount["mode"]


def _bind_name(sandbox_path: str, index: int) -> str:
    name = sandbox_path.strip("/").replace("/", "-")
    return name or f"mount-{index}"


def _append_nvidia_projection(
    mounts: list[dict[str, str]]
) -> tuple[list[dict[str, str]], bool]:
    seen: set[Path] = set()
    for dev in sorted(Path("/dev").glob("nvidia*")):
        if dev in seen:
            continue
        seen.add(dev)
        mounts.append(
            {
                "host_path": str(dev),
                "sandbox_path": str(dev),
                "mode": "rw",
                "purpose": "dev-nvidia",
            }
        )

    host_libdir = Path("/usr/lib/x86_64-linux-gnu")
    libs = sorted(host_libdir.glob("libcuda.so*")) + sorted(host_libdir.glob("libnvidia-*.so*"))
    if not libs:
        return mounts, False
    nvidia_host_dir = _cache_host_root() / "nvidia-host"
    nvidia_host_dir.mkdir(parents=True, exist_ok=True)
    mounts.append({"host_path": str(nvidia_host_dir), "sandbox_path": "/run/nvidia-host", "mode": "rw", "purpose": "nvidia-host"})
    for lib in libs:
        target = f"/run/nvidia-host/{lib.name}"
        mounts.append(
            {
                "host_path": str(lib),
                "sandbox_path": target,
                "mode": "ro",
                "purpose": "nvidia-host",
            }
        )
    nvidia_smi = Path("/usr/bin/nvidia-smi")
    if nvidia_smi.is_file():
        mounts.append(
            {
                "host_path": str(nvidia_smi),
                "sandbox_path": "/run/nvidia-host/nvidia-smi",
                "mode": "ro",
                "purpose": "nvidia-host",
            }
        )
    return mounts, True


def _preflight_host() -> None:
    arch = subprocess.check_output(["uname", "-m"], text=True).strip()
    if arch != _contract_value("MONARCH_ROOTFS_ARCH"):
        raise InsulaConfigError(
            f"unsupported architecture {arch}: scripts/run supports {_contract_value('MONARCH_ROOTFS_ARCH')} only"
        )
    if os.environ.get("MONARCH_GPU_PLATFORM") == "rocm":
        raise InsulaConfigError("unsupported platform: MONARCH_GPU_PLATFORM=rocm is not supported by the rootfs")
    if os.environ.get("MONARCH_ROOTFS_EMIT_PLAN_ONLY") != "1":
        if not _which("bwrap"):
            raise InsulaConfigError("bwrap not found on host")


def _ensure_rootfs(rootfs: Path, recipe_sha256: str) -> None:
    needs_build = not (rootfs / "bin" / "bash").is_file() or not _rootfs_contract_current(rootfs, recipe_sha256)
    if not needs_build:
        return
    if os.environ.get("MONARCH_ROOTFS_EMIT_PLAN_ONLY") == "1":
        print(f"== emit-only: rootfs at {rootfs} is not built ==", file=sys.stderr)
        return
    print(f"== building rootfs at {rootfs} ==", file=sys.stderr)
    subprocess.run([str(ROOTFS_DIR / "build_rootfs.sh"), "--dest", str(rootfs)], check=True)
    if not (rootfs / "bin" / "bash").is_file():
        raise InsulaConfigError(f"rootfs build did not produce a usable rootfs at {rootfs}")


def _verify_rootfs(rootfs: Path) -> None:
    if os.environ.get("MONARCH_ROOTFS_EMIT_PLAN_ONLY") == "1":
        return
    command = [sys.executable, str(ROOTFS_DIR / "verify_rootfs.py"), "--rootfs", str(rootfs), "--skip-command-checks"]
    cache_root = os.environ.get("MONARCH_ROOTFS_CACHE_ROOT")
    if cache_root:
        command.extend(["--cache-root", cache_root])
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def _recipe_sha256() -> str:
    return subprocess.check_output(
        [str(ROOTFS_DIR / "execution_contract.sh"), "recipe-sha256"],
        text=True,
        cwd=REPO_ROOT,
    ).strip()


def _rootfs_contract_current(rootfs: Path, recipe_sha256: str) -> bool:
    contract = rootfs / ROOTFS_CONTRACT_PATH.lstrip("/")
    return contract.is_file() and f"MONARCH_ROOTFS_RECIPE_SHA256={recipe_sha256}" in contract.read_text().splitlines()


def _in_valid_rootfs(repo_root: Path, tools: tuple[str, ...]) -> bool:
    if os.environ.get("MONARCH_IN_ROOTFS") != "1":
        return False
    if str(repo_root) != REPO_MOUNT:
        return False
    contract = Path(ROOTFS_CONTRACT_PATH)
    if not contract.is_file():
        return False
    if f"MONARCH_ROOTFS_RECIPE_SHA256={_recipe_sha256()}" not in contract.read_text().splitlines():
        return False
    uid_map = Path("/proc/self/uid_map")
    if not uid_map.is_file() or not _uid_map_controlled(uid_map):
        return False
    return all(_controlled_tool_path_ok(tool) for tool in tools)


def _controlled_tool_path_ok(tool: str) -> bool:
    resolved = _which(tool)
    if resolved is None:
        return False
    if tool == "python":
        return resolved in {"/usr/bin/python", f"{REPO_MOUNT}/.venv-rootfs/bin/python"}
    expected = {
        "uv": "/usr/local/bin/uv",
        "cargo": "/opt/cargo/bin/cargo",
    }.get(tool)
    return resolved == expected


def _which(tool: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / tool
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _uid_map_controlled(path: Path) -> bool:
    lines = [line.split() for line in path.read_text().splitlines()]
    if not lines:
        return True
    return len(lines) == 1 and len(lines[0]) == 3 and lines[0][2] == "1"


def _activate_rootfs_environment() -> None:
    for key in HOST_LEAK_VARS:
        os.environ.pop(key, None)
    snapshot = subprocess.check_output(
        [
            "bash",
            "-lc",
            f"source {shlex.quote(str(ROOTFS_DIR / 'activate_environment.sh'))} >/dev/null && env -0",
        ]
    )
    for item in snapshot.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        os.environ[key.decode()] = value.decode(errors="surrogateescape")
    os.environ.pop("PYTHONHOME", None)


def _checkout_relative_cwd(cwd: Path) -> str:
    resolved = cwd.resolve()
    repo = REPO_ROOT.resolve()
    if resolved == repo:
        return ""
    try:
        return str(resolved.relative_to(repo))
    except ValueError:
        return ""


def _normalize_checkout_rel(value: str) -> str:
    if value in {"", "."}:
        return ""
    if value.startswith("/"):
        raise InsulaConfigError(f"--chdir must be a relative path: {value}")
    parts = Path(value).parts
    if ".." in parts:
        raise InsulaConfigError(f"--chdir must stay below the checkout: {value}")
    return str(Path(value)).strip("/")


def _cache_host_root() -> Path:
    if os.environ.get("MONARCH_ROOTFS_CACHE_ROOT"):
        path = Path(os.environ["MONARCH_ROOTFS_CACHE_ROOT"])
        if not path.is_absolute():
            raise InsulaConfigError(f"MONARCH_ROOTFS_CACHE_ROOT must be absolute: {path}")
        return path
    return ROOTFS_DIR / "cache"


def _ensure_cache_dirs(cache_root: Path, cargo_target_host: Path) -> None:
    for name in ("uv", "cargo", "npm", "xdg"):
        (cache_root / name).mkdir(parents=True, exist_ok=True)
    cargo_target_host.mkdir(parents=True, exist_ok=True)


def _parse_bind_rw(value: str) -> tuple[Path, str]:
    if ":" not in value:
        raise InsulaConfigError("--bind-rw must be HOST:SANDBOX")
    host_raw, sandbox = value.split(":", 1)
    host = Path(host_raw)
    if not host.is_absolute():
        raise InsulaConfigError(f"--bind-rw host path must be absolute: {host}")
    if not sandbox.startswith("/"):
        raise InsulaConfigError(f"--bind-rw sandbox path must be absolute: {sandbox}")
    if sandbox == "/":
        raise InsulaConfigError("--bind-rw sandbox path must not be root")
    return host, sandbox


def _strip_separator(argv: list[str]) -> list[str]:
    return argv[1:] if argv and argv[0] == "--" else argv


def _contract_value(name: str) -> str:
    contract = ROOTFS_DIR / "contract.env"
    for line in contract.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1]
    raise InsulaConfigError(f"missing rootfs contract value: {name}")
