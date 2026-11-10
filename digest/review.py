from collections import defaultdict
from datetime import date
import json
import pathlib
import sys
from typing import Any

from digest.classify import SECTIONS, SECTION_ALIASES
from digest.config import WORK


def _canonical_section(sec: str | None) -> str:
    if not sec:
        return "other"
    sec_candidate = str(sec).strip().lower()
    canonical = SECTION_ALIASES.get(sec_candidate, sec_candidate)
    if canonical in SECTIONS:
        return canonical
    return "other"


def summarize(lines: list[dict[str, Any]], today: date | None = None) -> str:
    """Summarize reject/keep/neutral/auto-drop feedback and propose drop rules."""
    valid_entries: list[dict[str, Any]] = [
        item for item in lines if isinstance(item, dict) and any(item.values())
    ]
    if not valid_entries:
        return "# Feedback Review\n\nNo feedback yet.\n"

    if today is None:
        today = date.today()

    sub_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"keep": 0, "reject": 0, "neutral": 0, "auto-drop": 0})
    sec_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"keep": 0, "reject": 0, "neutral": 0, "auto-drop": 0})
    recent_auto_drops: list[tuple[str, str, str]] = []

    for entry in valid_entries:
        sub = str(entry.get("sub", "")).lstrip("/").removeprefix("r/").strip()
        sec = _canonical_section(entry.get("section", "other"))
        title = " ".join(str(entry.get("title", "")).split())
        decision = str(entry.get("decision", "neutral")).strip().lower()
        if decision == "save":
            decision = "keep"
        if decision not in ("keep", "reject", "neutral", "auto-drop"):
            decision = "neutral"

        if sub:
            sub_counts[sub][decision] += 1
        sec_counts[sec][decision] += 1

        if decision == "auto-drop":
            date_str = str(entry.get("date", "")).strip()
            is_recent = False
            try:
                entry_date = date.fromisoformat(date_str)
                if 0 <= (today - entry_date).days <= 14:
                    is_recent = True
            except Exception:
                pass
            if is_recent:
                recent_auto_drops.append((date_str, sub, title))

    # Identify proposed drop rules: groups with >= 10 marks and 0 keeps
    proposals: list[str] = []

    for sub, counts in sorted(sub_counts.items()):
        rejects = counts["reject"]
        keeps = counts["keep"]
        if rejects >= 10 and keeps == 0:
            proposals.append(f"- Subreddit **r/{sub}**: {rejects} rejects, 0 keeps (propose drop)")

    for sec_key in SECTIONS:
        if sec_key == "drop":
            continue
        counts = sec_counts[sec_key]
        rejects = counts["reject"]
        keeps = counts["keep"]
        sec_name = SECTIONS[sec_key]
        if rejects >= 10 and keeps == 0:
            proposals.append(f"- Section **{sec_name}** (`{sec_key}`): {rejects} rejects, 0 keeps (propose drop)")

    # Build markdown report
    output_lines: list[str] = ["# Feedback Review\n"]

    output_lines.append("## By Subreddit\n")
    output_lines.append("| Subreddit | Keep | Reject | Neutral | Auto-drop |")
    output_lines.append("|---|---|---|---|---|")
    for sub, counts in sorted(sub_counts.items()):
        output_lines.append(f"| r/{sub} | {counts['keep']} | {counts['reject']} | {counts['neutral']} | {counts['auto-drop']} |")
    output_lines.append("")

    output_lines.append("## By Section\n")
    output_lines.append("| Section | Keep | Reject | Neutral | Auto-drop |")
    output_lines.append("|---|---|---|---|---|")
    for sec_key, sec_name in SECTIONS.items():
        if sec_key in sec_counts or sec_key != "drop":
            counts = sec_counts[sec_key]
            output_lines.append(f"| {sec_name} (`{sec_key}`) | {counts['keep']} | {counts['reject']} | {counts['neutral']} | {counts['auto-drop']} |")
    output_lines.append("")

    output_lines.append("## Proposed Drop Rules\n")
    if proposals:
        for prop in proposals:
            output_lines.append(prop)
    else:
        output_lines.append("None")
    output_lines.append("")

    output_lines.append("## Auto-dropped (last 14 days)\n")
    if recent_auto_drops:
        for d_str, sub, title in recent_auto_drops:
            sub_part = f" `r/{sub}`" if sub else ""
            date_part = f" ({d_str})" if d_str else ""
            output_lines.append(f"- **{title}**{sub_part}{date_part}")
    else:
        output_lines.append("None")
    output_lines.append("")

    return "\n".join(output_lines)


def review_main(feedback_path: pathlib.Path | str | None = None) -> int:
    """CLI entrypoint for 'python -m digest review'."""
    if feedback_path is None:
        target_path = WORK / "feedback.jsonl"
    else:
        target_path = pathlib.Path(feedback_path)

    lines: list[dict[str, Any]] = []
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                        if isinstance(data, dict):
                            lines.append(data)
                    except Exception:
                        continue
        except OSError as e:
            print(f"Error reading feedback log: {e}", file=sys.stderr)
            return 1

    report = summarize(lines)
    print(report)
    return 0
