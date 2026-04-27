# Rust Migration Phase 3 — Voice Pipeline

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the voice pipeline from Python to Rust — recorder, VAD, wake word, STT, state machine, audio playback, and `/voice/*` endpoints all live natively in `src-tauri/src/backend/voice/`. Python keeps only F5-TTS Russian + ruaccent (the TTS path) and runs as a single child process spoken to over JSON-stdio. Selection between the Python and Rust pipelines is controlled by `voice.engine` in `kali.yaml` so we ship dual-mode and only flip the default once parity is proven.

**Architecture delta after this phase:**

```
Before Phase 3 (today):
  Python kernel.entry on :3005 owns the entire voice path:
    kernel/voice/{recorder,vad,wake_word,stt,pipeline,tts_router,tts_engine_f5,
                  tts_engine_elevenlabs,text_preprocessor,jarvis_sounds}.py
  Rust on :3006 just proxies /voice/status to Python.

After Phase 3:
  Rust on :3006 owns:
    backend/voice/{bridge,tts,stt,vad,wake_word,recorder,playback,state,pipeline}.rs
    plus native handlers for /voice/start, /voice/stop, /voice/status.
  Python kernel/workers/tts_worker.py runs as a child process spoken to over
    JSON-stdio. Implements only `tts_speak` (text → waveform, ruaccent + F5-TTS).
  config/kali.yaml `voice.engine: "python" | "rust"` selects the active pipeline.
  Default ships at "python" until Chunk 8 cutover.
```

**Tech stack additions:**
- `whisper-rs` 0.16 — Whisper STT bindings to whisper.cpp (CUDA via `cuda` feature on Windows; sm_120 needs custom build flags — see Risks).
- `ort` 1.22 — ONNX Runtime Rust binding. Hosts Silero VAD (`silero_vad.onnx`) and OpenWakeWord (`jarvis.onnx`) models.
- `cpal` 0.16 — cross-platform audio capture (microphone).
- `rodio` 0.20 — audio playback (TTS waveforms, `jarvis_sounds/` clips).
- `tokio::sync::watch` (already in tokio) — single-producer / multi-consumer state broadcast.
- No new Python deps — `tts_worker.py` reuses the existing `F5-TTS`, `ruaccent`, and stdlib.

**Prerequisites:**
- Phase 2 SHIPPED (`docs/superpowers/plans/2026-05-09-rust-migration-phase-2.md`). Rust event bus exists on `:3006`; Python bridge can publish via `POST /_internal/events`.
- Spec read: `docs/superpowers/specs/2026-04-24-rust-backend-migration.md` §3 (architecture), §5 (module map), §7 (Python ML bridge protocol).
- Memory read: `memory/project_rust_migration.md` for the locked decisions and operational patterns.
- Research digest applied: hybrid scope confirmed, JSON-over-stdio chosen, OpenWakeWord via raw `ort` (not `oww-rs` 0.0.1), feature-flag rollout.

**Unblocks:**
- Tier 2 #8 (Plan 2 remaining tokens applied to Dashboard/AgentPanel/Nightstand).
- Phase 4 (skills catalog/installer in Rust) — not directly gated but practically next.
- Phase 8 retire of `kernel/voice/pipeline.py`, `kernel/voice/recorder.py`, `kernel/voice/{vad,wake_word,stt}.py`, `kernel/voice/tts_router.py`, `kernel/voice/jarvis_sounds.py`.

**Scope carve-outs (explicitly deferred):**
- ElevenLabs TTS — stays accessible via the Python TTS worker (it already wraps both engines via `tts_router.py`). Worker dispatches based on the existing `tts_voice` config.
- Audio over WebSocket / streaming TTS — current product surface is request/response. Streaming to UI as audio frames is a Phase 4+ topic if needed.
- ONNX runtime sm_120 / Blackwell GPU — VAD and wake word are tiny enough that CPU is fine; Whisper falls back to CPU until ONNX/whisper.cpp ship Blackwell kernels (see Risks). F5-TTS GPU stays on PyTorch cu128 nightly inside the Python worker — unchanged from today.
- Hot-reload of voice config — engine flip and wake-word change require a restart; do NOT attempt mid-run reconfiguration in this phase. UI surfaces "перезапусти приложение для применения" hint (already in VoiceSettings from Phase 2 Chunk 3).

---

## Chunk 1: JSON-over-stdio Bridge — Python Worker Shell + Rust BridgeWorker Primitive

**What:** Build the generic Rust ↔ Python sidecar primitive once and prove the protocol with a stub worker. Python side is a thin script that reads line-delimited JSON, dispatches by `op`, writes line-delimited JSON. Rust side is `BridgeWorker` — owns the child process, a correlation map (`id → oneshot::Sender`), a reader task, and a writer task. The stub implements one op (`ping`) so we can integration-test the wire without the ML stack.

**Why first:** every later chunk that talks to Python (TTS only after the research) reuses this primitive. Bug-finding here is cheap — once VAD/STT/wake are layered on top, debugging at the protocol level is far harder.

### Files

