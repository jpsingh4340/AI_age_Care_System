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
    topic: str = ""  # for example "falls"; empty for care plan lines


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
    gaps: list[str] = []  # conditions that have no kept line, so the nurse can add one
    sources: list[SourceOut]
    model: str
    seconds: float
    draft_id: int  # the saved draft a nurse will review
    status: str = "draft"  # becomes "approved" only after a nurse approves
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




# ---------- Nurse approval and audit log ----------
class StoredLine(BaseModel):
    text: str
    source_id: str = ""
    source: str = ""
    quote: str = ""
    edited: bool = False  # True when a nurse wrote or changed the wording


class DraftOut(BaseModel):
    draft_id: int
    resident_id: int
    resident: str
    conditions: list[str]
    status: str  # draft, approved, rejected or replaced
    created_at: str
    model: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    watch_for: list[StoredLine]
    prevention: list[StoredLine]
    dropped: list[DroppedLine]
    gaps: list[str] = []
    sources: list[SourceOut]
    sources: list[SourceOut]


class DraftSummary(BaseModel):
    draft_id: int
    resident_id: int
    resident: str
    created_at: str
    lines: int


class FinalLine(BaseModel):
    text: str
    source_id: str = ""
    edited: bool = False


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=2, max_length=60)  # the nurse's name
    note: str = Field(default="", max_length=500)
    # The nurse's final lists. Leave out to approve the draft exactly as it is.
    watch_for: list[FinalLine] | None = None
    prevention: list[FinalLine] | None = None


class ApprovedOut(BaseModel):
    draft_id: int
    resident_id: int
    resident: str
    approved_by: str
    approved_at: str
    note: str
    watch_for: list[StoredLine]
    prevention: list[StoredLine]


class AuditOut(BaseModel):
    id: int
    at: str
    actor: str
    role: str
    action: str
    resident_id: int | None
    draft_id: int | None
    detail: str


    

# ---------- Saved health values and resident records (fake data) ----------
class ReadingIn(BaseModel):
    key: str  # for example "pulse"
    value: str  # the value the nurse checked, for example "76" or "128/82"


class SaveReadingsRequest(BaseModel):
    reviewer: str = Field(min_length=2, max_length=60)  # the nurse who checked the values
    report_date: str = ""  # the date printed on the report, as the nurse read it
    readings: list[ReadingIn] = Field(min_length=1, max_length=20)


class SavedReading(BaseModel):
    id: int
    key: str
    label: str
    value: str
    unit: str
    report_date: str
    checked_by: str
    saved_at: str


class Contact(BaseModel):
    name: str
    relationship: str
    phone: str


class Doctor(BaseModel):
    name: str
    practice: str
    phone: str


class CareTask(BaseModel):
    task: str
    status: Literal["given", "refused", "not_done"]
    time: str
    by: str


class Concern(BaseModel):
    type: str
    text: str  # the carer's own words
    time: str


class HistoryPoint(BaseModel):
    date: str
    value: float


class RecordsOut(BaseModel):
    resident_id: int
    name: str
    conditions: list[str]
    allergies: list[str]
    doctor: Doctor
    contacts: list[Contact]
    care_plan: list[str]
    care_record: list[CareTask]
    concerns: list[Concern]
    readings_history: dict[str, list[HistoryPoint]]  # fake past values for graphs
    readings_saved: list[SavedReading]  # values a nurse checked and saved


# ---------- Authentication & Roles ----------
class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    full_name: str = Field(min_length=2, max_length=100)
    role: Literal["nurse", "carer", "patient"]
    resident_id: int | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    username: str
    full_name: str
    role: str
    resident_id: int | None = None


class AuthResponse(BaseModel):
    token: str
    username: str
    full_name: str
    role: str
    resident_id: int | None = None
    expires_at: str


# ---------- Patient / Resident Portal Schemas ----------
class PatientWellbeingRequest(BaseModel):
    sentiment: Literal["great", "okay", "uncomfortable", "in_pain"]
    note: str = ""


class PatientCallBellRequest(BaseModel):
    request_type: str = Field(min_length=2, max_length=100)


class PatientScheduleItem(BaseModel):
    time: str
    title: str
    status: str
    completed_by: str | None = None


class ResidentProfileDetails(BaseModel):
    full_name: str
    preferred_name: str
    age: int
    wing: str
    primary_doctor: str
    assigned_nurse: str
    mobility_status: str
    dietary_plan: str
    emergency_contact: dict


class MealPlanItem(BaseModel):
    meal_type: str
    dish: str
    beverage: str
    dietary_badge: str


class ActivityItem(BaseModel):
    time: str
    title: str
    location: str
    joined: bool = False


class FamilyMessage(BaseModel):
    sender: str
    relationship: str
    timestamp: str
    message: str


class PatientDayResponse(BaseModel):
    resident_id: int
    name: str
    room: str
    schedule: list[PatientScheduleItem]
    approved_guidance: list[str]
    latest_sentiment: str | None = None
    profile_details: ResidentProfileDetails | None = None
    meals_today: list[MealPlanItem] = []
    activities_today: list[ActivityItem] = []
    family_messages: list[FamilyMessage] = []
    water_cups_logged: int = 0
    water_cups_target: int = 6


class PatientWaterLogRequest(BaseModel):
    amount_cups: int = 1


class PatientCompanionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    resident_id: int | None = None


class PatientCompanionResponse(BaseModel):
    reply: str
    speech_text: str
    emergency_alert: bool = False
    suggested_followups: list[str] = []