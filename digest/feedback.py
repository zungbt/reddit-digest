from collections.abc import Sequence
from dataclasses import dataclass
import datetime
import json
import pathlib
import re
from typing import Any

from digest.classify import SECTIONS, SECTION_ALIASES


@dataclass
class Mark:
    id: str
    sub: str
    section: str
    title: str
    url: str
    decision: str  # "keep" | "reject" | "neutral"


def _collapse_spaces(text: Any) -> str:
    if text is None:
        return ""
    return " ".join(str(text).split())


def _canonical_section(sec: str | None) -> str:
    if not sec:
        return "other"
    sec_candidate = str(sec).strip().lower()
    canonical = SECTION_ALIASES.get(sec_candidate, sec_candidate)
    if canonical in SECTIONS:
        return canonical
    return "other"


def read_marks(md: str | pathlib.Path | None) -> list[Mark]:
    """Parse marked lines from a rendered digest markdown text.
    
    Identifies items by the `<!-- id:... section:... -->` tag.
    Parses checkboxes:
      [x] or [X] -> "keep"   (interesting; few-shot signal only)
      [s] or [S] -> "save"   (worth keeping; also copied to saved.md)
      [-]        -> "reject"
      [ ]        -> "neutral"
    Ignores lines without an id tag. Returns [] if md is empty or None.
    """
    if md is None:
        return []
    if isinstance(md, pathlib.Path):
        try:
            md = md.read_text(encoding="utf-8")
        except OSError:
            return []

    md_str = str(md)
    if not md_str.strip():
        return []

    marks: list[Mark] = []
    for line in md_str.splitlines():
        line_str = line.strip()
        if not line_str:
            continue

        # Look for HTML comment containing id:
        m_tag = None
        for tag_match in re.finditer(r"<!--(.*?)-->", line_str):
            if re.search(r"\bid:\s*[a-zA-Z0-9_\-]+", tag_match.group(1)):
                m_tag = tag_match
                break
        if not m_tag:
            continue

        tag_content = m_tag.group(1)
        m_id = re.search(r"\bid:\s*([a-zA-Z0-9_\-]+)", tag_content)
        if not m_id:
            continue

        post_id = m_id.group(1).rstrip("-;,").strip()
        if not post_id:
            continue

        m_sec = re.search(r"\bsection:\s*([^\s;,\->]+)", tag_content)
        section = _canonical_section(m_sec.group(1).strip()) if m_sec else "other"

        # Checkbox decision at the beginning of the item (or after a leading comment)
        m_box = re.search(r"(?:^|-->)\s*(?:[-*+]|\d+\.)?\s*\[\s*([xXsS\-\s]?)\s*\]", line_str)
        if m_box:
            mark_char = m_box.group(1).strip().lower()
            if mark_char == "x":
                decision = "keep"
            elif mark_char == "s":
                decision = "save"
            elif mark_char == "-":
                decision = "reject"
            else:
                decision = "neutral"
        else:
            decision = "neutral"

        # Title: non-greedy match between ] and separator dash, or bold title
        m_title = re.search(r"\]\s*\*\*(.+?)\*\*\s*[—–-]", line_str)
        if not m_title:
            m_title = re.search(r"\*\*(.+?)\*\*\s*[—–-]", line_str)
        if not m_title:
            m_title = re.search(r"\*\*(.+?)\*\*", line_str)
        if not m_title:
            m_title = re.search(r"\]\s*(.+?)\s*[—–-]", line_str)
        title = _collapse_spaces(m_title.group(1)) if m_title else ""

        # URL
        m_url = re.search(r"\[post\]\(([^)]+)\)", line_str)
        if not m_url:
            m_url = re.search(r"\[(?:post|link)\]\(([^)]+)\)", line_str)
        if not m_url:
            m_url = re.search(r"\((https?://[^\s)]+)\)", line_str)
        if not m_url:
            m_url = re.search(r"\b(https?://[^\s>]+)", line_str)
        url = m_url.group(1).strip().rstrip(")") if m_url else ""

        # Subreddit
        m_sub = re.search(r"`(?:r/)?([^`]+)`", line_str)
        if not m_sub:
            m_sub = re.search(r"\b/?r/([A-Za-z0-9_]+)\b", line_str)
        sub = m_sub.group(1).strip() if m_sub else ""
        if not sub and url:
            m_sub_url = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)/", url)
            if m_sub_url:
                sub = m_sub_url.group(1).strip()
        sub = sub.lstrip("/").removeprefix("r/").strip()

        marks.append(
            Mark(
                id=post_id,
                sub=sub,
                section=section,
                title=title,
                url=url,
                decision=decision,
            )
        )

    return marks


