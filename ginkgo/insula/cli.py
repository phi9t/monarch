from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import yaml

from ginkgo.insula.bwrap_plan import emit_plan
from ginkgo.insula.compatibility import DEFAULT_ROOTFS
from ginkgo.insula.compatibility import EnterRootfsCompatArgs
from ginkgo.insula.compatibility import enter_rootfs_compat
from ginkgo.insula.compatibility import monarch_run
from ginkgo.insula.executor import execute_invocation
from ginkgo.insula.local_environment import load_local_environment
from ginkgo.insula.materialize import materialize_invocation
from ginkgo.insula.schema import InsulaConfigError
from ginkgo.insula.schema import load_invocation_spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ginkgo.insula.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    _add_invocation_args(run_parser)

    emit_plan_parser = subparsers.add_parser("emit-plan")
    _add_invocation_args(emit_plan_parser)
    emit_plan_parser.add_argument("--output", type=Path)

    monarch_run = subparsers.add_parser("monarch-run")
    monarch_run.add_argument("--chdir", default=".")
    monarch_run.add_argument("payload", nargs=argparse.REMAINDER)

    enter_rootfs = subparsers.add_parser("enter-rootfs-compat")
    enter_rootfs.add_argument("--chdir", default=".")
    enter_rootfs.add_argument("--repo-readonly", action="store_true")
    enter_rootfs.add_argument("--rootfs", type=Path, default=DEFAULT_ROOTFS)
    enter_rootfs.add_argument("--emit-plan", type=Path)
    enter_rootfs.add_argument("--bind-rw", action="append", default=[])
    enter_rootfs.add_argument("payload", nargs=argparse.REMAINDER)

    return parser


def run_insula_from_args(
    argv: list[str] | None = None,
    *,
    run: Callable[..., object] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "emit-plan":
        invocation = _load_materialized(args)
        plan = emit_plan(invocation)
        data = asdict(plan)
        if args.output is None:
            print(yaml.safe_dump(data, sort_keys=False), end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(yaml.safe_dump(data, sort_keys=False))
        return 0

    if args.command == "run":
        invocation = _load_materialized(args)
        result = execute_invocation(invocation, run=run)
        print(json.dumps(asdict(result), sort_keys=True))
        return result.returncode

    if args.command == "monarch-run":
        return monarch_run(args.payload)

    if args.command == "enter-rootfs-compat":
        return enter_rootfs_compat(
            EnterRootfsCompatArgs(
                rootfs=args.rootfs,
                chdir=args.chdir,
                repo_readonly=args.repo_readonly,
                emit_plan=args.emit_plan,
                bind_rw=tuple(args.bind_rw),
                payload=tuple(_strip_separator(args.payload)),
            )
        )

    raise InsulaConfigError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        return run_insula_from_args(argv)
    except InsulaConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _add_invocation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--local-environment", required=True, type=Path)
    parser.add_argument("--invocation-id", required=True)


def _load_materialized(args: argparse.Namespace):
    return materialize_invocation(
        spec=load_invocation_spec(args.spec),
        local_environment=load_local_environment(args.local_environment),
        invocation_id=args.invocation_id,
        compatibility={"adapter": "cli"},
    )


def _strip_separator(argv: list[str]) -> list[str]:
    return argv[1:] if argv and argv[0] == "--" else argv


if __name__ == "__main__":
    raise SystemExit(main())