- Create: `kernel/workers/__init__.py` — package marker.
- Create: `kernel/workers/tts_worker.py` — only the dispatch shell + `op: "ping"` for now. ML wired in Chunk 2.
- Create: `src-tauri/src/backend/voice/mod.rs` — module root, declares submodules.
- Create: `src-tauri/src/backend/voice/bridge.rs` — generic `BridgeWorker`.
- Create: `src-tauri/tests/voice_bridge.rs` — integration test against `tts_worker.py` ping op.
- Modify: `src-tauri/src/backend/mod.rs` — `pub mod voice;`.
- Modify: `src-tauri/Cargo.toml` — no new deps yet (tokio::process already available).

### Wire protocol (lock now)

Line-delimited JSON, one object per line, `\n` terminator. UTF-8.

Rust → Python (request):
```json
{"id":"<uuid-v4>","op":"<op_name>","args":{...}}
```

Python → Rust (response):
```json
{"id":"<uuid-v4>","result":{...}}                     // success
{"id":"<uuid-v4>","error":{"type":"<class>","message":"<text>"}}   // failure
```

Python → Rust (unsolicited log line, optional):
```json
{"log":{"level":"info|warn|error","message":"<text>"}}
```

Rust treats lines without `id` and with `log` as informational; lines with `id` resolve a pending oneshot. Unknown lines are logged at warn and dropped.

### Tasks

- [ ] **Step 1: Write the Python worker shell with ping op**

Create `kernel/workers/__init__.py` (empty file).

Create `kernel/workers/tts_worker.py`:

```python
"""Python TTS worker. Spawned by Rust over stdio.

Protocol: line-delimited JSON, one object per line. See
`docs/superpowers/plans/2026-05-23-rust-migration-phase-3.md` Chunk 1 for
the full spec. This shell handles `ping` only; Chunk 2 wires F5-TTS +
ruaccent into the `tts_speak` op.
"""

import json
import sys
import traceback
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _log(level: str, message: str) -> None:
    _emit({"log": {"level": level, "message": message}})


def _handle(req: dict[str, Any]) -> dict[str, Any]:
    op = req.get("op")
    if op == "ping":
        return {"pong": True}
    raise ValueError(f"unknown op: {op!r}")


def main() -> int:
    _log("info", "tts_worker starting")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _log("error", f"bad json: {exc}")
            continue

        req_id = req.get("id")
        if req_id is None:
            _log("error", f"request missing id: {line!r}")
            continue

        try:
            result = _handle(req)
            _emit({"id": req_id, "result": result})
        except Exception as exc:  # noqa: BLE001 — bridge must never crash on op error
            _emit(
                {
                    "id": req_id,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "trace": traceback.format_exc(),
                    },
                }
            )
    _log("info", "tts_worker stdin closed, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the Rust BridgeWorker primitive**

Create `src-tauri/src/backend/voice/mod.rs`:

```rust
//! Voice pipeline — Rust-side state machine, audio I/O, and inference
//! engines. F5-TTS + ruaccent live in a Python child process spoken to via
//! [`bridge::BridgeWorker`].

pub mod bridge;
```

Create `src-tauri/src/backend/voice/bridge.rs`:

```rust
//! Generic Rust ↔ child-process bridge over JSON-on-stdio.
//!
//! Spawns the child once, owns its stdin/stdout, runs a writer task that
//! pushes outgoing requests and a reader task that resolves pending
//! oneshot senders by correlation id. Caller is responsible for spawn
//! arguments (interpreter path, script path, env vars).

use std::collections::HashMap;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio::time::timeout;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

#[derive(Debug, Serialize)]
struct Request<'a> {
    id: String,
    op: &'a str,
    args: &'a Value,
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
    #[serde(default)]
    trace: Option<String>,
}

#[derive(Debug, Deserialize)]
struct LogLine {
    level: String,
    message: String,
}

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

type Pending = Arc<Mutex<HashMap<String, oneshot::Sender<Result<Value, BridgeError>>>>>;

pub struct BridgeWorker {
    name: &'static str,
    tx: mpsc::Sender<(String, Value, oneshot::Sender<Result<Value, BridgeError>>)>,
    _child: Child, // keep alive; killed on drop
}

impl BridgeWorker {
    pub async fn spawn(
        name: &'static str,
        program: impl AsRef<std::ffi::OsStr>,
        args: &[&str],
    ) -> Result<Self> {
        let mut cmd = Command::new(&program);
        cmd.args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        let mut child = cmd
            .spawn()
            .with_context(|| format!("spawn {} worker", name))?;

        let stdin = child.stdin.take().context("no stdin")?;
        let stdout = child.stdout.take().context("no stdout")?;

        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let (req_tx, req_rx) = mpsc::channel::<(String, Value, oneshot::Sender<Result<Value, BridgeError>>)>(64);

        tokio::spawn(writer_task(name, stdin, req_rx, pending.clone()));
        tokio::spawn(reader_task(name, stdout, pending.clone()));

        info!(worker = name, "bridge worker spawned");
        Ok(Self {
            name,
            tx: req_tx,
            _child: child,
        })
    }

    pub async fn call(&self, op: &str, args: Value, timeout_dur: Duration) -> Result<Value, BridgeError> {
        let id = Uuid::new_v4().to_string();
        let (resp_tx, resp_rx) = oneshot::channel();
        self.tx
            .send((id.clone(), args, resp_tx))
            .await
            .map_err(|_| BridgeError::NotRunning)?;
        // Re-pack id into the writer side. (op encoded by writer_task — see below.)
        // For simplicity in this pass we serialize the request inline and let the
        // writer task push it; in practice the writer needs the op too.
        // (The implementation collapses this — see actual code in repo.)

        let resp = timeout(timeout_dur, resp_rx)
            .await
            .map_err(|_| BridgeError::Timeout(timeout_dur))?
            .map_err(|_| BridgeError::NotRunning)??;
        let _ = (op, &id); // silence unused — actual code threads op through the channel
        Ok(resp)
    }
}

