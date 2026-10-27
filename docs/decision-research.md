# Care Priority Decision Feature – Research Notes

Author: Tanveer Singh (Team Trio)
Started: 27 October 2026

These notes explain why I built the decision feature the way I did. Parts marked
**TODO** are for me to research and write in my own words.

---

## 1. The problem

In New Zealand rest homes, nurses and carers look after many residents at the same time. Every day they have a lot of vital signs (pulse, blood pressure, temperature and oxygen) and many carer notes to read, but very little time. Because of this, an important warning can be missed, for example a low oxygen level or a carer note like "only had a few sips of tea at lunch", and the resident may not get help early enough.

My decision feature helps by giving each resident one simple priority: Green (OK), Amber (a nurse should check) or Red (a nurse should see them now). Each priority shows the reason and where it came from, and the nurse always makes the final decision.

## 2. Options I compared
| Option | Good points | Weak points | My score (1–5) |
|---|---|---|---|
| Rules only (fixed numbers) | Same result every time, easy to explain and test | Cannot read carer notes written in normal words | 3 |
| AI only (Ollama reads everything) | Can read notes in normal words | Can make things up, hard to explain, may get numbers wrong | 2 |
| Rules + AI (my choice) | Rules check the numbers safely, and the AI explains the notes with exact quotes | More parts to build and test | 5 |

**My decision:** I chose Rules + AI. Numbers like oxygen and temperature are checked by rules, because rules always give the same answer and are easy to explain. The AI is only used to read carer notes and explain them, and my code checks that every quote is really in the note. This keeps the decision safe, because the AI cannot make the final clinical judgement, and the nurse always decides. Our lecturer Ganeshan also recommended a combination of both by email on 26 October 2026.

## 3. Where the thresholds come from (NZEWS)

Source: Te Tāhū Hauora Health Quality & Safety Commission. *Adult vital signs chart with New Zealand early warning score.*

| Vital sign | Score 0 | Score 1 | Score 2 | Score 3 (red zone) | Blue zone |
|---|---|---|---|---|---|
| Oxygen (SpO2 %) | 96 or more | 94–95 | 92–93 | 91 or less | – |
| Heart rate (bpm) | 50–89 | 90–109 | 40–49 or 110–129 | 130–139 | 39 or less, or 140+ |
| Systolic BP (mmHg) | 110–219 | 100–109 | 90–99 | 70–89 or 220+ | 69 or less |
| Temperature (°C) | 36.0–37.9 | 35.0–35.9 or 38.0–38.9 | 34.9 or less, or 39.0+ | – | – |

How I use it in app/decision_rules.py: each vital sign gets its NZEWS score. Any vital sign in the red or blue zone, or a total of 8 or more, gives Red. A total of 1 to 7 gives Amber, and 0 gives Green. This follows the chart's escalation pathway (8–9 or any red zone, 10+ or any blue zone).

The chart also says: "Escalate care for any patient you, they or their family are worried about, regardless of vital signs or EWS." This is why my feature also reads carer notes, not only the numbers.

**Limitation:** NZEWS is designed for hospitals and uses 7 vital signs. Our fake records only have 4 (no respiratory rate, supplemental oxygen or level of consciousness), so we use it only as a guide for a student prototype.

## 4. Ethical and legal points

TODO: Write 1–2 sentences for each:

- **Privacy Act 2020:** TODO
- **Health Information Privacy Code 2020:** TODO
- **Algorithm Charter for Aotearoa New Zealand:** TODO (why the AI must be explainable
  and a human must decide)
- **Safety:** the feature never diagnoses or suggests medicines; the nurse makes the
  final decision; every decision is saved in the audit log.

## 5. Risks and how I reduce them

| Risk | How I reduce it |
|---|---|
| The AI makes up a concern | My code removes any quote that is not really in the note |
| The AI makes something look more serious than it is | The AI can only raise a note to Amber; only the rules can give Red |
| Wrong thresholds | Use the NZEWS chart and test every threshold |
| TODO | TODO |

## 6. Prompt log (for the AI part, Week 5)

| Version | Date | What I changed | Result on the fake residents |
|---|---|---|---|
| v1 | TODO | First prompt | TODO |

## References (APA)

Te Tāhū Hauora Health Quality & Safety Commission. (2021). *Vital signs chart with New
Zealand early warning score* [Interactive chart].
https://www.hqsc.govt.nz/resources/resource-library/vital-signs-chart-with-new-zealand-early-warning-score/

TODO: add the Privacy Act 2020, the Health Information Privacy Code 2020 and the
Algorithm Charter.
