# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Shared coordination-core substrate for the unified control plane.

Three primitives every Workload Plane (training, serving, data analysis) needs
equally, layered over Monarch's landed mesh + supervision core:

- :class:`~monarch._src.control_plane.placement.Placement` maps a workload's
  requested actors onto meshes.
- :class:`~monarch._src.control_plane.policy.ReallocationPolicy` decides what a
  :class:`MeshFailure` does instead of the default ``sys.exit(1)``.
- :class:`~monarch._src.control_plane.store.ControlStore` durably records
  workload specs and placement so a control-actor restart re-attaches.

See ``docs/adr/0003-shared-core-three-thin-planes.md`` and
``.scratch/monarch-unified-control-plane/spec/00-shared-substrate.md``.
"""

from monarch._src.control_plane.placement import (
    GangConstraint,
    HostCapacity,
    MeshPlan,
    Placement,
    PlacementError,
    WorkloadDemand,
)
from monarch._src.control_plane.policy import (
    Decision,
    Escalate,
    ReallocationPolicy,
    ReExecute,
    Replace,
    ReplacePolicy,
    Resume,
)
from monarch._src.control_plane.store import ControlStore, WorkloadRecord

__all__ = [
    "GangConstraint",
    "HostCapacity",
    "MeshPlan",
    "Placement",
    "PlacementError",
    "WorkloadDemand",
    "Decision",
    "Escalate",
    "ReallocationPolicy",
    "ReExecute",
    "Replace",
    "ReplacePolicy",
    "Resume",
    "ControlStore",
    "WorkloadRecord",
]
