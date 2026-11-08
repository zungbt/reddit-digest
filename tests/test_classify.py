import json
from dataclasses import asdict
from pathlib import Path
import pytest

from digest.atom import Post
from digest.history import Viewed
from digest.classify import (
    SECTIONS,
    Item,
    brief,
    classify,
    parse_reply,
    write_input,
)


def _make_post(
    id: str = "t3_100",
    sub: str = "LocalLLaMA",
    title: str = "Sample Post Title",
    url: str = "https://reddit.com/r/LocalLLaMA/comments/100",
    link: str | None = None,
    body: str = "This is a sample post body text.",
) -> Post:
    return Post(
        id=id,
        sub=sub,
        title=title,
        url=url,
        link=link,
        body=body,
        published="2026-11-08T12:00:00Z",
    )


def _make_viewed(
    id: str = "t3_200",
    sub: str = "embedded",
    title: str = "Viewed Post Title",
    url: str = "https://reddit.com/r/embedded/comments/200",
    visited: int = 1700000000000000,
) -> Viewed:
    return Viewed(
        id=id,
        sub=sub,
        title=title,
        url=url,
        visited=visited,
    )


def test_sections_definition():
    expected_order = [
        "repo",
        "showcase",
        "knowledge",
        "money",
        "career",
        "game",
        "qa_tools",
        "other",
        "drop",
    ]
    assert list(SECTIONS.keys()) == expected_order
    assert SECTIONS["repo"] == "Repo / Tool"
    assert SECTIONS["showcase"] == "Project / Showcase"
    assert SECTIONS["knowledge"] == "Useful knowledge"
    assert SECTIONS["money"] == "Money / content with AI"
    assert SECTIONS["career"] == "IT career / abroad"
    assert SECTIONS["game"] == "Game"
    assert SECTIONS["qa_tools"] == "Q&A about my tools"
    assert SECTIONS["other"] == "Other"
    assert SECTIONS["drop"] == "(not rendered)"


def test_parse_reply_ignores_noise():
    raw_text = """
Sure! Here is the classification you requested:

```json
{"id": "t3_abc1", "section": "repo", "confidence": 0.95, "summary": "A fast markdown parser for Python"}
{"id": "t3_abc2", "section": "game", "confidence": 0.88, "summary": "Indie developer shows demo of 3D platformer"}
```

Some additional explanation or notes from the model that should be ignored.
And a blank line:

{"id": "t3_abc3", "section": "knowledge", "confidence": 0.9, "summary": "Guide on quantizing LLMs on consumer hardware"}
Hope this helps!
"""
    parsed = parse_reply(raw_text)
    assert len(parsed) == 3
    assert parsed["t3_abc1"] == ("repo", 0.95, "A fast markdown parser for Python")
    assert parsed["t3_abc2"] == ("game", 0.88, "Indie developer shows demo of 3D platformer")
    assert parsed["t3_abc3"] == ("knowledge", 0.9, "Guide on quantizing LLMs on consumer hardware")


def test_unknown_section_becomes_other():
    raw_text = """
{"id": "t3_1", "section": "unrecognized_topic", "confidence": 0.85, "summary": "Something weird"}
{"id": "t3_2", "section": "RANDOM", "confidence": 0.6, "summary": "Random item"}
{"id": "t3_3", "section": "repo", "confidence": 0.99, "summary": "Known section"}
"""
    parsed = parse_reply(raw_text)
    assert parsed["t3_1"] == ("other", 0.85, "Something weird")
    assert parsed["t3_2"] == ("other", 0.6, "Random item")
    assert parsed["t3_3"] == ("repo", 0.99, "Known section")


def test_missing_ids_become_other():
    p1 = _make_post(id="t3_1", title="Post One", body="Body of post one.")
    p2 = _make_post(id="t3_2", title="Post Two", body="Long body for post two: " + "x" * 250)
    p3 = _make_post(id="t3_3", title="Post Three With No Body", body="")

    # agy only answers 2 of 3 (t3_1 and t3_2)
    def fake_agy(brief_text: str, label: str):
        reply = (
            '{"id": "t3_1", "section": "repo", "confidence": 0.95, "summary": "Summary 1"}\n'
            '{"id": "t3_2", "section": "knowledge", "confidence": 0.9, "summary": "Summary 2"}\n'
        )
        return 0, reply

    items = classify([p1, p2, p3], source="followed", run_agy=fake_agy)
    assert len(items) == 3

    assert items[0].id == "t3_1"
    assert items[0].section == "repo"
    assert items[0].summary == "Summary 1"

    assert items[1].id == "t3_2"
    assert items[1].section == "knowledge"
    assert items[1].summary == "Summary 2"

    # Missing post t3_3 must become "other", summary falls back to title because body is empty
    assert items[2].id == "t3_3"
    assert items[2].section == "other"
    assert items[2].summary == "Post Three With No Body"
    assert items[2].source == "followed"


