from typing import Literal

from pydantic import BaseModel, Field

# The only flag types the AI is allowed to use
FlagType = Literal[
    "Not eating",
    "Low fluids",
    "Fall risk",
    "Mobility",
    "Pain",
    "Vomiting",
    "Poor sleep",
    "Mood",
    "Other",
]


# ---------- What we force the small model to return ----------
class Flag(BaseModel):
    type: FlagType
    evidence: str  # exact words from the carer's note


class NoteAnalysis(BaseModel):
    summary: str
    flags: list[Flag]


class PlanItemCheck(BaseModel):
    item_number: int
    status: Literal["met", "not_mentioned", "off_plan"]
    note_evidence: str


class PlanCheckResult(BaseModel):
    checks: list[PlanItemCheck]


# ---------- What our API receives and sends ----------
class AnalyseRequest(BaseModel):
    resident_id: int
    note: str = Field(min_length=3, max_length=4000)
    use_rag: bool = True  # turn off to test the SLM alone


class RetrievedChunk(BaseModel):
    source: str
    text: str
    score: float


class PlanCheckOut(BaseModel):
    plan_item: str
    source: str
    status: str  # met, not_mentioned, off_plan, or unclear
    note_evidence: str


class AnalyseResponse(BaseModel):
    summary: str
    flags: list[Flag]
    dropped_flags: list[Flag]  # flags the AI made up (evidence not in the note)
    plan_checks: list[PlanCheckOut]
    retrieved: list[RetrievedChunk]  # the lines RAG found, so we can show our work
    model: str
    seconds: float
    status_note: str = "AI draft. A nurse must check and approve it."


# ---------- Feature A: symptoms to watch for and prevention ----------
class GuidanceLine(BaseModel):
    text: str  # one short plain-English sentence
    source_id: str  # for example "S3": which numbered source the line comes from
    quote: str  # words copied exactly from that source


class GuidanceDraft(BaseModel):
    watch_for: list[GuidanceLine]
    prevention: list[GuidanceLine]


class GuidanceRequest(BaseModel):
    resident_id: int


class SourceOut(BaseModel):
    id: str
    source: str
    text: str


class CheckedLine(BaseModel):
    text: str
    source_id: str
    source: str  # human name, for example "Reference note: Hydration"
    quote: str


class DroppedLine(BaseModel):
    list_name: str  # watch_for or prevention
    text: str
    source_id: str
    quote: str
    reason: str  # why the automatic check removed it


class GuidanceResponse(BaseModel):
    resident: str
    conditions: list[str]
    watch_for: list[CheckedLine]
    prevention: list[CheckedLine]
    dropped: list[DroppedLine]  # lines the check removed, so we can measure it
    sources: list[SourceOut]
    model: str
    seconds: float
    status: str = "draft"  # becomes "approved" only after a nurse approves (next step)
    status_note: str = "AI draft from approved sources. A nurse must approve it before anyone else sees it."




# ---------- OCR: read a photo of a fake health report ----------
class OcrLineOut(BaseModel):
    text: str
    confidence: float  # 0 to 1: how sure the OCR is about this line


class Reading(BaseModel):
    key: str  # for example "pulse"
    label: str  # for example "Pulse"
    value: str  # kept as text exactly as read, for example "128/82"
    unit: str
    raw_line: str  # the whole line the OCR read, so a nurse can compare
    confidence: float
    needs_check: bool  # True when the OCR is unsure or the number looks unusual
    reason: str


class OcrResponse(BaseModel):
    readings: list[Reading]
    lines: list[OcrLineOut]  # everything the OCR read, so we can show our work
    seconds: float
    status_note: str = "Read by OCR. A nurse must check every value against the photo before it is saved."