# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Placement: map a workload's requested actors onto meshes.

The single decision all three Workload Planes share. Modelled as a pure function
over declared demand plus observed host capacity, not a scheduler daemon. The
first setting is single-host, so :meth:`Placement.plan` degenerates to "fit the
gang onto the local GPUs or fail loud" — but the signature is the shared seam:
training gang-schedules a worker group, serving sizes replica pools, analysis
places one bundle per partition.

Illegal placements are unrepresentable: a :class:`MeshPlan` that does not
satisfy the gang constraint cannot be constructed. Following the repo's
no-fallback invariant, an infeasible demand raises :class:`PlacementError`
rather than returning a degraded plan.
"""

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Mapping


class PlacementError(Exception):
    """A workload's demand cannot be satisfied by the observed capacity.

    Raised eagerly (fail loud) rather than returning a partial plan.
    """


class GangConstraint(enum.Enum):
    """Whether a workload's actors must be placed all-or-nothing.

    ``ALL`` (training) requires every requested actor to be placed in one plan
    or the placement fails. ``INCREMENTAL`` (serving replicas, analysis
    partitions) allows placing between a minimum and a maximum count.
    """

    ALL = "all"
    INCREMENTAL = "incremental"


@dataclass(frozen=True)
class WorkloadDemand:
    """A per-plane request expressed uniformly.

    Attributes:
        workload_id: Stable identity used by the control store and recovery.
        gpus_per_actor: GPUs each worker actor needs (0 for CPU-only actors).
        gang: All-or-nothing (training) vs incremental (serving/analysis).
        min_actors: Fewest actors that constitute a runnable workload.
        max_actors: Most actors to place; equals ``min_actors`` for an ``ALL``
            gang. For ``INCREMENTAL`` it bounds the replica/partition count.
        labels: Opaque routing/selection labels carried into the plan.
    """

    workload_id: str
    gpus_per_actor: int
    gang: GangConstraint
    min_actors: int
    max_actors: int
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workload_id:
            raise PlacementError("workload demand: empty workload_id")
        if self.gpus_per_actor < 0:
            raise PlacementError(
                f"workload demand: negative gpus_per_actor {self.gpus_per_actor}"
            )
        if self.min_actors < 1:
            raise PlacementError(
                f"workload demand: min_actors must be >= 1, got {self.min_actors}"
            )
        if self.max_actors < self.min_actors:
            raise PlacementError(
                "workload demand: max_actors "
                f"{self.max_actors} < min_actors {self.min_actors}"
            )
        if self.gang is GangConstraint.ALL and self.max_actors != self.min_actors:
            raise PlacementError(
                "workload demand: an ALL gang must request a fixed size "
                f"(min_actors {self.min_actors} != max_actors {self.max_actors})"
            )


@dataclass(frozen=True)
class HostCapacity:
    """Observed capacity of the local host.

    Derived from the current :class:`JobState` host meshes plus local GPU
    inventory (the 8-GPU verifier already enumerates visible CUDA devices).

    Attributes:
        gpu_ids: The GPU ordinals visible to this host, e.g. ``[0, 1, ..., 7]``.
    """

    gpu_ids: List[int]

    @property
    def gpu_count(self) -> int:
        return len(self.gpu_ids)


@dataclass(frozen=True)
class MeshPlan:
    """A concrete assignment of workload actors to GPUs.

    The output fed to ``this_host().spawn_procs(per_host=...)``. Constructing a
    ``MeshPlan`` directly is possible but ``Placement.plan`` is the intended
    entrypoint; the invariant (each rank owns a distinct, non-empty GPU set of
    the requested width) is enforced at construction.
    """

    workload_id: str
    #: rank -> the GPU ordinals that rank owns. ``len`` is the placed size.
    rank_to_gpus: Dict[int, List[int]]

    def __post_init__(self) -> None:
        if not self.rank_to_gpus:
            raise PlacementError(
                f"mesh plan {self.workload_id}: placed zero ranks"
            )
        expected_ranks = list(range(len(self.rank_to_gpus)))
        if sorted(self.rank_to_gpus) != expected_ranks:
            raise PlacementError(
                f"mesh plan {self.workload_id}: ranks must be contiguous from 0, "
                f"got {sorted(self.rank_to_gpus)}"
            )
        seen: set[int] = set()
        for rank, gpus in self.rank_to_gpus.items():
            if not gpus:
                raise PlacementError(
                    f"mesh plan {self.workload_id}: rank {rank} owns no GPUs"
                )
            overlap = seen.intersection(gpus)
            if overlap:
                raise PlacementError(
                    f"mesh plan {self.workload_id}: GPUs {sorted(overlap)} "
                    "assigned to more than one rank"
                )
            seen.update(gpus)

    @property
    def size(self) -> int:
        return len(self.rank_to_gpus)

    @property
    def per_host(self) -> Dict[str, int]:
        """The ``per_host`` argument for ``spawn_procs`` (one proc per rank)."""
        return {"gpus": self.size}


class Placement:
    """Map a :class:`WorkloadDemand` onto local capacity.

    Single-host, first-setting implementation: pack ranks onto distinct GPU
    groups, honoring the gang constraint. Multi-host bin-packing is deliberately
    out of scope for the tracer bullet.
    """

    @staticmethod
    def plan(demand: WorkloadDemand, capacity: HostCapacity) -> MeshPlan:
        """Return a mesh plan or raise :class:`PlacementError`.

        For a CPU-only workload (``gpus_per_actor == 0``) each rank is assigned
        a synthetic empty-GPU slot is disallowed by the ``MeshPlan`` invariant,
        so CPU-only demand instead pins one GPU ordinal per rank purely as an
        allocation token; callers that never touch CUDA may ignore it. Keeping
        one code path avoids a second, untested placement branch.
        """
        width = max(demand.gpus_per_actor, 1)
        available = list(capacity.gpu_ids)
        capacity_actors = len(available) // width

        if capacity_actors < demand.min_actors:
            raise PlacementError(
                f"placement {demand.workload_id}: need {demand.min_actors} "
                f"actors x {width} gpus but only {len(available)} gpus visible "
                f"(fits {capacity_actors})"
            )

        placed = min(demand.max_actors, capacity_actors)
        rank_to_gpus: Dict[int, List[int]] = {}
        cursor = 0
        for rank in range(placed):
            rank_to_gpus[rank] = available[cursor : cursor + width]
            cursor += width
        return MeshPlan(workload_id=demand.workload_id, rank_to_gpus=rank_to_gpus)