def test_missing_ids_become_other_body_truncated():
    # If missing post has body > 200 chars, summary is first 200 chars
    long_body = "word " * 60  # 300 chars
    p = _make_post(id="t3_missing", title="Title", body=long_body)

    def fake_agy(brief_text: str, label: str):
        return 0, ""

    items = classify([p], source="followed", run_agy=fake_agy)
    assert len(items) == 1
    assert items[0].section == "other"
    assert items[0].summary == long_body[:200]
    assert len(items[0].summary) == 200


def test_low_confidence_drop_kept_for_followed():
    p1 = _make_post(id="t3_1", title="Followed Low Conf Drop")
    p2 = _make_post(id="t3_2", title="Followed High Conf Drop")
    p3 = _make_viewed(id="t3_3", title="Viewed Low Conf Drop")
    p4 = _make_post(id="t3_4", title="Followed Boundary Exact 0.9 Drop")

    def fake_agy(brief_text: str, label: str):
        reply = "\n".join([
            '{"id": "t3_1", "section": "drop", "confidence": 0.7, "summary": "Meme post"}',
            '{"id": "t3_2", "section": "drop", "confidence": 0.95, "summary": "Clear spam"}',
            '{"id": "t3_3", "section": "drop", "confidence": 0.7, "summary": "Meme post viewed"}',
            '{"id": "t3_4", "section": "drop", "confidence": 0.90, "summary": "Boundary drop"}',
        ])
        return 0, reply

    # Followed: drop with < 0.9 becomes other; >= 0.9 stays drop
    followed_items = classify([p1, p2, p4], source="followed", run_agy=fake_agy)
    assert followed_items[0].section == "other"
    assert followed_items[1].section == "drop"
    assert followed_items[2].section == "drop"

    # Viewed: keep model's drop as is regardless of confidence
    viewed_items = classify([p3], source="viewed", run_agy=fake_agy)
    assert viewed_items[0].section == "drop"


def test_agy_failure_all_other():
    p1 = _make_post(id="t3_1", title="First Post", body="Post one body")
    p2 = _make_viewed(id="t3_2", title="Second Post Viewed")

    def failing_agy(brief_text: str, label: str):
        return 11, "UNAUTHENTICATED: session expired"

    items = classify([p1, p2], source="followed", run_agy=failing_agy)
    assert len(items) == 2

    assert items[0].id == "t3_1"
    assert items[0].section == "other"
    assert items[0].summary == "Post one body"
    assert items[0].source == "followed"

    assert items[1].id == "t3_2"
    assert items[1].section == "other"
    assert items[1].summary == "Second Post Viewed"
    assert items[1].source == "followed"


def test_batches_of_150():
    posts = [_make_post(id=f"t3_{i}", title=f"Post {i}") for i in range(320)]
    agy_calls = []

    def recording_agy(brief_text: str, label: str):
        agy_calls.append((brief_text, label))
        # Return empty lines or valid dummy replies
        lines = [
            f'{{"id": "t3_{i}", "section": "repo", "confidence": 0.9, "summary": "Post {i}"}}'
            for i in range(320)
        ]
        return 0, "\n".join(lines)

    items = classify(posts, source="followed", run_agy=recording_agy)
    assert len(agy_calls) == 3
    assert len(items) == 320
    assert items[0].id == "t3_0"
    assert items[319].id == "t3_319"


def test_brief_size():
    b = brief("work/calib/batch1.jsonl")
    assert isinstance(b, str)
    assert len(b.encode("utf-8")) < 30000
    assert "work/calib/batch1.jsonl" in b


