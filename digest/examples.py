import json
import pathlib

from digest.config import FEWSHOT_N

__all__ = ["feedback_examples"]


def feedback_examples(path: pathlib.Path, n: int = FEWSHOT_N) -> str:
    if path is None:
        return ""
    p = pathlib.Path(path)
    if not p.is_file():
        return ""
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not content.strip():
        return ""

    # Track latest decision per item to prevent duplicates or stale decisions
    # Key by id (or title if id is missing)
    latest_items: dict[str, tuple[str, str, str]] = {}

    for line in content.splitlines():
        line_str = line.strip()
        if not line_str:
            continue
        try:
            data = json.loads(line_str)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        decision = data.get("decision")
        if decision not in ("reject", "keep", "save"):
            continue

        item_id = str(data.get("id") or "").strip()
        raw_title = data.get("title")
        clean_title = " ".join(str(raw_title or "").split())[:140]
        key = item_id if item_id else clean_title
        if not key:
            continue

        raw_sub = str(data.get("sub") or "").strip()
        sub = raw_sub.lstrip("/").removeprefix("r/").strip()
        canonical_decision = "keep" if decision in ("keep", "save") else "reject"

        latest_items[key] = (sub, clean_title, canonical_decision)

    rejects: list[str] = []
    keeps: list[str] = []

    for sub, clean_title, decision in latest_items.values():
        if decision == "reject":
            rejects.append(f"REJECT | r/{sub} | {clean_title}")
        else:
            keeps.append(f"KEEP | r/{sub} | {clean_title}")

    selected = (rejects[-n:] if n > 0 else []) + (keeps[-n:] if n > 0 else [])
    if not selected:
        return ""

    return "Examples of this reader's taste (from past marks):\n" + "\n".join(selected)
