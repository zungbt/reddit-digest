import datetime
import json
import pathlib
import pytest

from digest.classify import Item
from digest.feedback import Mark, apply


def _make_mark(
    id: str = "t3_m1",
    sub: str = "LocalLLaMA",
    section: str = "repo",
    title: str = "Mark Title",
    url: str = "https://www.reddit.com/r/LocalLLaMA/comments/m1/title/",
    decision: str = "keep",
) -> Mark:
    return Mark(
        id=id,
        sub=sub,
        section=section,
        title=title,
        url=url,
        decision=decision,
    )


def _make_item(
    id: str = "t3_drop1",
    sub: str = "LocalLLaMA",
    title: str = "Dropped Title",
    url: str = "https://www.reddit.com/r/LocalLLaMA/comments/drop1/title/",
    link: str | None = None,
    section: str = "drop",
    summary: str = "Dropped summary",
    source: str = "followed",
) -> Item:
    return Item(
        id=id,
        sub=sub,
        title=title,
        url=url,
        link=link,
        section=section,
        summary=summary,
        source=source,
    )


def test_apply_appends_keep_to_saved_md(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    marks = [
        _make_mark(id="t3_k1", title="Keep One", decision="keep"),
        _make_mark(id="t3_r1", title="Reject One", decision="reject"),
        _make_mark(id="t3_n1", title="Neutral One", decision="neutral"),
        _make_mark(id="t3_k2", title="Keep Two", decision="keep"),
    ]

    apply(marks, digest_day=day, saved=saved_file, log=log_file, dropped=[])

    assert saved_file.exists()
    content = saved_file.read_text(encoding="utf-8")
    assert "Keep One" in content
    assert "Keep Two" in content
    assert "Reject One" not in content
    assert "Neutral One" not in content
    assert "t3_k1" in content
    assert "t3_k2" in content
    assert "t3_r1" not in content


def test_apply_deduplicates_saved_md_if_run_twice(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    marks = [
        _make_mark(id="t3_k1", title="Keep One", decision="keep"),
    ]

    # First run
    apply(marks, digest_day=day, saved=saved_file, log=log_file, dropped=[])
    first_content = saved_file.read_text(encoding="utf-8")
    assert first_content.count("t3_k1") == 1

    # Second run with same marks
    apply(marks, digest_day=day, saved=saved_file, log=log_file, dropped=[])
    second_content = saved_file.read_text(encoding="utf-8")
    assert second_content.count("t3_k1") == 1


def test_apply_preserves_preexisting_saved_md(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    saved_file.write_text(
        "- [x] **Pre-existing Title** — [post](https://reddit.com/old) `r/old` <!-- id:t3_old section:repo -->\n",
        encoding="utf-8",
    )

    marks = [
        _make_mark(id="t3_old", title="Pre-existing Title", decision="keep"),
        _make_mark(id="t3_new", title="New Title", decision="keep"),
    ]

    apply(marks, digest_day=day, saved=saved_file, log=log_file, dropped=[])
    content = saved_file.read_text(encoding="utf-8")
    assert content.count("t3_old") == 1
    assert content.count("t3_new") == 1


def test_apply_appends_all_marks_and_auto_drops_to_feedback_jsonl(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    marks = [
        _make_mark(id="t3_k1", sub="FPGA", section="career", title="Keep Job", decision="keep"),
        _make_mark(id="t3_r1", sub="meme", section="other", title="Reject Meme", decision="reject"),
        _make_mark(id="t3_n1", sub="LocalLLaMA", section="repo", title="Neutral Tool", decision="neutral"),
    ]
    dropped = [
        _make_item(id="t3_d1", sub="funny", section="drop", title="Spam Link"),
    ]

    apply(marks, digest_day=day, saved=saved_file, log=log_file, dropped=dropped)

    assert log_file.exists()
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 4

    # Verify order and content
    assert lines[0] == {
        "date": "2026-11-08",
        "id": "t3_k1",
        "sub": "FPGA",
        "section": "career",
        "title": "Keep Job",
        "decision": "keep",
    }
    assert lines[1] == {
        "date": "2026-11-08",
        "id": "t3_r1",
        "sub": "meme",
        "section": "other",
        "title": "Reject Meme",
        "decision": "reject",
    }
    assert lines[2] == {
        "date": "2026-11-08",
        "id": "t3_n1",
        "sub": "LocalLLaMA",
        "section": "repo",
        "title": "Neutral Tool",
        "decision": "neutral",
    }
    assert lines[3] == {
        "date": "2026-11-08",
        "id": "t3_d1",
        "sub": "funny",
        "section": "drop",
        "title": "Spam Link",
        "decision": "auto-drop",
    }


def test_feedback_jsonl_uses_digest_day_not_today(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 1)  # A past date

    marks = [_make_mark(id="t3_past", decision="keep")]
    apply(marks, digest_day=day, saved=saved_file, log=log_file, dropped=[])

    line = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert line["date"] == "2026-11-01"


def test_apply_creates_nested_directories_if_missing(tmp_path: pathlib.Path):
    nested_saved = tmp_path / "nested" / "dir" / "saved.md"
    nested_log = tmp_path / "nested" / "other" / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    marks = [_make_mark(id="t3_nest", decision="keep")]
    apply(marks, digest_day=day, saved=nested_saved, log=nested_log, dropped=[])

    assert nested_saved.exists()
    assert nested_log.exists()


def test_apply_empty_marks_and_dropped(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    apply([], digest_day=day, saved=saved_file, log=log_file, dropped=[])
    # Should not crash, files can be created empty or uncreated
    if saved_file.exists():
        assert saved_file.read_text(encoding="utf-8") == ""
    if log_file.exists():
        assert log_file.read_text(encoding="utf-8") == ""


def test_apply_handles_dropped_as_dicts(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    dropped_dict = [{
        "id": "t3_dict_drop",
        "sub": "askreddit",
        "section": "drop",
        "title": "Dict Dropped Post",
    }]

    apply([], digest_day=day, saved=saved_file, log=log_file, dropped=dropped_dict)

    line = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert line["id"] == "t3_dict_drop"
    assert line["decision"] == "auto-drop"
    assert line["sub"] == "askreddit"


def test_apply_deduplication_does_not_false_positive_on_id_prefix(tmp_path: pathlib.Path):
    # t3_1 should NOT prevent t3_10 or t3_100 from being saved
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    # First save t3_1
    m1 = _make_mark(id="t3_1", title="Title 1", decision="keep")
    apply([m1], digest_day=day, saved=saved_file, log=log_file, dropped=[])

    # Now save t3_10
    m10 = _make_mark(id="t3_10", title="Title 10", decision="keep")
    apply([m10], digest_day=day, saved=saved_file, log=log_file, dropped=[])

    content = saved_file.read_text(encoding="utf-8")
    assert "Title 1" in content
    assert "Title 10" in content
    assert content.count("id:t3_1 ") == 1
    assert content.count("id:t3_10 ") == 1


def test_apply_duplicate_marks_in_single_call(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    # Two identical keep marks in the same batch
    m1 = _make_mark(id="t3_dup", title="Dup Title", decision="keep")
    m2 = _make_mark(id="t3_dup", title="Dup Title", decision="keep")

    apply([m1, m2], digest_day=day, saved=saved_file, log=log_file, dropped=[])

    content = saved_file.read_text(encoding="utf-8")
    assert content.count("id:t3_dup ") == 1
    # feedback.jsonl should also record it only once
    log_lines = [json.loads(l) for l in log_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(log_lines) == 1
    assert log_lines[0]["id"] == "t3_dup"


def test_apply_preserves_log_without_trailing_newline(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    # Pre-existing entry missing a trailing newline
    log_file.write_text('{"id":"t3_prev","decision":"neutral"}', encoding="utf-8")

    m = _make_mark(id="t3_next", title="Next", decision="keep")
    apply([m], digest_day=day, saved=saved_file, log=log_file, dropped=[])

    raw_lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw_lines) == 2
    parsed = [json.loads(line) for line in raw_lines]
    assert parsed[0]["id"] == "t3_prev"
    assert parsed[1]["id"] == "t3_next"


def test_apply_deduplication_saved_md_no_space_before_comment_close(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    # Pre-existing line formatted with <!-- id:t3_nospace-->
    saved_file.write_text("- [x] **Title** — [post](u) `r/sub` <!-- id:t3_nospace-->\n", encoding="utf-8")

    m = _make_mark(id="t3_nospace", title="Title", decision="keep")
    apply([m], digest_day=day, saved=saved_file, log=log_file, dropped=[])

    content = saved_file.read_text(encoding="utf-8")
    assert content.count("t3_nospace") == 1


def test_apply_canonicalizes_sections_in_feedback_and_saved(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    m = _make_mark(id="t3_sec1", section="qa-tools", decision="keep")
    d = _make_item(id="t3_sec2", section="Drop", title="D")
    apply([m], digest_day=day, saved=saved_file, log=log_file, dropped=[d])

    saved_content = saved_file.read_text(encoding="utf-8")
    assert "section:qa_tools" in saved_content

    log_entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").strip().splitlines()]
    assert log_entries[0]["section"] == "qa_tools"
    assert log_entries[1]["section"] == "drop"


def test_apply_extracts_date_from_path_or_filename_string(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"

    m = _make_mark(id="t3_path_date", decision="keep")
    apply([m], digest_day="digests/2026-11-08.md", saved=saved_file, log=log_file, dropped=[])

    log_entry = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert log_entry["date"] == "2026-11-08"


def test_apply_ignores_empty_or_whitespace_ids(tmp_path: pathlib.Path):
    saved_file = tmp_path / "saved.md"
    log_file = tmp_path / "feedback.jsonl"
    day = datetime.date(2026, 11, 8)

    m = _make_mark(id="   ", decision="keep")
    apply([m], digest_day=day, saved=saved_file, log=log_file, dropped=[])

    assert saved_file.read_text(encoding="utf-8") == ""
    assert log_file.read_text(encoding="utf-8") == ""