def test_write_input(tmp_path: Path):
    out_file = tmp_path / "input.jsonl"
    p1 = _make_post(
        id="t3_abc",
        sub="LocalLLaMA",
        title="Post Title",
        body="x" * 700,
    )
    v1 = _make_viewed(
        id="t3_def",
        sub="embedded",
        title="Viewed Title",
    )

    write_input([p1, v1], out_file)
    assert out_file.exists()

    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    data1 = json.loads(lines[0])
    assert data1["id"] == "t3_abc"
    assert data1["sub"] == "LocalLLaMA"
    assert data1["title"] == "Post Title"
    assert len(data1["body"]) == 600

    data2 = json.loads(lines[1])
    assert data2["id"] == "t3_def"
    assert data2["sub"] == "embedded"
    assert data2["title"] == "Viewed Title"
    assert data2["body"] == ""


def test_empty_posts():
    calls = []

    def mock_agy(brief_text: str, label: str):
        calls.append(label)
        return 0, ""

    items = classify([], source="followed", run_agy=mock_agy)
    assert items == []
    assert len(calls) == 0


def test_item_asdict_roundtrip():
    item = Item(
        id="t3_123",
        sub="LocalLLaMA",
        title="Test Item",
        url="https://reddit.com/r/LocalLLaMA/comments/123",
        link="https://github.com/foo/bar",
        section="repo",
        summary="A great repository.",
        source="followed",
    )
    d = asdict(item)
    restored = Item(**d)
    assert restored == item


def test_parse_reply_json_array():
    raw_array = json.dumps([
        {"id": "t3_10", "section": "game", "confidence": 0.8, "summary": "Game dev update"},
        {"id": "t3_20", "section": "career", "confidence": 0.75, "summary": "Career advice"},
    ])
    parsed = parse_reply(raw_array)
    assert len(parsed) == 2
    assert parsed["t3_10"] == ("game", 0.8, "Game dev update")
    assert parsed["t3_20"] == ("career", 0.75, "Career advice")


def test_parse_reply_empty_and_garbage():
    assert parse_reply("") == {}
    assert parse_reply("   \n\n  ") == {}
    assert parse_reply("This is not JSON at all.\nNo JSON objects here.") == {}


def test_classify_run_agy_exception_falls_back_to_other():
    p = _make_post(id="t3_err", title="Post On Error", body="Error body text")

    def exploding_agy(brief_text: str, label: str):
        raise RuntimeError("Subprocess execution failed unexpectedly")

    items = classify([p], source="followed", run_agy=exploding_agy)
    assert len(items) == 1
    assert items[0].id == "t3_err"
    assert items[0].section == "other"
    assert items[0].summary == "Error body text"


def test_parse_reply_multiline_json_objects():
    raw_text = """
Some introductory text from the assistant.
{
  "id": "t3_multi1",
  "section": "repo",
  "confidence": 0.95,
  "summary": "Multi-line JSON object parser"
}
Intermediate comment between items.
{
  "id": "t3_multi2",
  "section": "game",
  "confidence": 0.88,
  "summary": "Indie game release"
}
"""
    parsed = parse_reply(raw_text)
    assert len(parsed) == 2
    assert parsed["t3_multi1"] == ("repo", 0.95, "Multi-line JSON object parser")
    assert parsed["t3_multi2"] == ("game", 0.88, "Indie game release")


def test_parse_reply_multiline_json_array_in_code_fence():
    raw_text = """```json
[
  {
    "id": "t3_arr1",
    "section": "knowledge",
    "confidence": 0.9,
    "summary": "Deep dive into model quantization"
  },
  {
    "id": "t3_arr2",
    "section": "money",
    "confidence": 0.82,
    "summary": "Monetizing AI generated content"
  }
]
```"""
    parsed = parse_reply(raw_text)
    assert len(parsed) == 2
    assert parsed["t3_arr1"] == ("knowledge", 0.9, "Deep dive into model quantization")
    assert parsed["t3_arr2"] == ("money", 0.82, "Monetizing AI generated content")


