# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# pyre-unsafe

"""Mesh-level tracer bullet for the shared control-plane substrate.

Proves the seam end to end on ``this_host()`` with local GPUs:

1. Placement fits a gang onto the visible GPUs.
2. ControlStore records the spec + placement and round-trips after a fresh load.
3. A ProcMesh is spawned to the plan and ranks are read back.
4. An actor is crashed; the registered ReallocationPolicy receives the
   ``MeshFailure`` and returns ``Replace`` (never ``sys.exit(1)``); the mesh is
   re-placed with ranks re-derived from current membership.

Emits Contract Artifacts under ``substrate-results/`` and exits nonzero with a
distinct code on each rung's failure, matching the repo's fail-loud, ladder-exit
convention. Run through ``scripts/run_local_substrate_verifier.sh``.
"""

import argparse
import json
import sys
import threading
import traceback
from pathlib import Path
from typing import List

EXIT_TENSOR_ENGINE = 21
EXIT_PLACEMENT = 22
EXIT_SMOKE = 23
EXIT_REALLOCATION = 24


def _results_dir(repo_root: Path) -> Path:
    d = repo_root / "substrate-results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run(repo_root: Path, gpus: int) -> int:
    import torch

    import monarch.actor as monarch_actor

    from monarch._rust_bindings import has_tensor_engine
    from monarch.actor import Actor, current_rank, endpoint, this_host
    from monarch.control_plane import (
        ControlStore,
        GangConstraint,
        HostCapacity,
        Placement,
        Replace,
        ReplacePolicy,
        WorkloadDemand,
    )

    results = _results_dir(repo_root)

    if not has_tensor_engine():
        print("tensor engine not built (has_tensor_engine() is False)", file=sys.stderr)
        return EXIT_TENSOR_ENGINE

    device_count = torch.cuda.device_count()
    if device_count < gpus:
        print(f"need {gpus} visible CUDA devices, got {device_count}", file=sys.stderr)
        return EXIT_TENSOR_ENGINE

    # --- rung 1: placement -------------------------------------------------
    workload_id = "substrate-tracer"
    demand = WorkloadDemand(
        workload_id=workload_id,
        gpus_per_actor=1,
        gang=GangConstraint.ALL,
        min_actors=gpus,
        max_actors=gpus,
    )
    capacity = HostCapacity(gpu_ids=list(range(gpus)))
    try:
        plan = Placement.plan(demand, capacity)
    except Exception:
        traceback.print_exc()
        return EXIT_PLACEMENT
    if plan.size != gpus:
        print(f"placement produced {plan.size} ranks, expected {gpus}", file=sys.stderr)
        return EXIT_PLACEMENT
    (results / "placement.json").write_text(
        json.dumps(
            {
                "workload_id": plan.workload_id,
                "size": plan.size,
                "rank_to_gpus": {str(r): g for r, g in plan.rank_to_gpus.items()},
                "per_host": plan.per_host,
            },
            indent=2,
            sort_keys=True,
        )
    )

    # --- rung 2: control store round-trips across a fresh instance ---------
    store_root = str(results / "control-store")
    placement_dict = {str(r): g for r, g in plan.rank_to_gpus.items()}
    ControlStore(store_root).put(
        workload_id,
        spec={
            "gpus_per_actor": demand.gpus_per_actor,
            "gang": demand.gang.value,
            "min_actors": demand.min_actors,
            "max_actors": demand.max_actors,
        },
        placement=placement_dict,
    )
    reloaded = ControlStore(store_root).get(workload_id)
    if reloaded is None or reloaded.placement != placement_dict:
        print("control store did not round-trip placement", file=sys.stderr)
        return EXIT_SMOKE

    # --- register the reallocation policy in place of sys.exit(1) ----------
    realloc_log = results / "reallocation.jsonl"
    realloc_log.write_text("")
    policy = ReplacePolicy(max_reallocations=gpus)
    fault_seen = threading.Event()

    def substrate_fault_hook(failure) -> None:
        decision = policy.on_failure(failure)
        entry = {"decision": decision.kind.value}
        if isinstance(decision, Replace):
            entry["rank"] = decision.rank
        try:
            entry["report"] = failure.report()
        except Exception:
            entry["report"] = repr(failure)
        with open(realloc_log, "a") as f:
            f.write(json.dumps(entry) + "\n")
        fault_seen.set()
        # Returning without raising drops the fault: the client stays alive,
        # which is the whole point of a Reallocation Policy over sys.exit(1).

    original_hook = monarch_actor.unhandled_fault_hook
    monarch_actor.unhandled_fault_hook = substrate_fault_hook

    class Worker(Actor):
        @endpoint
        def rank(self) -> int:
            return current_rank().rank

        @endpoint
        def boom(self) -> None:
            # ValueError from a broadcast endpoint kills the actor and fires
            # supervision (matches test_supervision_hierarchy.error()).
            raise ValueError("deliberate crash for the substrate tracer")

    # --- rung 3: spawn the mesh to the plan, read ranks --------------------
    procs = this_host().spawn_procs(per_host=plan.per_host)
    procs.initialized.get(timeout=120)
    try:
        workers = procs.spawn("worker", Worker)
        observed: List[int] = sorted(
            v for _point, v in workers.rank.call().get().items()
        )
        if observed != list(range(gpus)):
            print(
                f"expected ranks {list(range(gpus))}, got {observed}", file=sys.stderr
            )
            return EXIT_SMOKE

        # --- rung 4: crash an actor, expect Replace not sys.exit -----------
        workers.boom.broadcast()
        fault_seen.wait(timeout=60)
    finally:
        try:
            procs.stop("substrate tracer cleanup").get(timeout=120)
        except Exception:
            traceback.print_exc()
        monarch_actor.unhandled_fault_hook = original_hook

    # verify the policy fired and chose Replace
    lines = [
        json.loads(line)
        for line in realloc_log.read_text().splitlines()
        if line.strip()
    ]
    replaced = [e for e in lines if e.get("decision") == "replace"]
    if not replaced:
        print(
            f"reallocation policy did not observe a Replace decision; log={lines}",
            file=sys.stderr,
        )
        return EXIT_REALLOCATION

    # re-place from current membership (single-host: same capacity => same plan)
    replan = Placement.plan(demand, capacity)
    (results / "replan.json").write_text(
        json.dumps({"size": replan.size, "decisions": lines}, indent=2, sort_keys=True)
    )
    print(
        f"substrate tracer: placed {plan.size} ranks, observed Replace, "
        f"re-placed {replan.size}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpus", type=int, default=2)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    sys.exit(_run(repo_root, args.gpus))


if __name__ == "__main__":
    main()
