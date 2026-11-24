from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ginkgo.insula.schema import InsulaBindSpec
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import InsulaPlan
from ginkgo.insula.schema import MaterializedInsulaInvocation


_HOME = "/home/monarch"
_NETWORK_MODES = {"share-net", "private"}
_GPU_MODES = {"none", "nvidia-if-present", "nvidia-required"}


def build_bwrap_argv(invocation: MaterializedInsulaInvocation) -> list[str]:
    _validate_invocation(invocation)

    argv = [
        "bwrap",
        "--ro-bind",
        invocation.rootfs_path,
        "/",
        "--proc",
        "/proc",
        "--ro-bind",
        "/sys",
        "/sys",
        "--tmpfs",
        "/tmp",
        "--dev",
        "/dev",
        "--tmpfs",
        "/home",
        "--dir",
        _HOME,
        "--unshare-all",
    ]
    if _network(invocation) == "share-net":
        argv.append("--share-net")
    argv.extend(["--die-with-parent", "--clearenv", "--chdir", invocation.command.cwd])

    for target in _created_writable_bind_tmpfs_targets(invocation.binds):
        argv.extend(["--tmpfs", target])
    for target in _created_writable_bind_dir_targets(invocation.binds):
        argv.extend(["--dir", target])
    for bind in invocation.binds:
        argv.extend([_bind_flag(bind), bind.host, bind.sandbox])
    for key, value in sorted(invocation.environment.items()):
        argv.extend(["--setenv", key, value])
    argv.extend(["--", *invocation.command.argv])
    return argv


def emit_plan(invocation: MaterializedInsulaInvocation) -> InsulaPlan:
    argv = build_bwrap_argv(invocation)
    return InsulaPlan(
        schema_version=invocation.schema_version,
        invocation_id=invocation.invocation_id,
        rootfs_path=invocation.rootfs_path,
        recipe_sha256=invocation.rootfs_recipe_sha256,
        cwd=invocation.command.cwd,
        network=_network(invocation),
        gpu=_gpu(invocation),
        mounts=_mounts(invocation),
        env=dict(sorted(invocation.environment.items())),
        command_argv=list(invocation.command.argv),
        bwrap_argv_sha256=_argv_digest(argv),
    )


def validate_plan(
    invocation: MaterializedInsulaInvocation, plan: InsulaPlan
) -> dict[str, object]:
    expected = emit_plan(invocation)

    if plan.schema_version != expected.schema_version:
        raise InsulaConfigError("schema version mismatch")
    if plan.invocation_id != expected.invocation_id:
        raise InsulaConfigError("invocation id mismatch")
    if plan.rootfs_path != expected.rootfs_path:
        raise InsulaConfigError("rootfs path mismatch")
    if plan.recipe_sha256 != expected.recipe_sha256:
        raise InsulaConfigError("recipe sha256 mismatch")
    if plan.cwd != expected.cwd:
        raise InsulaConfigError("cwd mismatch")
    if plan.network != expected.network:
        raise InsulaConfigError("network mismatch")
    if plan.gpu != expected.gpu:
        raise InsulaConfigError("gpu mismatch")
    if plan.env != expected.env:
        raise InsulaConfigError("env mismatch")
    if plan.command_argv != expected.command_argv:
        raise InsulaConfigError("command argv mismatch")
    _validate_mounts(plan.mounts, expected.mounts)
    if plan.bwrap_argv_sha256 != expected.bwrap_argv_sha256:
        raise InsulaConfigError("bwrap argv digest mismatch")

    return {"schema_version": plan.schema_version, "status": "passed"}


def _validate_invocation(invocation: MaterializedInsulaInvocation) -> None:
    _require_absolute_host_path(invocation.rootfs_path, "rootfs_path")
    _require_absolute_host_path(invocation.repo_root, "repo_root")
    _require_absolute_host_path(invocation.cache_root, "cache_root")
    if not invocation.command.cwd.startswith("/"):
        raise InsulaConfigError("command cwd must be absolute")
    if not invocation.command.argv:
        raise InsulaConfigError("command argv must be non-empty")
    for name, value in invocation.environment.items():
        if not isinstance(name, str) or not name:
            raise InsulaConfigError("environment names must be non-empty strings")
        if not isinstance(value, str):
            raise InsulaConfigError(f"environment value for {name} must be a string")
    for bind in invocation.binds:
        _validate_bind(bind)
    _network(invocation)
    _gpu(invocation)


def _validate_bind(bind: InsulaBindSpec) -> None:
    _require_absolute_host_path(bind.host, f"bind {bind.name} host")
    if not bind.sandbox.startswith("/") or bind.sandbox == "/":
        raise InsulaConfigError(f"bind {bind.name} sandbox must be absolute and not /")
    _bind_flag(bind)


def _created_writable_bind_tmpfs_targets(binds: list[InsulaBindSpec]) -> list[str]:
    targets = {
        f"/{bind.sandbox.strip('/').split('/', 1)[0]}"
        for bind in binds
        if bind.create and bind.mode == "rw"
    }
    return sorted(targets)


def _created_writable_bind_dir_targets(binds: list[InsulaBindSpec]) -> list[str]:
    return sorted(
        {
            bind.sandbox.rstrip("/") or bind.sandbox
            for bind in binds
            if bind.create and bind.mode == "rw"
        }
    )


def _require_absolute_host_path(value: str, field: str) -> None:
    if not Path(value).is_absolute():
        raise InsulaConfigError(f"{field} must be an absolute path")


def _bind_flag(bind: InsulaBindSpec) -> str:
    if bind.mode == "ro":
        return "--ro-bind"
    if bind.mode == "rw":
        return "--bind"
    if bind.mode == "dev":
        return "--dev-bind"
    raise InsulaConfigError(f"bind mode must be one of ro, rw, dev: {bind.mode}")


def _network(invocation: MaterializedInsulaInvocation) -> str:
    network = invocation.compatibility.get("network", "share-net")
    if network not in _NETWORK_MODES:
        raise InsulaConfigError(f"network must be one of private, share-net: {network}")
    return network


def _gpu(invocation: MaterializedInsulaInvocation) -> str:
    gpu = invocation.compatibility.get("gpu", "nvidia-if-present")
    if gpu not in _GPU_MODES:
        raise InsulaConfigError(
            f"gpu must be one of none, nvidia-if-present, nvidia-required: {gpu}"
        )
    return gpu


def _mounts(invocation: MaterializedInsulaInvocation) -> list[dict[str, str]]:
    return [
        {
            "name": "sysfs",
            "host": "/sys",
            "sandbox": "/sys",
            "mode": "ro",
        },
        {
            "name": "rootfs",
            "host": invocation.rootfs_path,
            "sandbox": "/",
            "mode": "ro",
        },
        *[
            {
                "name": bind.name,
                "host": bind.host,
                "sandbox": bind.sandbox,
                "mode": bind.mode,
            }
            for bind in invocation.binds
        ],
    ]


def _validate_mounts(
    actual_mounts: list[dict[str, str]], expected_mounts: list[dict[str, str]]
) -> None:
    actual = {mount.get("sandbox"): mount for mount in actual_mounts}
    expected = {mount["sandbox"]: mount for mount in expected_mounts}
    for sandbox, expected_mount in expected.items():
        if actual.get(sandbox) != expected_mount:
            raise InsulaConfigError(f"mount mismatch for {sandbox}")
    unexpected = sorted(set(actual) - set(expected))
    if unexpected:
        raise InsulaConfigError(f"unexpected mount: {unexpected[0]}")


def _argv_digest(argv: list[str]) -> str:
    payload = json.dumps(argv, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()
