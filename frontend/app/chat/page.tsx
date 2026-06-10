"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, api, newConversationId, type ProposalCard } from "@/lib/api";
import { EvidenceModal } from "@/components/EvidenceModal";

const CID_STORAGE_KEY = "wf_conversation_id";

type RecalledMemory = {
  text: string;
  source_event_id: string;
  event_type: string;
};

type ChatEvent =
  | { kind: "user_message"; content: string }
  | { kind: "context_loaded"; message: string }
  | { kind: "hypothesis"; label: string; confidence: number; summary: string }
  | { kind: "memories"; memories: RecalledMemory[] }
  | { kind: "reasoning"; content: string }
  | { kind: "tool_started"; tool_name: string }
  | { kind: "tool_finished"; tool_name: string; status: string }
  | { kind: "observation"; content: string }
  | { kind: "proposal"; proposalId: string; toolName: string; arguments: Record<string, unknown>; rationale: string }
  // draft = 流式生成中的回答缓冲；final_answer 到达时被替换
  | { kind: "draft"; content: string }
  | { kind: "final"; content: string }
  | { kind: "notice"; message: string }
  | { kind: "error"; message: string }
  | { kind: "divider"; label: string };

export default function ChatPage() {
  const [conversationId, setConversationId] = useState<string>("");
  const [input, setInput] = useState("");
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [proposalStatuses, setProposalStatuses] = useState<
    Record<string, ProposalCard["status"]>
  >({});
  const [traceEventId, setTraceEventId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // -------- conversation id persistence (fixes "history lost on navigation")
  // Resolution order when this page mounts:
  //   1. cid stored in localStorage  → continue exactly that conversation
  //   2. cid of the most recent server-side conversation → continue last one
  //   3. otherwise → mint a fresh cid
  // This means a user who navigates away and comes back will see their own
  // last message + any proposal that came out of it, in one thread.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let cid = "";
      if (typeof window !== "undefined") {
        cid = window.localStorage.getItem(CID_STORAGE_KEY) || "";
      }
      if (!cid) {
        try {
          const convs = await api.conversations();
          if (convs.length > 0) cid = convs[0].conversation_id;
        } catch {
          // ignore — fall through to fresh cid
        }
      }
      if (!cid) {
        cid = newConversationId();
      }
      if (typeof window !== "undefined") {
        window.localStorage.setItem(CID_STORAGE_KEY, cid);
      }
      if (!cancelled) setConversationId(cid);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // -------- replay history when conversation id is known
  const loadHistory = useCallback(async (cid: string) => {
    if (!cid) return;
    try {
      // Pull ALL proposals (any status) so historical confirmed/rejected ones
      // render correctly. Filter to pending for the orphan-injection step.
      const [history, allProposals] = await Promise.all([
        api.chatHistory(cid).catch(() => []),
        api.proposals().catch(() => [])
      ]);
      const proposals = allProposals.filter((p) => p.status === "pending");

      const evts: ChatEvent[] = history.map((h) => {
        const d = h.data;
        switch (h.kind) {
          case "user_message":
            return { kind: "user_message", content: String(d.content ?? "") };
          case "hypothesis_generated":
            return {
              kind: "hypothesis",
              label: String(d.label ?? ""),
              confidence: Number(d.confidence ?? 0),
              summary: String(d.summary ?? "")
            };
          case "reasoning_step":
            return { kind: "reasoning", content: stripThink(String(d.content ?? "")) };
          case "tool_call_finished":
            return {
              kind: "tool_finished",
              tool_name: String(d.tool_name ?? ""),
              status: String(d.status ?? "")
            };
          case "proposal_created":
            return {
              kind: "proposal",
              proposalId: String(d.proposal_id ?? ""),
              toolName: String(d.tool_name ?? ""),
              arguments: (d.arguments as Record<string, unknown>) ?? {},
              rationale: stripThink(String(d.rationale ?? ""))
            };
          case "final_answer":
            return { kind: "final", content: String(d.content ?? "") };
          default:
            return { kind: "reasoning", content: `(${h.kind})` };
        }
      });

      // Show "其他对话的待确认" only for proposals NOT already in this thread.
      const seenInThisConv = new Set(
        evts.filter((e) => e.kind === "proposal").map((e) => (e as any).proposalId)
      );
      const orphanProposals = proposals.filter((p) => !seenInThisConv.has(p.id));
      const orphanEvents: ChatEvent[] =
        orphanProposals.length > 0
          ? [
              { kind: "divider", label: "其他对话的待确认 proposal" },
              ...orphanProposals.map<ChatEvent>((p) => ({
                kind: "proposal",
                proposalId: p.id,
                toolName: p.tool_name,
                arguments: p.arguments,
                rationale: stripThink(p.rationale || "")
              })),
              { kind: "divider", label: "本对话" }
            ]
          : [];

      // Seed status from ALL proposals so historical ones have the right
      // initial state (otherwise undefined falls back to the "pending"
      // branch and re-shows confirm/reject buttons — which then 409 on click).
      const initialStatuses: Record<string, ProposalCard["status"]> = {};
      allProposals.forEach((p) => {
        initialStatuses[p.id] = p.status;
      });
      setProposalStatuses(initialStatuses);

      setEvents([...orphanEvents, ...evts]);
    } catch (err) {
      console.error("history load failed", err);
    }
  }, []);

  useEffect(() => {
    if (conversationId) loadHistory(conversationId);
  }, [conversationId, loadHistory]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  function startNewConversation() {
    const cid = newConversationId();
    if (typeof window !== "undefined") {
      window.localStorage.setItem(CID_STORAGE_KEY, cid);
    }
    setConversationId(cid);
    setEvents([]);
    setProposalStatuses({});
  }

  async function send() {
    const text = input.trim();
    if (!text || streaming || !conversationId) return;
    setInput("");
    setStreaming(true);
    setEvents((prev) => [...prev, { kind: "user_message", content: text }]);

    try {
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: conversationId })
      });
      if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // sse-starlette terminates frames with \r\n\r\n (not \n\n) — split on
        // both, or the buffer never flushes and the UI renders nothing.
        const parts = buffer.split(/\r?\n\r?\n/);
        buffer = parts.pop() ?? "";
        for (const part of parts) handleSseChunk(part);
      }
    } catch (e) {
      setEvents((prev) => [
        ...prev,
        { kind: "error", message: (e as Error).message }
      ]);
    } finally {
      setStreaming(false);
      // 流意外中断时，把生成到一半的 draft 固化下来，不让它带着光标悬置。
      setEvents((p) => {
        const last = p[p.length - 1];
        if (last && last.kind === "draft") {
          return [...p.slice(0, -1), { kind: "final", content: last.content }];
        }
        return p;
      });
    }
  }

  function handleSseChunk(chunk: string) {
    let event = "";
    let data = "";
    for (const line of chunk.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!event) return;
    let payload: Record<string, unknown> = {};
    try {
      payload = JSON.parse(data || "{}");
    } catch {
      payload = {};
    }
    switch (event) {
      case "context_loaded":
        setEvents((p) => [
          ...p,
          { kind: "context_loaded", message: String(payload.message ?? "") }
        ]);
        break;
      case "memories_recalled":
        setEvents((p) => [
          ...p,
          {
            kind: "memories",
            memories: Array.isArray(payload.memories)
              ? (payload.memories as RecalledMemory[])
              : []
          }
        ]);
        break;
      case "answer_delta": {
        const piece = String(payload.content ?? "");
        if (!piece) break;
        setEvents((p) => {
          const last = p[p.length - 1];
          if (last && last.kind === "draft") {
            return [...p.slice(0, -1), { kind: "draft", content: last.content + piece }];
          }
          return [...p, { kind: "draft", content: piece }];
        });
        break;
      }
      case "hypothesis_generated":
        setEvents((p) => [
          ...p,
          {
            kind: "hypothesis",
            label: String(payload.label ?? ""),
            confidence: Number(payload.confidence ?? 0),
            summary: String(payload.summary ?? "")
          }
        ]);
        break;
      case "reasoning_step":
        // 流式 draft 缓冲的其实是这段 reasoning（content + tool_calls 同发）——
        // 用正式的 reasoning 行替换掉 draft，避免同一段文字出现两次。
        setEvents((p) => [
          ...dropTrailingDraft(p),
          { kind: "reasoning", content: stripThink(String(payload.content ?? "")) }
        ]);
        break;
      case "tool_call_started":
        setEvents((p) => [
          ...dropTrailingDraft(p),
          { kind: "tool_started", tool_name: String(payload.tool_name ?? "") }
        ]);
        break;
      case "tool_call_finished":
        setEvents((p) => [
          ...p,
          {
            kind: "tool_finished",
            tool_name: String(payload.tool_name ?? ""),
            status: String(payload.status ?? "")
          }
        ]);
        break;
      case "observation_summary":
        setEvents((p) => [
          ...p,
          { kind: "observation", content: String(payload.content ?? "") }
        ]);
        break;
      case "proposal_created":
        setEvents((p) => [
          ...p,
          {
            kind: "proposal",
            proposalId: String(payload.proposal_id ?? ""),
            toolName: String(payload.tool_name ?? ""),
            arguments: (payload.arguments as Record<string, unknown>) ?? {},
            rationale: stripThink(String(payload.rationale ?? ""))
          }
        ]);
        setProposalStatuses((p) => ({
          ...p,
          [String(payload.proposal_id ?? "")]: "pending"
        }));
        break;
      case "final_answer":
        // 替换流式 draft，而不是再追加一条 —— 内容相同，状态升级为 final。
        setEvents((p) => [
          ...dropTrailingDraft(p),
          { kind: "final", content: String(payload.content ?? "") }
        ]);
        break;
      case "error":
        setEvents((p) => [
          ...p,
          { kind: "error", message: String(payload.message ?? "") }
        ]);
        break;
    }
  }

  async function confirmProposal(id: string) {
    setProposalStatuses((p) => ({ ...p, [id]: "confirmed" }));
    setEvents((p) => [
      ...p,
      { kind: "notice", message: "已确认执行，Agent 正在基于执行结果继续…" }
    ]);
    try {
      await api.executeProposal(id);
      // 执行成功后后端会 resume 暂停的 graph，并把续写的回答落进 L1 —
      // 重新拉取历史，让用户当场看到 Agent 的后续回答而不用手动刷新。
      await loadHistory(conversationId);
    } catch (e) {
      const msg = (e as Error).message;
      // 409 means the proposal is already in a terminal state on the server.
      // Reverting to "pending" would re-show the buttons and the user would
      // 409 again — keep it sticky at "confirmed" instead.
      if (/\b409\b|already/.test(msg)) {
        await loadHistory(conversationId);
        return;
      }
      setProposalStatuses((p) => ({ ...p, [id]: "pending" }));
      setEvents((p) => [...p, { kind: "error", message: "执行失败：" + msg }]);
    }
  }

  async function rejectProposal(id: string) {
    setProposalStatuses((p) => ({ ...p, [id]: "rejected" }));
    try {
      await api.rejectProposal(id);
    } catch (e) {
      const msg = (e as Error).message;
      if (/\b409\b|already/.test(msg)) return;
      setProposalStatuses((p) => ({ ...p, [id]: "pending" }));
      setEvents((p) => [...p, { kind: "error", message: "拒绝失败：" + msg }]);
    }
  }

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-widest muted">驾驶舱 · T4 Chat</div>
          <h1 className="mt-2 font-serif text-3xl tracking-tight">和 WF 说话</h1>
          <p className="mt-1 text-sm muted">
            会话持久化：刷新或回主页再回来仍是同一会话。
          </p>
        </div>
        <button
          onClick={startNewConversation}
          className="text-xs rounded-md border border-black/10 dark:border-white/20 px-3 py-1.5 hover:bg-black/5 dark:hover:bg-white/10"
        >
          + 新对话
        </button>
      </div>

      {conversationId && (
        <div className="text-xs muted">
          conv_id: <code>{conversationId.slice(0, 24)}…</code>
        </div>
      )}

      <div className="card space-y-3 min-h-[300px]">
        {events.length === 0 && (
          <p className="muted text-sm">
            问个问题开始吧 · 例：「帮我看看明天怎么安排」
          </p>
        )}
        {events.map((ev, i) => (
          <EventLine
            key={i}
            ev={ev}
            proposalStatus={
              ev.kind === "proposal" ? proposalStatuses[ev.proposalId] : undefined
            }
            onConfirm={() => ev.kind === "proposal" && confirmProposal(ev.proposalId)}
            onReject={() => ev.kind === "proposal" && rejectProposal(ev.proposalId)}
            onTrace={(eventId) => setTraceEventId(eventId)}
          />
        ))}
        <div ref={endRef} />
      </div>

      {traceEventId && (
        <EvidenceModal eventId={traceEventId} onClose={() => setTraceEventId(null)} />
      )}

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Don't submit while IME composition is active (Enter is being
            // used to commit a candidate — Pinyin, Kana, Hangul, etc.)
            // `e.nativeEvent.isComposing` is the standardized check; `keyCode === 229`
            // is the legacy fallback some browsers still emit.
            if (e.key !== "Enter") return;
            if (e.nativeEvent.isComposing || e.keyCode === 229) return;
            if (e.shiftKey) return; // Shift+Enter could later be used for newline
            e.preventDefault();
            send();
          }}
          placeholder="例：帮我看看明天怎么安排…"
          className="flex-1 rounded-md border border-black/10 dark:border-white/20 bg-transparent px-3 py-2"
        />
        <button
          onClick={send}
          disabled={streaming || !conversationId}
          className="rounded-md bg-black px-4 py-2 text-white dark:bg-white dark:text-black disabled:opacity-50"
        >
          {streaming ? "思考中…" : "发送"}
        </button>
      </div>
    </div>
  );
}

