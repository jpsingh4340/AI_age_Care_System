"""Demo of the Care Priority Decision feature (Tanveer).

Shows the Green / Amber / Red priority for each fake resident.

Run from the project folder:
    python tools/decision_demo.py         rules only (NZEWS), no AI needed
    python tools/decision_demo.py --ai    rules + AI reading the carer notes (needs Ollama)
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so "app" can be imported when run from tools/

from app.decision_rules import check_vitals, highest_level, rules_level, total_score  # noqa: E402

ICONS = {"Green": "[GREEN]", "Amber": "[AMBER]", "Red": "[RED]  "}


def load(name: str) -> dict:
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def main() -> None:
    use_ai = "--ai" in sys.argv
    if use_ai:
        from app import decision_ai

    names = {r["resident_id"]: r["name"] for r in load("residents.json")["residents"]}

    title = "rules (NZEWS) + AI reading carer notes" if use_ai else "rules part only (NZEWS)"
    print(f"Care Priority Decision - {title}. Fake residents only.")
    print("=" * 70)

    for record in load("records.json")["residents"]:
        name = names.get(record["resident_id"], f"Resident {record['resident_id']}")
        results = check_vitals(record["readings_history"])
        rules = rules_level(results)

        concerns, dropped, seconds = [], [], 0.0
        if use_ai:
            start = time.perf_counter()
            concerns, dropped = decision_ai.read_notes(record["concerns"])
            seconds = time.perf_counter() - start

        final = highest_level([rules] + [c["level"] for c in concerns])
        print(f"\n{ICONS[final]} {name}")
        print(f"    Rules: {rules} (NZEWS total {total_score(results)})")
        for result in results:
            if result["score"] != 0:
                print(f"      - {result['reason']}  [{result['source']}]")

        if use_ai:
            print(f"    AI read the carer notes in {seconds:.1f} seconds:")
            for concern in concerns:
                print(f"      - {concern['level']}: {concern['type']} - {concern['reason']}")
                print(f"        Quote: \"{concern['quote']}\"  [{concern['source']}]")
            for concern in dropped:
                print(f"      - Removed by my check: \"{concern['quote']}\" ({concern['why']})")
            if not concerns and not dropped:
                print("      - No worries found in the notes.")
        else:
            for note in record["concerns"]:
                print(f"    Carer note ({note['time']}): \"{note['text']}\"  (run with --ai to read it)")

    print("\nThe nurse always makes the final decision.")


if __name__ == "__main__":
    main()