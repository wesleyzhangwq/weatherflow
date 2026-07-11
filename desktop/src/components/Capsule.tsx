import { useState, type DragEvent, type FormEvent } from "react";
import { WeatherFlowClient } from "../bridge";

interface CapsuleProps { client: WeatherFlowClient; onAccepted: () => void }

export function Capsule({ client, onAccepted }: CapsuleProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const intent = value.trim();
    if (!intent || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await client.createRun(intent, crypto.randomUUID());
      onAccepted();
    } catch {
      setError("WeatherFlow is unavailable. Your input is still here.");
      setSubmitting(false);
    }
  };

  const drop = (event: DragEvent<HTMLInputElement>) => {
    event.preventDefault();
    const names = Array.from(event.dataTransfer.files, (file) => file.name);
    if (names.length) setValue((current) => `${current}${current ? " " : ""}${names.map((name) => `[${name}]`).join(" ")}`);
  };

  return (
    <main className="capsule-shell">
      <form className="command-capsule" onSubmit={submit}>
        <span className="capsule-mark" aria-hidden="true" />
        <input
          autoFocus
          aria-label="Tell WeatherFlow what to do"
          placeholder="What should WeatherFlow handle?"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={drop}
          disabled={submitting}
        />
        <kbd>↵</kbd>
      </form>
      {error && <p role="alert">{error}</p>}
    </main>
  );
}
