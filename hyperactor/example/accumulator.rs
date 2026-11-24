/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the BSD-style license found in the
 * LICENSE file in the root directory of this source tree.
 */

//! Accumulator / streaming-reducer example.
//!
//! Demonstrates the `Accumulator` trait and built-in accumulators:
//!   - `accum::sum::<T>()` — non-CRDT sum accumulator
//!   - `accum::join_semilattice::<Max<T>>()` — lattice-based CRDT with idempotency
//!   - `accum::join_semilattice::<GCounterUpdate>()` — distributed grow-only counter
//!   - Custom `impl Accumulator` — extend with your own logic
//!   - Actor-based aggregation — using an accumulator inside a message handler
//!
//! Run with:
//!   cargo run --bin hyperactor_example_accumulator

use std::time::Duration;

use async_trait::async_trait;
use hyperactor::Actor;
use hyperactor::Context;
use hyperactor::HandleClient;
use hyperactor::Handler;
use hyperactor::RefClient;
use hyperactor::accum;
use hyperactor::accum::Accumulator;
use hyperactor::accum::GCounterUpdate;
use hyperactor::accum::Max;
use hyperactor::proc::Proc;
use hyperactor::reference;
use serde::Deserialize;
use serde::Serialize;
use typeuri::Named;

// ─────────────────────────────── Demo 1: sum ─────────────────────────────────

fn demo_sum() {
    let acc = accum::sum::<u64>();
    let mut state: u64 = 0;

    acc.accumulate(&mut state, 10).unwrap();
    acc.accumulate(&mut state, 20).unwrap();
    acc.accumulate(&mut state, 5).unwrap();

    assert_eq!(state, 35);
    println!("[PASS] sum accumulator: 10 + 20 + 5 = {}", state);
}

// ─────────────────────────────── Demo 2: Max (CRDT) ──────────────────────────

fn demo_max() {
    let acc = accum::join_semilattice::<Max<u64>>();
    let mut state = Max(0u64);

    // Apply values in arbitrary order.
    acc.accumulate(&mut state, Max(50)).unwrap();
    acc.accumulate(&mut state, Max(20)).unwrap();
    acc.accumulate(&mut state, Max(80)).unwrap();
    acc.accumulate(&mut state, Max(30)).unwrap();

    assert_eq!(state, Max(80));
    println!("[PASS] max accumulator: max(50,20,80,30) = {}", state.0);

    // Idempotency: applying Max(80) again has no effect.
    acc.accumulate(&mut state, Max(80)).unwrap();
    assert_eq!(state, Max(80));
    println!("[PASS] max idempotency: duplicate update has no effect");

    // A smaller value also has no effect.
    acc.accumulate(&mut state, Max(1)).unwrap();
    assert_eq!(state, Max(80));
    println!("[PASS] max CRDT: stale update has no effect");
}

// ─────────────────────────────── Demo 3: GCounter (CRDT) ─────────────────────

fn demo_gcounter() {
    let acc = accum::join_semilattice::<GCounterUpdate>();
    let mut state = GCounterUpdate::default();

    // Three ranks contribute counts.
    acc.accumulate(&mut state, GCounterUpdate::from((0, 10)))
        .unwrap();
    acc.accumulate(&mut state, GCounterUpdate::from((1, 20)))
        .unwrap();
    acc.accumulate(&mut state, GCounterUpdate::from((2, 5)))
        .unwrap();

    assert_eq!(state.get(), 35); // 10 + 20 + 5
    assert_eq!(state.get_rank(0), Some(10));
    assert_eq!(state.get_rank(1), Some(20));
    assert_eq!(state.get_rank(2), Some(5));
    println!("[PASS] gcounter: total={} (ranks: 0={:?} 1={:?} 2={:?})",
        state.get(), state.get_rank(0), state.get_rank(1), state.get_rank(2));

    // Rank 0 increases its count to 15 (pointwise-max merge).
    acc.accumulate(&mut state, GCounterUpdate::from((0, 15)))
        .unwrap();
    assert_eq!(state.get_rank(0), Some(15));
    assert_eq!(state.get(), 40); // 15 + 20 + 5

    // Idempotency: replaying the same update has no effect.
    acc.accumulate(&mut state, GCounterUpdate::from((0, 15)))
        .unwrap();
    assert_eq!(state.get(), 40);
    println!("[PASS] gcounter idempotency: replay has no effect, total={}", state.get());

    // Stale update (lower count) is ignored.
    acc.accumulate(&mut state, GCounterUpdate::from((0, 3)))
        .unwrap();
    assert_eq!(state.get_rank(0), Some(15));
    println!("[PASS] gcounter CRDT: stale update ignored, rank-0={:?}", state.get_rank(0));
}