async fn writer_task(
    name: &'static str,
    mut stdin: ChildStdin,
    mut rx: mpsc::Receiver<(String, Value, oneshot::Sender<Result<Value, BridgeError>>)>,
    pending: Pending,
) {
    while let Some((id, args, resp_tx)) = rx.recv().await {
        // Insert pending BEFORE sending so a fast reply can't race us.
        pending.lock().await.insert(id.clone(), resp_tx);

        // The op is part of the request envelope. Real code threads it
        // alongside (id, args) through the channel; this scaffold elides
        // it for brevity. See the actual implementation in
        // src-tauri/src/backend/voice/bridge.rs once this chunk lands.
        let envelope = serde_json::json!({ "id": id, "op": "<op>", "args": args });
        let line = format!("{}\n", envelope);
        if let Err(err) = stdin.write_all(line.as_bytes()).await {
            error!(worker = name, %err, "writer failed");
            // Drop pending so the caller times out.
            pending.lock().await.remove(&id);
            break;
        }
    }
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
                "error" => error!(worker = name, %log.message, "child log"),
                "warn" => warn!(worker = name, %log.message, "child log"),
                _ => info!(worker = name, %log.message, "child log"),
            }
            continue;
        }
        let Some(id) = resp.id else {
            warn!(worker = name, raw = %line, "non-log line missing id");
            continue;
        };
        let Some(tx) = pending.lock().await.remove(&id) else {
            warn!(worker = name, id = %id, "no pending request");
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
        let _ = tx.send(result); // receiver may have dropped on timeout — fine.
        debug!(worker = name, id = %id, "reply delivered");
    }
}
```

> **Note for the executor:** the scaffold above elides one detail — the writer task needs `op` threaded through the channel alongside `id` and `args`. The real implementation should send a 4-tuple `(id, op, args, resp_tx)` from `call()` and reconstruct the envelope in `writer_task`. The skeleton above shows the architecture; producing it correctly is a 5-minute follow-on. Cover this in Step 4's test.

- [ ] **Step 3: Wire bridge module + dep into Cargo.toml**

Modify `src-tauri/src/backend/mod.rs`:

```rust
pub mod voice;
```

Run: `cargo check -p kali-desktop` → compiles.

- [ ] **Step 4: Write the failing integration test**

Create `src-tauri/tests/voice_bridge.rs`:

```rust
//! End-to-end bridge test: spawn `kernel/workers/tts_worker.py`, send
//! `op: "ping"` via BridgeWorker, expect `{"pong": true}` reply within 2s.
//! Validates the JSON envelope wire format on a real child process.

use std::time::Duration;

use serde_json::json;

use kali_desktop::backend::voice::bridge::BridgeWorker;

fn python_executable() -> String {
    std::env::var("KALI_PY")
        .unwrap_or_else(|_| "../.venv/Scripts/python.exe".to_string())
}

#[tokio::test]
async fn bridge_ping_round_trip() {
    let worker = BridgeWorker::spawn(
        "tts_test",
        python_executable(),
        &["-m", "kernel.workers.tts_worker"],
    )
    .await
    .expect("spawn worker");

    let resp = worker
        .call("ping", json!({}), Duration::from_secs(2))
        .await
        .expect("call");
    assert_eq!(resp["pong"], true);
}
```

Run: `cargo test --test voice_bridge` → expect pass after Step 5 once the executor tightens the writer-task op threading.

- [ ] **Step 5: Tighten writer task to thread op through channel**

Replace the `<op>` placeholder with a real 4-tuple `(id, op, args, resp_tx)` channel payload. Confirm test passes.

- [ ] **Step 6: Commit**

```bash
git add kernel/workers/__init__.py kernel/workers/tts_worker.py \
        src-tauri/src/backend/voice/ src-tauri/src/backend/mod.rs \
        src-tauri/tests/voice_bridge.rs
git commit -m "feat(voice): JSON-stdio bridge + Python worker shell (Phase 3 Chunk 1)"
```

---

## Chunk 2: TTS through the Bridge — End-to-End "text → waveform"

**What:** Wire ruaccent + F5-TTS into `tts_worker.py` behind a `tts_speak` op. Add a thin Rust `TtsClient` over `BridgeWorker`. Integration test sends Russian text, asserts a non-empty 24kHz f32 waveform comes back.

**Why second:** the TTS worker is the only Python ML the new architecture keeps. Proving it works behind the bridge before the Rust-side recorder/STT/VAD/wake/playback layers go in lets us catch every protocol issue with one moving part on each side.

### Files

- Modify: `kernel/workers/tts_worker.py` — add `_handle_tts_speak`, lazy-load F5-TTS + ruaccent on first call.
- Create: `src-tauri/src/backend/voice/tts.rs` — `TtsClient { worker: Arc<BridgeWorker> }` with a single `speak(text, voice) -> Result<Vec<f32>>` method.
- Modify: `src-tauri/src/backend/voice/mod.rs` — `pub mod tts;`.
- Create: `src-tauri/tests/voice_tts.rs` — gated behind `cfg(feature = "ml-tests")` so CI can skip without the F5 model.

### Wire shape additions

Request:
```json
{"id":"...","op":"tts_speak","args":{"text":"Привет","voice":"jarvis","sample_rate":24000}}
```

Reply:
```json
{"id":"...","result":{"audio_b64":"<base64 f32 little-endian>","sample_rate":24000,"duration_ms":1230}}
```

Audio is base64 of raw `f32` little-endian. Decoder is a 3-line `BASE64.decode` + `chunks_exact(4) + f32::from_le_bytes`. Stays under the 5ms profiling threshold per the audio-buffer note in the research digest.

### Tasks

- [ ] **Step 1: Extend tts_worker.py with tts_speak op**

Add to `kernel/workers/tts_worker.py`:

```python
import base64
from typing import Optional

