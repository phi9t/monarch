from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from ginkgo.insula.bwrap_plan import build_bwrap_argv
from ginkgo.insula.bwrap_plan import emit_plan
from ginkgo.insula.bwrap_plan import validate_plan
from ginkgo.insula.schema import MaterializedInsulaInvocation


def write_invocation_artifacts(
    invocation: MaterializedInsulaInvocation,
) -> dict[str, str]:
    plan = emit_plan(invocation)
    validation = validate_plan(invocation, plan)
    argv = build_bwrap_argv(invocation)
    paths = _artifact_paths(invocation)

    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    _write_yaml(paths["materialized"], asdict(invocation))
    _write_json(paths["argv"], argv)
    _write_json(paths["env"], invocation.environment)
    _write_yaml(paths["plan"], asdict(plan))
    _write_json(paths["validation"], validation)
    paths["stdout"].touch()
    paths["stderr"].touch()

    return {name: str(path) for name, path in paths.items()}


def _artifact_paths(invocation: MaterializedInsulaInvocation) -> dict[str, Path]:
    root = Path(invocation.artifacts["root"])
    return {
        "root": root,
        "materialized": Path(
            invocation.artifacts.get("materialized", root / "materialized.yaml")
        ),
        "argv": Path(invocation.artifacts.get("argv", root / "argv.json")),
        "env": Path(invocation.artifacts.get("env", root / "env.json")),
        "plan": Path(invocation.artifacts["plan"]),
        "validation": Path(
            invocation.artifacts.get("validation", root / "validation.json")
        ),
        "stdout": Path(invocation.artifacts["stdout"]),
        "stderr": Path(invocation.artifacts["stderr"]),
        "result": Path(invocation.artifacts["result"]),
    }


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))
