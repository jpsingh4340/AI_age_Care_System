"""API for the Care Priority Decision feature (written by Tanveer).

GET  /api/residents/{resident_id}/decision          the suggested priority, reasons and sources
POST /api/residents/{resident_id}/decision/review   a nurse accepts or changes it (nurse only)
"""
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app import auth, decision

router = APIRouter()

Level = Literal["Green", "Amber", "Red"]


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=2, max_length=60)
    suggested: Level
    final: Level
    note: str = Field(default="", max_length=300)


def _need_nurse(x_role: str, x_session_token: str) -> None:
    """Only a nurse may accept or change a priority (same check as the rest of the app)."""
    if x_role.strip().lower() == "nurse":
        return
    session = auth.get_session(x_session_token) if x_session_token else None
    if session and session["role"] == "nurse":
        return
    raise HTTPException(status_code=403, detail="Only a nurse can accept or change a priority.")


@router.get("/api/residents/{resident_id}/decision")
def get_decision(resident_id: int, use_ai: bool = True):
    """Rules (NZEWS) + AI reading the carer notes. Use use_ai=false for the rules only."""
    result = decision.build_decision(resident_id, use_ai=use_ai)
    if result is None:
        raise HTTPException(status_code=404, detail="Resident not found.")
    return result


@router.post("/api/residents/{resident_id}/decision/review")
def review_decision(
    resident_id: int,
    body: ReviewIn,
    x_role: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    _need_nurse(x_role, x_session_token)
    if body.final != body.suggested and not body.note.strip():
        raise HTTPException(status_code=422, detail="Please write why you changed the priority.")
    return decision.save_review(resident_id, body.reviewer.strip(), body.suggested, body.final, body.note.strip())