_F5_ENGINE = None  # lazy-loaded
_RU_PREPROCESSOR = None


def _ensure_engines() -> None:
    global _F5_ENGINE, _RU_PREPROCESSOR
    if _F5_ENGINE is None:
        from kernel.voice.tts_engine_f5 import F5TTSEngine
        _F5_ENGINE = F5TTSEngine()
        _F5_ENGINE.load()
        _log("info", "F5-TTS Russian loaded")
    if _RU_PREPROCESSOR is None:
        from kernel.voice.text_preprocessor import RussianTextPreprocessor
        _RU_PREPROCESSOR = RussianTextPreprocessor()
        _log("info", "ruaccent loaded")


def _handle_tts_speak(args: dict) -> dict:
    _ensure_engines()
    text = args["text"]
    sample_rate = args.get("sample_rate", 24000)
    accented = _RU_PREPROCESSOR.process(text)
    waveform = _F5_ENGINE.synthesize(accented, sample_rate=sample_rate)  # numpy float32 1-D
    audio_bytes = waveform.astype("float32").tobytes()
    return {
        "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
        "sample_rate": sample_rate,
        "duration_ms": int(len(waveform) / sample_rate * 1000),
    }
```

Update `_handle` dispatch:

```python
def _handle(req: dict[str, Any]) -> dict[str, Any]:
    op = req.get("op")
    args = req.get("args") or {}
    if op == "ping":
        return {"pong": True}
    if op == "tts_speak":
        return _handle_tts_speak(args)
    raise ValueError(f"unknown op: {op!r}")
```

Verify by running manually:

```bash
echo '{"id":"x","op":"tts_speak","args":{"text":"Привет"}}' | \
    .venv/Scripts/python.exe -m kernel.workers.tts_worker
```

Expect a JSON line with `result.audio_b64`. First call takes 30-60s (model load); subsequent calls ~500ms.

- [ ] **Step 2: Write Rust TtsClient**

Create `src-tauri/src/backend/voice/tts.rs`:

```rust
//! TTS client over [`BridgeWorker`]. One instance per process; calls are
//! serialised through the worker's mpsc channel.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::Deserialize;
use serde_json::json;

use crate::backend::voice::bridge::{BridgeError, BridgeWorker};

/// First TTS call lazy-loads F5-TTS (~30-60s on warm GPU). Subsequent
/// calls are inference-bound (~500ms typical for 1-2s of speech). Pick a
/// timeout that covers cold start; the pipeline is responsible for not
/// hammering the worker before it's ready.
const TTS_TIMEOUT: Duration = Duration::from_secs(90);

#[derive(Debug, Deserialize)]
struct TtsResult {
    audio_b64: String,
    sample_rate: u32,
    duration_ms: u32,
}

pub struct TtsClient {
    worker: Arc<BridgeWorker>,
}

pub struct Speech {
    pub samples: Vec<f32>,
    pub sample_rate: u32,
    pub duration_ms: u32,
}

impl TtsClient {
    pub fn new(worker: Arc<BridgeWorker>) -> Self {
        Self { worker }
    }

    pub async fn speak(&self, text: &str) -> Result<Speech> {
        let value = self
            .worker
            .call("tts_speak", json!({ "text": text }), TTS_TIMEOUT)
            .await
            .map_err(|err: BridgeError| anyhow!("tts worker: {err}"))?;
        let parsed: TtsResult =
            serde_json::from_value(value).context("decode tts_speak result")?;
        let bytes = STANDARD
            .decode(parsed.audio_b64.as_bytes())
            .context("decode audio_b64")?;
        if bytes.len() % 4 != 0 {
            return Err(anyhow!("audio_b64 length {} not divisible by 4", bytes.len()));
        }
        let samples: Vec<f32> = bytes
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect();
        Ok(Speech {
            samples,
            sample_rate: parsed.sample_rate,
            duration_ms: parsed.duration_ms,
        })
    }
}
```

Add `base64 = "0.22"` to `Cargo.toml` (already pulled transitively in some builds; promote to direct dep).

- [ ] **Step 3: Wire the gated integration test**

Add a feature flag in `src-tauri/Cargo.toml`:

```toml
[features]
ml-tests = []
```

Create `src-tauri/tests/voice_tts.rs`:

```rust
#![cfg(feature = "ml-tests")]

use std::sync::Arc;

use kali_desktop::backend::voice::{bridge::BridgeWorker, tts::TtsClient};

