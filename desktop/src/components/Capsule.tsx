import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { X } from "@phosphor-icons/react";
import { WeatherFlowClient } from "../bridge";

interface CapsuleProps { client: WeatherFlowClient; workspaceId?: string | null; onAccepted: () => void; onCancel: () => void }

export function Capsule({ client, workspaceId, onAccepted, onCancel }: CapsuleProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const composing = useRef(false);

  useEffect(() => {
    window.addEventListener("blur", onCancel);
    return () => window.removeEventListener("blur", onCancel);
  }, [onCancel]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (composing.current) return;
    if (!workspaceId) {
      setError("请先在控制台选择项目，再创建任务。");
      return;
    }
    const intent = value.trim();
    if (!intent || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await client.createRun(intent, crypto.randomUUID(), workspaceId);
      onAccepted();
    } catch {
      setError("暂时无法连接 WeatherFlow，输入内容已保留。");
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
        <input
          autoFocus
          aria-label="告诉 WeatherFlow 要做什么"
          placeholder="交给 WeatherFlow 一件事…"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={drop}
          onCompositionStart={() => { composing.current = true; }}
          onCompositionEnd={() => { composing.current = false; }}
          onKeyDown={(event) => {
            if (event.key === "Escape") onCancel();
            if (event.key === "Enter" && (event.nativeEvent.isComposing || event.keyCode === 229)) {
              event.preventDefault();
            }
          }}
          disabled={submitting}
        />
        <button type="button" className="capsule-close" aria-label="关闭输入框" onClick={onCancel}><X /></button>
      </form>
      {error && <p role="alert">{error}</p>}
    </main>
  );
}
