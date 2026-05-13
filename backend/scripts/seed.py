"""Seed the local DB with a few synthetic days so the dashboard isn't empty.

Usage:
    cd backend
    python -m scripts.seed
"""

from __future__ import annotations

from datetime import date, timedelta

from app.memory import (
    checkin_repo,
    episodic,
    reflection_repo,
    semantic,
    state_repo,
    timeline,
)
from app.memory.schemas import CheckinIn, UserStateOut
from app.memory.store import init_db


_DAYS = [
    {
        "offset": 5,
        "weather": "Confusion",
        "vec": (55, 50, 30, 45, 50, 50),
        "checkin": CheckinIn(
            status="foggy", did_today="read three articles, wrote nothing",
            stuck_on="what to actually build", anxiety="time slipping",
        ),
        "reflection": (
            "Today was foggy. You took in a lot and put little out. "
            "That's allowed; not every day belongs to shipping."
        ),
        "rationale": "High input, low output. The fog is information overload.",
    },
    {
        "offset": 4,
        "weather": "Overload",
        "vec": (45, 65, 40, 35, 45, 50),
        "checkin": CheckinIn(
            status="scattered", did_today="started 2 new repos",
            stuck_on="finishing the older one", anxiety="frameworks fatigue",
        ),
        "reflection": (
            "You started two new things today. Notice the pattern  when you can't "
            "finish, starting feels like motion. It isn't quite the same."
        ),
        "rationale": "Project switching detected. Closing one small loop would help.",
    },
    {
        "offset": 2,
        "weather": "Recovery",
        "vec": (60, 40, 25, 60, 55, 60),
        "checkin": CheckinIn(
            status="lighter", did_today="closed a tiny PR",
            stuck_on=None, anxiety="not much",
        ),
        "reflection": (
            "Something opened back up today. You closed a tiny loop and said so. "
            "Keep it small; small is how you came back."
        ),
        "rationale": "You re-entered after a stuck stretch.",
    },
    {
        "offset": 0,
        "weather": "Momentum",
        "vec": (72, 30, 20, 75, 65, 70),
        "checkin": CheckinIn(
            status="alive", did_today="shipped a small RAG demo",
            stuck_on=None, anxiety="just protecting the rhythm",
        ),
        "reflection": (
            "You shipped today. Don't add anything new tomorrow. "
            "Protecting the rhythm is the work."
        ),
        "rationale": "Focus and momentum are both up. Recovery has consolidated.",
    },
]


def seed() -> None:
    init_db()
    today = date.today()

    for d in _DAYS:
        when = (today - timedelta(days=d["offset"])).isoformat()
        checkin_repo.add(d["checkin"], when=when)

        focus, stress, burnout, momentum, confidence, motivation = d["vec"]
        state = UserStateOut(
            focus=focus,
            stress=stress,
            burnout=burnout,
            momentum=momentum,
            confidence=confidence,
            motivation=motivation,
            weather_label=d["weather"],
            rationale=d["rationale"],
        )
        state_repo.add(state, ts=f"{when} 09:00:00")

        reflection_repo.add(
            content=d["reflection"],
            kind="daily",
            insights={"weather_label": d["weather"]},
            when=when,
        )

        episodic.add(d["reflection"], source="reflection:daily")

    semantic.upsert("evening_efficiency", "drops sharply after 9pm", confidence=0.7)
    semantic.upsert(
        "shipping_pattern",
        "tends to ship in short bursts after a quiet stretch",
        confidence=0.6,
    )

    timeline.add(
        "First RAG demo shipped",
        kind="milestone",
        description="A small but real end-to-end RAG demo, finished and posted.",
        tags=["rag", "ship"],
    )
    timeline.add(
        "Returned from a quiet stretch",
        kind="phase",
        description="Two days of rest, then a tiny PR closed; momentum re-entered.",
        tags=["recovery"],
    )

    print("Seeded WeatherFlow with synthetic data.")


if __name__ == "__main__":
    seed()
