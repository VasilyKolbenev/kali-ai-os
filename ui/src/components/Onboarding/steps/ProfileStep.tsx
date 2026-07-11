import { useEffect, useState } from "react";
import { Mic, Square } from "lucide-react";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { api } from "../../../api/client";
import { FadeSlideUp } from "../../../motion";
import { useAudioCapture } from "../../VoiceBuilder/useAudioCapture";

type Gender = "male" | "female";
type TextField = "name" | "city" | "occupation";

const OCCUPATION_CHIPS = ["Строитель", "Врач", "Офис", "Учитель"];
const AGE_RANGES = ["18-25", "26-35", "36-45", "46-55", "55+"];

async function transcribeAudio(audio: Uint8Array, sample_rate: number): Promise<string> {
  const { builderApi } = await import("../../../api/builder");
  let bin = "";
  for (let i = 0; i < audio.length; i++) bin += String.fromCharCode(audio[i]);
  try {
    const r = await builderApi.transcribe(btoa(bin), sample_rate, "ru");
    // Whisper often appends a terminal period to short dictation — strip it.
    return r.text.trim().replace(/\.$/, "");
  } catch {
    return "";
  }
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "var(--j-space-2) var(--j-space-3)",
  background: "var(--j-surface)",
  border: "1px solid var(--j-border)",
  borderRadius: "var(--j-radius-md)",
  color: "var(--j-text)",
  fontSize: "var(--j-text-sm)",
};

function chipStyle(selected: boolean): React.CSSProperties {
  return {
    padding: "var(--j-space-2) var(--j-space-4)",
    borderRadius: "var(--j-radius-md)",
    background: selected
      ? "color-mix(in srgb, var(--j-cyan) 15%, transparent)"
      : "var(--j-surface)",
    border: `1px solid ${selected ? "var(--j-border-glow)" : "var(--j-border)"}`,
    color: selected ? "var(--j-cyan)" : "var(--j-text-dim)",
    fontFamily: "var(--j-font-mono)",
    fontSize: "var(--j-text-xs)",
    letterSpacing: "var(--j-tracking-wide)",
    cursor: "pointer",
  };
}

