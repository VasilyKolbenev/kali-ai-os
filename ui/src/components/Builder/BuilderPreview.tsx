import { useBuilderStore } from "../../stores/builder";

export function BuilderPreview() {
  const { preview, deploy, cancel } = useBuilderStore();
  if (!preview) return null;
  return (
    <div className="builder-preview">
      <h3>Превью агента</h3>
      <p><strong>Название:</strong> {preview.name}</p>
      <p><strong>Описание:</strong> {preview.description}</p>
      <p><strong>Тип:</strong> {preview.template ?? "agent"}</p>
      <pre>{JSON.stringify(preview.config, null, 2)}</pre>
      <div className="actions">
        <button onClick={deploy}>Запустить</button>
        <button onClick={cancel}>Отменить</button>
      </div>
    </div>
  );
}
