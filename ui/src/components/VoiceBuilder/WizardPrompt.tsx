// ui/src/components/VoiceBuilder/WizardPrompt.tsx
import { useEffect } from "react";
import { builderApi } from "../../api/builder";

interface Props {
  question: string;
  step: number;
  totalSteps: number;
  onTtsDone: () => void;
}

export function WizardPrompt({ question, step, totalSteps, onTtsDone }: Props) {
  useEffect(() => {
    let cancelled = false;
    void builderApi.say(question, "ru").finally(() => {
      if (!cancelled) onTtsDone();
    });
    return () => {
      cancelled = true;
    };
  }, [question, onTtsDone]);

  return (
    <div style={{ textAlign: "center", margin: "12px auto" }}>
      <div style={{ color: "var(--j-cyan)", fontSize: 18, fontWeight: 600 }}>
        {question}
      </div>
      <div style={{ color: "var(--j-text-dim)", fontSize: 12, marginTop: 8 }}>
        Шаг {step + 1} из {totalSteps}
      </div>
    </div>
  );
}
