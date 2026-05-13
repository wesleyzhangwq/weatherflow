import type { WeatherLabel } from "./api";

/** Emoji / symbol for weather — keep simple for cross-font support */
export const WEATHER_GLYPH: Record<WeatherLabel, string> = {
  Momentum: "☀",
  Confusion: "☁",
  Burnout: "⛈",
  Overload: "🌧",
  Recovery: "🌤"
};

export const WEATHER_LABEL_ZH: Record<WeatherLabel, string> = {
  Momentum: "顺势",
  Confusion: "迷雾",
  Burnout: "耗竭",
  Overload: "过载",
  Recovery: "回升"
};

export const WEATHER_BLURB: Record<WeatherLabel, string> = {
  Momentum: "你在节奏里，尽量护住它。",
  Confusion: "有些不清楚也没关系，允许自己停在这里。",
  Burnout: "累了就先当正事休息，不必愧疚。",
  Overload: "输入太多时，先关掉一条支流。",
  Recovery: "能回来一点点就很难得，保持小事就好。"
};
