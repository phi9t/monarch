/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the BSD-style license found in the
 * LICENSE file in the root directory of this source tree.
 */

//! Per-actor isolated storage example using `ActorLocal<T>`.
//!
//! Demonstrates:
//!   - Declaring `static ActorLocal<T>` for global-static, per-actor storage
//!   - Fluent update API: `entry(cx).or_default().get_mut()`
//!   - Structured insert: `entry(cx).or_insert_with(f).get_mut()`
//!   - Pattern-matching API: `Entry::Occupied` / `Entry::Vacant`
//!   - Isolation verification: three actors see only their own counters
//!
//! Run with:
//!   cargo run --bin hyperactor_example_actor_local

use std::time::Duration;

use async_trait::async_trait;
use hyperactor::Actor;
use hyperactor::ActorLocal;
use hyperactor::Context;
use hyperactor::HandleClient;
use hyperactor::Handler;
use hyperactor::RefClient;
use hyperactor::actor_local::Entry;
use hyperactor::proc::Proc;
use hyperactor::reference;
use serde::Deserialize;
use serde::Serialize;
use typeuri::Named;

// ─────────────────────────────── Actor-local statics ─────────────────────────

/// Per-actor message counter. Each actor has its own independent value.
static MSG_COUNT: ActorLocal<u64> = ActorLocal::new();

/// The last message received by each actor. Isolated per actor instance.
static LAST_MSG: ActorLocal<String> = ActorLocal::new();

// ─────────────────────────────── Actor definition ────────────────────────────

/// An actor that counts incoming messages and remembers the last one.
#[derive(Debug)]
struct CountingActor {
    name: String,
}

/// Messages handled by [`CountingActor`].
#[derive(Handler, HandleClient, RefClient, Debug, Serialize, Deserialize, Named)]
enum CountMsg {
    /// Record a ping — increments the per-actor counter and stores the payload.
    Ping(String),
    /// Return `(message_count, last_message)` for this actor (RPC reply).
    QueryStats(#[reply] reference::OncePortRef<(u64, String)>),
}

impl Actor for CountingActor {}

#[async_trait]
#[hyperactor::handle(CountMsg)]
impl CountMsgHandler for CountingActor {
    async fn ping(&mut self, cx: &Context<Self>, msg: String) -> Result<(), anyhow::Error> {
        // Fluent increment — inserts default (0) if not yet present.
        let new_count = {
            let mut e = MSG_COUNT.entry(cx).or_default();
            *e.get_mut() += 1;
            *e.get()
        };

        // Structured insert/update — inserts empty string if not yet present.
        *LAST_MSG.entry(cx).or_insert_with(String::new).get_mut() = msg;

        println!("  {}: ping #{}", self.name, new_count);
        Ok(())
    }

    async fn query_stats(
        &mut self,
        cx: &Context<Self>,
    ) -> Result<(u64, String), anyhow::Error> {
        // Pattern-matching style — no side-effects when the entry is absent.
        let count = match MSG_COUNT.entry(cx) {
            Entry::Occupied(o) => *o.get(),
            Entry::Vacant(_) => 0,
        };
        let last = match LAST_MSG.entry(cx) {
            Entry::Occupied(o) => o.get().clone(),
            Entry::Vacant(_) => String::new(),
        };
        Ok((count, last))
    }
}

// ─────────────────────────────── Main ────────────────────────────────────────

#[tokio::main]
async fn main() -> Result<(), anyhow::Error> {
    let mut proc = Proc::local();
    let (client, _) = proc.instance("client").unwrap();

    // Spawn three independent actors sharing the same static `ActorLocal`s.
    let alice = proc.spawn("alice", CountingActor { name: "alice".into() })?;
    let bob = proc.spawn("bob", CountingActor { name: "bob".into() })?;
    let carol = proc.spawn("carol", CountingActor { name: "carol".into() })?;

    // Send different numbers of pings to each actor.
    for i in 0..3u64 {
        alice.ping(&client, format!("alice-ping-{}", i)).await?;
    }
    for i in 0..5u64 {
        bob.ping(&client, format!("bob-ping-{}", i)).await?;
    }
    carol.ping(&client, "carol-ping-0".into()).await?;

    // Query each actor's isolated stats.
    let (alice_count, alice_last) = alice.query_stats(&client).await?;
    let (bob_count, bob_last) = bob.query_stats(&client).await?;
    let (carol_count, carol_last) = carol.query_stats(&client).await?;

    // ── Verify counts are isolated per actor ──────────────────────────────────
    assert_eq!(alice_count, 3, "alice should have 3 pings");
    assert_eq!(bob_count, 5, "bob should have 5 pings");
    assert_eq!(carol_count, 1, "carol should have 1 ping");
    println!(
        "[PASS] counts isolated: alice={} bob={} carol={}",
        alice_count, bob_count, carol_count,
    );

    // ── Verify last-message is also isolated ─────────────────────────────────
    assert!(
        alice_last.starts_with("alice-"),
        "alice's last_msg should be an alice message, got: {}",
        alice_last,
    );
    assert!(
        bob_last.starts_with("bob-"),
        "bob's last_msg should be a bob message, got: {}",
        bob_last,
    );
    assert_eq!(carol_last, "carol-ping-0");
    println!("[PASS] last messages isolated per actor");
    println!("  alice: \"{}\"", alice_last);
    println!("  bob:   \"{}\"", bob_last);
    println!("  carol: \"{}\"", carol_last);

    let _ = proc
        .destroy_and_wait::<()>(Duration::from_secs(1), None, "actor_local example cleanup")
        .await?;
    println!("[PASS] actor_local example complete");
    Ok(())
}