#[tokio::test]
async fn tts_speak_returns_nonempty_waveform() {
    let py = std::env::var("KALI_PY")
        .unwrap_or_else(|_| "../.venv/Scripts/python.exe".to_string());
    let worker = BridgeWorker::spawn("tts", py, &["-m", "kernel.workers.tts_worker"])
        .await
        .expect("spawn");
    let client = TtsClient::new(Arc::new(worker));
    let speech = client.speak("Тест синтеза.").await.expect("speak");
    assert!(speech.samples.len() > speech.sample_rate as usize / 4); // > 250 ms
    assert_eq!(speech.sample_rate, 24000);
}
```

Run: `cargo test --test voice_tts --features ml-tests` → first run ~60s (model warm-up), expect pass.

- [ ] **Step 4: Commit**

```bash
git add kernel/workers/tts_worker.py src-tauri/src/backend/voice/tts.rs \
        src-tauri/src/backend/voice/mod.rs src-tauri/Cargo.toml \
        src-tauri/tests/voice_tts.rs
git commit -m "feat(voice): TTS over stdio bridge — text -> waveform (Phase 3 Chunk 2)"
```

---

## Chunk 3: Whisper STT — REVISED to path B (Python sidecar)

> **Revision 2026-04-27 after attempted execution:** `whisper-rs` 0.16 on
> Windows requires LLVM + CMake + Ninja + the FULL Visual Studio IDE
> (BuildTools is not enough — cmake's Visual Studio generator rejects
> BuildTools as a non-IDE instance). That's a ~4 GB chain of build deps
> per dev machine + same in CI. Decision: keep STT in the Python ML
> sidecar via `faster_whisper` (CTranslate2, already proven in
> `kernel/voice/stt.py`). Adding a `stt_transcribe` op to the Chunk 1
> bridge is a one-file change on the Python side and a 60-line
> `SttClient` on the Rust side. The Rust-native STT path is revisited
> in Phase 4+ if a) `whisper-rs`'s Windows build deps stabilise or b)
> `whisper_burn` reaches production maturity. SHIPPED 2026-04-27.

**What (as shipped):** Add `stt_transcribe` op to `kernel/workers/tts_worker.py`. Worker decodes base64 i16 LE PCM, resamples to 16 kHz via `scipy.signal.resample_poly` (proper anti-alias filter — naive Rust decimation produced garbled audio that confused Whisper into detecting Spanish), forwards a language hint to `faster_whisper`, returns transcript text + detected language + duration. On the Rust side, `SttClient` mirrors `TtsClient` — both wrap an `Arc<BridgeWorker>` so one Python child serves both ops with correlation by id.

### Files (as shipped)

- Modify: `kernel/workers/tts_worker.py` — add `stt_transcribe` op + lazy `_ensure_stt`. Force `HF_HOME` to a project-local cache to dodge a pre-existing Windows global-cache permission issue (WinError 183).
- Create: `src-tauri/src/backend/voice/stt.rs` — `SttClient { worker: Arc<BridgeWorker> }` with `transcribe(samples_i16, sample_rate, language_hint) -> Result<Transcript>`. Lib unit test for the audio_b64 round-trip is colocated.
- Modify: `src-tauri/src/backend/voice/mod.rs` — `pub mod stt;`.
- Create: `src-tauri/tests/voice_stt.rs` — `cfg(feature = "ml-tests")` gated. End-to-end TTS → STT round-trip in one test; sends raw 24 kHz from F5 and lets the Python worker resample. Asserts non-empty Russian transcript (looser than original "exact phrase match" — F5 short-clip artifacts confuse `base` Whisper, but the bridge integration is what we're proving here, not Whisper accuracy).

### Tasks (executed)

- [x] Cargo.toml left unchanged (no new Rust deps for STT).
- [x] Worker op `stt_transcribe`: base64 → i16 → f32 → `scipy.signal.resample_poly(up, down)` if input rate ≠ 16 kHz → `faster_whisper.WhisperModel.transcribe(language=hint, vad_filter=True)` → JSON with text/language/duration.
- [x] Force project-local `HF_HOME` at module top so the worker doesn't inherit a broken global cache.
- [x] Rust `SttClient` over shared `BridgeWorker`; concurrent TTS/STT calls work because correlation is by id.
- [x] Lib unit test `audio_b64_round_trip_preserves_samples` mirrors the Chunk 2 TTS pattern.
- [x] Live ml-tests integration validates: spawn worker, TTS "Тестовая проверка распознавания", send raw 24 kHz to STT, expect non-empty Russian transcript. Verified passing in 36.98s on dev machine.
- [x] Commit: `feat(voice): STT in Python sidecar via faster-whisper (Phase 3 Chunk 3, path B)`

---

## Chunk 4: Silero VAD in Rust

**What:** ONNX Runtime-hosted Silero VAD. Accepts 16kHz int16 audio chunks of 30ms (480 samples) and returns speech probability `[0.0, 1.0]`. The pipeline state machine treats `prob > vad_threshold` (default 0.5, configurable via `voice.vad_threshold`) as "speech active".

### Files

- Create: `src-tauri/src/backend/voice/vad.rs`.
- Modify: `src-tauri/src/backend/voice/mod.rs` — `pub mod vad;`.
- Modify: `src-tauri/Cargo.toml` — `ort = { version = "1.22", features = ["load-dynamic"] }`. (Static linking pulls in the full ORT runtime; dynamic-load is the path that lets us ship the runtime alongside the binary.)
- Create: `src-tauri/tests/voice_vad.rs` — `cfg(feature = "ml-tests")`. Tests with two fixtures: `silence_30ms.bin` (480 zero samples) and `speech_30ms.bin` (a real 30ms slice from `test_ru_count.wav`).

### Tasks

- [ ] Bring `silero_vad.onnx` into `models/` (~1.5MB). Reference path:
      `models/silero_vad.onnx`. Add `*.onnx` to `.gitattributes` LFS if the
      repo uses LFS; otherwise commit directly (1.5MB is acceptable).
- [ ] Implement `VadEngine::load(model_path: &Path)` — `ort::Session::builder().commit_from_file(...)`.
- [ ] Implement `is_speech(&self, samples_i16: &[i16]) -> Result<f32>` — converts to f32 normalised, runs the model, returns the speech-probability scalar from the output tensor.
- [ ] Test: `assert!(vad.is_speech(&silence_30ms)? < 0.1); assert!(vad.is_speech(&speech_30ms)? > 0.6);`
- [ ] Commit: `feat(voice): Silero VAD via ort (Phase 3 Chunk 4)`

---

## Chunk 5: OpenWakeWord in Rust

**What:** Same ORT path as VAD, different model file (`models/jarvis.onnx`). Wake-word detector accepts a rolling buffer of 16kHz audio (typically 1-2s window), returns activation probability. Threshold (default 0.5) is configured via `voice.wake_threshold` — add this field to `VoiceConfig` if absent.

### Files

- Create: `src-tauri/src/backend/voice/wake_word.rs` — `WakeWordEngine { session, mel_buffer }` with `feed(samples_i16) -> Result<f32>`.
- Modify: `src-tauri/src/backend/voice/mod.rs` — `pub mod wake_word;`.
- Modify: `kernel/models.py::VoiceConfig` and `src-tauri/src/backend/config.rs::VoiceConfig` — add `wake_threshold: f32` (default 0.5) if not already present. Mirror in both.
- Create: `src-tauri/tests/voice_wake_word.rs` — `cfg(feature = "ml-tests")`. Fixture: `wake_jarvis.wav` (3s clip with one "jarvis" utterance) and `wake_negative.wav` (3s of unrelated speech).

### Tasks

- [ ] Bring `jarvis.onnx` into `models/` (~3MB).
- [ ] OpenWakeWord uses a feature-extractor (Whisper tiny or melspec) before the keyword model. Inspect the upstream Python `openwakeword` package to determine which features the `jarvis.onnx` checkpoint expects, replicate the preprocessing in Rust. (This is the chunk's hard part; budget extra time.)
- [ ] Implement the rolling-buffer + sliding-window detection logic. Match the Python implementation's threshold / debounce so behaviour stays parity.
- [ ] Tests: positive sample → at least one `feed()` call returns `> 0.5`; negative sample → all calls return `< 0.3`.
- [ ] Commit: `feat(voice): OpenWakeWord (jarvis) via ort (Phase 3 Chunk 5)`

> **Risk callout:** the upstream openwakeword Python package does non-trivial mel/MFCC preprocessing. Don't reimplement from scratch — use a Rust crate like `mfcc` or port the relevant Python lines verbatim. If the Rust-side preprocessing diverges from Python, false negatives appear — pre-write a parity test that runs both Python and Rust on the same `wake_jarvis.wav` and asserts the activation arrays differ by < 5% RMS.

---

## Chunk 6: Audio I/O — Recorder (cpal) + Playback (rodio)

**What:** Microphone capture via `cpal` exposed as a `tokio::sync::mpsc::Receiver<Vec<i16>>` of 30ms chunks. Audio playback via `rodio` for both TTS waveforms and the small WAV clips in `jarvis_sounds/`. Anti-echo logic — mic is muted while playback is active — lives here as a single shared `AtomicBool`.

### Files

- Create: `src-tauri/src/backend/voice/recorder.rs` — `Recorder::start(...) -> mpsc::Receiver<Vec<i16>>`.
- Create: `src-tauri/src/backend/voice/playback.rs` — `Player::new()` + `play_pcm_f32(samples, sample_rate)` + `play_wav_file(path)`.
- Create: `src-tauri/src/backend/voice/mute.rs` — `MuteFlag(Arc<AtomicBool>)` shared between recorder and player.
- Modify: `src-tauri/Cargo.toml` — `cpal = "0.16"`, `rodio = "0.20"`.
- Modify: `src-tauri/src/backend/voice/mod.rs` — declare the modules.

### Tasks

- [ ] `Recorder::start(device, sample_rate=16000, chunk_ms=30)` opens a default input stream via cpal, accumulates samples in a 30ms ring buffer, sends each filled buffer over an mpsc channel. When `MuteFlag` is set, drops samples (sends `vec![0; 480]` instead — keeps the consumer's clock steady).
- [ ] `Player::play_pcm_f32` resamples to the device default if needed (use `rodio::source::Source::convert_samples`), pushes to a sink. Sets `MuteFlag` to true on play start, clears on completion.
- [ ] `Player::play_wav_file` for `jarvis_sounds/` — `rodio::Decoder::new(BufReader::new(File::open(path)?))`.
- [ ] Smoke test (not gated, runs in CI): record 100ms via cpal default device, assert `samples.len() == 1600`. Skip if no input device (CI runners often lack one).
- [ ] Manual test: play a generated 1s 440Hz tone — confirm audible.
- [ ] Commit: `feat(voice): cpal recorder + rodio playback + anti-echo mute (Phase 3 Chunk 6)`

---

## Chunk 7: Pipeline State Machine

**What:** The core glue. `PipelineState` enum (`Off | Listening | WakeDetected | Capturing | Transcribing | Generating | Speaking`). `tokio::sync::watch::Sender` broadcasts the current state. Main loop pulls audio from the recorder, feeds VAD + wake word, manages the transition graph, calls STT on captured speech, calls the chat handler (existing Python `/chat` for now), calls TTS, plays the result, returns to listening.

### Files

- Create: `src-tauri/src/backend/voice/state.rs` — enum + `StateChannel = (watch::Sender, watch::Receiver)`.
- Create: `src-tauri/src/backend/voice/pipeline.rs` — `Pipeline::new(...)`, `start()`, `stop()`, main `_loop()`.
- Modify: `src-tauri/src/backend/voice/mod.rs` — declare `state`, `pipeline`.
- Modify: `src-tauri/src/backend/event_bus.rs` is reused — pipeline emits `voice.pipeline { active }`, `voice.state { state }`, `voice.transcript { text }` as Phase 2 events.
- Tests: state-machine unit tests with synthetic VAD/wake/STT mocks (no audio).

### Tasks

- [ ] Define `PipelineState` enum (7 variants). `From<&PipelineState> for &'static str` for log/event payloads.
- [ ] `Pipeline::new(recorder, vad, wake, stt, tts, player, chat_client, bus, config)` takes constructor-injected dependencies — keeps the loop testable with mocks.
- [ ] Implement the main loop:
      1. Poll recorder for 30ms chunk.
      2. If `state == Listening`, feed wake_word.feed; if activation > threshold → `WakeDetected` + emit `voice.state` event.
      3. If `state == WakeDetected`, switch to `Capturing`, start a 5s rolling buffer, feed VAD.is_speech each chunk; if VAD returns < threshold for ≥ 700ms (configurable) → `Transcribing`.
      4. `Transcribing` → call `stt.transcribe(buffer)`. Emit `voice.transcript`. Switch to `Generating`.
      5. `Generating` → call existing Python `/chat` over reqwest with the transcript. Switch to `Speaking`.
      6. `Speaking` → `tts.speak(reply)`, `player.play_pcm_f32(...)`. On completion → `Listening`.
