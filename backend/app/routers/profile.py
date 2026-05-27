"""Profile.md read/edit endpoints."""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.memory import profile_md
from app.memory.profile_md import SECTION_ORDER
from app.memory.schemas import ProfileSection

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileOut(BaseModel):
    path: str
    markdown: str
    sections: Dict[ProfileSection, str]


class SectionEditIn(BaseModel):
    content: str


@router.get("", response_model=ProfileOut)
def get_profile() -> ProfileOut:
    path = profile_md.ensure_profile()
    return ProfileOut(
        path=str(path),
        markdown=profile_md.read_profile(),
        sections=profile_md.read_sections(),
    )


@router.get("/sections", response_model=List[str])
def list_sections() -> list[str]:
    return list(SECTION_ORDER)


@router.put("/sections/{section}", response_model=dict)
def edit_section(section: ProfileSection, body: SectionEditIn) -> dict:
    if section not in SECTION_ORDER:
        raise HTTPException(status_code=400, detail=f"Unknown section: {section}")
    path = profile_md.write_section(section, body.content)
    return {"section": section, "path": str(path)}
