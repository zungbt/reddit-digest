from datetime import date, timedelta
import json
from pathlib import Path
import pytest

from digest.__main__ import main
from digest.review import review_main, summarize


def test_empty_log_returns_no_feedback_yet():
    assert "no feedback yet" in summarize([]).lower()
    assert "no feedback yet" in summarize([{"sub": "", "title": ""}]).lower()


def test_counts_per_group():
    lines = [
        {"date": "2026-11-08", "id": "t3_1", "sub": "LocalLLaMA", "section": "repo", "title": "Post 1", "decision": "keep"},
        {"date": "2026-11-08", "id": "t3_2", "sub": "LocalLLaMA", "section": "repo", "title": "Post 2", "decision": "reject"},
        {"date": "2026-11-08", "id": "t3_3", "sub": "LocalLLaMA", "section": "game", "title": "Post 3", "decision": "neutral"},
        {"date": "2026-11-08", "id": "t3_4", "sub": "LocalLLaMA", "section": "other", "title": "Post 4", "decision": "auto-drop"},
        {"date": "2026-11-08", "id": "t3_5", "sub": "ClaudeAI", "section": "repo", "title": "Post 5", "decision": "keep"},
    ]
    report = summarize(lines)

    # Sub counts
    assert "LocalLLaMA" in report
    assert "ClaudeAI" in report
    # Section counts
    assert "repo" in report or "Repo / Tool" in report
    assert "game" in report or "Game" in report


def test_proposal_appears_for_12_rejects_0_keeps():
    lines = [
        {
            "date": "2026-11-08",
            "id": f"t3_{i}",
            "sub": "annoying_sub",
            "section": "other",
            "title": f"Spam {i}",
            "decision": "reject",
        }
        for i in range(12)
    ]
    report = summarize(lines)
    report_lower = report.lower()
    assert "proposed drop" in report_lower or "proposal" in report_lower or "drop rule" in report_lower
    assert "annoying_sub" in report


def test_no_proposal_for_12_rejects_1_keep():
    lines = [
        {
            "date": "2026-11-08",
            "id": f"t3_{i}",
            "sub": "mixed_sub",
            "section": "other",
            "title": f"Spam {i}",
            "decision": "reject",
        }
        for i in range(12)
    ]
    lines.append(
        {
            "date": "2026-11-08",
            "id": "t3_good",
            "sub": "mixed_sub",
            "section": "other",
            "title": "Good Post",
            "decision": "keep",
        }
    )
    report = summarize(lines)
    if "proposed drop rules" in report.lower():
        proposed_section = report.lower().split("proposed drop rules")[1].split("##")[0]
        assert "mixed_sub" not in proposed_section


def test_no_proposal_under_10_marks():
    lines = [
        {
            "date": "2026-11-08",
            "id": f"t3_{i}",
            "sub": "small_sub",
            "section": "other",
            "title": f"Spam {i}",
            "decision": "reject",
        }
        for i in range(9)
    ]
    report = summarize(lines)
    if "proposed drop rules" in report.lower():
        proposed_section = report.lower().split("proposed drop rules")[1].split("##")[0]
        assert "small_sub" not in proposed_section


def test_section_proposal_appears_for_10_rejects_0_keeps():
    lines = [
        {
            "date": "2026-11-08",
            "id": f"t3_{i}",
            "sub": f"sub_{i}",
            "section": "career",
            "title": f"Resume {i}",
            "decision": "reject",
        }
        for i in range(10)
    ]
    report = summarize(lines)
    assert "career" in report.lower()
    proposed_section = report.lower().split("proposed drop rules")[1].split("##")[0]
    assert "career" in proposed_section


def test_auto_dropped_titles_last_14_days():
    today = date(2026, 11, 8)
    recent_date = (today - timedelta(days=3)).isoformat()
    old_date = (today - timedelta(days=20)).isoformat()

    lines = [
        {
            "date": recent_date,
            "id": "t3_recent",
            "sub": "sub1",
            "section": "drop",
            "title": "Recent Auto-Dropped Post",
            "decision": "auto-drop",
        },
        {
            "date": old_date,
            "id": "t3_old",
            "sub": "sub2",
            "section": "drop",
            "title": "Old Auto-Dropped Post",
            "decision": "auto-drop",
        },
    ]

    report = summarize(lines, today=today)
    assert "Recent Auto-Dropped Post" in report
    assert "Old Auto-Dropped Post" not in report


def test_review_main_cli(tmp_path, capsys):
    log_file = tmp_path / "feedback.jsonl"
    entries = [
        {"date": "2026-11-08", "id": "t3_1", "sub": "testsub", "section": "repo", "title": "Test", "decision": "keep"}
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    rc = review_main(feedback_path=log_file)
    assert rc == 0
    captured = capsys.readouterr()
    assert "testsub" in captured.out


def test_main_cli_dispatch(capsys):
    rc = main(["review"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Feedback Review" in captured.out
