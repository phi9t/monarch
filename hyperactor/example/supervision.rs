/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the BSD-style license found in the
 * LICENSE file in the root directory of this source tree.
 */

//! Supervision tree example: parent actors catching and absorbing child failures.
//!
//! Demonstrates:
//!   - Spawning child actors inside `Actor::init`
//!   - Implementing `Actor::handle_supervision_event` to intercept child failures
//!   - Returning `Ok(true)` so the proc survives after children crash
//!   - `ActorSupervisionEvent::actually_failing_actor()` for root-cause traversal
//!
//! Run with:
//!   cargo run --bin hyperactor_example_supervision

use std::time::Duration;

use async_trait::async_trait;
use hyperactor::Actor;
use hyperactor::ActorHandle;
use hyperactor::Context;
use hyperactor::HandleClient;
use hyperactor::Handler;
use hyperactor::Instance;
use hyperactor::RefClient;
use hyperactor::proc::Proc;
use hyperactor::reference;
use hyperactor::supervision::ActorSupervisionEvent;
use serde::Deserialize;
use serde::Serialize;
use typeuri::Named;

// ─────────────────────────────── Worker actor ────────────────────────────────

/// A simple worker actor that can do work or simulate a crash.
#[derive(Debug)]
struct WorkerActor {
    id: usize,
}

/// Messages handled by [`WorkerActor`].
#[derive(Handler, HandleClient, RefClient, Debug, Serialize, Deserialize, Named)]
enum WorkerMsg {
    /// Do some work (always succeeds).
    DoWork(String),
    /// Simulate a crash — the handler returns `Err`, triggering supervision.
    Crash(String),
}

impl Actor for WorkerActor {}

#[async_trait]
#[hyperactor::handle(WorkerMsg)]
impl WorkerMsgHandler for WorkerActor {
    async fn do_work(&mut self, _cx: &Context<Self>, task: String) -> Result<(), anyhow::Error> {
        println!("  worker[{}]: working on '{}'", self.id, task);
        Ok(())
    }

    async fn crash(&mut self, _cx: &Context<Self>, reason: String) -> Result<(), anyhow::Error> {
        println!("  worker[{}]: simulating crash ({})", self.id, reason);
        Err(anyhow::anyhow!("worker {} crashed: {}", self.id, reason))
    }
}

// ─────────────────────────────── Supervisor actor ────────────────────────────

/// A supervisor that spawns workers as children and handles their failures.
#[derive(Debug, Default)]
struct SupervisorActor {
    workers: Vec<ActorHandle<WorkerActor>>,
    failed_count: usize,
}

/// Messages handled by [`SupervisorActor`].
#[derive(Handler, HandleClient, RefClient, Debug, Serialize, Deserialize, Named)]
enum SupervisorMsg {
    /// Forward a work task to the nth worker.
    ForwardWork(usize, String),
    /// Ask the nth worker to crash.
    CrashWorker(usize),
    /// Query how many workers have failed so far (RPC — awaits a reply).
    FailCount(#[reply] reference::OncePortRef<usize>),
}

#[async_trait]
impl Actor for SupervisorActor {
    /// Spawn 3 worker children on initialization.
    async fn init(&mut self, this: &Instance<Self>) -> Result<(), anyhow::Error> {
        for id in 0..3 {
            let worker = WorkerActor { id }.spawn(this)?;
            self.workers.push(worker);
        }
        println!("supervisor: spawned {} worker children", self.workers.len());
        Ok(())
    }

    /// Absorb failures from child actors.
    ///
    /// Returning `Ok(true)` signals that this actor handled the event — the
    /// proc stays alive and the event is not propagated further.
    async fn handle_supervision_event(
        &mut self,
        _this: &Instance<Self>,
        event: &ActorSupervisionEvent,
    ) -> Result<bool, anyhow::Error> {
        // Walk the chain to find the root-cause actor.
        let root = event.actually_failing_actor();
        println!(
            "supervisor: caught failure of {} (is_error={})",
            root.actor_id,
            event.is_error(),
        );
        self.failed_count += 1;
        Ok(true) // absorbed — proc stays alive
    }
}

#[async_trait]
#[hyperactor::handle(SupervisorMsg)]
impl SupervisorMsgHandler for SupervisorActor {
    async fn forward_work(
        &mut self,
        cx: &Context<Self>,
        idx: usize,
        task: String,
    ) -> Result<(), anyhow::Error> {
        self.workers[idx].send(cx, WorkerMsg::DoWork(task))?;
        Ok(())
    }

    async fn crash_worker(
        &mut self,
        cx: &Context<Self>,
        idx: usize,
    ) -> Result<(), anyhow::Error> {
        println!("supervisor: directing worker[{}] to crash", idx);
        self.workers[idx].send(cx, WorkerMsg::Crash("test-induced".to_string()))?;
        Ok(())
    }

    async fn fail_count(&mut self, _cx: &Context<Self>) -> Result<usize, anyhow::Error> {
        Ok(self.failed_count)
    }
}

// ─────────────────────────────── Main ────────────────────────────────────────

#[tokio::main]
async fn main() -> Result<(), anyhow::Error> {
    let mut proc = Proc::local();
    let (client, _) = proc.instance("client").unwrap();

    // Spawn the supervisor. Its `init` will spawn 3 worker children.
    let supervisor = proc.spawn("supervisor", SupervisorActor::default())?;

    // Give `init` time to complete.
    tokio::time::sleep(Duration::from_millis(100)).await;

    // ── Verify initial state ──────────────────────────────────────────────────
    let count = supervisor.fail_count(&client).await?;
    assert_eq!(count, 0);
    println!("[PASS] initial fail_count == 0");

    // ── Crash worker[0] and wait for the supervision event to propagate ───────
    supervisor.crash_worker(&client, 0).await?;
    tokio::time::sleep(Duration::from_millis(300)).await;

    let count = supervisor.fail_count(&client).await?;
    assert_eq!(count, 1);
    println!("[PASS] fail_count == 1 after crashing worker[0]");

    // ── Workers 1 and 2 are still alive ──────────────────────────────────────
    supervisor
        .forward_work(&client, 1, "still alive".into())
        .await?;
    supervisor
        .forward_work(&client, 2, "still alive".into())
        .await?;
    println!("[PASS] workers 1 and 2 functional after sibling failure");

    // ── Crash worker[1] — supervisor absorbs a second failure ────────────────
    supervisor.crash_worker(&client, 1).await?;
    tokio::time::sleep(Duration::from_millis(300)).await;

    let count = supervisor.fail_count(&client).await?;
    assert_eq!(count, 2);
    println!("[PASS] fail_count == 2 after crashing worker[1]");

    // ── Worker 2 is still alive ───────────────────────────────────────────────
    supervisor
        .forward_work(&client, 2, "last worker standing".into())
        .await?;
    println!("[PASS] worker[2] functional after both sibling failures");

    // ── Graceful shutdown ─────────────────────────────────────────────────────
    let _ = proc
        .destroy_and_wait::<()>(Duration::from_secs(2), None, "supervision example cleanup")
        .await?;
    println!("[PASS] supervision example complete — proc survived child failures");
    Ok(())
}
