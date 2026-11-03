# Carer to nurse to family handover workflow

Student project, Otago Polytechnic. FAKE DATA ONLY. Not for real residents.

This page explains how a shift moves from the carer, to the nurse, to the family.
The AI only drafts. A registered nurse checks and approves everything before
carers or families see it.

## The flow in one picture

    Nurse: Schedule        Carer: My shift          Carer: Handover
    daily care plan  --->  notes, tasks,      --->  AI drafts ISBAR handover,
    and medicines          vital signs,             carer checks and sends
                           ticks the plan                   |
                                                            v
    Family: Updates  <---  Nurse: Handovers    <---  waiting for nurse
    reads update,          edits, approves or
    chats with nurse       sends back; AI drafts
                           family update; chat

## 1. Nurse sets the care plan (Schedule page, /nurse/schedule)
- Pick a resident and add daily tasks: shower, meals, walks, change position, medicine rounds.
- Each task can have a time, a note for carers, and days of the week (no days ticked = every day).
- A task whose name mentions medicines (medicine, medication, meds, tablets, pills, insulin,
  inhaler, eye drops) is always a medicine round.
- For a medicine round the nurse lists each medicine from the medicine chart:
  name, dose, how it is given and instructions. Saving needs a tick:
  "I have checked these against [resident]'s medicine chart". The app records who checked and when.
- The medicine chart stays the legal record. The AI never suggests medicines.

## 2. Carer works the shift (My shift page, /carer)
- Pick a resident with the big resident buttons.
- Quick note: short notes as things happen ("Ate half of lunch").
- Care task, Vital signs and Concern tabs record the usual shift records.
  A reading outside the usual range tells the carer to inform the nurse.
- Today's care plan (right side): switch each task on when it is done.
  Tasks past their time show "Overdue".
- Medicine rounds are locked unless the manager has signed the carer off as medication competent.
  A round that includes an injection can only be ticked by a nurse.
- "This shift so far" lists everything recorded today for the resident.

## 3. Carer sends the handover (Handover page, /handover)
- Shifts: AM 07:00 to 15:00, PM 15:00 to 23:00, Night 23:00 to 07:00.
  In the first hour of a shift the page suggests the shift that just ended.
- The table shows each resident's handover status:
  Not started, Draft, Waiting for nurse, Approved, Sent back.
- "Draft handover" asks the local AI (Ollama) to write an ISBAR handover from the shift's records:
  - Identify: resident, room, shift, carer
  - Situation: concerns and readings outside the usual range first
  - Background: the resident's recorded conditions
  - Assessment: what the carer saw and did
  - Recommendation: what to check, and care plan tasks still to do
- The carer's records are shown next to the draft, with times.
- The carer fixes anything wrong and presses "Send to nurse".
- If the AI is off, or adds a medicine, dose or diagnosis word the carer never wrote,
  a rule-based ISBAR draft is used instead.

## 4. Nurse reviews (Handovers page, /nurse/handover)
- The navigation bar shows a number on "Handovers": handovers waiting plus unread family
  messages. It turns red if a family message may be urgent.
- The nurse reads the AI summary next to the carer's timed notes and edits it.
- "Approve handover" saves the nurse's version. "Send back to carer" needs a note saying what to change.
- Every decision is saved in the audit log.

## 5. Family update and messages (Handovers page, then Family page /family)
- After approval, "Draft family update with AI" writes a short, kind update from the approved handover.
- Family updates never include clinical numbers or words like SpO2, pulse or blood pressure.
  If the AI writes one, a safe plain message is used instead.
- The nurse edits the update and presses "Approve and send to family".
- Nurse and family message each other in one thread per resident.
- Family messages that mention a fall, pain, breathing, hospital and similar are flagged as urgent
  for the nurse. The family is told to phone reception for anything urgent.
- Families only see nurse-approved updates and the messages about their own family member.

## Who can do what
| Action | Carer | Nurse | Manager | Family |
|---|---|---|---|---|
| Set the care plan and medicines | | yes | | |
| Write notes, tasks, vital signs | yes | yes | | |
| Tick a normal care plan task | yes | yes | | |
| Tick a medicine round | if signed off | yes | | |
| Tick a round with an injection | | yes | | |
| Draft and send a handover | yes | yes | | |
| Approve or send back a handover | | yes | | |
| Send a family update | | yes | | |
| Sign a carer off for medicines | | | yes | |
| Read updates, message the nurses | | yes | | yes |

## Main API endpoints
| Endpoint | Used for |
|---|---|
| `POST /api/carer/notes` | carer quick note |
| `GET/POST/PUT/DELETE /api/schedule` | care plan |
| `POST /api/schedule/{id}/done` | tick a care plan task |
| `GET /api/shifts` | current and previous shift |
| `POST /api/handovers/draft` | AI drafts the ISBAR handover |
| `POST /api/handovers/{id}/send` | carer sends to nurse |
| `POST /api/handovers/{id}/review` | nurse approves or sends back |
| `POST /api/handovers/{id}/family-draft` | AI drafts the family update |
| `GET/POST /api/chat/{resident_id}` | nurse and family messages |
| `GET /api/chat/urgent` | urgent family messages |
| `GET /api/workflow/counts` | numbers for the navigation bar |
| `PUT /api/manager/users/{username}/medicines` | manager medicine sign-off |

Code: `app/routers/handover.py`. Tests: `tests/test_handover.py`.

## Demo accounts
nurse1, carer1, family1 (Margaret T.'s daughter) and manager1. Password: password123.
