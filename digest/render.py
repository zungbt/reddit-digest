from collections.abc import Sequence
import datetime
from typing import Any

from digest.classify import Item, SECTIONS, SECTION_ALIASES
from digest.feedback import Mark, read_marks

__all__ = ["render", "Mark", "read_marks", "SECTION_ORDER"]

SECTION_ORDER: list[str] = [
    "repo",
    "showcase",
    "knowledge",
    "money",
    "career",
    "game",
    "qa_tools",
    "other",
]


def _canonical_section(sec: str | None) -> str:
    if not sec:
        return "other"
    sec_candidate = str(sec).strip().lower()
    canonical = SECTION_ALIASES.get(sec_candidate, sec_candidate)
    if canonical in SECTIONS:
        return canonical
    return "other"


def _format_item_line(item: Item) -> str:
    title = " ".join(str(item.title or "").split())
    summary = " ".join(str(item.summary or "").split())
    url = str(item.url or "").strip()
    raw_sub = str(item.sub or "").strip()
    sub = raw_sub.lstrip("/").removeprefix("r/").strip()
    sec = _canonical_section(item.section)
    post_id = str(item.id or "").strip()

    link_part = ""
    if item.link and str(item.link).strip():
        link_part = f" · [link]({str(item.link).strip()})"

    summary_part = f" — {summary}" if summary else ""

    return (
        f"- [ ] **{title}**{summary_part} — [post]({url}){link_part} `r/{sub}` <!-- id:{post_id} section:{sec} -->"
    )


def _render_group(group_heading: str, group_items: Sequence[Item]) -> str:
    rendered_sections: list[str] = []

    for sec in SECTION_ORDER:
        sec_items = [it for it in group_items if _canonical_section(it.section) == sec]
        if not sec_items:
            continue

        heading_title = SECTIONS.get(sec, sec)
        section_lines = [f"### {heading_title}"]
        for it in sec_items:
            section_lines.append(_format_item_line(it))

        rendered_sections.append("\n".join(section_lines))

    if not rendered_sections:
        return ""

    return f"{group_heading}\n\n" + "\n\n".join(rendered_sections)


def render(
    items: Sequence[Item] = (),
    warnings: Sequence[str] | None = None,
    suggestions: Sequence[tuple[str, int]] | None = None,
    day: datetime.date | datetime.datetime | str | None = None,
) -> str:
    """Render daily digest markdown matching spec §7.
    
    Item line format:
    - [ ] **{title}** — {summary} — [post]({url}){ · [link]({link}) if link} `r/{sub}` <!-- id:{id} section:{section} -->
    
    drop items are not rendered. Empty sections omitted.
    Sections in Global Constraints order.
    """
    blocks: list[str] = []

    # 1. Warnings at top
    if warnings:
        warn_lines: list[str] = []
        for w in warnings:
            if not w:
                continue
            for line in str(w).splitlines():
                clean_line = line.strip().removeprefix(">").strip()
                if clean_line:
                    warn_lines.append(f"> {clean_line}")
        if warn_lines:
            blocks.append("\n".join(warn_lines))

    # 2. Partition items by source (skipping drop items)
    followed_items: list[Item] = []
    viewed_items: list[Item] = []

    for it in items:
        if _canonical_section(it.section) == "drop":
            continue
        if getattr(it, "source", "") == "viewed":
            viewed_items.append(it)
        else:
            followed_items.append(it)

    # 3. Followed subs group
    if followed_items:
        group_str = _render_group("## From followed subs", followed_items)
        if group_str:
            blocks.append(group_str)

    # 4. Viewed posts group
    if viewed_items:
        group_str = _render_group("## From posts you viewed", viewed_items)
        if group_str:
            blocks.append(group_str)

    # 5. Sub suggestions
    if suggestions:
        sugg_lines: list[str] = ["## Sub suggestions"]
        for sub, count in suggestions:
            clean_sub = str(sub).strip().lstrip("/").removeprefix("r/").strip()
            if not clean_sub:
                continue
            sugg_lines.append(f"- r/{clean_sub} — opened {count} times since last run")
        if len(sugg_lines) > 1:
            blocks.append("\n".join(sugg_lines))

    if not blocks:
        return ""

    return "\n\n".join(blocks) + "\n"
