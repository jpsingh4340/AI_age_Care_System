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
| Rules only (fixed numbers) | Same result every time, easy to explain and test | Cannot read carer notes written in normal words | TODO |
| AI only (Ollama reads everything) | Can read notes in normal words | Can make things up; hard to explain; numbers can be wrong | TODO |
| Rules + AI (my choice) | Rules handle numbers safely; AI explains notes with exact quotes | More parts to build and test | TODO |

**My decision:** TODO – explain in your own words why Rules + AI is the best choice.
(Our lecturer Ganeshan also recommended a combination of both by email on 26 October.)

## 3. Where the thresholds come from (NZEWS)

Source: Te Tāhū Hauora Health Quality & Safety Commission. *Vital signs chart with
New Zealand early warning score.*
https://www.hqsc.govt.nz/resources/resource-library/vital-signs-chart-with-new-zealand-early-warning-score/

TODO: Open the chart PDF and copy the score bands for each vital sign:

| Vital sign | Score 3 (red zone) | Score 2 | Score 1 | Score 0 (normal) |
|---|---|---|---|---|
| Oxygen (SpO2) | TODO | TODO | TODO | TODO |
| Temperature | TODO | TODO | TODO | TODO |
| Pulse (heart rate) | TODO | TODO | TODO | TODO |
| Systolic blood pressure | TODO | TODO | TODO | TODO |

TODO: Explain how I turn these bands into Green, Amber and Red in `app/decision_rules.py`.

**Limitation:** NZEWS is designed for hospitals. Our project is a student prototype
using fake data, so we use it only as a guide.

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
