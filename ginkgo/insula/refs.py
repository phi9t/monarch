from __future__ import annotations

from pathlib import Path

from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import InsulaLocalEnvironment


_REF_MARKER = "://"


def resolve_path_ref(env: InsulaLocalEnvironment, ref: str) -> str:
    scheme, suffix = _split_ref(ref)
    if scheme == "host":
        if not suffix.startswith("/"):
            raise InsulaConfigError(f"host refs must be absolute: {ref}")
        return suffix
    if scheme == "rootfs":
        if suffix not in env.rootfs:
            raise InsulaConfigError(f"unknown rootfs ref: {suffix}")
        return env.rootfs[suffix]

    roots = {
        "repo": env.repo,
        "cache": env.cache,
        "temp": env.temp,
        "run": env.run,
        "results": env.results,
    }
    try:
        root = roots[scheme]
    except KeyError as error:
        raise InsulaConfigError(f"unsupported path ref: {ref}") from error

    if suffix.startswith("/"):
        suffix = suffix[1:]
    return str(Path(root) / suffix)


def _split_ref(ref: str) -> tuple[str, str]:
    if not isinstance(ref, str) or _REF_MARKER not in ref:
        raise InsulaConfigError(f"unsupported path ref: {ref}")
    scheme, suffix = ref.split(_REF_MARKER, 1)
    if not scheme:
        raise InsulaConfigError(f"unsupported path ref: {ref}")
    return scheme, suffix
