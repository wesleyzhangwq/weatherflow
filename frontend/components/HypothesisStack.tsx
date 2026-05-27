"use client";

import { useEffect, useState } from "react";
import { api, type HypothesisCard as Card } from "@/lib/api";
import { HypothesisCard } from "./HypothesisCard";

export function HypothesisStack() {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await api.hypotheses(3);
      setCards(data);
    } catch (e) {
      console.error(e);
      setCards([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (loading) return <p className="muted text-sm">加载中…</p>;
  if (!cards || cards.length === 0) {
    return (
      <div className="card">
        <p className="muted">
          主页堆为空。做一次签到，或者等定时检查到点，会自动出现一张卡片。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {cards.map((c, i) => (
        <HypothesisCard
          key={c.id}
          card={c}
          isTop={i === 0}
          onCalibrated={load}
        />
      ))}
    </div>
  );
}
