#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PATCH_ID = "glm52-offloader-v1-plain-tensor-attrs-v1"
EXPECTED_MARKERS = (
    "_OFFLOADED_TENSOR_ATTRS",
    "_move_plain_tensor_attrs_for_forward",
    "_restore_plain_tensor_attrs",
    "tie_weights=False",
)
TENSOR_ATTRS = (
    "w_kc",
    "w_vc",
    "w_scale",
    "w_scale_k",
    "w_scale_v",
    "w_kc_qrep",
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _patched(text: str) -> bool:
    return all(marker in text for marker in EXPECTED_MARKERS)


def _patch_text(text: str) -> str:
    if _patched(text):
        return text

    anchor = "_WhitelistParamNamesCreator = Callable[[torch.nn.Module], List[str]]\n"
    helper = f'''
_OFFLOADED_TENSOR_ATTRS = {TENSOR_ATTRS!r}


def _move_plain_tensor_attrs_for_forward(module: torch.nn.Module, device: torch.device):
    moved_attrs = []
    for submodule in module.modules():
        for attr_name in _OFFLOADED_TENSOR_ATTRS:
            value = getattr(submodule, attr_name, None)
            if not isinstance(value, torch.Tensor) or value.device == device:
                continue
            moved_attrs.append((submodule, attr_name, value))
            setattr(submodule, attr_name, value.to(device, non_blocking=True))
    return moved_attrs


def _restore_plain_tensor_attrs(moved_attrs):
    for submodule, attr_name, value in reversed(moved_attrs):
        setattr(submodule, attr_name, value)
'''
    if anchor not in text:
        raise RuntimeError("offloader.py missing whitelist type alias anchor")
    text = text.replace(anchor, anchor + helper, 1)

    old_without_tie_weights = '''            def forward(*args, **kwargs):
                module.forward = original_forward
                device_state = {
                    # here we blindly call `to(device)`
                    # if the parameter is already on the device, it will be a no-op
                    k: v.to(device, non_blocking=True)
                    for k, v in module.state_dict().items()
                }
                output = functional_call(
                    module,
                    device_state,
                    args=args,
                    kwargs=kwargs,
                )
                module.forward = forward
                return output
'''
    old_with_tie_weights = '''            def forward(*args, **kwargs):
                module.forward = original_forward
                device_state = {
                    # here we blindly call `to(device)`
                    # if the parameter is already on the device, it will be a no-op
                    k: v.to(device, non_blocking=True)
                    for k, v in module.state_dict().items()
                }
                output = functional_call(
                    module,
                    device_state,
                    args=args,
                    kwargs=kwargs,
                    tie_weights=False,
                )
                module.forward = forward
                return output
'''
    old_single_line = '''            def forward(*args, **kwargs):
                module.forward = original_forward
                device_state = {
                    # here we blindly call `to(device)`
                    # if the parameter is already on the device, it will be a no-op
                    k: v.to(device, non_blocking=True)
                    for k, v in module.state_dict().items()
                }
                output = functional_call(module, device_state, args=args, kwargs=kwargs)
                module.forward = forward
                return output
'''
    new = '''            def forward(*args, **kwargs):
                module.forward = original_forward
                moved_attrs = _move_plain_tensor_attrs_for_forward(module, device)
                try:
                    device_state = {
                        # here we blindly call `to(device)`
                        # if the parameter is already on the device, it will be a no-op
                        k: v.to(device, non_blocking=True)
                        for k, v in module.state_dict().items()
                    }
                    output = functional_call(
                        module,
                        device_state,
                        args=args,
                        kwargs=kwargs,
                        tie_weights=False,
                    )
                finally:
                    _restore_plain_tensor_attrs(moved_attrs)
                    module.forward = forward
                return output
'''
    if old_without_tie_weights in text:
        text = text.replace(old_without_tie_weights, new, 1)
    elif old_with_tie_weights in text:
        text = text.replace(old_with_tie_weights, new, 1)
    elif old_single_line in text:
        text = text.replace(old_single_line, new, 1)
    else:
        raise RuntimeError("offloader.py missing expected OffloaderV1 forward wrapper")
    if not _patched(text):
        raise RuntimeError("offloader.py patch markers missing after patch")
    return text


def apply_patch(path: Path) -> dict[str, object]:
    before = path.read_text()
    patched_before = _patched(before)
    after = _patch_text(before)
    if after != before:
        path.write_text(after)
    return {
        "patch_id": PATCH_ID,
        "path": str(path),
        "already_patched": patched_before,
        "changed": after != before,
        "sha256_before": _digest(before),
        "sha256_after": _digest(after),
        "markers": list(EXPECTED_MARKERS),
    }


def verify_patch(path: Path) -> dict[str, object]:
    text = path.read_text()
    missing = [marker for marker in EXPECTED_MARKERS if marker not in text]
    if missing:
        raise RuntimeError(f"offloader.py missing patch markers: {missing}")
    return {
        "patch_id": PATCH_ID,
        "path": str(path),
        "sha256": _digest(text),
        "markers": list(EXPECTED_MARKERS),
        "patched": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offloader", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    evidence = verify_patch(args.offloader) if args.verify_only else apply_patch(args.offloader)
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