/** Strip <think>...</think> blocks from reasoning-model output (MiniMax-M2,
 * DeepSeek-R1, etc). Backend also strips on JSON parse, but tool_calls have
 * the think block in message.content which lands in L1 as-is. */
function stripThink(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
}

function dropTrailingDraft(events: ChatEvent[]): ChatEvent[] {
  const last = events[events.length - 1];
  return last && last.kind === "draft" ? events.slice(0, -1) : events;
}

function EventLine({
  ev,
  proposalStatus,
  onConfirm,
  onReject,
  onTrace
}: {
  ev: ChatEvent;
  proposalStatus?: ProposalCard["status"];
  onConfirm?: () => void;
  onReject?: () => void;
  onTrace?: (eventId: string) => void;
}) {
  switch (ev.kind) {
    case "user_message":
      return (
        <div className="rounded-md bg-black/5 dark:bg-white/10 px-3 py-2 text-sm self-end">
          🙂 {ev.content}
        </div>
      );
    case "context_loaded":
      return <p className="text-xs muted">· {ev.message}</p>;
    case "memories":
      if (ev.memories.length === 0) return null;
      return (
        <div className="text-xs">
          <span className="muted">🧠 想起了 {ev.memories.length} 段过往：</span>
          <span className="inline-flex flex-wrap gap-1.5 align-middle ml-1">
            {ev.memories.map((m, i) => (
              <button
                key={i}
                type="button"
                onClick={() => m.source_event_id && onTrace?.(m.source_event_id)}
                title={m.text}
                className="max-w-[16rem] truncate rounded-full border border-black/10 dark:border-white/20 px-2 py-0.5 hover:bg-black/5 dark:hover:bg-white/10"
              >
                {m.text}
              </button>
            ))}
          </span>
        </div>
      );
    case "notice":
      return <p className="text-xs muted">⏳ {ev.message}</p>;
    case "draft":
      return (
        <div className="rounded-md bg-black/5 dark:bg-white/5 p-3">
          <div className="text-xs uppercase tracking-widest muted">回答中…</div>
          <p className="mt-1 text-sm whitespace-pre-wrap">
            {ev.content}
            <span className="animate-pulse">▌</span>
          </p>
        </div>
      );
    case "hypothesis":
      return (
        <div className="rounded-md border-l-2 border-black/40 dark:border-white/40 pl-3 py-1">
          <div className="text-xs uppercase tracking-widest muted">hypothesis</div>
          <div className="text-sm">
            {ev.label} (conf {(ev.confidence * 100).toFixed(0)}%) — {ev.summary}
          </div>
        </div>
      );
    case "reasoning":
      if (!ev.content) return null;
      return <p className="text-sm">{ev.content}</p>;
    case "tool_started":
      return <p className="text-xs muted">🔧 调用 {ev.tool_name} …</p>;
    case "tool_finished":
      return <p className="text-xs muted">  → {ev.tool_name} {ev.status}</p>;
    case "observation":
      return <p className="text-xs muted">📥 {ev.content}</p>;
    case "proposal":
      return (
        <div className="rounded-md border border-yellow-500/40 bg-yellow-50/40 dark:bg-yellow-900/10 p-3">
          <div className="text-xs uppercase tracking-widest muted">
            Proposal · {ev.toolName}
          </div>
          {Object.keys(ev.arguments).length > 0 && (
            <pre className="mt-1 text-xs muted overflow-auto">
              {JSON.stringify(ev.arguments, null, 2)}
            </pre>
          )}
          {ev.rationale && <p className="mt-1 text-sm">{ev.rationale}</p>}
          {proposalStatus === "pending" || proposalStatus === undefined ? (
            <div className="mt-2 flex gap-2">
              <button
                onClick={onConfirm}
                className="rounded-md bg-black px-3 py-1 text-sm text-white dark:bg-white dark:text-black"
              >
                确认执行
              </button>
              <button
                onClick={onReject}
                className="rounded-md border border-black/10 dark:border-white/20 px-3 py-1 text-sm"
              >
                拒绝
              </button>
            </div>
          ) : (
            <p className="mt-2 text-xs muted">状态：{proposalStatus}</p>
          )}
        </div>
      );
    case "final":
      return (
        <div className="rounded-md bg-black/5 dark:bg-white/5 p-3">
          <div className="text-xs uppercase tracking-widest muted">最终回答</div>
          <p className="mt-1 text-sm whitespace-pre-wrap">{ev.content}</p>
        </div>
      );
    case "error":
      return <p className="text-sm text-red-600">⚠ {ev.message}</p>;
    case "divider":
      return (
        <div className="flex items-center gap-2 pt-3">
          <div className="h-px flex-1 bg-black/10 dark:bg-white/10" />
          <span className="text-[10px] uppercase tracking-widest muted">
            {ev.label}
          </span>
          <div className="h-px flex-1 bg-black/10 dark:bg-white/10" />
        </div>
      );
  }
}
