import json
from pathlib import Path
import pytest

from digest.config import FEWSHOT_N
from digest.examples import feedback_examples


def test_examples_missing_file_returns_empty(tmp_path: Path):
    assert feedback_examples(tmp_path / "nonexistent.jsonl") == ""


def test_examples_empty_file_returns_empty(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert feedback_examples(p) == ""
    p.write_text("   \n\n  ", encoding="utf-8")
    assert feedback_examples(p) == ""


def test_examples_skips_corrupt_lines_and_neutral(tmp_path: Path):
    p = tmp_path / "feedback.jsonl"
    lines = [
        "not json at all",
        json.dumps({"id": "t3_1", "sub": "LocalLLaMA", "title": "Neutral title", "decision": "neutral"}),
        json.dumps({"id": "t3_2", "sub": "embedded", "title": "Auto drop title", "decision": "auto-drop"}),
        json.dumps({"id": "t3_3", "sub": "LocalLLaMA", "title": "Reject one", "decision": "reject"}),
        json.dumps({"id": "t3_4", "sub": "embedded", "title": "Reject two", "decision": "reject"}),
        json.dumps({"id": "t3_5", "sub": "FPGA", "title": "Keep one", "decision": "keep"}),
    ]
    p.write_text("\n".join(lines), encoding="utf-8")

    out = feedback_examples(p)
    assert out.startswith("Examples of this reader's taste (from past marks):")
    out_lines = out.strip().splitlines()
    # 1 header line + 3 example lines = 4 lines
    assert len(out_lines) == 4
    assert out_lines[1] == "REJECT | r/LocalLLaMA | Reject one"
    assert out_lines[2] == "REJECT | r/embedded | Reject two"
    assert out_lines[3] == "KEEP | r/FPGA | Keep one"


def test_examples_limits_to_n_most_recent(tmp_path: Path):
    p = tmp_path / "feedback.jsonl"
    lines = [
        json.dumps({"id": f"t3_{i}", "sub": "sub", "title": f"Title {i}", "decision": "reject"})
        for i in range(40)
    ]
    p.write_text("\n".join(lines), encoding="utf-8")

    out = feedback_examples(p, n=15)
    out_lines = out.strip().splitlines()[1:]
    assert len(out_lines) == 15
    # Last 15: 25 to 39
    assert out_lines[0] == "REJECT | r/sub | Title 25"
    assert out_lines[-1] == "REJECT | r/sub | Title 39"
