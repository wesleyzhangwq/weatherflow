import type { HypothesisLabel, Weather } from "./api";

// ----- Hypothesis labels (system judgment, 6 fixed) -----
export const LABEL_TEXT: Record<HypothesisLabel, string> = {
  Flow: "心流高产",
  Steady: "平稳推进",
  Recovery: "恢复模式",
  Overload: "过载",
  Blocked: "卡住",
  Fragmented: "碎片化"
};

export const LABEL_GLYPH: Record<HypothesisLabel, string> = {
  Flow: "☀",
  Steady: "⛅",
  Recovery: "☁",
  Overload: "🌧",
  Blocked: "⛈",
  Fragmented: "🌫"
};

// ----- Weather (user self-report, 6 fixed) -----
export const WEATHER_TEXT: Record<Weather, string> = {
  sunny: "☀ 晴天",
  partly_cloudy: "⛅ 多云",
  cloudy: "☁ 阴天",
  rainy: "🌧 小雨",
  thunderstorm: "⛈ 雷暴",
  foggy: "🌫 大雾"
};

// 1:1 mapping to labels (ADR-002). UI shows these next to each option so the
// user knows what semantic state they're reporting.
export const WEATHER_SEMANTIC: Record<Weather, string> = {
  sunny: "清醒高效 · 思路清楚行动顺畅",
  partly_cloudy: "能工作但不锋利 · 容易分心",
  cloudy: "低能量拖延 · 脑子沉启动难",
  rainy: "情绪干扰中 · 焦虑烦躁内耗",
  thunderstorm: "混乱过载 · 任务失控",
  foggy: "思路碎片化 · 难以专注"
};

export const WEATHER_DEFAULT_LABEL: Record<Weather, HypothesisLabel> = {
  sunny: "Flow",
  partly_cloudy: "Steady",
  cloudy: "Recovery",
  rainy: "Overload",
  thunderstorm: "Blocked",
  foggy: "Fragmented"
};

export const SOURCE_TAG_TEXT: Record<string, string> = {
  checkin: "签到",
  scheduled: "定时检查",
  chat: "对话",
  recalibrate: "重新校准"
};
