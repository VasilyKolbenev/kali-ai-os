import { useEffect, useState } from "react";
import { api } from "../../../api/client";
import { HexFrame, HudDivider } from "../../hud";

type Gender = "male" | "female";

const OCCUPATION_CHIPS = ["Строитель", "Врач", "Офис", "Учитель"];
const AGE_RANGES = ["18-25", "26-35", "36-45", "46-55", "55+"];

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

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--j-font-mono)",
  fontSize: "var(--j-text-xs)",
  letterSpacing: "var(--j-tracking-wide)",
  textTransform: "uppercase",
  color: "var(--j-text-dim)",
};

/**
 * Editable questionnaire («анкета») — the onboarding ProfileStep's fields,
 * revisitable any time. Save sends ALL five fields: an emptied field goes as
 * "" which the backend treats as an explicit clear (deletes the fact).
 */
export function ProfileSettings() {
  const [name, setName] = useState("");
  const [gender, setGender] = useState<Gender | null>(null);
  const [occupation, setOccupation] = useState("");
  const [city, setCity] = useState("");
  const [ageRange, setAgeRange] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .profile()
      .then((p) => {
        if (cancelled) return;
        setName(p.name ?? "");
        setGender(p.gender);
        setOccupation(p.occupation ?? "");
        setCity(p.city ?? "");
        setAgeRange(p.age_range ?? "");
      })
      .catch((e) =>
        setError(`Не удалось загрузить профиль: ${e instanceof Error ? e.message : e}`),
      );
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await api.updateProfile({
        name: name.trim(),
        gender: gender ?? "",
        occupation: occupation.trim(),
        city: city.trim(),
        age_range: ageRange,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(`Не удалось сохранить: ${e instanceof Error ? e.message : e}`);
    }
    setSaving(false);
  };

  return (
    <div style={{ marginBottom: "var(--j-space-5)" }}>
      <HudDivider label="ПРОФИЛЬ" />
      <div style={{ height: "var(--j-space-3)" }} />
      <HexFrame>
        <div
          style={{
            padding: "var(--j-space-4)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--j-space-4)",
          }}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="settings-profile-name" style={labelStyle}>
              Имя
            </label>
            <input
              id="settings-profile-name"
              aria-label="Имя"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={inputStyle}
            />
          </div>

          <div className="flex flex-col gap-1">
            <span style={labelStyle}>Пол</span>
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
            <span style={labelStyle}>Род занятий</span>
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
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="settings-profile-city" style={labelStyle}>
              Город
            </label>
            <input
              id="settings-profile-city"
              aria-label="Город"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              style={inputStyle}
            />
          </div>

          <div className="flex flex-col gap-1">
            <span style={labelStyle}>Возраст</span>
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

          <button
            onClick={save}
            disabled={saving}
            style={{
              padding: "var(--j-space-2) var(--j-space-5)",
              alignSelf: "flex-start",
              background: saved
                ? "color-mix(in srgb, var(--j-success) 12%, transparent)"
                : "color-mix(in srgb, var(--j-cyan) 12%, transparent)",
              border: `1px solid ${saved ? "var(--j-success-glow)" : "var(--j-border-glow)"}`,
              borderRadius: "var(--j-radius-md)",
              color: saved ? "var(--j-success)" : "var(--j-cyan)",
              fontFamily: "var(--j-font-mono)",
              fontSize: "var(--j-text-xs)",
              letterSpacing: "var(--j-tracking-wide)",
              textTransform: "uppercase",
              cursor: saving ? "wait" : "pointer",
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? "Сохраняю..." : saved ? "Сохранено" : "Сохранить профиль"}
          </button>
        </div>
      </HexFrame>
    </div>
  );
}
