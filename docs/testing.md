# Testing: UI redesign and handover workflow

Student project, Otago Polytechnic. FAKE DATA ONLY.

Branch: `feature/carer-nurse-handover` (pull request #47).
Tested by: Tanveer Singh.

## 1. Automated tests

Run from the project folder:

    python -m pytest

Result: **159 passed** (1 warning from the test client library, not from our code).

| Test file | Tests | What it covers |
|---|---|---|
| tests/test_handover.py | 20 | notes, care plan, days, medicine rounds and medicine list, shifts, ISBAR handover, nurse review, family update, chat, urgent messages, nav counts |
| tests/test_carer.py | 10 | carer tasks, vital signs, concerns, sign-in needed |
| tests/test_auth.py | 11 | sign in, roles, family update approval |
| tests/test_guidance.py | 16 | guidance drafting |
| tests/test_decision_rules.py | 14 | care priority rules |
| tests/test_decision_api.py | 10 | care priority API |
| tests/test_cue_check.py | 13 | face cue check |
| tests/test_vision_api.py | 12 | camera alerts |
| other files | 53 | approval, ask AI, OCR, records, RAG, fall rules, Ollama retry |

The AI is replaced by a fake answer in tests, so they run without Ollama.

Key safety tests in `tests/test_handover.py`:
- a carer cannot tick a medicine round unless the manager signed them off
- a round with an injection can only be ticked by a nurse
- medicines are only saved after the nurse confirms the medicine chart was checked
- a task named with medicine words is always a medicine round, even if the box is unticked
- if the AI adds a medicine or dose the carer never wrote, the rule-based draft is used
- a family update that mentions SpO2 or other readings falls back to the safe text
- a family account can only see and send messages about its own family member

## 2. Browser tests (manual)

Setup: `uvicorn app.main:app --reload`, Ollama running, Microsoft Edge.
Accounts: nurse1, carer1, family1, manager1 (password: password123).
Use two different browsers when two people need to be signed in at the same time.

Result: Pass, Fail, or Not run yet. Fill in the date when tested.

### A. Sign-in and roles
| # | Steps | Expected | Result |
|---|---|---|---|
| A1 | Open /nurse without signing in | Sent to the sign-in page | Not run yet |
| A2 | Sign in as carer1, open /nurse | Sent to the carer's page | Not run yet |
| A3 | Carer page open, sign in as manager1 in another tab | Carer tab switches to the manager page | Not run yet |

### B. Care schedule (nurse)
| # | Steps | Expected | Result |
|---|---|---|---|
| B1 | Schedule, Margaret: add Hair wash with one day ticked | Days column shows that day; "Not today" on other days | Pass |
| B2 | Add a task with a time already passed | "Overdue" | Pass |
| B3 | Click the Medicine round quick pick | Notice shows, medicine box ticked and locked, medicine list appears | Pass |
| B4 | Add two medicines, save without the chart tick | Refused: asks to tick the chart box | Pass |
| B5 | Tick the chart box, save | Medicines listed with "Checked against the chart by" | Pass |
| B6 | Edit the round, remove a medicine, save with the chart tick | List updated | Pass |
| B7 | Add an Insulin round with route "Injection (nurse only)" | Row says "Includes an injection: nurse only" | Pass |

### C. Carer shift
| # | Steps | Expected | Result |
|---|---|---|---|
| C1 | carer1, My shift, Margaret | Care plan shows medicines under the medicine round, switch locked | Pass |
| C2 | Manager signs carer1 off, carer refreshes | Medicine round switch unlocked and can be ticked | Pass |
| C3 | Injection round with a signed-off carer | Still locked: nurse only | Pass |
| C4 | Switch on a normal task | "Done by ... at ..." and shown in This shift so far | Pass |
| C5 | Save two quick notes | Shown in This shift so far | Not run yet |
| C6 | Save SpO2 92 | Amber message to tell the nurse | Not run yet |

### D. Handover (carer to nurse)
| # | Steps | Expected | Result |
|---|---|---|---|
| D1 | Handover page | Two shift choices; the right one is picked | Not run yet |
| D2 | Draft handover for Margaret | ISBAR draft with Identify, Situation, Background, Assessment, Recommendation; records listed with times | Not run yet |
| D3 | Send to nurse | Status "Waiting for nurse" | Not run yet |
| D4 | nurse1, dashboard and Handovers | Number on Handovers in the nav bar; handover listed | Not run yet |
| D5 | Send back without a note | Asks for a note | Not run yet |
| D6 | Send back with a note | Carer sees "Sent back" and the reason; carer can send again | Not run yet |
| D7 | Edit and approve | Status "Approved"; shown as labelled ISBAR sections | Not run yet |

### E. Family update and messages
| # | Steps | Expected | Result |
|---|---|---|---|
| E1 | Draft family update with AI | Short "Kia ora" update with no clinical numbers | Not run yet |
| E2 | Approve and send | family1 sees the update at the top | Not run yet |
| E3 | family1 sends "Mum had a fall" | Amber message to phone reception | Not run yet |
| E4 | nurse1 refreshes | Red number in the nav bar; message highlighted as urgent | Not run yet |
| E5 | Nurse replies in the chat | Reply shows on the family page | Not run yet |

### F. Phone and dark mode
| # | Steps | Expected | Result |
|---|---|---|---|
| F1 | Each page at phone width (375px) | No sideways scrolling; Menu button opens the navigation | Not run yet |
| F2 | Each page with Windows dark mode on | Readable dark colours | Not run yet |

## 3. Problems found while testing and fixed
| Problem | Fix |
|---|---|
| The AI wrote "She has a low SpO2" in a family update | Family drafts with clinical words or numbers fall back to safe text |
| A medicine round could be saved as a normal task if the box was unticked by mistake | Names with medicine words are always medicine rounds; box locked |
| Medicine label was hard to see | Teal "Medicine" tag and a notice as soon as a medicine task is picked |
| Medicine fields were squashed in the narrow form | Each medicine uses two rows |
| Signing in as another account in one tab broke the other tabs with "Your account does not have access" | Tabs now follow the signed-in account; the message says who is signed in |
| Carer endpoints accepted requests without sign-in | They now need a signed-in carer or nurse |
| Nurse dashboard showed carer concerns twice | Duplicates removed |
