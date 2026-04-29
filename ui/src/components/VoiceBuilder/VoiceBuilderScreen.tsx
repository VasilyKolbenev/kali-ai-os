// ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { useBuilderStore } from "../../stores/builder";
import { VoiceOrb, type VoiceOrbState } from "./VoiceOrb";
import { LiveTranscript } from "./LiveTranscript";
import { SpecCard } from "./SpecCard";
import { WizardPrompt } from "./WizardPrompt";
import { PreviewConfirm } from "./PreviewConfirm";
import { StarterExamples } from "./StarterExamples";
import { useAudioCapture } from "./useAudioCapture";
import { useRmsVad } from "./useRmsVad";
import { parseVoiceCommand } from "./voiceCommands";

export function VoiceBuilderScreen() {
  const {
    phase,
    askingSubState,
    transcript,
    question,
    step,
    totalSteps,
    preview,
    partialSpec,
    error,
    tap,
    submitAudio,
    answer,
    cancel,
    deploy,
    editField,
    reset,
    setAskingSubState,
    start,
  } = useBuilderStore();

  const [showFallback, setShowFallback] = useState(false);
  const [textInput, setTextInput] = useState("");
  // Phase ref so the VAD onSilence closure (created once) reads current
  // phase without forcing the audio hook to re-create on every change.
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const askingSubStateRef = useRef(askingSubState);
  askingSubStateRef.current = askingSubState;

  // Stable callback — hoisted to avoid inline lambda causing WizardPrompt's
  // useEffect to re-fire (which would trigger multiple overlapping say() calls).
  const onTtsDone = useCallback(
    () => setAskingSubState("listening_for_answer"),
    [setAskingSubState],
  );

  // Single VAD — phase-aware dispatch in onSilence keeps the wiring
  // simple and avoids the parallel-VAD race that double-stops audio.
  const vad = useRmsVad({
    silenceMs: 1500,
    threshold: 0.01,
    onSilence: async () => {
      const captured = await audio.stop();
      if (!captured) return;
      const currentPhase = phaseRef.current;
      if (currentPhase === "listening") {
        await submitAudio(captured.audio, captured.sample_rate);
      } else if (
        currentPhase === "asking" &&
        askingSubStateRef.current === "listening_for_answer"
      ) {
        const text = await transcribeOnly(captured.audio, captured.sample_rate);
        if (!text) return;
        const cmd = parseVoiceCommand(text, { phase: "asking", knownFields: [] });
        if (cmd.intent === "cancel") void cancel();
        else if (cmd.intent === "answer") await answer(cmd.text);
      } else if (currentPhase === "previewing") {
        const text = await transcribeOnly(captured.audio, captured.sample_rate);
        if (!text) return;
        const known = preview ? Object.keys(preview.config ?? {}) : [];
        const cmd = parseVoiceCommand(text, { phase: "previewing", knownFields: known });
        if (cmd.intent === "confirm") void deploy();
        else if (cmd.intent === "cancel") void cancel();
        else if (cmd.intent === "edit") void editField(cmd.field);
      }
    },
  });

  // Audio capture wired to feed the single VAD via onFrame.
  const audio = useAudioCapture({ onFrame: vad.feed });

  // Ref to capture live isRecording state for unmount cleanup.
  const isRecordingRef = useRef(audio.isRecording);
  isRecordingRef.current = audio.isRecording;

  // Hook the orb tap → start/stop recording.
  const handleTap = async () => {
    if (phase === "idle") {
      try {
        await audio.start();
        tap();  // store transitions to listening
      } catch (e) {
        // permission denied → fallback path
        setShowFallback(true);
      }
    } else if (phase === "listening") {
      const captured = await audio.stop();
      if (!captured) return;
      tap();  // back to idle (cancel turn)
      // intentionally NOT submitting — tap-to-cancel behaviour
    }
  };

  // Cancel paths.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancel]);

  // Mode-switch / unmount cleanup — stop any in-flight recording so
  // the OS mic indicator doesn't stay lit when the user navigates away.
  useEffect(() => {
    return () => {
      if (isRecordingRef.current) {
        void audio.stop();
      }
    };
  }, []);

  // Map phase → orb state
  const orbState: VoiceOrbState =
    phase === "listening" || (phase === "asking" && askingSubState === "listening_for_answer")
      ? "listening"
      : phase === "transcribing" || phase === "extracting" || phase === "deploying"
      ? "processing"
      : "idle";

  return (
    <div className="voice-builder-screen" style={{ padding: 32, textAlign: "center" }}>
      <h2 style={{ color: "var(--j-text)" }}>Создать агента</h2>

      {error && (
        <div style={{ color: "var(--j-danger)", margin: 8 }}>{error}</div>
      )}

      {phase !== "previewing" && phase !== "done" && (
        <>
          <div style={{ display: "flex", justifyContent: "center", margin: 24 }}>
            <VoiceOrb state={orbState} onTap={handleTap} />
          </div>

          <LiveTranscript transcript={transcript} />

          {phase === "asking" && question && askingSubState === "tts_speaking" && (
            <WizardPrompt
              question={question}
              step={step}
              totalSteps={totalSteps}
              onTtsDone={onTtsDone}
            />
          )}

          {(phase === "asking" || phase === "listening" || phase === "transcribing" || phase === "extracting") && (
            <SpecCard spec={partialSpec ?? null} highlighted={false} />
          )}
        </>
      )}

      {phase === "previewing" && preview && (
        <PreviewConfirm spec={preview} />
      )}

      {phase === "done" && (
        <div>
          <p style={{ color: "var(--j-cyan)", fontSize: 18 }}>
            Агент готов. Попробуй: «{preview?.name}, начни»
          </p>
          <button onClick={reset} style={{ margin: 8 }}>Создать ещё</button>
        </div>
      )}

      {/* Fallback path */}
      {phase === "idle" && (
        <div style={{ marginTop: 24 }}>
          <button
            onClick={() => setShowFallback(!showFallback)}
            style={{
              background: "none",
              border: "none",
              color: "var(--j-text-dim)",
              fontSize: 12,
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            печатать вместо голоса
          </button>
          {showFallback && (
            <div style={{ marginTop: 12 }}>
              <input
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && textInput.trim()) {
                    void start(textInput);
                    setTextInput("");
                  }
                }}
                placeholder="напр. трекер воды каждые 2 часа"
                style={{
                  padding: 8,
                  borderRadius: 4,
                  border: "1px solid var(--j-border)",
                  background: "var(--j-bg)",
                  color: "var(--j-text)",
                  width: 320,
                }}
              />
              <StarterExamples onPick={(ex: string) => setTextInput(ex)} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Helper: transcribe a captured audio blob without going through submitAudio.
async function transcribeOnly(
  audio: Uint8Array,
  sample_rate: number,
): Promise<string> {
  const { builderApi } = await import("../../api/builder");
  let bin = "";
  for (let i = 0; i < audio.length; i++) bin += String.fromCharCode(audio[i]);
  const audio_b64 = btoa(bin);
  try {
    const r = await builderApi.transcribe(audio_b64, sample_rate, "ru");
    return r.text.trim();
  } catch {
    return "";
  }
}
