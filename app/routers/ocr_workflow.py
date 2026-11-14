"""Carer-to-Nurse OCR Document Upload, Processing, Verification, and Approval Workflow."""
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app import auth, db, guidance, ocr

router = APIRouter()

MAX_DOC_BYTES = 6 * 1024 * 1024
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


def _upload_dir() -> Path:
    # Keep medical documents in a private folder next to the SQLite DB (never inside /static)
    folder = db.DB_PATH.parent / "ocr_uploads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _caller(
    allowed_roles: tuple[str, ...],
    authorization: str = "",
    x_session_token: str = "",
    x_role: str = "",
    x_user: str = "",
    x_resident_id: str = "",
) -> dict:
    """Resolve and authorise the caller from session token or role header."""
    sess = auth.session_from_headers(authorization, x_session_token)
    if sess:
        role = (sess.get("role") or "").lower()
        if role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied for role '{role}'. Required: {', '.join(allowed_roles)}.",
            )
        return {
            "username": sess.get("username") or "staff",
            "full_name": sess.get("full_name") or sess.get("username") or "Staff",
            "role": role,
            "resident_id": sess.get("resident_id"),
        }

    role_hdr = (x_role or "").strip().lower()
    if role_hdr:
        if role_hdr not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied for role '{role_hdr}'. Required: {', '.join(allowed_roles)}.",
            )
        default_name = "Nurse Sarah Johnson (RN)" if role_hdr == "nurse" else "Carer Mia"
        res_id = int(x_resident_id) if x_resident_id.strip().isdigit() else None
        return {
            "username": (x_user or f"{role_hdr}1").strip(),
            "full_name": (x_user or default_name).strip(),
            "role": role_hdr,
            "resident_id": res_id,
        }

    raise HTTPException(status_code=401, detail="Please sign in to access medical documents.")


def _check_resident_access(caller: dict, resident_id: int) -> None:
    """Ensure a user assigned to a specific resident cannot access another resident's documents."""
    assigned = caller.get("resident_id")
    if assigned is not None and int(assigned) != int(resident_id):
        raise HTTPException(
            status_code=403,
            detail="You are not authorised to access documents for this resident.",
        )


def _log_ocr_audit(
    conn,
    caller: dict,
    action: str,
    document_id: int | None,
    resident_id: int | None,
    detail: str,
) -> None:
    ts = db.now()
    conn.execute(
        "INSERT INTO ocr_audit_logs (user_id, user_name, role, action, document_id, resident_id, detail, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            caller["username"],
            caller["full_name"],
            caller["role"],
            action,
            document_id,
            resident_id,
            detail,
            ts,
        ),
    )
    db._audit(conn, caller["full_name"], caller["role"], action, resident_id, document_id, detail)


