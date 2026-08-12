# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_CUDA_VISIBLE_DEVICES = "0,1,2,3,4,5,6,7"


class CudaVisibleDevicesError(ValueError):
    pass


def validated_cuda_visible_devices(value: str | None) -> tuple[str, bool]:
    if value is None or value == "":
        return DEFAULT_CUDA_VISIBLE_DEVICES, True

    devices = value.split(",")
    if len(devices) != 8 or any(device == "" for device in devices):
        raise CudaVisibleDevicesError(
            "CUDA_VISIBLE_DEVICES must name exactly 8 non-empty comma-separated "
            f"devices, got: {value}"
        )
    return value, False


def _int_attr(element: ET.Element, name: str) -> int:
    return int(element.attrib.get(name, "0"))


def parse_nextest_junit(
    path: str | Path, *, not_before_ns: int | None = None
) -> str:
    try:
        _require_fresh_artifact(path, not_before_ns)
        root = ET.parse(path).getroot()
        suites = _suite_elements(root)
        tests = sum(_int_attr(element, "tests") for element in suites)
        failures = sum(_int_attr(element, "failures") for element in suites)
        errors = sum(_int_attr(element, "errors") for element in suites)
    except Exception:
        return "unknown"
    if tests == 0:
        return "unknown"
    return "pass" if failures == 0 and errors == 0 else "fail"


def failed_pytest_node_ids(
    path: str | Path, *, not_before_ns: int | None = None
) -> list[str]:
    _require_fresh_artifact(path, not_before_ns)
    root = ET.parse(path).getroot()
    failed_tests = []
    for testcase in root.iter("testcase"):
        if not testcase.findall("failure") and not testcase.findall("error"):
            continue

        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        if not classname or not name:
            raise ValueError(
                "cannot map JUnit testcase without classname and name: "
                f"{classname} {name}"
            )
        failed_tests.append(_pytest_node_id(classname, name))
    return failed_tests


def _require_fresh_artifact(path: str | Path, not_before_ns: int | None) -> None:
    if not_before_ns is None:
        return
    modified_ns = Path(path).stat().st_mtime_ns
    if modified_ns < not_before_ns:
        raise ValueError(
            f"stale artifact: modified at {modified_ns}, run started at {not_before_ns}"
        )


def _suite_elements(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        suites = list(root.iter("testsuite"))
        return suites if suites else [root]
    return [root]


def _pytest_node_id(classname: str, name: str) -> str:
    prefix = "python.tests."
    if not classname.startswith(prefix):
        raise ValueError(f"cannot map JUnit testcase: {classname} {name}")

    module = classname.replace(".", "/") + ".py"
    return f"{module}::{name}"


def _cmd_cuda_visible_devices(_args: argparse.Namespace) -> int:
    try:
        value, defaulted = validated_cuda_visible_devices(
            os.environ.get("CUDA_VISIBLE_DEVICES")
            if "CUDA_VISIBLE_DEVICES" in os.environ
            else None
        )
    except CudaVisibleDevicesError as error:
        print(error, file=sys.stderr)
        return 2

    print(value)
    print("defaulted" if defaulted else "explicit")
    return 0


def _cmd_nextest_status(args: argparse.Namespace) -> int:
    print(parse_nextest_junit(args.junit, not_before_ns=args.not_before_ns))
    return 0


def _cmd_pytest_failures(args: argparse.Namespace) -> int:
    try:
        for node_id in failed_pytest_node_ids(
            args.junit, not_before_ns=args.not_before_ns
        ):
            print(node_id)
    except Exception as error:
        print(f"cannot parse Python JUnit: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="8-GPU verifier helpers")
    subparsers = parser.add_subparsers(required=True)

    cuda_parser = subparsers.add_parser("cuda-visible-devices")
    cuda_parser.set_defaults(func=_cmd_cuda_visible_devices)

    nextest_parser = subparsers.add_parser("nextest-status")
    nextest_parser.add_argument("junit", type=Path)
    nextest_parser.add_argument("--not-before-ns", type=int)
    nextest_parser.set_defaults(func=_cmd_nextest_status)

    pytest_parser = subparsers.add_parser("pytest-failures")
    pytest_parser.add_argument("junit", type=Path)
    pytest_parser.add_argument("--not-before-ns", type=int)
    pytest_parser.set_defaults(func=_cmd_pytest_failures)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