export function ProfileStep() {
  const advance = useOnboardingStore((s) => s.advance);
  const micPermission = useOnboardingStore((s) => s.micPermission);

  const [name, setName] = useState("");
  const [gender, setGender] = useState<Gender | null>(null);
  const [occupation, setOccupation] = useState("");
  const [city, setCity] = useState("");
  const [ageRange, setAgeRange] = useState("");
  const [sttReady, setSttReady] = useState(false);
  const [recordingField, setRecordingField] = useState<TextField | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const { start, stop } = useAudioCapture();

  useEffect(() => {
    let cancelled = false;
    api
      .voiceStatus()
      .then((s) => {
        if (!cancelled) setSttReady(Boolean((s as { models_ready?: boolean }).models_ready));
      })
      .catch(() => {
        // Honest degradation: no voice buttons when the pipeline is unknown.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const voiceEnabled = micPermission === "granted" && sttReady;

  const setField = (field: TextField, value: string) => {
    if (field === "name") setName(value);
    else if (field === "city") setCity(value);
    else setOccupation(value);
  };

  const toggleVoice = async (field: TextField) => {
    if (recordingField === field) {
      setRecordingField(null);
      const result = await stop();
      if (result) {
        const text = await transcribeAudio(result.audio, result.sample_rate);
        if (text) setField(field, text);
      }
      return;
    }
    if (recordingField !== null) return; // one recording at a time
    try {
      await start();
      setRecordingField(field);
    } catch {
      // mic grab failed mid-flow — leave the form usable
    }
  };

  const save = async () => {
    const patch: Record<string, string> = {};
    if (name.trim()) patch.name = name.trim();
    if (gender) patch.gender = gender;
    if (occupation.trim()) patch.occupation = occupation.trim();
    if (city.trim()) patch.city = city.trim();
    if (ageRange) patch.age_range = ageRange;
    if (Object.keys(patch).length === 0) {
      advance();
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.updateProfile(patch);
      advance();
    } catch (e) {
      setError(
        `Не удалось сохранить: ${e instanceof Error ? e.message : e}. Можно пропустить.`,
      );
    }
    setSaving(false);
  };

  const voiceButton = (field: TextField) =>
    voiceEnabled ? (
      <button
        aria-label={`Сказать голосом: ${field}`}
        onClick={() => toggleVoice(field)}
        style={{
          padding: "var(--j-space-2)",
          background: "transparent",
          border: "1px solid var(--j-border)",
          borderRadius: "var(--j-radius-md)",
          color: recordingField === field ? "var(--j-danger)" : "var(--j-cyan)",
          cursor: "pointer",
        }}
      >
        {recordingField === field ? (
          <Square style={{ width: 14, height: 14 }} />
        ) : (
          <Mic style={{ width: 14, height: 14 }} />
        )}
      </button>
    ) : null;

  const label: React.CSSProperties = {
    fontFamily: "var(--j-font-mono)",
    fontSize: "var(--j-text-xs)",
    letterSpacing: "var(--j-tracking-wide)",
    textTransform: "uppercase",
    color: "var(--j-text-dim)",
  };

  return (
    <FadeSlideUp>
      <div
        className="flex flex-col gap-5 w-full max-w-xl"
        data-onboarding-step="profile"
      >
        <div className="text-center">
          <h2 style={{ fontSize: "var(--j-text-xl)", color: "var(--j-text)" }}>
            Расскажи о себе
          </h2>
          <p style={{ color: "var(--j-text-muted)", fontSize: "var(--j-text-sm)" }}>
            Jarvis будет обращаться правильно. Всё можно пропустить.
          </p>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="profile-name" style={label}>
            Имя
          </label>
          <div className="flex gap-2 items-center">
            <input
              id="profile-name"
              aria-label="Имя"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={inputStyle}
            />
            {voiceButton("name")}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span style={label}>Пол</span>
          <div className="flex gap-2">
            {(
              [
                ["male", "Мужской"],
                ["female", "Женский"],
              ] as [Gender, string][]
            ).map(([value, text]) => (
              <button
                key={value}
                onClick={() => setGender(gender === value ? null : value)}
                style={chipStyle(gender === value)}
              >
                {text}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span style={label}>Род занятий</span>
          <div className="flex gap-2 flex-wrap items-center">
            {OCCUPATION_CHIPS.map((chip) => (
              <button
                key={chip}
                onClick={() => setOccupation(occupation === chip ? "" : chip)}
                style={chipStyle(occupation === chip)}
              >
                {chip}
              </button>
            ))}
            <input
              aria-label="Род занятий"
              placeholder="Другое"
              value={OCCUPATION_CHIPS.includes(occupation) ? "" : occupation}
              onChange={(e) => setOccupation(e.target.value)}
              style={{ ...inputStyle, width: "10rem" }}
            />
            {voiceButton("occupation")}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="profile-city" style={label}>
            Город
          </label>
          <div className="flex gap-2 items-center">
            <input
              id="profile-city"
              aria-label="Город"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              style={inputStyle}
            />
            {voiceButton("city")}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span style={label}>Возраст</span>
          <div className="flex gap-2 flex-wrap">
            {AGE_RANGES.map((range) => (
              <button
                key={range}
                onClick={() => setAgeRange(ageRange === range ? "" : range)}
                style={chipStyle(ageRange === range)}
              >
                {range}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div style={{ color: "var(--j-danger)", fontSize: "var(--j-text-sm)" }}>
            {error}
          </div>
        )}

        <div className="flex gap-3 justify-center">
          <button
            onClick={() => advance()}
            style={{
              padding: "var(--j-space-3) var(--j-space-6)",
              background: "var(--j-surface)",
              border: "1px solid var(--j-border)",
              borderRadius: "var(--j-radius-md)",
              color: "var(--j-text-dim)",
              fontFamily: "var(--j-font-mono)",
              letterSpacing: "var(--j-tracking-wide)",
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            Пропустить
          </button>
          <button
            onClick={save}
            disabled={saving}
            style={{
              padding: "var(--j-space-3) var(--j-space-6)",
              background: "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
              border: "1px solid var(--j-border-glow)",
              borderRadius: "var(--j-radius-md)",
              color: "var(--j-cyan)",
              fontFamily: "var(--j-font-mono)",
              letterSpacing: "var(--j-tracking-wide)",
              textTransform: "uppercase",
              cursor: saving ? "wait" : "pointer",
              opacity: saving ? 0.6 : 1,
            }}
          >
            Далее
          </button>
        </div>
      </div>
    </FadeSlideUp>
  );
}