def _detect_mime(data: bytes, filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF, JPG, and PNG documents are allowed.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    raise HTTPException(status_code=400, detail="Invalid file format. Upload a real PDF, JPG, or PNG document.")


def _doc_row_to_dict(row, include_details: bool = False) -> dict:
    extracted = json.loads(row["extracted_json"] or "[]")
    out = {
        "id": row["id"],
        "document_id": row["id"],
        "resident_id": row["resident_id"],
        "resident_name": row["resident_name"],
        "uploaded_by": row["uploaded_by"],
        "uploader_name": row["uploader_name"],
        "uploader_role": row["uploader_role"],
        "original_filename": row["original_filename"],
        "mime_type": row["mime_type"],
        "document_type": row["document_type"],
        "carer_comment": row["carer_comment"],
        "upload_date": row["upload_date"],
        "processing_status": row["processing_status"],
        "review_status": row["review_status"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "review_comment": row["review_comment"],
        "file_url": f"/api/ocr/documents/{row['id']}/file",
        "extracted_fields": extracted,
    }
    if include_details:
        out["raw_text"] = row["raw_text"]
    return out


class OcrFieldEdit(BaseModel):
    key: str
    label: str = ""
    value: str = ""
    unit: str = ""


class NurseReviewRequest(BaseModel):
    decision: Literal["Approved", "Needs Correction", "Rejected"]
    review_comment: str = Field(default="", max_length=600)
    verified_accurate: bool = False
    reviewer_name: str = Field(default="", max_length=80)
    fields: list[OcrFieldEdit] = Field(default_factory=list)


@router.post("/api/ocr/documents", status_code=201)
async def upload_ocr_document(
    resident_id: int = Form(...),
    document_type: str = Form(default="Health Report"),
    carer_comment: str = Form(default=""),
    file: UploadFile = File(...),
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
    x_role: str = Header(default=""),
    x_user: str = Header(default=""),
    x_resident_id: str = Header(default=""),
):
    """Step 1 & 2: Carer (or Nurse) uploads a resident health document (PDF, JPG, PNG) and triggers OCR."""
    caller = _caller(("carer", "nurse"), authorization, x_session_token, x_role, x_user, x_resident_id)
    _check_resident_access(caller, resident_id)

    resident = guidance.load_resident(resident_id)
    if resident is None:
        raise HTTPException(status_code=404, detail="Resident not found.")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(status_code=413, detail="The document is too large. Upload a file under 6 MB.")

    filename = Path(file.filename or "document.png").name
    mime_type = _detect_mime(data, filename)

    ext = Path(filename).suffix.lower() or (".pdf" if mime_type == "application/pdf" else ".png")
    storage_ref = f"doc_{resident_id}_{uuid.uuid4().hex[:12]}{ext}"
    (_upload_dir() / storage_ref).write_bytes(data)

    # Run OCR processing
    processing_status = "Processing OCR"
    review_status = "Pending Nurse Review"
    raw_text = ""
    extracted_fields: list[dict] = []
    doc_type_final = (document_type or "Health Report").strip()

    try:
        lines = await run_in_threadpool(ocr.read_document_lines, data, filename)
        raw_text = "\n".join(f"{l.text} ({round(l.confidence * 100)}%)" for l in lines)
        extracted_fields = ocr.extract_document_fields(lines)
        for item in extracted_fields:
            if item["key"] == "document_type" and item["value"] and doc_type_final == "Health Report":
                doc_type_final = item["value"]
            if item["key"] == "resident_name" and not item["value"]:
                item["value"] = resident["name"]
        processing_status = "Pending Nurse Review"
        review_status = "Pending Nurse Review"
    except Exception as exc:
        processing_status = "OCR Failed"
        review_status = "OCR Failed"
        raw_text = f"OCR error: {exc}"
        extracted_fields = ocr.extract_document_fields([])

    ts = db.now()
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO ocr_documents ("
            "resident_id, resident_name, uploaded_by, uploader_name, uploader_role, "
            "original_filename, mime_type, storage_ref, document_type, carer_comment, "
            "upload_date, processing_status, review_status, raw_text, extracted_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                resident_id,
                resident["name"],
                caller["username"],
                caller["full_name"],
                caller["role"],
                filename,
                mime_type,
                storage_ref,
                doc_type_final,
                carer_comment.strip(),
                ts,
                processing_status,
                review_status,
                raw_text,
                json.dumps(extracted_fields),
            ),
        )
        doc_id = cur.lastrowid
        _log_ocr_audit(
            conn,
            caller,
            "ocr_document_uploaded" if review_status != "OCR Failed" else "ocr_processing_failed",
            doc_id,
            resident_id,
            f"Uploaded '{filename}' ({doc_type_final}) for {resident['name']} — status: {review_status}.",
        )
        row = conn.execute("SELECT * FROM ocr_documents WHERE id = ?", (doc_id,)).fetchone()

    return _doc_row_to_dict(row, include_details=True)


@router.get("/api/ocr/documents")
def list_ocr_documents(
    resident_id: int | None = None,
    status: str | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
    x_role: str = Header(default=""),
    x_user: str = Header(default=""),
    x_resident_id: str = Header(default=""),
):
    """List uploaded OCR documents for the Nurse Review Queue or Carer 'My Uploaded Documents' table."""
    caller = _caller(("carer", "nurse", "manager"), authorization, x_session_token, x_role, x_user, x_resident_id)
    if resident_id is not None:
        _check_resident_access(caller, resident_id)

    sql = "SELECT * FROM ocr_documents WHERE 1=1"
    args: list = []
    if caller.get("resident_id") is not None:
        sql += " AND resident_id = ?"
        args.append(int(caller["resident_id"]))
    elif resident_id is not None:
        sql += " AND resident_id = ?"
        args.append(resident_id)
    if status:
        sql += " AND review_status = ?"
        args.append(status)
    sql += " ORDER BY id DESC"

    with db.session() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_doc_row_to_dict(r, include_details=False) for r in rows]


