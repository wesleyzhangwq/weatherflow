"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type Props = {
  suggestionText: string;
  patternCodes: string[];
  reflectionId: number;
  sessionId?: string;
};

export function SuggestionFeedback({
  suggestionText,
  patternCodes,
  reflectionId,
  sessionId = "default"
}: Props) {
  const [done, setDone] = useState<"hit" | "miss" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const send = async (helpful: boolean) => {
    setErr(null);
    try {
      await api.submitSuggestionFeedback({
        helpful,
        suggestion_text: suggestionText,
        pattern_codes: patternCodes,
        reflection_id: reflectionId,
        session_id: sessionId
      });
      setDone(helpful ? "hit" : "miss");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  if (done) {
    return (
      <p className="text-sm muted mt-3">
        {done === "hit"
          ? "已记录：这条建议对你有用。会纳入后续记忆与建议。"
          : "已记录：这条建议不太贴切。会用来校准后续判断。"}
      </p>
    );
  }

  return (
    <div className="mt-4 pt-4 border-t border-black/10 dark:border-white/10">
      <div className="text-sm muted mb-2">这条「轻轻的一句」说得准吗？</div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void send(true)}
          className="rounded-lg px-4 py-1.5 text-sm border border-black/15 dark:border-white/20 hover:bg-black/5 dark:hover:bg-white/10"
        >
          说中了
        </button>
        <button
          type="button"
          onClick={() => void send(false)}
          className="rounded-lg px-4 py-1.5 text-sm border border-black/15 dark:border-white/20 hover:bg-black/5 dark:hover:bg-white/10"
        >
          不太对
        </button>
      </div>
      {err ? (
        <p className="text-sm text-red-600 dark:text-red-400 mt-2">{err}</p>
      ) : null}
    </div>
  );
}
