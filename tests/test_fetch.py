import pytest
from digest.atom import Post
from digest.fetch import Response, FeedResult, curl_get, fetch_feed


def make_feed_xml(post_ids: list[str], sub: str = "embedded") -> str:
    entries = []
    for pid in post_ids:
        entries.append(
            f"""  <entry>
    <id>{pid}</id>
    <category term="{sub}"/>
    <title>Title for {pid}</title>
    <link href="https://www.reddit.com/r/{sub}/comments/{pid}/"/>
    <published>2026-11-08T00:00:00+00:00</published>
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


def test_no_last_id_single_page():
    ids = [f"t3_p1_{i}" for i in range(100)]
    feed_xml = make_feed_xml(ids)
    requested_urls: list[str] = []

    def fake_get(url: str) -> Response:
        requested_urls.append(url)
        return Response(status=200, headers={}, body=feed_xml)

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test-feed",
        subs=["embedded"],
        last_id=None,
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.name == "test-feed"
    assert result.requests == 1
    assert len(result.posts) == 100
    assert result.newest_id == "t3_p1_0"
    assert result.error is None
    assert len(sleep.slept) == 0


def test_paginates_until_last_id():
    p1_ids = [f"t3_p1_{i}" for i in range(100)]
    p2_ids = ["t3_p2_0", "t3_p2_1", "t3_last_target", "t3_p2_3"]

    requested_urls: list[str] = []

    def fake_get(url: str) -> Response:
        requested_urls.append(url)
        if len(requested_urls) == 1:
            return Response(status=200, headers={}, body=make_feed_xml(p1_ids))
        else:
            return Response(status=200, headers={}, body=make_feed_xml(p2_ids))

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="hardware",
        subs=["embedded", "FPGA"],
        last_id="t3_last_target",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 2
    assert len(requested_urls) == 2
    assert "after=t3_p1_99" in requested_urls[1]
    assert len(result.posts) == 102
    assert result.posts[0].id == "t3_p1_0"
    assert result.posts[99].id == "t3_p1_99"
    assert result.posts[100].id == "t3_p2_0"
    assert result.posts[101].id == "t3_p2_1"
    assert result.newest_id == "t3_p1_0"
    assert result.error is None


def test_deadline_stops_requests():
    p1_ids = [f"t3_p1_{i}" for i in range(100)]
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        clock.advance(15.0)
        return Response(status=200, headers={}, body=make_feed_xml(p1_ids))

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_old",
        deadline=10.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert result.error == "deadline"
    assert len(result.posts) == 100
    assert result.newest_id == "t3_p1_0"


def test_no_new_posts():
    p1_ids = ["t3_known_last", "t3_older_1", "t3_older_2"]

    def fake_get(url: str) -> Response:
        return Response(status=200, headers={}, body=make_feed_xml(p1_ids))

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_known_last",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(result.posts) == 0
    assert result.newest_id == "t3_known_last"
    assert result.error is None


def test_stops_at_10_pages():
    pages = {i: [f"t3_p{i}_{j}" for j in range(100)] for i in range(1, 15)}
    requested_urls: list[str] = []

    def fake_get(url: str) -> Response:
        requested_urls.append(url)
        page_idx = len(requested_urls)
        return Response(status=200, headers={}, body=make_feed_xml(pages[page_idx]))

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_non_existent",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 10
    assert len(result.posts) == 1000
    assert result.newest_id == "t3_p1_0"
    assert result.error is None


def test_waits_on_ratelimit():
    p1_ids = [f"t3_p1_{i}" for i in range(100)]
    p2_ids = ["t3_target_last"]
    requested_urls: list[str] = []

    def fake_get(url: str) -> Response:
        requested_urls.append(url)
        if len(requested_urls) == 1:
            headers = {"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "20"}
            return Response(status=200, headers=headers, body=make_feed_xml(p1_ids))
        else:
            return Response(status=200, headers={}, body=make_feed_xml(p2_ids))

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_target_last",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 2
    assert sleep.slept == [22.0]
    assert len(result.posts) == 100
    assert result.error is None


def test_429_retries_then_gives_up():
    def fake_get(url: str) -> Response:
        return Response(status=429, headers={"x-ratelimit-reset": "60"}, body="Too Many Requests")

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_target",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 4
    assert sleep.slept == [62.0, 62.0, 62.0]
    assert result.error is not None
    assert "429" in result.error
    assert result.posts == []


def test_connection_failure():
    def fake_get(url: str) -> Response:
        return Response(status=0, headers={}, body="")

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_target",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert result.error is not None
    assert result.posts == []


def test_url_format():
    recorded_urls: list[str] = []

    def fake_get(url: str) -> Response:
        recorded_urls.append(url)
        return Response(status=200, headers={}, body=make_feed_xml([]))

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    fetch_feed(
        name="hardware",
        subs=["embedded", "FPGA"],
        last_id=None,
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert len(recorded_urls) == 1
    assert recorded_urls[0] == "https://www.reddit.com/r/embedded+FPGA/new/.rss?limit=100"


def test_429_retry_success():
    calls = 0

    def fake_get(url: str) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response(status=429, headers={"x-ratelimit-reset": "80"}, body="Too Many Requests")
        return Response(status=200, headers={}, body=make_feed_xml(["t3_post1"]))

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id=None,
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 2
    assert sleep.slept == [82.0]  # max(80, 60) + 2
    assert result.error is None
    assert len(result.posts) == 1
    assert result.newest_id == "t3_post1"


def test_ratelimit_sleep_crosses_deadline():
    p1_ids = [f"t3_p1_{i}" for i in range(100)]
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        return Response(
            status=200,
            headers={"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "20"},
            body=make_feed_xml(p1_ids),
        )

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_old",
        deadline=15.0,  # 22s sleep would exceed 15s deadline
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(sleep.slept) == 0  # sleep was skipped
    assert result.error == "deadline"
    assert len(result.posts) == 100


def test_429_sleep_crosses_deadline():
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        return Response(
            status=429,
            headers={"x-ratelimit-reset": "60"},
            body="Too Many Requests",
        )

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id=None,
        deadline=50.0,  # 62s sleep would exceed 50s deadline
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(sleep.slept) == 0  # sleep was skipped
    assert result.error == "deadline"
    assert result.posts == []


def test_curl_get_connection_failure():
    resp = curl_get("http://127.0.0.1:9")
    assert resp.status == 0
    assert resp.headers == {}
    assert resp.body == ""


def test_page_under_100_stops_pagination():
    p1_ids = [f"t3_p1_{i}" for i in range(40)]  # only 40 items

    def fake_get(url: str) -> Response:
        return Response(status=200, headers={}, body=make_feed_xml(p1_ids))

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_old_target",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(result.posts) == 40
    assert result.error is None


def test_malformed_xml_sets_error():
    def fake_get(url: str) -> Response:
        return Response(status=200, headers={}, body="<not-valid-xml")

    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id=None,
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert result.error is not None
    assert "parse error" in result.error
    assert result.posts == []


def test_negative_ratelimit_reset_does_not_crash():
    p1_ids = [f"t3_p1_{i}" for i in range(100)]
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        return Response(
            status=200,
            headers={"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "-15"},
            body=make_feed_xml(p1_ids),
        )

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_old_target",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    # reset is clamped to 0.0 + 2.0 = 2.0, never negative
    assert sleep.slept[0] == 2.0


def test_ratelimit_sleep_exact_deadline_skips_sleep():
    p1_ids = [f"t3_p1_{i}" for i in range(100)]
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        return Response(
            status=200,
            headers={"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "20"},
            body=make_feed_xml(p1_ids),
        )

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_old",
        deadline=22.0,  # 0.0 + 22.0 == deadline exactly
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(sleep.slept) == 0  # sleep was skipped because clock + wait >= deadline
    assert result.error == "deadline"
    assert len(result.posts) == 100


def test_429_sleep_exact_deadline_skips_sleep():
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        return Response(
            status=429,
            headers={"x-ratelimit-reset": "60"},
            body="Too Many Requests",
        )

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id=None,
        deadline=62.0,  # 0.0 + 62.0 == deadline exactly
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(sleep.slept) == 0
    assert result.error == "deadline"
    assert result.posts == []


def test_last_id_without_t3_prefix():
    ids = ["t3_abc123", "t3_xyz789", "t3_older"]
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        return Response(status=200, headers={}, body=make_feed_xml(ids))

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="xyz789",  # unprefixed
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(result.posts) == 1
    assert result.posts[0].id == "t3_abc123"
    assert result.newest_id == "t3_abc123"
    assert result.error is None


def test_empty_last_id_fetches_single_page():
    urls: list[str] = []
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        urls.append(url)
        return Response(status=200, headers={}, body=make_feed_xml([f"t3_{len(urls)}_{i}" for i in range(100)]))

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="",  # empty string
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 1
    assert len(urls) == 1
    assert len(result.posts) == 100


def test_empty_subs_returns_error_without_requests():
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        raise AssertionError("Should not be called")

    result = fetch_feed(
        name="test",
        subs=[],
        last_id=None,
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 0
    assert result.error == "no subreddits specified"
    assert result.posts == []


def test_stuck_pagination_stops():
    page_ids = [f"t3_{i}" for i in range(100)]
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        return Response(status=200, headers={}, body=make_feed_xml(page_ids))

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_nonexistent",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    # Detects page_posts[-1].id == after_id on page 2 and stops instead of running 10 pages
    assert result.requests == 2
    assert len(result.posts) == 100
    assert result.error is None


def test_deduplicates_posts_across_pages():
    p1 = [f"t3_{i}" for i in range(100)]
    # Overlapping posts p1[98], p1[99] returned on page 2
    p2 = [f"t3_{i}" for i in range(98, 140)]

    calls = 0
    clock = FakeClock(0.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response(status=200, headers={}, body=make_feed_xml(p1))
        return Response(status=200, headers={}, body=make_feed_xml(p2))

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_nonexistent",
        deadline=1000.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 2
    assert len(result.posts) == 140
    unique_ids = set(p.id for p in result.posts)
    assert len(unique_ids) == 140


def test_deadline_at_start_no_requests():
    clock = FakeClock(10.0)
    sleep = RecordingSleep(clock)

    def fake_get(url: str) -> Response:
        raise AssertionError("Should not be called")

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_target",
        deadline=10.0,
        get=fake_get,
        sleep=sleep,
        clock=clock,
    )

    assert result.requests == 0
    assert result.error == "deadline"
    assert result.posts == []
    assert result.newest_id == "t3_target"




def test_stops_at_seen_post_when_last_id_missing():
    # last_id was deleted from the feed; the first already-seen post must still end paging
    pages = {
        1: [f"t3_p1_{j}" for j in range(100)],
        2: [f"t3_p2_{j}" for j in range(30)] + ["t3_seen_a", "t3_seen_b"] + [f"t3_p2_{j}" for j in range(30, 68)],
        3: [f"t3_p3_{j}" for j in range(100)],
    }
    requested_urls: list[str] = []

    def fake_get(url: str) -> Response:
        requested_urls.append(url)
        return Response(status=200, headers={}, body=make_feed_xml(pages[len(requested_urls)]))

    clock = FakeClock(0.0)
    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id="t3_deleted",
        deadline=1000.0,
        get=fake_get,
        sleep=RecordingSleep(clock),
        clock=clock,
        seen={"t3_seen_a": "2026-11-09", "t3_seen_b": "2026-11-09"},
    )

    assert result.requests == 2
    assert len(result.posts) == 130
    assert "t3_seen_a" not in {p.id for p in result.posts}
    assert result.newest_id == "t3_p1_0"
    assert result.error is None


def test_seen_ignored_on_first_run_single_page():
    def fake_get(url: str) -> Response:
        return Response(status=200, headers={}, body=make_feed_xml(["t3_a", "t3_seen", "t3_b"]))

    result = fetch_feed(
        name="test",
        subs=["embedded"],
        last_id=None,
        deadline=1000.0,
        get=fake_get,
        clock=FakeClock(0.0),
        seen={"t3_seen": "2026-11-09"},
    )

    assert result.requests == 1
    assert [p.id for p in result.posts] == ["t3_a", "t3_seen", "t3_b"]
