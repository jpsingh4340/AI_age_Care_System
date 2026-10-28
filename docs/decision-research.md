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

- **Privacy Act 2020:** This law has 13 privacy principles about how personal information is collected, stored, used and shared. Our project uses only fake residents, so no real personal information is collected. If the system was used for real, we would only collect what is needed and keep it safe.

- **Health Information Privacy Code 2020:** This code has 13 rules for health information, which is extra sensitive. In our system, only staff with the right role can see the decision, carers cannot change it, and every nurse decision is saved in the audit log, so we can see who did what and when.

- **Algorithm Charter for Aotearoa New Zealand:** This charter is signed by NZ government agencies and asks them to make algorithms transparent, explainable and checked by a human. Our project is not a government system, but we follow it as good practice: every priority shows its reason and source, the rules are based on a published chart (NZEWS), and a nurse always makes the final decision.

- **Safety:** The feature only gives a priority and a suggested check. It never diagnoses, never names medicines or doses, and the AI can only raise a note to Amber, never Red. Only the NZEWS rules can give Red.

- **Honesty about limits:** This is a student prototype with fake data. NZEWS is made for hospitals and we only have 4 of its 7 vital signs, so the results are a guide, not a clinical decision.

## 5. References (APA)
Department of Internal Affairs & Stats NZ. (2020). *Algorithm charter for Aotearoa New Zealand*. https://data.govt.nz/toolkit/data-ethics/government-algorithm-transparency-and-accountability/algorithm-charter/

Privacy Act 2020. https://www.legislation.govt.nz/act/public/2020/0031/latest/whole.html

Privacy Commissioner. (2020). *Health information privacy code 2020*. https://www.privacy.org.nz/privacy-act-2020/codes-of-practice/hipc2020/

Te Tāhū Hauora Health Quality & Safety Commission. (2021). *Vital signs chart with New Zealand early warning score*. https://www.hqsc.govt.nz/resources/resource-library/vital-signs-chart-with-new-zealand-early-warning-score/

## 6. Prompt log

Tested on our 4 fake residents with llama3.2:3b on my laptop (Intel i3, 8 GB RAM, CPU only).

| Version | Date | What I changed | Result |
|---|---|---|---|
| v1 | 29 Oct 2026 | First prompt: use only the notes, copy exact quotes, never diagnose or name medicines | Ron H. went from Green to Amber because of "Nearly slipped when getting out of the chair". All quotes were real. But the AI wrote "Resident may be dehydrated" (sounds like a diagnosis) and "may need fluids and monitoring" (sounds like treatment advice). Time: 41.9 s for the first resident (model loading), then about 8 s each. |
| v2 | 29 Oct 2026 | Added a rule: describe only what happened, do not name a condition or say what treatment or fluids are needed | The reasons now only describe what happened: "Did not have enough fluids", "Lost balance while getting out of chair", "Vomited after breakfast". Ron H. is still Amber. All quotes were real. Time: 27.0 s for the first resident, then about 8–9 s each. |

**What I learned:** small models follow short, specific rules better than general ones. "Never diagnose" was not enough, so I had to give examples of words not to use. My code checks still matter, because a prompt cannot fully control the AI.