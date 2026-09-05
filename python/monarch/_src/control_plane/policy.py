# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Reallocation policy: what a mesh failure does instead of exiting.

Monarch's default :func:`monarch.actor.unhandled_fault_hook` calls
``sys.exit(1)`` — the right default for an unmanaged client, the wrong default
for a supervised workload. A Workload Plane registers a
:class:`ReallocationPolicy` whose :meth:`on_failure` maps a :class:`MeshFailure`
to a closed :class:`Decision`:

- :class:`Resume` — training resumes the gang from the last checkpoint.
- :class:`Replace` — serving replaces one failed replica.
- :class:`ReExecute` — analysis re-runs one failed stage.
- :class:`Escalate` — give up on this workload; fall through to the default hook.

The three planes differ only by which variant they return. Retries are bounded
by a counter (``max_reallocations``); when exhausted the policy escalates.
Recovery re-derives topology from *current* mesh membership, never a cached
world size (torch-elastic reassigns RANK/WORLD_SIZE on every restart).

See ``.scratch/monarch-unified-control-plane/spec/00-shared-substrate.md``.
"""

import enum
from dataclasses import dataclass
from typing import Optional, Union


class DecisionKind(enum.Enum):
    RESUME = "resume"
    REPLACE = "replace"
    REEXECUTE = "reexecute"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Resume:
    """Resume the whole gang from a checkpoint (training)."""

    from_checkpoint: str

    kind: DecisionKind = DecisionKind.RESUME


@dataclass(frozen=True)
class Replace:
    """Replace one failed rank/replica in place (serving)."""

    rank: int

    kind: DecisionKind = DecisionKind.REPLACE


@dataclass(frozen=True)
class ReExecute:
    """Re-execute one failed stage (data analysis)."""

    stage: str

    kind: DecisionKind = DecisionKind.REEXECUTE


@dataclass(frozen=True)
class Escalate:
    """Give up: fall through to the default fault hook."""

    reason: str

    kind: DecisionKind = DecisionKind.ESCALATE


#: A closed set of reallocation decisions.
Decision = Union[Resume, Replace, ReExecute, Escalate]


class ReallocationPolicy:
    """Base class a Workload Plane specializes.

    Subclasses implement :meth:`decide`. This base owns the shared bounded-retry
    accounting so every plane escalates identically once
    ``max_reallocations`` is exhausted.
    """

    def __init__(self, max_reallocations: int) -> None:
        if max_reallocations < 0:
            raise ValueError(
                f"reallocation policy: max_reallocations must be >= 0, "
                f"got {max_reallocations}"
            )
        self._max_reallocations = max_reallocations
        self._used = 0

    @property
    def reallocations_used(self) -> int:
        return self._used

    @property
    def reallocations_remaining(self) -> int:
        return self._max_reallocations - self._used

    def on_failure(self, failure: "object") -> Decision:
        """Route a ``MeshFailure`` through the retry budget to a decision.

        Increments the retry counter and delegates to :meth:`decide`. When the
        budget is exhausted, returns :class:`Escalate` without calling
        :meth:`decide`, so the default fault hook takes over.

        ``failure`` is typed ``object`` to avoid importing the Rust binding at
        module load; a real ``MeshFailure`` is passed at runtime.
        """
        if self._used >= self._max_reallocations:
            return Escalate(
                reason=(
                    f"reallocation budget exhausted "
                    f"({self._used}/{self._max_reallocations})"
                )
            )
        self._used += 1
        return self.decide(failure)

    def decide(self, failure: "object") -> Decision:
        """Return the plane-specific decision for one failure.

        Must be overridden by a Workload Plane.
        """
        raise NotImplementedError(
            "ReallocationPolicy subclasses must implement decide()"
        )


class ReplacePolicy(ReallocationPolicy):
    """Reference policy for the tracer bullet: always replace the failed rank.

    The serving plane's shape. Reads the failed rank from the failure when
    available, else falls back to ``default_rank``. This proves the seam —
    ``MeshFailure -> Replace`` instead of ``sys.exit(1)`` — without a full
    serving fleet.
    """

    def __init__(self, max_reallocations: int, default_rank: int = 0) -> None:
        super().__init__(max_reallocations)
        self._default_rank = default_rank

    def decide(self, failure: "object") -> Decision:
        return Replace(rank=_failed_rank(failure, self._default_rank))


def _failed_rank(failure: "object", default: int) -> int:
    """Best-effort extraction of the failed rank from a ``MeshFailure``.

    ``MeshFailure`` currently exposes ``mesh``/``mesh_name``/``report()`` but not
    a structured rank, so this stays defensive at the binding boundary only and
    falls back to ``default``. When the binding gains a rank field, read it here.
    """
    rank = getattr(failure, "failed_rank", None)
    if isinstance(rank, int):
        return rank
    return default
