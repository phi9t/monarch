# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# pyre-unsafe

"""Unit tests for the shared control-plane substrate.

Pure Python — no mesh spawn, no GPU. Exercises Placement gang fit, the Decision
enum + bounded-retry accounting, and ControlStore round-trip. The mesh-level
tracer bullet (kill a rank -> Replace, not sys.exit) lives in the local run
verifier ``scripts/run_local_substrate_verifier.sh``.
"""

import pytest
from monarch.control_plane import (
    ControlStore,
    Escalate,
    GangConstraint,
    HostCapacity,
    MeshPlan,
    Placement,
    PlacementError,
    ReallocationPolicy,
    Replace,
    ReplacePolicy,
    Resume,
    WorkloadDemand,
)


def _gang(workload_id="train", size=4, gpus_per_actor=1):
    return WorkloadDemand(
        workload_id=workload_id,
        gpus_per_actor=gpus_per_actor,
        gang=GangConstraint.ALL,
        min_actors=size,
        max_actors=size,
    )


def _replicas(workload_id="serve", lo=1, hi=8, gpus_per_actor=1):
    return WorkloadDemand(
        workload_id=workload_id,
        gpus_per_actor=gpus_per_actor,
        gang=GangConstraint.INCREMENTAL,
        min_actors=lo,
        max_actors=hi,
    )


class TestPlacement:
    def test_gang_fits_exact(self) -> None:
        plan = Placement.plan(_gang(size=8), HostCapacity(list(range(8))))
        assert plan.size == 8
        assert plan.rank_to_gpus == {i: [i] for i in range(8)}
        assert plan.per_host == {"gpus": 8}

    def test_gang_multi_gpu_per_actor(self) -> None:
        plan = Placement.plan(
            _gang(size=2, gpus_per_actor=4), HostCapacity(list(range(8)))
        )
        assert plan.rank_to_gpus == {0: [0, 1, 2, 3], 1: [4, 5, 6, 7]}

    def test_gang_infeasible_fails_loud(self) -> None:
        with pytest.raises(PlacementError, match="only"):
            Placement.plan(_gang(size=8), HostCapacity([0, 1, 2, 3]))

    def test_incremental_caps_at_capacity(self) -> None:
        # asks up to 8 replicas but only 3 gpus -> place 3
        plan = Placement.plan(_replicas(lo=1, hi=8), HostCapacity([0, 1, 2]))
        assert plan.size == 3

    def test_incremental_respects_max(self) -> None:
        plan = Placement.plan(_replicas(lo=1, hi=2), HostCapacity(list(range(8))))
        assert plan.size == 2

    def test_incremental_below_min_fails(self) -> None:
        with pytest.raises(PlacementError):
            Placement.plan(_replicas(lo=4, hi=8), HostCapacity([0, 1]))

    def test_all_gang_must_be_fixed_size(self) -> None:
        with pytest.raises(PlacementError, match="fixed size"):
            WorkloadDemand(
                workload_id="x",
                gpus_per_actor=1,
                gang=GangConstraint.ALL,
                min_actors=2,
                max_actors=4,
            )

    def test_meshplan_rejects_overlapping_gpus(self) -> None:
        with pytest.raises(PlacementError, match="more than one rank"):
            MeshPlan(workload_id="x", rank_to_gpus={0: [0, 1], 1: [1, 2]})

    def test_meshplan_rejects_noncontiguous_ranks(self) -> None:
        with pytest.raises(PlacementError, match="contiguous"):
            MeshPlan(workload_id="x", rank_to_gpus={0: [0], 2: [1]})


class TestReallocationPolicy:
    def test_replace_policy_returns_replace(self) -> None:
        policy = ReplacePolicy(max_reallocations=3, default_rank=2)
        decision = policy.on_failure(object())
        assert isinstance(decision, Replace)
        assert decision.rank == 2
        assert policy.reallocations_used == 1

    def test_replace_policy_reads_failed_rank(self) -> None:
        class FakeFailure:
            failed_rank = 5

        decision = ReplacePolicy(max_reallocations=1).on_failure(FakeFailure())
        assert isinstance(decision, Replace)
        assert decision.rank == 5

    def test_budget_exhaustion_escalates(self) -> None:
        policy = ReplacePolicy(max_reallocations=1)
        assert isinstance(policy.on_failure(object()), Replace)
        second = policy.on_failure(object())
        assert isinstance(second, Escalate)
        assert "budget exhausted" in second.reason

    def test_zero_budget_escalates_immediately(self) -> None:
        assert isinstance(
            ReplacePolicy(max_reallocations=0).on_failure(object()), Escalate
        )

    def test_base_decide_is_abstract(self) -> None:
        with pytest.raises(NotImplementedError):
            ReallocationPolicy(max_reallocations=1).on_failure(object())

    def test_negative_budget_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReplacePolicy(max_reallocations=-1)

    def test_resume_decision_carries_checkpoint(self) -> None:
        r = Resume(from_checkpoint="ckpt://run/42")
        assert r.from_checkpoint == "ckpt://run/42"


class TestControlStore:
    def test_put_get_round_trip(self, tmp_path) -> None:
        store = ControlStore(str(tmp_path / "cp"))
        store.put("job-1", spec={"size": 8}, placement={"0": [0]})
        rec = store.get("job-1")
        assert rec is not None
        assert rec.workload_id == "job-1"
        assert rec.spec == {"size": 8}
        assert rec.placement == {"0": [0]}

    def test_reload_after_fresh_store(self, tmp_path) -> None:
        root = str(tmp_path / "cp")
        ControlStore(root).put("job-1", spec={"a": 1})
        # simulate a control-actor restart: brand-new store over the same root
        rec = ControlStore(root).get("job-1")
        assert rec is not None and rec.spec == {"a": 1}

    def test_get_missing_returns_none(self, tmp_path) -> None:
        assert ControlStore(str(tmp_path)).get("nope") is None

    def test_list_sorted(self, tmp_path) -> None:
        store = ControlStore(str(tmp_path))
        store.put("b", spec={})
        store.put("a", spec={})
        assert store.list() == ["a", "b"]

    def test_delete_idempotent(self, tmp_path) -> None:
        store = ControlStore(str(tmp_path))
        store.put("a", spec={})
        store.delete("a")
        store.delete("a")
        assert store.get("a") is None

    def test_workload_id_rejects_path_separator(self, tmp_path) -> None:
        store = ControlStore(str(tmp_path))
        with pytest.raises(ValueError, match="filename stem"):
            store.put("a/b", spec={})

    def test_overwrite_is_atomic_last_writer_wins(self, tmp_path) -> None:
        store = ControlStore(str(tmp_path))
        store.put("a", spec={"v": 1})
        store.put("a", spec={"v": 2})
        assert store.get("a").spec == {"v": 2}
