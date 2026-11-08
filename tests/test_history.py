import os
import pathlib
import sqlite3
import pytest

from digest.config import WORK
from digest.history import PROFILE, Viewed, parse_reddit_comment_url, viewed_since


def create_history_db(
    db_path: pathlib.Path,
    places: list[tuple[int, str, str | None]],
    visits: list[tuple[int, int, int]],
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE moz_places ("
        "id INTEGER PRIMARY KEY, "
        "url TEXT, "
        "title TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE moz_historyvisits ("
        "id INTEGER PRIMARY KEY, "
        "place_id INTEGER, "
        "visit_date INTEGER"
        ")"
    )
    conn.executemany("INSERT INTO moz_places (id, url, title) VALUES (?, ?, ?)", places)
    conn.executemany("INSERT INTO moz_historyvisits (id, place_id, visit_date) VALUES (?, ?, ?)", visits)
    conn.commit()
    conn.close()


def test_profile_constant_is_path():
    assert isinstance(PROFILE, pathlib.Path)
    assert PROFILE.name == "s4mt22a6.default-release"
    assert "Waterfox" in str(PROFILE)


def test_only_reddit_comment_urls_returned(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/technology/comments/123/tech_news/", "Tech News : r/technology"),
        (2, "https://github.com/astral-sh/uv", "astral-sh/uv: Python package installer"),
        (3, "https://www.reddit.com/r/technology/", "Technology : r/technology"),
        (4, "https://www.reddit.com/r/technology/top/?t=all", "Top Posts : r/technology"),
        (5, "https://reddit.com/r/LocalLLaMA/comments/456/new_model/", "New Model : r/LocalLLaMA"),
    ]
    visits = [
        (101, 1, 1000),
        (102, 2, 2000),
        (103, 3, 3000),
        (104, 4, 4000),
        (105, 5, 5000),
    ]
    create_history_db(db_file, places, visits)

    tmp_scratch = tmp_path / "scratch"
    viewed, counts, max_us = viewed_since(0, profile=profile_dir, tmp=tmp_scratch)

    assert len(viewed) == 2
    viewed_ids = {v.id for v in viewed}
    assert viewed_ids == {"t3_123", "t3_456"}
    assert counts == {"technology": 1, "LocalLLaMA": 1}
    assert max_us == 5000


def test_since_filter(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/sub1/comments/post1/slug/", "Post 1 : r/sub1"),
        (2, "https://www.reddit.com/r/sub2/comments/post2/slug/", "Post 2 : r/sub2"),
        (3, "https://www.reddit.com/r/sub3/comments/post3/slug/", "Post 3 : r/sub3"),
    ]
    visits = [
        (101, 1, 100),
        (102, 2, 200),
        (103, 3, 300),
    ]
    create_history_db(db_file, places, visits)

    # since_us = 150 -> only visits > 150 (200, 300)
    viewed, counts, max_us = viewed_since(150, profile=profile_dir, tmp=tmp_path / "scratch")
    assert [v.id for v in viewed] == ["t3_post3", "t3_post2"]
    assert counts == {"sub2": 1, "sub3": 1}
    assert max_us == 300

    # since_us = 350 -> nothing new
    viewed_none, counts_none, max_us_none = viewed_since(350, profile=profile_dir, tmp=tmp_path / "scratch")
    assert viewed_none == []
    assert counts_none == {}
    assert max_us_none == 350


def test_title_suffix_stripped(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/embedded/comments/p1/a/", "IMC Hardware Engineering role : r/embedded"),
        (2, "https://www.reddit.com/r/EMBEDDED/comments/p2/b/", "Different casing test : r/EMBEDDED"),
        (3, "https://www.reddit.com/r/c_sharp/comments/p3/c/", "Title with colon : something : r/c_sharp"),
        (4, "https://www.reddit.com/r/c_sharp/comments/p4/d/", "Title without any suffix"),
        (5, "https://www.reddit.com/r/c_sharp/comments/p5/e/", None),
        (6, "https://www.reddit.com/r/c_sharp/comments/p6/f/", "   "),
    ]
    visits = [
        (101, 1, 100),
        (102, 2, 200),
        (103, 3, 300),
        (104, 4, 400),
        (105, 5, 500),
        (106, 6, 600),
    ]
    create_history_db(db_file, places, visits)

    viewed, _, _ = viewed_since(0, profile=profile_dir, tmp=tmp_path / "scratch")
    by_id = {v.id: v for v in viewed}

    assert by_id["t3_p1"].title == "IMC Hardware Engineering role"
    assert by_id["t3_p2"].title == "Different casing test"
    assert by_id["t3_p3"].title == "Title with colon : something"
    assert by_id["t3_p4"].title == "Title without any suffix"
    assert by_id["t3_p5"].title == ""
    assert by_id["t3_p6"].title == ""


def test_per_sub_counts(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/LocalLLaMA/comments/m1/post1/", "Post 1 : r/LocalLLaMA"),
        (2, "https://www.reddit.com/r/LocalLLaMA/comments/m2/post2/", "Post 2 : r/LocalLLaMA"),
        (3, "https://www.reddit.com/r/ClaudeCode/comments/c1/post3/", "Post 3 : r/ClaudeCode"),
    ]
    visits = [
        (101, 1, 1000),
        (102, 1, 1050),  # post 1 opened a second time
        (103, 2, 1100),
        (104, 3, 1200),
    ]
    create_history_db(db_file, places, visits)

    viewed, counts, max_us = viewed_since(0, profile=profile_dir, tmp=tmp_path / "scratch")

    assert counts == {"LocalLLaMA": 3, "ClaudeCode": 1}
    assert len(viewed) == 3
    assert max_us == 1200


def test_returned_max_visit_time_newest_and_since_when_none(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/FPGA/comments/f1/role/", "FPGA Role : r/FPGA"),
    ]
    visits = [
        (101, 1, 9999),
    ]
    create_history_db(db_file, places, visits)

    # When fixture has visits after since_us
    _, _, max_us = viewed_since(100, profile=profile_dir, tmp=tmp_path / "scratch")
    assert max_us == 9999

    # When nothing new after since_us
    _, _, max_us_empty = viewed_since(9999, profile=profile_dir, tmp=tmp_path / "scratch")
    assert max_us_empty == 9999

    _, _, max_us_future = viewed_since(15000, profile=profile_dir, tmp=tmp_path / "scratch")
    assert max_us_future == 15000


def test_copy_in_tmp_deleted_afterwards(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/sub/comments/s1/title/", "Title : r/sub"),
    ]
    visits = [(101, 1, 100)]
    create_history_db(db_file, places, visits)

    tmp_scratch = tmp_path / "custom_tmp"
    tmp_scratch.mkdir(parents=True, exist_ok=True)

    viewed, counts, max_us = viewed_since(0, profile=profile_dir, tmp=tmp_scratch)
    assert len(viewed) == 1

    # Verify that places.sqlite (and any related temp db files) are cleaned up
    assert not (tmp_scratch / "places.sqlite").exists()
    assert not (tmp_scratch / "places.sqlite-wal").exists()
    assert not (tmp_scratch / "places.sqlite-shm").exists()
    assert list(tmp_scratch.glob("places*")) == []


def test_missing_profile_raises_file_not_found(tmp_path):
    missing_dir = tmp_path / "nonexistent_profile"
    with pytest.raises(FileNotFoundError):
        viewed_since(0, profile=missing_dir, tmp=tmp_path / "scratch")


def test_missing_places_sqlite_in_profile_raises_file_not_found(tmp_path):
    empty_profile = tmp_path / "empty_profile"
    empty_profile.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        viewed_since(0, profile=empty_profile, tmp=tmp_path / "scratch")


def test_one_row_per_post_keeps_latest_visit(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/sub/comments/repeat/slug1/", "Title Old : r/sub"),
        (2, "https://www.reddit.com/r/sub/comments/repeat/slug2/", "Title New : r/sub"),
    ]
    visits = [
        (101, 1, 100),
        (102, 1, 200),
        (103, 2, 300),  # Same post ID 'repeat', latest visit 300
    ]
    create_history_db(db_file, places, visits)

    viewed, counts, max_us = viewed_since(0, profile=profile_dir, tmp=tmp_path / "scratch")

    assert len(viewed) == 1
    post = viewed[0]
    assert post.id == "t3_repeat"
    assert post.visited == 300
    assert post.title == "Title New"
    assert post.url == "https://www.reddit.com/r/sub/comments/repeat/slug2/"
    assert counts == {"sub": 3}
    assert max_us == 300


def test_preserves_earlier_title_if_latest_visit_title_is_empty(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/sub/comments/p1/slug/", "Good Title : r/sub"),
        (2, "https://www.reddit.com/r/sub/comments/p1/", None),
    ]
    visits = [
        (101, 1, 100),
        (102, 2, 200),
    ]
    create_history_db(db_file, places, visits)

    viewed, _, _ = viewed_since(0, profile=profile_dir, tmp=tmp_path / "scratch")
    assert len(viewed) == 1
    assert viewed[0].title == "Good Title"
    assert viewed[0].visited == 200


def test_wal_file_is_copied_and_deleted(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"
    wal_file = profile_dir / "places.sqlite-wal"

    # Set up WAL mode database
    profile_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute("CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)")
    conn.execute(
        "INSERT INTO moz_places VALUES (1, 'https://www.reddit.com/r/wal_sub/comments/wal1/test/', 'WAL Post : r/wal_sub')"
    )
    conn.execute("INSERT INTO moz_historyvisits VALUES (101, 1, 5555)")
    conn.commit()
    # Check that WAL file exists while connection is open or after
    assert wal_file.exists() or db_file.exists()

    tmp_scratch = tmp_path / "scratch"
    viewed, counts, max_us = viewed_since(0, profile=profile_dir, tmp=tmp_scratch)
    conn.close()

    assert len(viewed) == 1
    assert viewed[0].id == "t3_wal1"
    assert counts == {"wal_sub": 1}
    assert max_us == 5555
    assert not (tmp_scratch / "places.sqlite").exists()
    assert not (tmp_scratch / "places.sqlite-wal").exists()


def test_invalid_since_us_raises(tmp_path):
    with pytest.raises(ValueError):
        viewed_since(-1, profile=tmp_path)
    with pytest.raises(ValueError):
        viewed_since("100", profile=tmp_path)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        viewed_since(True, profile=tmp_path)  # type: ignore[arg-type]


def test_profile_accepts_direct_file_path(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "custom.sqlite"

    places = [(1, "https://www.reddit.com/r/direct/comments/d1/link/", "Direct : r/direct")]
    visits = [(101, 1, 42)]
    create_history_db(db_file, places, visits)

    viewed, counts, max_us = viewed_since(0, profile=db_file, tmp=tmp_path / "scratch")
    assert len(viewed) == 1
    assert viewed[0].id == "t3_d1"
    assert counts == {"direct": 1}
    assert max_us == 42


def test_cleanup_occurs_even_on_database_error(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Corrupt sqlite database file
    db_file.write_bytes(b"not a valid sqlite database header at all")

    tmp_scratch = tmp_path / "scratch"
    with pytest.raises(sqlite3.DatabaseError):
        viewed_since(0, profile=profile_dir, tmp=tmp_scratch)

    # Ensure cleanup still happened
    assert not (tmp_scratch / "places.sqlite").exists()


def test_parse_reddit_comment_url_rejects_non_reddit_and_relative_urls():
    assert parse_reddit_comment_url(None) is None
    assert parse_reddit_comment_url("") is None
    assert parse_reddit_comment_url("/r/python/comments/123/title/") is None
    assert parse_reddit_comment_url("file:///r/python/comments/123/title/") is None
    assert parse_reddit_comment_url("javascript:/r/python/comments/123/title/") is None
    assert parse_reddit_comment_url("https://attacker.com/r/python/comments/123/title/") is None
    assert parse_reddit_comment_url("https://reddit.com.attacker.com/r/python/comments/123/title/") is None
    assert parse_reddit_comment_url("https://not-reddit.com/r/python/comments/123/title/") is None
    assert parse_reddit_comment_url("https://www.reddit.com/r/../comments/123/title/") is None
    assert parse_reddit_comment_url("https://www.reddit.com/r//comments/123/title/") is None
    assert parse_reddit_comment_url("https://www.reddit.com/r/technology/comments/") is None
    assert parse_reddit_comment_url("https://www.reddit.com/r/technology/comments") is None


def test_parse_reddit_comment_url_accepts_valid_schemes_and_ports():
    assert parse_reddit_comment_url("https://reddit.com/r/technology/comments/123/tech/") == ("technology", "123")
    assert parse_reddit_comment_url("http://www.reddit.com/r/technology/comments/123/tech/") == ("technology", "123")
    assert parse_reddit_comment_url("https://old.reddit.com/r/technology/comments/123/tech/") == ("technology", "123")
    assert parse_reddit_comment_url("https://user:pass@reddit.com/r/technology/comments/123/tech/") == ("technology", "123")
    assert parse_reddit_comment_url("https://www.reddit.com:443/r/technology/comments/123/tech/") == ("technology", "123")
    assert parse_reddit_comment_url("https://reddit.com/r/LocalLLaMA/comments/t3_456/") == ("LocalLLaMA", "456")


def test_post_id_case_normalization_and_deduplication(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/sub/comments/AbC123/slug1/", "Title 1 : r/sub"),
        (2, "https://www.reddit.com/r/sub/comments/abc123/slug2/", "Title 2 : r/sub"),
    ]
    visits = [
        (101, 1, 100),
        (102, 2, 200),
    ]
    create_history_db(db_file, places, visits)

    viewed, counts, max_us = viewed_since(0, profile=profile_dir, tmp=tmp_path / "scratch")
    assert len(viewed) == 1
    assert viewed[0].id == "t3_abc123"
    assert viewed[0].visited == 200
    assert counts == {"sub": 2}


def test_stale_temp_artifacts_cleaned_before_copy(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [(1, "https://www.reddit.com/r/sub/comments/s1/title/", "Title : r/sub")]
    visits = [(101, 1, 100)]
    create_history_db(db_file, places, visits)

    tmp_scratch = tmp_path / "scratch"
    tmp_scratch.mkdir(parents=True, exist_ok=True)
    # Pre-populate stale artifacts
    (tmp_scratch / "places.sqlite-wal").write_bytes(b"stale-wal-garbage")
    (tmp_scratch / "places.sqlite-shm").write_bytes(b"stale-shm-garbage")

    viewed, counts, max_us = viewed_since(0, profile=profile_dir, tmp=tmp_scratch)
    assert len(viewed) == 1
    assert viewed[0].id == "t3_s1"
    # Ensure all cleaned up
    assert not (tmp_scratch / "places.sqlite").exists()
    assert not (tmp_scratch / "places.sqlite-wal").exists()
    assert not (tmp_scratch / "places.sqlite-shm").exists()


def test_missing_sqlite_file_error_message(tmp_path):
    missing_file = tmp_path / "custom_missing.sqlite"
    with pytest.raises(FileNotFoundError) as exc_info:
        viewed_since(0, profile=missing_file, tmp=tmp_path / "scratch")
    # Must report the missing file path itself, not appending places.sqlite
    assert "custom_missing.sqlite" in str(exc_info.value)
    assert "custom_missing.sqlite\\places.sqlite" not in str(exc_info.value)
    assert "custom_missing.sqlite/places.sqlite" not in str(exc_info.value)


def test_deterministic_sort_order_with_identical_timestamps(tmp_path):
    profile_dir = tmp_path / "profile"
    db_file = profile_dir / "places.sqlite"

    places = [
        (1, "https://www.reddit.com/r/sub/comments/bbb/title/", "Post B : r/sub"),
        (2, "https://www.reddit.com/r/sub/comments/aaa/title/", "Post A : r/sub"),
        (3, "https://www.reddit.com/r/sub/comments/ccc/title/", "Post C : r/sub"),
    ]
    visits = [
        (101, 1, 1000),
        (102, 2, 1000),
        (103, 3, 1000),
    ]
    create_history_db(db_file, places, visits)

    viewed, _, _ = viewed_since(0, profile=profile_dir, tmp=tmp_path / "scratch")
    ids = [v.id for v in viewed]
    # Sorted by (visited, id) descending -> ccc, bbb, aaa
    assert ids == ["t3_ccc", "t3_bbb", "t3_aaa"]
