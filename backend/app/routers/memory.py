"""Profile memory endpoint.

The lightweight WeatherFlow loop exposes one long-term memory surface:
`profile.md`.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from app.memory import profile_md

router = APIRouter(prefix="/api/memory", tags=["memory"])


class ProfileOut(BaseModel):
    markdown: str
    path: str


@router.get("/profile", response_model=ProfileOut)
async def get_profile() -> ProfileOut:
    path = profile_md.ensure_profile()
    return ProfileOut(markdown=profile_md.read_profile(max_chars=12000), path=str(path))