def test_parse_reply_section_aliases_and_headings():
    raw_text = """
{"id": "t3_1", "section": "Repo / Tool", "confidence": 0.95, "summary": "Tool repo"}
{"id": "t3_2", "section": "Project / Showcase", "confidence": 0.9, "summary": "Project showcase"}
{"id": "t3_3", "section": "Useful knowledge", "confidence": 0.85, "summary": "Useful article"}
{"id": "t3_4", "section": "Money / content with AI", "confidence": 0.9, "summary": "Content AI"}
{"id": "t3_5", "section": "IT career / abroad", "confidence": 0.88, "summary": "Abroad career"}
{"id": "t3_6", "section": "qa-tools", "confidence": 0.92, "summary": "Quant setup Q&A"}
{"id": "t3_7", "section": "Q&A about my tools", "confidence": 0.91, "summary": "Tool questions"}
{"id": "t3_8", "section": "totally_random_thing", "confidence": 0.5, "summary": "Unknown"}
"""
    parsed = parse_reply(raw_text)
    assert parsed["t3_1"][0] == "repo"
    assert parsed["t3_2"][0] == "showcase"
    assert parsed["t3_3"][0] == "knowledge"
    assert parsed["t3_4"][0] == "money"
    assert parsed["t3_5"][0] == "career"
    assert parsed["t3_6"][0] == "qa_tools"
    assert parsed["t3_7"][0] == "qa_tools"
    assert parsed["t3_8"][0] == "other"


def test_parse_reply_confidence_percentage_and_scaling():
    p1 = _make_post(id="t3_pct", title="Pct Conf Drop")
    p2 = _make_post(id="t3_int80", title="Int 80 Conf Drop")
    p3 = _make_post(id="t3_int95", title="Int 95 Conf Drop")

    def fake_agy(brief_text: str, label: str):
        reply = "\n".join([
            '{"id": "t3_pct", "section": "drop", "confidence": "85%", "summary": "Meme pct"}',
            '{"id": "t3_int80", "section": "drop", "confidence": 80, "summary": "Meme int"}',
            '{"id": "t3_int95", "section": "drop", "confidence": 95, "summary": "Spam int"}',
        ])
        return 0, reply

    items = classify([p1, p2, p3], source="followed", run_agy=fake_agy)
    # 85% = 0.85 < 0.9 -> other
    assert items[0].section == "other"
    # 80 = 0.80 < 0.9 -> other
    assert items[1].section == "other"
    # 95 = 0.95 >= 0.9 -> drop
    assert items[2].section == "drop"


def test_classify_collapses_whitespace_and_newlines_in_summary():
    p1 = _make_post(id="t3_nl1", title="Title\nWith\nNewlines", body="Body line 1\n\nBody line 2")
    p2 = _make_post(id="t3_nl2", title="Title Two", body="Fallback body")

    def fake_agy(brief_text: str, label: str):
        reply = '{"id": "t3_nl2", "section": "repo", "confidence": 0.95, "summary": "Line one\\nLine two\\n\\nLine three"}'
        return 0, reply

    items = classify([p1, p2], source="followed", run_agy=fake_agy)
    # p1 falls back to clean body
    assert "\n" not in items[0].summary
    assert "\r" not in items[0].summary
    assert "\n" not in items[0].title

    # p2 uses model summary with newlines collapsed
    assert "\n" not in items[1].summary
    assert "\r" not in items[1].summary
    assert items[1].summary == "Line one Line two Line three"


def test_write_input_and_classify_none_fields(tmp_path: Path):
    # Posts with None fields should never produce the string "None"
    class NonePost:
        id = "t3_none"
        sub = None
        title = None
        body = None
        url = None
        link = ""

    out_file = tmp_path / "none_post.jsonl"
    write_input([NonePost()], out_file)
    data = json.loads(out_file.read_text(encoding="utf-8").strip())
    assert data["id"] == "t3_none"
    assert data["sub"] == ""
    assert data["title"] == ""
    assert data["body"] == ""

    def fake_agy(brief_text: str, label: str):
        return 0, ""

    items = classify([NonePost()], source="followed", run_agy=fake_agy)
    assert items[0].id == "t3_none"
    assert items[0].sub == ""
    assert items[0].title == ""
    assert items[0].url == ""
    assert items[0].link is None
    assert items[0].section == "other"


def test_classify_empty_string_link_normalized_to_none():
    p = _make_post(id="t3_empty_link", link="")

    def fake_agy(brief_text: str, label: str):
        return 0, '{"id": "t3_empty_link", "section": "repo", "confidence": 0.9, "summary": "Test"}'

    items = classify([p], source="followed", run_agy=fake_agy)
    assert items[0].link is None
