const STARTER_EXAMPLES = [
  "Напомни пить воду каждые 2 часа",
  "Веди дневник настроения — спрашивай раз в день",
  "Таймер для плова — 30 минут с напоминаниями",
  "Трекер ежедневных трат — голосом",
  "Мониторинг курса биткоина — оповещай при падении 5%",
];

interface Props {
  onPick: (text: string) => void;
}

export function StarterExamples({ onPick }: Props) {
  return (
    <div className="starter-examples">
      <p className="label">Или начни с примера:</p>
      <div className="example-list">
        {STARTER_EXAMPLES.map((ex) => (
          <button key={ex} onClick={() => onPick(ex)} className="example-chip">
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
