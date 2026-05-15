"""Synthetic 300-check-in dataset for manual WeatherFlow review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.memory.schemas import CheckinIn


@dataclass(frozen=True)
class DemoCheckin:
    day: str
    checkin: CheckinIn


_PHASES = [
    (
        45,
        "☁ 有点乱 / 分散",
        "收集资料、打开了很多方向，但还没形成闭环",
        "不知道先收哪一个项目",
        "整理了一些笔记",
    ),
    (
        55,
        "🌧 压力大 / 疲惫",
        "同时推进多个任务，会议和上下文切换都偏多",
        "最拖住我的是切换成本",
        "完成了必要回复",
    ),
    (
        40,
        "⛈ 失控 / 焦虑",
        "感觉任务堆在一起，不知道从哪里开始",
        "担心错过关键期限",
        "只完成了一点点整理",
    ),
    (
        50,
        "⛅ 普通 / 稳定",
        "把一个小任务拆清楚，开始慢慢恢复节奏",
        "容易被新想法带走",
        "完成了一个小闭环",
    ),
    (
        60,
        "☀ 清晰 / 有动力",
        "今天最想完成一个明确交付，并保持节奏",
        "不要临时开新坑",
        "推进并收尾了核心任务",
    ),
    (
        50,
        "⛅ 普通 / 稳定",
        "保持稳定输入输出，不追求爆发",
        "体力和注意力的边界",
        "完成了复盘和维护",
    ),
]


def generate_demo_checkins(count: int = 300) -> list[DemoCheckin]:
    today = date.today()
    rows: list[DemoCheckin] = []
    day_index = 0
    for phase_index, (length, status, intention, blocker, completed) in enumerate(_PHASES):
        for offset in range(length):
            if len(rows) >= count:
                return rows
            day = today - timedelta(days=count - day_index - 1)
            rows.append(
                DemoCheckin(
                    day=day.isoformat(),
                    checkin=CheckinIn(
                        status=status,
                        raw=f"phase={phase_index + 1}; today_intention: {intention}",
                        stuck_on=blocker,
                        did_today=f"{completed}（第 {offset + 1} 天）",
                        anxiety=None,
                    ),
                )
            )
            day_index += 1
    return rows[:count]


__all__ = ["DemoCheckin", "generate_demo_checkins"]