// ─────────────────────────────── Demo 4: custom Accumulator ──────────────────

/// A simple histogram that counts how many times each bucket was incremented.
struct BucketHistogram {
    num_buckets: usize,
}

impl Accumulator for BucketHistogram {
    /// The accumulated histogram (one count per bucket).
    type State = Vec<u64>;
    /// An incoming bucket index.
    type Update = usize;

    fn accumulate(&self, state: &mut Vec<u64>, bucket: usize) -> anyhow::Result<()> {
        if bucket < self.num_buckets {
            state[bucket] += 1;
        }
        Ok(())
    }

    fn reducer_spec(&self) -> Option<accum::ReducerSpec> {
        // No comm-reducer needed for this local-only accumulator.
        None
    }
}

fn demo_custom() {
    let acc = BucketHistogram { num_buckets: 3 };
    let mut state = vec![0u64; 3];

    // Record some observations.
    acc.accumulate(&mut state, 0).unwrap();
    acc.accumulate(&mut state, 1).unwrap();
    acc.accumulate(&mut state, 0).unwrap();
    acc.accumulate(&mut state, 2).unwrap();
    acc.accumulate(&mut state, 0).unwrap();

    // Out-of-range update is silently ignored.
    acc.accumulate(&mut state, 99).unwrap();

    assert_eq!(state[0], 3, "bucket 0 should have count 3");
    assert_eq!(state[1], 1, "bucket 1 should have count 1");
    assert_eq!(state[2], 1, "bucket 2 should have count 1");
    println!("[PASS] custom histogram: {:?}", state);
}

// ─────────────────────────────── Demo 5: actor-based aggregation ─────────────

/// An actor that accumulates incoming values using the `sum` accumulator.
#[derive(Debug, Default)]
struct AggActor {
    total: u64,
}

/// Messages handled by [`AggActor`].
#[derive(Handler, HandleClient, RefClient, Debug, Serialize, Deserialize, Named)]
enum AggMsg {
    /// Add a value to the running total.
    Add(u64),
    /// Return the current total (RPC reply).
    Total(#[reply] reference::OncePortRef<u64>),
}

impl Actor for AggActor {}

#[async_trait]
#[hyperactor::handle(AggMsg)]
impl AggMsgHandler for AggActor {
    async fn add(&mut self, _cx: &Context<Self>, value: u64) -> Result<(), anyhow::Error> {
        // Use the sum accumulator to update state — identical result to `+=`,
        // but shows how accumulators plug into actor handlers.
        accum::sum::<u64>().accumulate(&mut self.total, value)?;
        Ok(())
    }

    async fn total(&mut self, _cx: &Context<Self>) -> Result<u64, anyhow::Error> {
        Ok(self.total)
    }
}

async fn demo_in_actor_context() -> Result<(), anyhow::Error> {
    let mut proc = Proc::local();
    let (client, _) = proc.instance("client").unwrap();

    let agg = proc.spawn("agg", AggActor::default())?;

    // Send a batch of values to the actor.
    for &val in &[10u64, 20, 5, 3, 7] {
        agg.add(&client, val).await?;
    }

    // Query the accumulated total.
    let total = agg.total(&client).await?;
    assert_eq!(total, 45, "actor-based sum should be 45");
    println!("[PASS] actor-based accumulation: sum(10,20,5,3,7) = {}", total);

    let _ = proc
        .destroy_and_wait::<()>(
            Duration::from_secs(1),
            None,
            "accumulator actor demo cleanup",
        )
        .await?;
    Ok(())
}

// ─────────────────────────────── Main ────────────────────────────────────────

#[tokio::main]
async fn main() -> Result<(), anyhow::Error> {
    println!("── Demo 1: sum accumulator ──────────────────────────────────────");
    demo_sum();

    println!("\n── Demo 2: Max CRDT (join_semilattice) ─────────────────────────");
    demo_max();

    println!("\n── Demo 3: GCounter CRDT ────────────────────────────────────────");
    demo_gcounter();

    println!("\n── Demo 4: custom Accumulator impl ─────────────────────────────");
    demo_custom();

    println!("\n── Demo 5: accumulator inside an actor handler ──────────────────");
    demo_in_actor_context().await?;

    println!("\n[ALL PASS] accumulator example complete");
    Ok(())
}
