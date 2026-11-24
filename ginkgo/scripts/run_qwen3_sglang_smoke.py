#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from typing import TextIO


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ginkgo.local_run import LocalRunError as SmokeError
from ginkgo.local_run import Qwen3SglangWorkload
from ginkgo.local_run import RuntimeBackedLocalRunAdapter
from ginkgo.local_run import SglangLocalRun


DEFAULT_DECLARED_SPEC = Qwen3SglangWorkload.default_declared_spec


def run_smoke(
    *,
    declared_spec: Path,
    local_environment: Path,
    run_id: str | None = None,
    port: int | None = None,
    runtime: Any | None = None,
    output: TextIO | None = None,
) -> dict[str, Any]:
    adapter = RuntimeBackedLocalRunAdapter(runtime) if runtime is not None else None
    result = SglangLocalRun(
        workload=Qwen3SglangWorkload(),
        runtime=adapter,
    ).run(
        declared_spec=declared_spec,
        local_environment=local_environment,
        run_id=run_id,
        port=port,
        output=output,
    )
    return {
        "status": result.status,
        "run_id": result.run_id,
        "port": result.port,
        "generated_text": result.generated_text,
        "evidence_manifest": result.evidence_manifest,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Ginkgo Qwen3 dense SGLang serving smoke")
    parser.add_argument("--declared-spec", type=Path, default=DEFAULT_DECLARED_SPEC)
    parser.add_argument("--local-environment", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--port", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run_smoke(
            declared_spec=args.declared_spec,
            local_environment=args.local_environment,
            run_id=args.run_id,
            port=args.port,
        )
    except SmokeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
