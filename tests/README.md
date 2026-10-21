# Age-Care Intelligence System (backend)
Student project, Otago Polytechnic. FAKE DATA ONLY.

## Setup (Python 3.13)
    py -3.13 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    ollama pull llama3.2:3b
    ollama pull nomic-embed-text

## Run
    uvicorn app.main:app --reload
Open http://127.0.0.1:8000 (guidance), /ocr (health report), /docs (API).

## Test
    python -m pytest -q

## Notes
- The model runs on the CPU only. To use the GPU: set NUM_GPU=-1.
- The database file is data/agecare.db. It is not committed.
- X-Role (nurse/carer) is a prototype header, NOT real login.