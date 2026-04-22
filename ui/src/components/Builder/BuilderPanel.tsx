import { useState } from "react";
import { useBuilderStore } from "../../stores/builder";
import { BuilderProgress } from "./BuilderProgress";
import { BuilderPreview } from "./BuilderPreview";
import { StarterExamples } from "./StarterExamples";

export function BuilderPanel() {
  const { phase, question, answer, start, reset, error } = useBuilderStore();
  const [text, setText] = useState("");

  const submit = async () => {
    if (!text.trim()) return;
    if (phase === "idle") await start(text);
    else if (phase === "asking") await answer(text);
    setText("");
  };

  return (
    <div className="builder-panel">
      <BuilderProgress />
      {error && <div className="error">{error}</div>}

      {phase === "idle" && (
        <div>
          <p>Скажи или напиши идею агента:</p>
          <input
            placeholder="напр. 'напомни пить воду каждые 2 часа'"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          <button onClick={submit}>Создать</button>
          <StarterExamples onPick={(ex) => setText(ex)} />
        </div>
      )}

      {phase === "asking" && question && (
        <div>
          <p><strong>{question}</strong></p>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            autoFocus
          />
          <button onClick={submit}>Ответить</button>
        </div>
      )}

      {phase === "previewing" && <BuilderPreview />}

      {phase === "done" && (
        <div>
          <p>Агент запущен</p>
          <button onClick={reset}>Создать ещё</button>
        </div>
      )}
    </div>
  );
}