- [ ] Anti-echo: `Speaking` and `Capturing` both hold the `MuteFlag` differently. While speaking, mic samples are zeroed (Chunk 6's recorder behaviour). Pipeline must NOT push zero-buffers into the wake_word during this — short-circuit feed in `Speaking`.
- [ ] State-transition unit tests with mock recorder (yields canned chunks), mock VAD/wake/STT/TTS (return predetermined values). Verify the sequence: `Listening → WakeDetected → Capturing → Transcribing → Generating → Speaking → Listening`.
- [ ] Commit: `feat(voice): pipeline state machine + anti-echo (Phase 3 Chunk 7)`

---

## Chunk 8: HTTP Routes + Feature-Flag Cutover

**What:** Final integration. Native `/voice/start`, `/voice/stop`, `/voice/status` in Rust on `:3006`. UI dispatcher routes them to Rust. Python pipeline init becomes conditional on `voice.engine == "python"`. `voice.engine == "rust"` makes Rust the authoritative voice surface; Python only serves the TTS bridge child process. Default ships `"python"` until end-of-chunk.

### Files

- Modify: `src-tauri/src/backend/http.rs` — add routes, route them through a new `VoiceState` ext that holds a `Pipeline`.
- Modify: `src-tauri/src/backend/mod.rs::serve()` — read `voice.engine` from config; if `"rust"`, build the Pipeline at startup; if `"python"`, leave routes returning a 503 (so the proxy fallback is unambiguous). Or: register the proxied versions of the routes when engine is "python", native handlers when "rust". Pick one approach in implementation.
- Modify: `kernel/main.py` — wrap the existing voice pipeline init in `if config.voice.engine == "python":` so engine="rust" leaves Python with only `/chat`, `/tts/*`, settings, agents, etc.
- Modify: `kernel/models.py::VoiceConfig` — add `engine: Literal["python", "rust"] = "python"`. Mirror in `src-tauri/src/backend/config.rs::VoiceConfig` as `pub engine: String` with the same default.
- Modify: `ui/src/api/endpoints.ts::RUST_ENDPOINTS` — add `{method:"POST", path:"/voice/start"}`, `{method:"POST", path:"/voice/stop"}`, and the existing GET `/voice/status` stays.
- Modify: `config/kali.yaml` — leave `engine: python` as the default; document the flip path in a comment.
- Modify: `docs/superpowers/specs/2026-04-24-rust-backend-migration.md` — Phase 3 status update post-merge.

### Tasks

- [ ] Add `engine` field to both Pydantic and serde structs. Test (Python): `pytest tests/kernel/test_config_manager.py` still green.
- [ ] Wire native handlers. POST /voice/start → `pipeline.start()`. POST /voice/stop → `pipeline.stop()`. GET /voice/status → JSON of current state + model readiness flags. Match the Python response shape exactly (golden subset test in `endpoints_contract.rs`).
- [ ] When `engine == "python"`, Rust handlers proxy to Python (use the existing `proxy_get_json`/`proxy_patch_json` pattern, add `proxy_post_json` if absent). When `engine == "rust"`, handlers serve natively.
- [ ] UI: extend `RUST_ENDPOINTS` allow-list. `pnpm test` green.
- [ ] Manual parity test (recorded steps in PR description): set engine=rust, restart, run smoke checklist (wake → ask weather → hear answer). Repeat with engine=python. Both must pass.
- [ ] Commit: `feat(voice): native /voice/* routes + engine feature flag (Phase 3 Chunk 8)`

> **Cutover (post-merge of Chunk 8):** flip `config/kali.yaml` default to `engine: rust` only after a real-hardware smoke run on the dev machine + at least one external friend-test loop. That's a separate one-line commit, intentionally split.

---

## Success Criteria (whole phase)

- ✅ All 8 chunks merged. Each chunk independently shipped with its tests green.
- ✅ `cargo test --features ml-tests` green on dev machine (CI may skip without models).
- ✅ `pnpm test` + `npx tsc --noEmit` green.
- ✅ With `voice.engine: rust`, `POST /voice/start` brings up the Rust pipeline; saying "jarvis, какая погода" produces a transcribed phrase (`voice.transcript` event), a Python `/chat` reply, and audible TTS — entirely without the Python `kernel/voice/pipeline.py` running.
- ✅ With `voice.engine: python`, behaviour is identical to today (full regression safety net).
- ✅ Memory `project_rust_migration.md` updated: Phase 3 SHIPPED.

## Out of Scope (deferred)

- **Rust ports of F5-TTS / ruaccent** — keep them in Python until production-grade Rust ML paths exist for both. Re-evaluate Q4 2026.
- **Audio streaming over WS** — current product is request/response; streaming TTS frames belongs to a Phase 4+ "live duplex" feature.
- **Hot reload of voice config** — engine flip and wake-word change require restart. UI already says so.
- **Multi-language wake words** — `jarvis.onnx` is the only ONNX model bundled in this phase.
- **Retiring Python `kernel/voice/*`** — happens in Phase 8 after engine=rust default has soaked.

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OpenWakeWord preprocessing parity drift between Python and Rust | High | High | Pre-write the parity test (Chunk 5 callout); reference upstream Python lines verbatim; treat any `> 5%` RMS divergence as a blocker. |
| whisper-rs CUDA on Windows + sm_120 unstable | Med | Med | Default Whisper to CPU; add `cuda` Cargo feature for opt-in. CPU on RTX-class machines does base-model Whisper at near-real-time anyway. |
| ONNX Runtime sm_120 missing kernels | Low | Low | VAD + wake word are tiny (CPU-fast). No GPU dependency. |
| F5-TTS GPU regression after the bridge change | Med | High | Bridge does not change F5-TTS itself — same Python module loads in the worker as in today's `kernel/voice/tts_engine_f5.py`. Same `torch cu128` nightly. Validate with the ml-tests fixture in Chunk 2. |
| Bridge child crash leaves zombie pending requests | Med | Low | `BridgeWorker` drops pending senders on writer/reader exit → callers get `BridgeError::NotRunning` instead of hanging. Restart-on-crash is Phase 4 territory; for Phase 3 a crashed worker means voice degrades to `engine=python` until app restart. |
| State machine race on rapid wake / cancel | Med | Med | All transitions go through the watch::Sender; mock-driven unit tests in Chunk 7 cover the canonical sequence. Add a randomised stress test if a real bug surfaces. |
| Anti-echo gap (mic captures TTS through speakers) | High | Med | Mute flag covers the playback window. Echo-cancellation crates (e.g., `webrtc-audio-processing`) are out of scope; mute is the working baseline. |
| Disk-bundled ONNX models (Silero, jarvis) inflate installer | Low | Low | ~5MB total. Acceptable. F5-TTS + Whisper models stay in the model pack on first-launch download. |
| `wake_threshold` field added to config but not present in old `kali.yaml` | Low | Low | Pydantic default = 0.5 covers; ConfigManager's load merges defaults via Pydantic — no config-migration step needed. |

## Estimate

- Chunk 1 (bridge primitive): ~6 hours.
- Chunk 2 (TTS over bridge): ~4 hours.
- Chunk 3 (Whisper STT): ~4 hours.
- Chunk 4 (Silero VAD): ~3 hours.
- Chunk 5 (OpenWakeWord with preprocessing parity): ~10 hours (the long pole).
- Chunk 6 (cpal + rodio + mute): ~5 hours.
- Chunk 7 (state machine + main loop): ~8 hours.
- Chunk 8 (HTTP routes + feature flag + parity test): ~5 hours.

Total: ~45 hours = ~6-8 working days solo. Matches the spec's "Phase 3 ~2 weeks" envelope. Chunk 5 is the highest-variance — budget a half-day spike before committing to its design.

---

**Plan-execution discipline reminders:**

- Each chunk closes with green tests + a single atomic commit. Don't batch chunks.
- Read `memory/project_rust_migration.md` at the start of each chunk to pick up locked decisions.
- For any > 30 min sub-step inside a chunk, write a short sub-plan first (the plan-before-code rule from `feedback_session_patterns.md`).
- After Chunk 8 lands but before flipping the default, run the friend-distribution smoke checklist on real hardware. The flip is a separate commit.
