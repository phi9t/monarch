# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Control store: durable record of workload specs and placement.

Promotes Monarch's existing pickle-cache pattern (``JobTrait.dump`` /
``_load_cached`` at ``.monarch/job_state.pkl``) into an explicit, named
interface so a control-actor restart re-attaches to running work rather than
restarting it from zero. Recovery keys on a stable ``workload_id`` (Ray Train
resumes a whole run from ``(storage_path, run_name)``; recovery keys on
identity, not live state).

First implementation is a filesystem directory of JSON records with
atomic write-then-rename. Not a database — the interface is what lets a real
store swap in later without touching the Workload Planes.

See ``.scratch/monarch-unified-control-plane/spec/00-shared-substrate.md``.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, List, Mapping, Optional


@dataclass(frozen=True)
class WorkloadRecord:
    """One durable workload entry.

    Attributes:
        workload_id: Stable identity; also the record filename stem.
        spec: The declarative workload demand as a plain dict (plane-defined).
        placement: The current mesh plan as a plain dict (rank -> gpu ordinals).
    """

    workload_id: str
    spec: Mapping[str, Any]
    placement: Mapping[str, Any] = field(default_factory=dict)


class ControlStore:
    """A filesystem-backed record of workloads under a control root.

    Layout: ``<root>/<workload_id>.json``. Writes are atomic (write to a temp
    file in the same directory, then ``os.replace``), matching the durability
    the pickle cache relies on. ``workload_id`` must be a safe filename stem;
    path separators are rejected (fail loud) rather than sanitized.
    """

    def __init__(self, root: str) -> None:
        self._root = os.path.abspath(root)
        os.makedirs(self._root, exist_ok=True)

    @property
    def root(self) -> str:
        return self._root

    def _path(self, workload_id: str) -> str:
        if not workload_id:
            raise ValueError("control store: empty workload_id")
        if os.sep in workload_id or (os.altsep and os.altsep in workload_id):
            raise ValueError(
                f"control store: workload_id must be a filename stem, "
                f"got {workload_id!r}"
            )
        return os.path.join(self._root, f"{workload_id}.json")

    def put(
        self,
        workload_id: str,
        spec: Mapping[str, Any],
        placement: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Durably record (or overwrite) a workload's spec and placement."""
        record = WorkloadRecord(
            workload_id=workload_id,
            spec=dict(spec),
            placement=dict(placement or {}),
        )
        path = self._path(workload_id)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(record), f, sort_keys=True, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def get(self, workload_id: str) -> Optional[WorkloadRecord]:
        """Return the record for ``workload_id`` or ``None`` if absent."""
        path = self._path(workload_id)
        try:
            with open(path) as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        return WorkloadRecord(
            workload_id=data["workload_id"],
            spec=data["spec"],
            placement=data.get("placement", {}),
        )

    def list(self) -> List[str]:
        """Return the workload ids currently recorded, sorted."""
        ids = [
            name[: -len(".json")]
            for name in os.listdir(self._root)
            if name.endswith(".json")
        ]
        return sorted(ids)

    def delete(self, workload_id: str) -> None:
        """Remove a workload record if present (idempotent)."""
        try:
            os.remove(self._path(workload_id))
        except FileNotFoundError:
            pass