@router.get("/api/ocr/documents/{doc_id}")
def get_ocr_document(
    doc_id: int,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
    x_role: str = Header(default=""),
    x_user: str = Header(default=""),
    x_resident_id: str = Header(default=""),
):
    """Get a single OCR document with its extracted fields, raw text, and review history."""
    caller = _caller(("carer", "nurse", "manager"), authorization, x_session_token, x_role, x_user, x_resident_id)
    with db.session() as conn:
        row = conn.execute("SELECT * FROM ocr_documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found.")
        _check_resident_access(caller, row["resident_id"])
        reviews = conn.execute(
            "SELECT * FROM ocr_reviews WHERE document_id = ? ORDER BY id DESC", (doc_id,)
        ).fetchall()

    out = _doc_row_to_dict(row, include_details=True)
    out["reviews"] = [
        {
            "id": rv["id"],
            "document_id": rv["document_id"],
            "reviewer_username": rv["reviewer_username"],
            "reviewer_name": rv["reviewer_name"],
            "decision": rv["decision"],
            "review_comment": rv["review_comment"],
            "verified_accurate": bool(rv["verified_accurate"]),
            "reviewed_at": rv["reviewed_at"],
            "corrected_fields": json.loads(rv["corrected_json"] or "[]"),
        }
        for rv in reviews
    ]
    return out


