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

    rejects: list[str] = []
    keeps: list[str] = []

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
        if decision not in ("reject", "keep"):
            continue

        raw_sub = str(data.get("sub") or "").strip()
        sub = raw_sub.lstrip("/").removeprefix("r/").strip()
        raw_title = data.get("title")
        clean_title = " ".join(str(raw_title or "").split())[:140]

        if decision == "reject":
            rejects.append(f"REJECT | r/{sub} | {clean_title}")
        elif decision == "keep":
            keeps.append(f"KEEP | r/{sub} | {clean_title}")

    selected = (rejects[-n:] if n > 0 else []) + (keeps[-n:] if n > 0 else [])
    if not selected:
        return ""

    return "Examples of this reader's taste (from past marks):\n" + "\n".join(selected)
