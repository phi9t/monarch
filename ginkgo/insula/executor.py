from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
from typing import BinaryIO
from typing import Callable

from ginkgo.insula.artifacts import write_invocation_artifacts
from ginkgo.insula.bwrap_plan import build_bwrap_argv
from ginkgo.insula.schema import InsulaExecutionResult
from ginkgo.insula.schema import MaterializedInsulaInvocation


Runner = Callable[
    [list[str]],
    int | subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str],
]


def execute_invocation(
    invocation: MaterializedInsulaInvocation,
    *,
    run: Callable[..., object] | None = None,
) -> InsulaExecutionResult:
    paths = write_invocation_artifacts(invocation)
    argv = build_bwrap_argv(invocation)
    runner = run or _subprocess_run
    started_at = _timestamp()

    with open(paths["stdout"], "wb") as stdout, open(paths["stderr"], "wb") as stderr:
        completed = runner(argv, stdout=stdout, stderr=stderr, env=invocation.environment)
        returncode = _returncode(completed)

    completed_at = _timestamp()
    result = InsulaExecutionResult(
        schema_version=invocation.schema_version,
        invocation_id=invocation.invocation_id,
        status="passed" if returncode == 0 else "failed",
        returncode=returncode,
        started_at=started_at,
        completed_at=completed_at,
        stdout_path=paths["stdout"],
        stderr_path=paths["stderr"],
        materialized_path=paths["materialized"],
        plan_path=paths["plan"],
        validation_path=paths["validation"],
    )
    with open(paths["result"], "w") as f:
        json.dump(asdict(result), f, indent=2, sort_keys=True)
        f.write("\n")
    return result


def _subprocess_run(
    argv: list[str],
    *,
    stdout: BinaryIO,
    stderr: BinaryIO,
    env: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, check=False, stdout=stdout, stderr=stderr, env=env)


def _returncode(result: object) -> int:
    if isinstance(result, int):
        return result
    returncode = getattr(result, "returncode", None)
    if isinstance(returncode, int):
        return returncode
    raise TypeError("runner must return an int or object with integer returncode")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