@router.get("/api/ocr/documents/{doc_id}/file")
def get_ocr_document_file(
    doc_id: int,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
    x_role: str = Header(default=""),
    x_user: str = Header(default=""),
    x_resident_id: str = Header(default=""),
):
    """Serve the original uploaded medical document only to authorised clinical staff."""
    caller = _caller(("carer", "nurse", "manager"), authorization, x_session_token, x_role, x_user, x_resident_id)
    with db.session() as conn:
        row = conn.execute("SELECT * FROM ocr_documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    _check_resident_access(caller, row["resident_id"])

    file_path = _upload_dir() / row["storage_ref"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Original document file is missing.")
    return Response(
        content=file_path.read_bytes(),
        media_type=row["mime_type"],
        headers={"Content-Disposition": f'inline; filename="{row["original_filename"]}"'},
    )


@router.post("/api/ocr/documents/{doc_id}/resubmit")
async def resubmit_ocr_document(
    doc_id: int,
    carer_comment: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
    x_role: str = Header(default=""),
    x_user: str = Header(default=""),
    x_resident_id: str = Header(default=""),
):
    """Step 6: Carer resubmits a corrected document or updated note when status is Needs Correction or OCR Failed."""
    caller = _caller(("carer", "nurse"), authorization, x_session_token, x_role, x_user, x_resident_id)
    with db.session() as conn:
        row = conn.execute("SELECT * FROM ocr_documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    _check_resident_access(caller, row["resident_id"])

    filename = row["original_filename"]
    mime_type = row["mime_type"]
    storage_ref = row["storage_ref"]
    raw_text = row["raw_text"]
    extracted_fields = json.loads(row["extracted_json"] or "[]")
    processing_status = "Pending Nurse Review"
    review_status = "Pending Nurse Review"

    if file is not None:
        data = await file.read()
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="The replacement file is empty.")
        if len(data) > MAX_DOC_BYTES:
            raise HTTPException(status_code=413, detail="The document is too large. Upload a file under 6 MB.")
        filename = Path(file.filename or filename).name
        mime_type = _detect_mime(data, filename)
        ext = Path(filename).suffix.lower() or ".png"
        storage_ref = f"doc_{row['resident_id']}_{uuid.uuid4().hex[:12]}{ext}"
        (_upload_dir() / storage_ref).write_bytes(data)
        try:
            lines = await run_in_threadpool(ocr.read_document_lines, data, filename)
            raw_text = "\n".join(f"{l.text} ({round(l.confidence * 100)}%)" for l in lines)
            extracted_fields = ocr.extract_document_fields(lines)
        except Exception as exc:
            processing_status = "OCR Failed"
            review_status = "OCR Failed"
            raw_text = f"OCR error: {exc}"

    with db.session() as conn:
        conn.execute(
            "UPDATE ocr_documents SET original_filename = ?, mime_type = ?, storage_ref = ?, "
            "carer_comment = ?, upload_date = ?, processing_status = ?, review_status = ?, "
            "raw_text = ?, extracted_json = ? WHERE id = ?",
            (
                filename,
                mime_type,
                storage_ref,
                carer_comment.strip() or row["carer_comment"],
                db.now(),
                processing_status,
                review_status,
                raw_text,
                json.dumps(extracted_fields),
                doc_id,
            ),
        )
        _log_ocr_audit(
            conn,
            caller,
            "ocr_document_resubmitted",
            doc_id,
            row["resident_id"],
            f"Resubmitted document #{doc_id} ('{filename}') for nurse review.",
        )
        updated = conn.execute("SELECT * FROM ocr_documents WHERE id = ?", (doc_id,)).fetchone()
    return _doc_row_to_dict(updated, include_details=True)


@router.post("/api/ocr/documents/{doc_id}/review")
def review_ocr_document(
    doc_id: int,
    body: NurseReviewRequest,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
    x_role: str = Header(default=""),
    x_user: str = Header(default=""),
):
    """Step 4 & 5: Nurse reviews, edits extracted fields, and Approves, Requests Correction, or Rejects."""
    caller = _caller(("nurse",), authorization, x_session_token, x_role, x_user)
    reviewer_name = body.reviewer_name.strip() or caller["full_name"]

    if body.decision == "Approved" and not body.verified_accurate:
        raise HTTPException(
            status_code=422,
            detail="You must confirm that you compared the extracted information with the original medical document.",
        )
    if body.decision in ("Needs Correction", "Rejected") and len(body.review_comment.strip()) < 3:
        raise HTTPException(
            status_code=422,
            detail="Please provide a review comment explaining the correction needed or reason for rejection.",
        )

    with db.session() as conn:
        row = conn.execute("SELECT * FROM ocr_documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found.")

        existing_fields = json.loads(row["extracted_json"] or "[]")
        if body.fields:
            edits_by_key = {f.key: f for f in body.fields}
            merged_fields: list[dict] = []
            seen_keys: set[str] = set()
            for item in existing_fields:
                k = item["key"]
                seen_keys.add(k)
                if k in edits_by_key:
                    edit = edits_by_key[k]
                    merged_fields.append({
                        **item,
                        "label": edit.label or item.get("label", k),
                        "value": edit.value.strip(),
                        "unit": edit.unit or item.get("unit", ""),
                        "needs_check": False,
                        "reason": "",
                    })
                else:
                    merged_fields.append(item)
            for k, edit in edits_by_key.items():
                if k not in seen_keys:
                    merged_fields.append({
                        "key": k,
                        "label": edit.label or k.replace("_", " ").title(),
                        "value": edit.value.strip(),
                        "unit": edit.unit,
                        "raw_line": "",
                        "confidence": 1.0,
                        "needs_check": False,
                        "reason": "",
                    })
        else:
            merged_fields = existing_fields

        ts = db.now()
        doc_type = row["document_type"]
        report_date = ""
        for f in merged_fields:
            if f["key"] == "document_type" and f["value"]:
                doc_type = f["value"]
            if f["key"] == "report_date" and f["value"]:
                report_date = f["value"]

        conn.execute(
            "UPDATE ocr_documents SET document_type = ?, processing_status = 'Completed', "
            "review_status = ?, extracted_json = ?, reviewed_by = ?, reviewed_at = ?, review_comment = ? "
            "WHERE id = ?",
            (
                doc_type,
                body.decision,
                json.dumps(merged_fields),
                reviewer_name,
                ts,
                body.review_comment.strip(),
                doc_id,
            ),
        )
        conn.execute(
            "INSERT INTO ocr_reviews (document_id, reviewer_username, reviewer_name, decision, "
            "corrected_json, review_comment, verified_accurate, reviewed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                caller["username"],
                reviewer_name,
                body.decision,
                json.dumps(merged_fields),
                body.review_comment.strip(),
                1 if body.verified_accurate else 0,
                ts,
            ),
        )

        # If Approved, also save verified clinical readings to the resident's readings history
        saved_items: list[dict] = []
        if body.decision == "Approved":
            saveable_labels = {
                "blood_pressure": ("Blood pressure", "mmHg"),
                "pulse": ("Pulse", "bpm"),
                "temperature": ("Temperature", "°C"),
                "spo2": ("Oxygen saturation", "%"),
                "weight": ("Weight", "kg"),
                "glucose": ("Blood glucose", "mmol/L"),
                "medications": ("Medication details", ""),
                "allergies": ("Allergy information", ""),
            }
            for f in merged_fields:
                k = f["key"]
                val = str(f.get("value", "")).strip()
                if k in saveable_labels and val:
                    lbl, unit = saveable_labels[k]
                    conn.execute(
                        "INSERT INTO readings (resident_id, key, label, value, unit, report_date, checked_by, saved_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (row["resident_id"], k, lbl, val, unit, report_date, reviewer_name, ts),
                    )
                    saved_items.append({"key": k, "label": lbl, "value": val, "unit": unit})

        action_map = {
            "Approved": "ocr_document_approved",
            "Needs Correction": "ocr_document_needs_correction",
            "Rejected": "ocr_document_rejected",
        }
        detail_msg = (
            f"{body.decision} OCR document #{doc_id} ('{row['original_filename']}') for {row['resident_name']}."
            + (f" Saved {len(saved_items)} verified fields." if saved_items else "")
            + (f" Note: {body.review_comment.strip()}" if body.review_comment.strip() else "")
        )
        _log_ocr_audit(conn, caller, action_map[body.decision], doc_id, row["resident_id"], detail_msg)
        updated = conn.execute("SELECT * FROM ocr_documents WHERE id = ?", (doc_id,)).fetchone()

    return _doc_row_to_dict(updated, include_details=True)


@router.get("/api/ocr/audit")
def list_ocr_audit_logs(
    limit: int = 50,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
    x_role: str = Header(default=""),
    x_user: str = Header(default=""),
):
    """Return OCR workflow audit history. Nurse and Manager get full access; Carer sees own logs."""
    caller = _caller(("carer", "nurse", "manager"), authorization, x_session_token, x_role, x_user)
    with db.session() as conn:
        if caller["role"] == "carer":
            rows = conn.execute(
                "SELECT * FROM ocr_audit_logs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (caller["username"], min(max(limit, 1), 200)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ocr_audit_logs ORDER BY id DESC LIMIT ?",
                (min(max(limit, 1), 200),),
            ).fetchall()
    return [dict(r) for r in rows]
