import dataclasses
from datetime import date, datetime, timezone
import json
from pathlib import Path
import pytest

from digest.atom import Post
from digest.classify import Item
from digest.fetch import Response
from digest.history import Viewed
from digest.run import Deps, run
from digest.state import State, load, save
from digest.__main__ import main


def make_feed_xml(post_ids: list[str], sub: str = "LocalLLaMA", published: str = "2026-11-08T12:00:00+00:00") -> str:
    entries = []
    for pid in post_ids:
        entries.append(
            f"""  <entry>
    <id>{pid}</id>
    <category term="{sub}"/>
    <title>Title for {pid}</title>
    <link href="https://www.reddit.com/r/{sub}/comments/{pid}/"/>
    <published>{published}</published>
    <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;Body of {pid}&lt;/div&gt;&lt;!-- SC_ON --&gt;</content>
  </entry>"""
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        + "\n".join(entries)
        + "\n</feed>"
    )


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


class RecordingSleep:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.slept: list[float] = []
        self.clock = clock

    def __call__(self, duration: float) -> None:
        self.slept.append(duration)
        if self.clock is not None:
            self.clock.advance(duration)


def test_happy_path_writes_digest_and_updates_state(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"
    clock = FakeClock(100.0)
    sleep = RecordingSleep(clock)

    feed1_xml = make_feed_xml(["t3_f1_p1", "t3_f1_p2"], sub="LocalLLaMA")
    feed2_xml = make_feed_xml(["t3_f2_p1"], sub="embedded")

    def fake_get(url: str) -> Response:
        if "LocalLLaMA" in url:
            return Response(status=200, headers={}, body=feed1_xml)
        elif "embedded" in url:
            return Response(status=200, headers={}, body=feed2_xml)
        return Response(status=200, headers={}, body=make_feed_xml([]))

    def fake_run_agy(brief_text: str, label: str) -> tuple[int, str]:
        # Return classification for posts:
        # t3_f1_p1 -> repo
        # t3_f1_p2 -> drop (confidence 0.95)
        # t3_f2_p1 -> showcase
        # t3_v1 -> knowledge
        lines = [
            json.dumps({"id": "t3_f1_p1", "section": "repo", "confidence": 0.95, "summary": "Cool repo"}),
            json.dumps({"id": "t3_f1_p2", "section": "drop", "confidence": 0.95, "summary": "Drop post"}),
            json.dumps({"id": "t3_f2_p1", "section": "showcase", "confidence": 0.9, "summary": "Hardware showcase"}),
            json.dumps({"id": "t3_v1", "section": "knowledge", "confidence": 0.85, "summary": "Useful knowledge"}),
        ]
        return 0, "\n".join(lines)

    def fake_viewed(since_us: int, profile: Path, tmp: Path) -> tuple[list[Viewed], dict[str, int], int]:
        viewed_posts = [
            Viewed(
                id="t3_v1",
                sub="unfollowed_sub",
                title="Viewed Title",
                url="https://reddit.com/r/unfollowed_sub/comments/v1/",
                visited=1700000050,
            )
        ]
        sub_counts = {
            "unfollowed_sub": 4,
            "LocalLLaMA": 8,  # followed sub, should not be in suggestions
        }
        return viewed_posts, sub_counts, 1700000050

    feeds = [
        ("solo_llama", ["LocalLLaMA"]),
        ("solo_emb", ["embedded"]),
    ]

    deps = Deps(
        get=fake_get,
        sleep=sleep,
        clock=clock,
        run_agy=fake_run_agy,
        viewed=fake_viewed,
        feeds=feeds,
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    digest_path = run(today=date(2026, 11, 8), deps=deps)

    assert digest_path.is_file()
    assert digest_path.name == "2026-11-08.md"
    content = digest_path.read_text(encoding="utf-8")

    # Followed subs section present
    assert "## From followed subs" in content
    assert "### Repo / Tool" in content
    assert "Title for t3_f1_p1" in content
    assert "### Project / Showcase" in content
    assert "Title for t3_f2_p1" in content

    # Dropped item is NOT rendered
    assert "Title for t3_f1_p2" not in content

    # Viewed posts section present
    assert "## From posts you viewed" in content
    assert "### Useful knowledge" in content
    assert "Viewed Title" in content

    # Sub suggestions
    assert "## Sub suggestions" in content
    assert "- r/unfollowed_sub — opened 4 times since last run" in content
    # Followed sub must not be suggested
    assert "LocalLLaMA" not in content.split("## Sub suggestions")[-1]

    # Dropped file written
    dropped_file = work_dir / "dropped" / "2026-11-08.jsonl"
    assert dropped_file.is_file()
    dropped_lines = dropped_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(dropped_lines) == 1
    dropped_data = json.loads(dropped_lines[0])
    assert dropped_data["id"] == "t3_f1_p2"
    assert dropped_data["section"] == "drop"

    # State updated
    state = load(work_dir / "state.json")
    assert "t3_f1_p1" in state.seen
    assert "t3_f1_p2" in state.seen
    assert "t3_f2_p1" in state.seen
    assert "t3_v1" in state.seen
    assert state.last_ids["solo_llama"] == "t3_f1_p1"
    assert state.last_ids["solo_emb"] == "t3_f2_p1"
    assert state.history_since == 1700000050
    assert state.last_digest == str(digest_path)

    # Log written
    log_file = work_dir / "log.txt"
    assert log_file.is_file()
    log_content = log_file.read_text(encoding="utf-8")
    assert "solo_llama" in log_content
    assert "solo_emb" in log_content


def test_feed_error_adds_warning_line_other_feeds_still_present(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    def fake_get(url: str) -> Response:
        if "failing" in url:
            return Response(status=0, headers={}, body="")
        return Response(status=200, headers={}, body=make_feed_xml(["t3_good_1"], sub="goodsub"))

    deps = Deps(
        get=fake_get,
        run_agy=lambda b, l: (0, json.dumps({"id": "t3_good_1", "section": "repo", "confidence": 1.0, "summary": "ok"})),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("failing_feed", ["failingsub"]), ("good_feed", ["goodsub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    digest_path = run(today=date(2026, 11, 8), deps=deps)
    content = digest_path.read_text(encoding="utf-8")

    assert "> Feed 'failing_feed': connection failure" in content
    assert "## From followed subs" in content
    assert "Title for t3_good_1" in content


def test_history_file_not_found_adds_warning_digest_written(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    def fake_viewed(since_us: int, profile: Path, tmp: Path) -> tuple[list[Viewed], dict[str, int], int]:
        raise FileNotFoundError("places.sqlite not found")

    deps = Deps(
        get=lambda u: Response(status=200, headers={}, body=make_feed_xml(["t3_ok_1"], sub="sub")),
        run_agy=lambda b, l: (0, json.dumps({"id": "t3_ok_1", "section": "repo", "confidence": 1.0, "summary": "ok"})),
        viewed=fake_viewed,
        feeds=[("feed1", ["sub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    digest_path = run(today=date(2026, 11, 8), deps=deps)
    content = digest_path.read_text(encoding="utf-8")

    assert "Waterfox history unavailable" in content
    assert "Title for t3_ok_1" in content
    state = load(work_dir / "state.json")
    assert state.history_since == 0


def test_agy_rc_11_warning_all_items_under_other(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    deps = Deps(
        get=lambda u: Response(status=200, headers={}, body=make_feed_xml(["t3_p1", "t3_p2"], sub="sub")),
        run_agy=lambda b, l: (11, "Token expired or network error"),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("feed1", ["sub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    digest_path = run(today=date(2026, 11, 8), deps=deps)
    content = digest_path.read_text(encoding="utf-8")

    assert "agy error (rc=11)" in content
    assert "### Other" in content
    assert "Title for t3_p1" in content
    assert "Title for t3_p2" in content
    assert "### Repo / Tool" not in content


def test_crash_in_render_leaves_state_file_unchanged(tmp_path: Path, monkeypatch):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    initial_state = State(seen={"t3_old": "2026-11-01"}, history_since=500)
    state_file = work_dir / "state.json"
    save(initial_state, state_file)

    deps = Deps(
        get=lambda u: Response(status=200, headers={}, body=make_feed_xml(["t3_new_1"], sub="sub")),
        run_agy=lambda b, l: (0, ""),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("feed1", ["sub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    def failing_render(*args, **kwargs):
        raise RuntimeError("Crash during render")

    monkeypatch.setattr("digest.run.render", failing_render)

    with pytest.raises(RuntimeError, match="Crash during render"):
        run(today=date(2026, 11, 8), deps=deps)

    current_state = load(state_file)
    assert current_state == initial_state


def test_second_run_applies_marks_from_first_digest(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    feed_xml = make_feed_xml(["t3_item1", "t3_item2", "t3_item3"], sub="testsub")

    def fake_agy(b: str, l: str) -> tuple[int, str]:
        lines = [
            json.dumps({"id": "t3_item1", "section": "repo", "confidence": 1.0, "summary": "Item 1"}),
            json.dumps({"id": "t3_item2", "section": "showcase", "confidence": 1.0, "summary": "Item 2"}),
            json.dumps({"id": "t3_item3", "section": "drop", "confidence": 1.0, "summary": "Item 3"}),
        ]
        return 0, "\n".join(lines)

    deps = Deps(
        get=lambda u: Response(status=200, headers={}, body=feed_xml),
        run_agy=fake_agy,
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("feed1", ["testsub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    # 1. Run day 1
    d1_path = run(today=date(2026, 11, 8), deps=deps)
    assert d1_path.is_file()

    # User marks day 1 digest
    d1_content = d1_path.read_text(encoding="utf-8")
    d1_modified = d1_content.replace(
        "- [ ] **Title for t3_item1**", "- [x] **Title for t3_item1**"
    ).replace(
        "- [ ] **Title for t3_item2**", "- [-] **Title for t3_item2**"
    )
    d1_path.write_text(d1_modified, encoding="utf-8")

    # 2. Run day 2
    deps_day2 = Deps(
        get=lambda u: Response(status=200, headers={}, body=make_feed_xml(["t3_day2_p1"], sub="testsub")),
        run_agy=lambda b, l: (0, json.dumps({"id": "t3_day2_p1", "section": "repo", "confidence": 1.0, "summary": "D2"})),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("feed1", ["testsub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    d2_path = run(today=date(2026, 11, 9), deps=deps_day2)
    assert d2_path.is_file()

    # Verify saved.md has keep item
    saved_file = work_dir / "saved.md"
    assert saved_file.is_file()
    saved_text = saved_file.read_text(encoding="utf-8")
    assert "t3_item1" in saved_text
    assert "t3_item2" not in saved_text

    # Verify feedback.jsonl has keep, reject, auto-drop
    feedback_file = work_dir / "feedback.jsonl"
    assert feedback_file.is_file()
    fb_lines = [json.loads(line) for line in feedback_file.read_text(encoding="utf-8").strip().splitlines()]

    decisions = {item["id"]: item["decision"] for item in fb_lines}
    assert decisions["t3_item1"] == "keep"
    assert decisions["t3_item2"] == "reject"
    assert decisions["t3_item3"] == "auto-drop"

    state = load(work_dir / "state.json")
    assert str(d1_path) in state.applied or d1_path.name in state.applied


def test_third_run_with_same_last_digest_logs_nothing_new(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    feed_xml = make_feed_xml(["t3_item1"], sub="testsub")
    deps = Deps(
        get=lambda u: Response(status=200, headers={}, body=feed_xml),
        run_agy=lambda b, l: (0, json.dumps({"id": "t3_item1", "section": "repo", "confidence": 1.0, "summary": "Item 1"})),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("feed1", ["testsub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    d1 = run(today=date(2026, 11, 8), deps=deps)
    d1.write_text(d1.read_text().replace("- [ ]", "- [x]"))

    d2 = run(today=date(2026, 11, 9), deps=deps)

    saved_file = work_dir / "saved.md"
    feedback_file = work_dir / "feedback.jsonl"
    saved_size_before = len(saved_file.read_text(encoding="utf-8").splitlines())
    feedback_size_before = len(feedback_file.read_text(encoding="utf-8").splitlines())

    # Third run: same last_digest is now in applied
    # Set state last_digest back to d1 to test idempotency when already in applied
    st = load(work_dir / "state.json")
    assert str(d1) in st.applied or d1.name in st.applied
    st.last_digest = str(d1)
    save(st, work_dir / "state.json")

    run(today=date(2026, 11, 10), deps=deps)

    saved_size_after = len(saved_file.read_text(encoding="utf-8").splitlines())
    feedback_size_after = len(feedback_file.read_text(encoding="utf-8").splitlines())

    assert saved_size_after == saved_size_before
    assert feedback_size_after == feedback_size_before


def test_feed_missing_from_last_ids_fetches_one_page(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    # Pre-populate state without 'new_feed'
    initial_state = State(last_ids={"existing_feed": "t3_existing"})
    save(initial_state, work_dir / "state.json")

    urls_requested: list[str] = []

    def fake_get(url: str) -> Response:
        urls_requested.append(url)
        # return a 100-post page to see if it would paginate if last_id was set
        post_ids = [f"t3_post_{i}" for i in range(100)]
        return Response(status=200, headers={}, body=make_feed_xml(post_ids, sub="newsub"))

    deps = Deps(
        get=fake_get,
        run_agy=lambda b, l: (0, ""),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("new_feed", ["newsub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    run(today=date(2026, 11, 8), deps=deps)

    # Only 1 request must have been made because last_id was None (first run for this feed)
    assert len(urls_requested) == 1
    assert "after=" not in urls_requested[0]


def test_deadline_reached_during_fetch_warning_digest_still_written(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    clock = FakeClock(0.0)

    def fake_get(url: str) -> Response:
        # First feed succeeds at clock 0.0, then advance clock past deadline
        if "first" in url:
            clock.advance(3000.0)  # > 45 min (2700 s)
            return Response(status=200, headers={}, body=make_feed_xml(["t3_f1_ok"], sub="first"))
        return Response(status=200, headers={}, body=make_feed_xml(["t3_f2_skipped"], sub="second"))

    deps = Deps(
        get=fake_get,
        clock=clock,
        run_agy=lambda b, l: (0, json.dumps({"id": "t3_f1_ok", "section": "repo", "confidence": 1.0, "summary": "first"})),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("first_feed", ["first"]), ("second_feed", ["second"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
        deadline_seconds=2700.0,
    )

    digest_path = run(today=date(2026, 11, 8), deps=deps)
    content = digest_path.read_text(encoding="utf-8")

    assert "deadline" in content
    assert "Title for t3_f1_ok" in content
    assert "Title for t3_f2_skipped" not in content


def test_high_volume_sub_warning_when_posts_exceed_500(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    # Generate 505 posts published within 24h of today
    pids = [f"t3_spam_{i}" for i in range(505)]
    xml = make_feed_xml(pids, sub="busy_sub", published="2026-11-08T10:00:00+00:00")

    deps = Deps(
        get=lambda u: Response(status=200, headers={}, body=xml),
        run_agy=lambda b, l: (0, ""),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("busy_feed", ["busy_sub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    digest_path = run(today=date(2026, 11, 8), deps=deps)
    content = digest_path.read_text(encoding="utf-8")

    assert "r/busy_sub exceeded 500 posts in the last 24h (505 posts)" in content


def test_deduplication_seen_cross_feed_and_viewed(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    # Pre-existing seen id: t3_seen_before
    initial_state = State(seen={"t3_seen_before": "2026-11-07"})
    save(initial_state, work_dir / "state.json")

    # Feed 1 has: t3_seen_before, t3_cross_dup, t3_unique_f1
    # Feed 2 has: t3_cross_dup, t3_view_overlap
    feed1_xml = make_feed_xml(["t3_seen_before", "t3_cross_dup", "t3_unique_f1"], sub="sub1")
    feed2_xml = make_feed_xml(["t3_cross_dup", "t3_view_overlap"], sub="sub2")

    def fake_get(url: str) -> Response:
        if "sub1" in url:
            return Response(status=200, headers={}, body=feed1_xml)
        return Response(status=200, headers={}, body=feed2_xml)

    # History viewed has: t3_seen_before, t3_view_overlap, t3_view_unique
    def fake_viewed(since: int, profile: Path, tmp: Path) -> tuple[list[Viewed], dict[str, int], int]:
        views = [
            Viewed(id="t3_seen_before", sub="sub3", title="Seen Before", url="https://reddit.com/r/sub3/comments/seen_before/", visited=1),
            Viewed(id="t3_view_overlap", sub="sub2", title="Overlap", url="https://reddit.com/r/sub2/comments/view_overlap/", visited=2),
            Viewed(id="t3_view_unique", sub="sub3", title="Unique View", url="https://reddit.com/r/sub3/comments/view_unique/", visited=3),
        ]
        return views, {"sub3": 2}, 3

    deps = Deps(
        get=fake_get,
        run_agy=lambda b, l: (0, ""),
        viewed=fake_viewed,
        feeds=[("f1", ["sub1"]), ("f2", ["sub2"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    digest_path = run(today=date(2026, 11, 8), deps=deps)
    content = digest_path.read_text(encoding="utf-8")

    # t3_seen_before should not appear anywhere
    assert "t3_seen_before" not in content

    # t3_cross_dup should appear exactly once under followed subs
    assert content.count("id:t3_cross_dup") == 1

    # t3_view_overlap should appear only under followed subs, NOT under viewed posts
    followed_part, viewed_part = content.split("## From posts you viewed")
    assert "id:t3_view_overlap" in followed_part
    assert "id:t3_view_overlap" not in viewed_part

    # t3_view_unique should appear under viewed posts
    assert "id:t3_view_unique" in viewed_part


def test_same_day_rerun_overwrites_digest(tmp_path: Path):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    def make_deps(pids: list[str]) -> Deps:
        return Deps(
            get=lambda u: Response(status=200, headers={}, body=make_feed_xml(pids, sub="sub")),
            run_agy=lambda b, l: (0, ""),
            viewed=lambda s, p, t: ([], {}, s),
            feeds=[("f1", ["sub"])],
            work_dir=work_dir,
            digests_dir=digests_dir,
        )

    p1 = run(today=date(2026, 11, 8), deps=make_deps(["t3_run1"]))
    assert "t3_run1" in p1.read_text(encoding="utf-8")

    p2 = run(today=date(2026, 11, 8), deps=make_deps(["t3_run2"]))
    assert p1 == p2
    assert "t3_run2" in p2.read_text(encoding="utf-8")


def test_cli_run_command(tmp_path: Path, monkeypatch):
    work_dir = tmp_path / "work"
    digests_dir = tmp_path / "digests"

    # Monkeypatch Deps default paths or run
    deps = Deps(
        get=lambda u: Response(status=200, headers={}, body=make_feed_xml(["t3_cli_1"], sub="sub")),
        run_agy=lambda b, l: (0, ""),
        viewed=lambda s, p, t: ([], {}, s),
        feeds=[("f1", ["sub"])],
        work_dir=work_dir,
        digests_dir=digests_dir,
    )

    monkeypatch.setattr("digest.__main__.Deps", lambda: deps)

    ret = main(["run", "--date", "2026-11-08"])
    assert ret == 0
    assert (digests_dir / "2026-11-08.md").is_file()
