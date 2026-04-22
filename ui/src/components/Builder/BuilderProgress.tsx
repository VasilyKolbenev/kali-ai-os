import { useBuilderStore } from "../../stores/builder";

const PHASE_LABEL: Record<string, string> = {
  idle: "Готов",
  asking: "Задаю уточняющие вопросы",
  generating: "Анализирую запрос",
  previewing: "Готовлю превью",
  deploying: "Собираю и запускаю",
  done: "Готово!",
  error: "Ошибка",
};

export function BuilderProgress() {
  const { phase, step, totalSteps } = useBuilderStore();
  return (
    <div className="builder-progress">
      <div className="phase-label">{PHASE_LABEL[phase]}</div>
      {totalSteps > 0 && (
        <div className="step-dots">
          {Array.from({ length: totalSteps }).map((_, i) => (
            <span
              key={i}
              className={`dot ${i < step ? "filled" : ""} ${i === step ? "current" : ""}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