def apply(
    marks: Sequence[Any],
    digest_day: datetime.date | datetime.datetime | str,
    saved: pathlib.Path | str,
    log: pathlib.Path | str,
    dropped: Sequence[Any] | None = None,
) -> None:
    """Apply marked decisions from a digest:
    
    1. Append "save" items to saved.md (deduplicated by id).
    2. Append every mark and every dropped item ("auto-drop") to feedback.jsonl
       with format {date, id, sub, section, title, decision}.
    """
    if isinstance(digest_day, (datetime.date, datetime.datetime)):
        date_str = digest_day.strftime("%Y-%m-%d")
    else:
        m_day = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", str(digest_day))
        date_str = m_day.group(1) if m_day else str(digest_day).strip()

    saved_path = pathlib.Path(saved)
    log_path = pathlib.Path(log)

    saved_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not saved_path.exists():
        saved_path.touch()

    if not log_path.exists():
        log_path.touch()

    # 1. Deduplicate and append save marks to saved.md
    existing_content = saved_path.read_text(encoding="utf-8")
    existing_ids = {
        m.group(1).rstrip("-;,").strip().lower()
        for m in re.finditer(r"\bid:\s*([a-zA-Z0-9_\-]+)", existing_content)
    }

    new_saved_lines: list[str] = []
    for mark in marks:
        if isinstance(mark, dict):
            decision = str(mark.get("decision", "")).strip().lower()
            m_id = str(mark.get("id", "")).strip()
            title = _collapse_spaces(mark.get("title", ""))
            url = str(mark.get("url", "")).strip()
            raw_sub = str(mark.get("sub", "")).strip()
            sub = raw_sub.lstrip("/").removeprefix("r/").strip()
            section = _canonical_section(mark.get("section", "other"))
        else:
            decision = str(getattr(mark, "decision", "")).strip().lower()
            m_id = str(getattr(mark, "id", "")).strip()
            title = _collapse_spaces(getattr(mark, "title", ""))
            url = str(getattr(mark, "url", "")).strip()
            raw_sub = str(getattr(mark, "sub", "")).strip()
            sub = raw_sub.lstrip("/").removeprefix("r/").strip()
            section = _canonical_section(getattr(mark, "section", "other"))

        if decision == "save" and m_id:
            if m_id.lower() not in existing_ids:
                existing_ids.add(m_id.lower())
                new_saved_lines.append(
                    f"- [s] **{title}** — [post]({url}) `r/{sub}` <!-- id:{m_id} section:{section} -->\n"
                )

    if new_saved_lines:
        with open(saved_path, "a", encoding="utf-8") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            f.writelines(new_saved_lines)

    # 2. Append all marks and dropped items to feedback.jsonl
    feedback_entries: list[dict[str, str]] = []
    seen_feedback_ids: set[str] = set()

    for mark in marks:
        if isinstance(mark, dict):
            m_id = str(mark.get("id", "")).strip()
            raw_sub = str(mark.get("sub", "")).strip()
            sub = raw_sub.lstrip("/").removeprefix("r/").strip()
            section = _canonical_section(mark.get("section", "other"))
            title = _collapse_spaces(mark.get("title", ""))
            decision = str(mark.get("decision", "neutral")).strip().lower()
        else:
            m_id = str(getattr(mark, "id", "")).strip()
            raw_sub = str(getattr(mark, "sub", "")).strip()
            sub = raw_sub.lstrip("/").removeprefix("r/").strip()
            section = _canonical_section(getattr(mark, "section", "other"))
            title = _collapse_spaces(getattr(mark, "title", ""))
            decision = str(getattr(mark, "decision", "neutral")).strip().lower()

        if not m_id:
            continue
        if m_id.lower() in seen_feedback_ids:
            continue
        seen_feedback_ids.add(m_id.lower())

        if decision not in ("keep", "save", "reject", "neutral"):
            decision = "neutral"

        feedback_entries.append(
            {
                "date": date_str,
                "id": m_id,
                "sub": sub,
                "section": section,
                "title": title,
                "decision": decision,
            }
        )

    if dropped:
        for item in dropped:
            if isinstance(item, dict):
                d_id = str(item.get("id", "")).strip()
                raw_sub = str(item.get("sub", "")).strip()
                sub = raw_sub.lstrip("/").removeprefix("r/").strip()
                section = _canonical_section(item.get("section", "drop"))
                title = _collapse_spaces(item.get("title", ""))
            else:
                d_id = str(getattr(item, "id", "")).strip()
                raw_sub = str(getattr(item, "sub", "")).strip()
                sub = raw_sub.lstrip("/").removeprefix("r/").strip()
                section = _canonical_section(getattr(item, "section", "drop"))
                title = _collapse_spaces(getattr(item, "title", ""))

            if not d_id:
                continue
            if d_id.lower() in seen_feedback_ids:
                continue
            seen_feedback_ids.add(d_id.lower())

            feedback_entries.append(
                {
                    "date": date_str,
                    "id": d_id,
                    "sub": sub,
                    "section": section,
                    "title": title,
                    "decision": "auto-drop",
                }
            )

    if feedback_entries:
        existing_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        with open(log_path, "a", encoding="utf-8") as f:
            if existing_log and not existing_log.endswith("\n"):
                f.write("\n")
            for entry in feedback_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
