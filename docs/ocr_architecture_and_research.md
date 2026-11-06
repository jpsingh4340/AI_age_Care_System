# OCR Health Report Reader & 4-Role Architecture Notes

**Author:** Jaspreet Singh  
**Course:** IA728001 Studio 5  

## 1. Decomposed OCR Subcomponent & Information Flow

Instead of treating the backend as a single box, the OCR Health Report Reader (`app/ocr.py` and `app/main.py`) is decomposed into five distinct processing stages before any reading reaches SQLite:

1. **Binary Magic-Byte & Size Validator (`POST /api/ocr/extract`)**:
   - Rejects files over 6 MB (`413`) and checks PNG (`\x89PNG\r\n\x1a\n`) or JPEG (`\xff\xd8\xff`) magic bytes (`400`) before touching the OCR engine.
2. **Local ONNX Text Detector & Recognizer (`read_lines`)**:
   - Runs `RapidOCR` in a background thread (`run_in_threadpool`) to detect text bounding boxes `(x, top, bottom)` and per-box confidence scores `(0.0 - 1.0)`.
3. **Geometric Row Grouping (`group_into_lines`)**:
   - Sorts boxes top-to-bottom by vertical midpoint `(top + bottom) / 2` and merges boxes whose vertical midpoints are within `max(10, 0.6 * height)` pixels, then sorts left-to-right by `x`.
4. **Deterministic Regex & Physiological Range Checker (`extract_readings`, `_check`)**:
   - Matches 7 vital fields (`report_date`, `blood_pressure`, `pulse`, `temperature`, `spo2`, `weight`, `glucose`) using regex rules (`FIELDS`) and flags `needs_check = True` when confidence `< 0.70` or values fall outside `RANGES`.
5. **Mandatory Nurse Verification & Audit Gate (`static/ocr.html`, `POST /api/residents/{id}/readings`)**:
   - Locks the Save button until the nurse ticks every extracted value against the report photo, then validates format (`value_error`) and writes to `readings` and `audit_log`.

## 2. Comparison with Existing Aged-Care & OCR Systems

| Feature / System | VCare / eCase (NZ Aged-Care EHR) | Medi-Map (NZ Medication Charting) | Cloud Consumer Medical OCR | Care Signal / AgeCare (Our System) |
|---|---|---|---|---|
| **Printed Report OCR** | Manual keyboard entry | None | Cloud OCR + LLM | Local `RapidOCR` (ONNX) + Regex Rules |
| **Digit Hallucination Prevention** | N/A | N/A | None (LLM can alter numbers) | Deterministic regex + physiological range check (`RANGES`) |
| **Data Privacy** | Cloud | Cloud | External cloud API | 100% offline local processing |
| **Mandatory Nurse Tick-Box Gate** | Manual entry | Pharmacist/GP only | None | Required before `Save` unlocks |
| **4-Role Connected Workflow** | Staff only | Prescriber/Staff | Single user | Carer -> Nurse -> Manager -> Family |

