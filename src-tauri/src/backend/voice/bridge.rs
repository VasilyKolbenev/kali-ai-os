//! Generic Rust ↔ child-process bridge over JSON-on-stdio.
//!
//! Spawns the child once, owns its stdin/stdout, runs a writer task that
//! pushes outgoing requests and a reader task that resolves pending
//! oneshot senders by correlation id. Caller supplies the program path
//! and arguments (e.g. `"python.exe"`, `["-m", "kernel.workers.tts_worker"]`).
//!
//! Wire protocol (line-delimited JSON, UTF-8):
//!
//!   Rust → child:  {"id":"<uuid>","op":"<op>","args":{...}}\n
//!   child → Rust:  {"id":"<uuid>","result":{...}}\n
//!                  {"id":"<uuid>","error":{"type":"...","message":"..."}}\n
//!                  {"log":{"level":"info|warn|error","message":"..."}}\n
//!
//! Lines without `id` and with `log` are emitted as `tracing` events
//! and dropped. Lines with an unknown `id` are warned and dropped.
//!
//! Restart-on-crash is intentionally NOT implemented in Phase 3 Chunk 1
//! — a worker crash drops every pending oneshot so callers see
//! `BridgeError::NotRunning` instead of hanging. Restart logic lands in
//! a later phase if the operational signal demands it.

use std::collections::HashMap;
use std::ffi::OsStr;
use std::path::Path;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio::time::timeout;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum BridgeError {
    #[error("worker not running")]
    NotRunning,
    #[error("worker reply timed out after {0:?}")]
    Timeout(Duration),
    #[error("worker error [{kind}]: {message}")]
    Worker { kind: String, message: String },
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("serde: {0}")]
    Serde(#[from] serde_json::Error),
    #[error(transparent)]
    Other(#[from] anyhow::Error),
}

#[derive(Debug, Deserialize)]
struct Response {
    id: Option<String>,
    result: Option<Value>,
    error: Option<ErrorBody>,
    log: Option<LogLine>,
}

#[derive(Debug, Deserialize)]
struct ErrorBody {
    #[serde(rename = "type")]
    kind: String,
    message: String,
    #[allow(dead_code)]
    #[serde(default)]
    trace: Option<String>,
}

#[derive(Debug, Deserialize)]
struct LogLine {
    level: String,
    message: String,
}

/// Payload pushed by `call()` onto the writer task's channel. Carries
/// everything the writer needs to assemble the envelope and the
/// oneshot the reader will fulfil.
struct OutgoingRequest {
    id: String,
    op: String,
    args: Value,
    resp_tx: oneshot::Sender<Result<Value, BridgeError>>,
}

type Pending = Arc<Mutex<HashMap<String, oneshot::Sender<Result<Value, BridgeError>>>>>;

/// Owns the child process and the writer-task mpsc sender. Drop kills
/// the child (`kill_on_drop(true)` on the underlying `Command`).
pub struct BridgeWorker {
    name: &'static str,
    tx: mpsc::Sender<OutgoingRequest>,
    _child: Child,
}

impl BridgeWorker {
    pub async fn spawn(
        name: &'static str,
        program: impl AsRef<OsStr>,
        args: &[&str],
        cwd: impl AsRef<Path>,
    ) -> Result<Self> {
        let mut cmd = Command::new(&program);
        cmd.args(args)
            .current_dir(cwd.as_ref())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);

        let mut child = cmd
            .spawn()
            .with_context(|| format!("spawn {} worker", name))?;

        let stdin = child.stdin.take().context("worker has no stdin")?;
        let stdout = child.stdout.take().context("worker has no stdout")?;

        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let (req_tx, req_rx) = mpsc::channel::<OutgoingRequest>(64);

        tokio::spawn(writer_task(name, stdin, req_rx, pending.clone()));
        tokio::spawn(reader_task(name, stdout, pending));

        info!(worker = name, "bridge worker spawned");
        Ok(Self {
            name,
            tx: req_tx,
            _child: child,
        })
    }

    /// Send an op to the worker and await the reply. Errors if the worker
    /// is gone (channel closed), if no reply lands inside `timeout_dur`,
    /// or if the worker returns an error envelope.
    pub async fn call(
        &self,
        op: &str,
        args: Value,
        timeout_dur: Duration,
    ) -> Result<Value, BridgeError> {
        let id = Uuid::new_v4().to_string();
        let (resp_tx, resp_rx) = oneshot::channel();
        let outgoing = OutgoingRequest {
            id: id.clone(),
            op: op.to_string(),
            args,
            resp_tx,
        };
        if self.tx.send(outgoing).await.is_err() {
            return Err(BridgeError::NotRunning);
        }
        let outcome = timeout(timeout_dur, resp_rx)
            .await
            .map_err(|_| BridgeError::Timeout(timeout_dur))?
            .map_err(|_| BridgeError::NotRunning)?;
        debug!(worker = self.name, id = %id, "call resolved");
        outcome
    }
}

async fn writer_task(
    name: &'static str,
    mut stdin: ChildStdin,
    mut rx: mpsc::Receiver<OutgoingRequest>,
    pending: Pending,
) {
    while let Some(req) = rx.recv().await {
        // Insert pending BEFORE sending so a fast reply can't race us.
        pending.lock().await.insert(req.id.clone(), req.resp_tx);

        let envelope = json!({
            "id": req.id,
            "op": req.op,
            "args": req.args,
        });
        let line = format!("{}\n", envelope);
        if let Err(err) = stdin.write_all(line.as_bytes()).await {
            error!(worker = name, %err, "writer io failed; dropping pending");
            // Drop the oneshot we just stashed so the caller fails fast.
            if let Some(tx) = pending.lock().await.remove(&req.id) {
                let _ = tx.send(Err(BridgeError::NotRunning));
            }
            break;
        }
        if let Err(err) = stdin.flush().await {
            warn!(worker = name, %err, "writer flush failed");
        }
    }
    info!(worker = name, "writer task exiting");
}

async fn reader_task(name: &'static str, stdout: ChildStdout, pending: Pending) {
    let mut lines = BufReader::new(stdout).lines();
    loop {
        let line = match lines.next_line().await {
            Ok(Some(l)) => l,
            Ok(None) => {
                info!(worker = name, "stdout closed, reader exiting");
                break;
            }
            Err(err) => {
                error!(worker = name, %err, "reader io error");
                break;
            }
        };
        let resp: Response = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(err) => {
                warn!(worker = name, %err, raw = %line, "skipping malformed line");
                continue;
            }
        };
        if let Some(log) = resp.log {
            match log.level.as_str() {
                "error" => error!(worker = name, child_msg = %log.message),
                "warn" => warn!(worker = name, child_msg = %log.message),
                _ => info!(worker = name, child_msg = %log.message),
            }
            continue;
        }
        let Some(id) = resp.id else {
            warn!(worker = name, raw = %line, "non-log line missing id");
            continue;
        };
        let Some(tx) = pending.lock().await.remove(&id) else {
            warn!(worker = name, id = %id, "no pending request for reply");
            continue;
        };
        let result = if let Some(err) = resp.error {
            Err(BridgeError::Worker {
                kind: err.kind,
                message: err.message,
            })
        } else {
            Ok(resp.result.unwrap_or(Value::Null))
        };
        // Receiver may have dropped (timeout) — that's fine, just discard.
        let _ = tx.send(result);
        debug!(worker = name, id = %id, "reply delivered");
    }
    // On reader exit (worker died), drain pending so no caller hangs.
    let mut map = pending.lock().await;
    for (_, tx) in map.drain() {
        let _ = tx.send(Err(BridgeError::NotRunning));
    }
}
