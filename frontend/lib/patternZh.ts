/** Display strings for deterministic pattern codes (API still returns English). */

export const PATTERN_LABEL_ZH: Record<string, string> = {
  input_up_output_down: "输入多、输出少",
  project_switching_up: "项目切换变频繁",
  burnout_climbing: "倦怠信号在走高",
  momentum_recovering: "动能在回升"
};

export const PATTERN_EXPLAIN_ZH: Record<string, string> = {
  input_up_output_down:
    "笔记/收集涨得快，但代码或成稿输出相对变少，有时是「收集模式」偏强。",
  project_switching_up:
    "这段时间在仓库之间跳得比上一段更勤，先收掉一个小闭环往往比再开第三个更省力。",
  burnout_climbing:
    "倦怠分数比上一窗口明显抬升，适合刻意缩小范围，而不是再硬顶。",
  momentum_recovering:
    "动能从低点在回来——把你带回正轨的做法，尽量保持小而可持续。"
};

export const SEVERITY_ZH: Record<string, string> = {
  info: "参考",
  watch: "留意",
  alert: "注意"
};

export function patternLabelZh(code: string, fallback: string): string {
  return PATTERN_LABEL_ZH[code] ?? fallback;
}

export function patternExplainZh(code: string, fallback: string): string {
  return PATTERN_EXPLAIN_ZH[code] ?? fallback;
}
