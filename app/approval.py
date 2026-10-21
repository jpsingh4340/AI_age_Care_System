"""Turn a nurse's decision into the final lines that get saved.

The nurse may remove lines, edit the wording, or approve the draft as it is.
Whatever the nurse sends, the server re-checks it, so a changed request cannot
sneak in text that the AI never wrote or that mentions medicines.
"""
from .guidance import MAX_LINE_LENGTH, contains_blocked
from .schemas import DecisionRequest

KEYS = ("watch_for", "prevention")


class ApprovalError(Exception):
    """The nurse's lines cannot be approved. The message is safe to show."""


def final_content(draft: dict, request: DecisionRequest) -> tuple[dict, str]:
    """Return (the content to save, a short description for the audit log)."""
    content = {key: draft[key] for key in ("resident", "conditions", "watch_for", "prevention", "dropped", "sources")}

    # the lines the AI wrote and the automatic check kept, by (text, source)
    original = {(line["text"], line["source_id"]): line for key in KEYS for line in draft[key]}
    source_names = {source["id"]: source["source"] for source in draft["sources"]}

    for key in KEYS:
        submitted = getattr(request, key)
        if submitted is None:
            continue  # the nurse did not touch this list
        final = []
        for line in submitted:
            text = line.text.strip()
            if not text or len(text) > MAX_LINE_LENGTH:
                raise ApprovalError(f"Each line must be between 1 and {MAX_LINE_LENGTH} characters.")
            if contains_blocked(text):
                raise ApprovalError(
                    f'"{text}" mentions a medicine, dose or diagnosis. Please remove that wording.'
                )
            if line.edited:
                source_id = line.source_id if line.source_id in source_names else ""
                final.append({
                    "text": text, "source_id": source_id,
                    "source": source_names.get(source_id, "Written by the nurse"),
                    "quote": "", "edited": True,
                })
            else:
                match = original.get((text, line.source_id))
                if match is None:
                    raise ApprovalError(
                        "A line that is not marked as edited does not match the AI draft."
                    )
                final.append({**match, "edited": False})
        content[key] = final

    total = len(content["watch_for"]) + len(content["prevention"])
    if total == 0:
        raise ApprovalError("There is nothing to approve. Reject the draft instead.")

    edited = sum(1 for key in KEYS for line in content[key] if line.get("edited"))
    original_count = sum(len(draft[key]) for key in KEYS)
    detail = f"{total} lines approved ({edited} written or edited by the nurse). The AI draft had {original_count} lines."
    return content, detail