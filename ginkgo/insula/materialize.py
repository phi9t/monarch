from __future__ import annotations

from ginkgo.insula.refs import resolve_path_ref
from ginkgo.insula.schema import InsulaBindSpec
from ginkgo.insula.schema import InsulaInvocationSpec
from ginkgo.insula.schema import InsulaLocalEnvironment
from ginkgo.insula.schema import MaterializedInsulaInvocation


def materialize_invocation(
    *,
    spec: InsulaInvocationSpec,
    local_environment: InsulaLocalEnvironment,
    invocation_id: str,
    compatibility: dict[str, str] | None = None,
) -> MaterializedInsulaInvocation:
    return MaterializedInsulaInvocation(
        schema_version=spec.schema_version,
        invocation_id=invocation_id,
        name=spec.name,
        repo_root=local_environment.repo,
        rootfs_path=resolve_path_ref(local_environment, spec.rootfs_ref),
        rootfs_recipe_sha256="",
        cache_root=local_environment.cache,
        command=spec.command,
        binds=[_resolve_bind(local_environment, spec.repo)]
        + [_resolve_bind(local_environment, bind) for bind in spec.binds],
        environment=dict(spec.environment.values),
        bwrap_argv=[],
        artifacts={
            name: resolve_path_ref(local_environment, ref)
            for name, ref in spec.artifacts.items()
        },
        compatibility={
            **dict(compatibility or {}),
            "network": spec.network,
            "gpu": spec.gpu,
        },
    )


def _resolve_bind(
    local_environment: InsulaLocalEnvironment, bind: InsulaBindSpec
) -> InsulaBindSpec:
    return InsulaBindSpec(
        name=bind.name,
        host=resolve_path_ref(local_environment, bind.host),
        sandbox=bind.sandbox,
        mode=bind.mode,
        create=bind.create,
        required=bind.required,
    )
