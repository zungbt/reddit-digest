import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from digest.state import State, load, prune, save


def test_state_defaults():
    s = State()
    assert s.seen == {}
    assert s.last_ids == {}
    assert s.history_since == 0
    assert s.last_digest is None
    assert s.applied == []


def test_roundtrip(tmp_path: Path):
    target = tmp_path / "state.json"
    original = State(
        seen={"t3_post1": "2026-11-01", "t3_post2": "2026-11-02"},
        last_ids={"LocalLLaMA": "t3_100", "hardware": "t3_200"},
        history_since=1710000000000,
        last_digest="digests/2026-11-07.md",
        applied=["digests/2026-11-05.md", "digests/2026-11-06.md"],
    )

    save(original, target)
    assert target.is_file()

    # Verify no temp files leaked in target directory
    directory_files = [f.name for f in tmp_path.iterdir()]
    assert directory_files == ["state.json"]

    loaded = load(target)
    assert loaded == original
    assert loaded.seen == original.seen
    assert loaded.last_ids == original.last_ids
    assert loaded.history_since == original.history_since
    assert loaded.last_digest == original.last_digest
    assert loaded.applied == original.applied


def test_save_str_path(tmp_path: Path):
    target = str(tmp_path / "state_str.json")
    s = State(history_since=42)
    save(s, target)
    loaded = load(target)
    assert loaded.history_since == 42


def test_save_creates_parent_directories(tmp_path: Path):
    target = tmp_path / "nested" / "sub" / "folder" / "state.json"
    s = State(last_digest="digests/foo.md")
    save(s, target)
    assert target.is_file()
    loaded = load(target)
    assert loaded.last_digest == "digests/foo.md"


def test_save_atomic_overwrite(tmp_path: Path):
    target = tmp_path / "state.json"
    s1 = State(seen={"t3_1": "2026-11-01"})
    save(s1, target)

    s2 = State(seen={"t3_2": "2026-11-02"}, history_since=999)
    save(s2, target)

    loaded = load(target)
    assert loaded.seen == {"t3_2": "2026-11-02"}
    assert loaded.history_since == 999
    # Confirm no orphan temp files
    assert list(tmp_path.glob("*.tmp")) == []


def test_missing_file_returns_empty(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist.json"
    s = load(nonexistent)
    assert s == State()
    assert s.seen == {}
    assert s.last_ids == {}
    assert s.history_since == 0
    assert s.last_digest is None
    assert s.applied == []


def test_corrupt_json_raises(tmp_path: Path):
    target = tmp_path / "corrupt.json"
    target.write_text("{broken json: [", encoding="utf-8")

    with pytest.raises(Exception):
        load(target)


def test_empty_file_raises(tmp_path: Path):
    target = tmp_path / "empty.json"
    target.write_text("", encoding="utf-8")

    with pytest.raises(Exception):
        load(target)


def test_non_dict_json_raises(tmp_path: Path):
    target = tmp_path / "array.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError):
        load(target)


def test_invalid_field_types_raise(tmp_path: Path):
    bad_seen = tmp_path / "bad_seen.json"
    bad_seen.write_text(json.dumps({"seen": "not-a-dict"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(bad_seen)

    bad_seen_vals = tmp_path / "bad_seen_vals.json"
    bad_seen_vals.write_text(json.dumps({"seen": {"t3_1": 12345}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(bad_seen_vals)

    bad_last_ids = tmp_path / "bad_last_ids.json"
    bad_last_ids.write_text(json.dumps({"last_ids": {"sub": 999}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(bad_last_ids)

    bad_history = tmp_path / "bad_history.json"
    bad_history.write_text(json.dumps({"history_since": "not-an-int"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(bad_history)

    bad_applied = tmp_path / "bad_applied.json"
    bad_applied.write_text(json.dumps({"applied": "not-a-list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(bad_applied)

    bad_applied_vals = tmp_path / "bad_applied_vals.json"
    bad_applied_vals.write_text(json.dumps({"applied": [123]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(bad_applied_vals)


def test_load_directory_raises(tmp_path: Path):
    dir_path = tmp_path / "somedir"
    dir_path.mkdir()
    with pytest.raises(IsADirectoryError):
        load(dir_path)


def test_prune_invalid_date_format_raises():
    s = State(seen={"t3_invalid": "not-a-valid-date"})
    with pytest.raises(ValueError):
        prune(s, today=date(2026, 11, 8))


def test_load_partial_dict(tmp_path: Path):
    target = tmp_path / "partial.json"
    target.write_text(json.dumps({"seen": {"t3_x": "2026-11-08"}}), encoding="utf-8")
    s = load(target)
    assert s.seen == {"t3_x": "2026-11-08"}
    assert s.last_ids == {}
    assert s.history_since == 0
    assert s.last_digest is None
    assert s.applied == []


def test_prune_drops_older_than_30_days():
    today = date(2026, 11, 8)
    # 30 days ago is 2026-10-09
    # 31 days ago is 2026-10-08
    s = State(
        seen={
            "t3_today": "2026-11-08",
            "t3_recent": "2026-11-01",
            "t3_29d": "2026-10-10",
            "t3_30d": "2026-10-09",
            "t3_31d": "2026-10-08",
            "t3_old": "2026-09-01",
        }
    )
    prune(s, today=today, days=30)
    assert "t3_today" in s.seen
    assert "t3_recent" in s.seen
    assert "t3_29d" in s.seen
    assert "t3_30d" in s.seen
    assert "t3_31d" not in s.seen
    assert "t3_old" not in s.seen


def test_prune_custom_days():
    today = date(2026, 11, 8)
    s = State(
        seen={
            "t3_today": "2026-11-08",
            "t3_5d": "2026-11-03",
            "t3_7d": "2026-11-01",
            "t3_8d": "2026-10-31",
        }
    )
    prune(s, today=today, days=7)
    assert s.seen == {
        "t3_today": "2026-11-08",
        "t3_5d": "2026-11-03",
        "t3_7d": "2026-11-01",
    }


def test_prune_iso_datetime_strings():
    today = date(2026, 11, 8)
    s = State(
        seen={
            "t3_iso_recent": "2026-11-08T14:30:00+00:00",
            "t3_iso_old": "2026-09-01T00:00:00Z",
        }
    )
    prune(s, today=today, days=30)
    assert "t3_iso_recent" in s.seen
    assert "t3_iso_old" not in s.seen


def test_prune_accepts_datetime_as_today():
    today_dt = datetime(2026, 11, 8, 21, 0, 0)
    s = State(
        seen={
            "t3_recent": "2026-11-07",
            "t3_old": "2026-09-01",
        }
    )
    prune(s, today=today_dt, days=30)
    assert "t3_recent" in s.seen
    assert "t3_old" not in s.seen


def test_prune_keeps_last_60_applied():
    s = State(applied=[f"digest_{i}.md" for i in range(100)])
    prune(s, today=date(2026, 11, 8))
    assert len(s.applied) == 60
    assert s.applied == [f"digest_{i}.md" for i in range(40, 100)]


def test_prune_preserves_short_applied():
    s = State(applied=["digest_1.md", "digest_2.md"])
    prune(s, today=date(2026, 11, 8))
    assert s.applied == ["digest_1.md", "digest_2.md"]


def test_prune_empty_state():
    s = State()
    prune(s, today=date(2026, 11, 8))
    assert s.seen == {}
    assert s.applied == []


def test_load_boolean_history_since_raises(tmp_path: Path):
    target = tmp_path / "bool_history.json"
    target.write_text(json.dumps({"history_since": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="'history_since' must be a non-negative int"):
        load(target)


def test_load_negative_history_since_raises(tmp_path: Path):
    target = tmp_path / "neg_history.json"
    target.write_text(json.dumps({"history_since": -1}), encoding="utf-8")
    with pytest.raises(ValueError, match="'history_since' must be a non-negative int"):
        load(target)


def test_load_invalid_seen_date_format_raises(tmp_path: Path):
    target = tmp_path / "bad_date_seen.json"
    target.write_text(json.dumps({"seen": {"t3_bad": "not-an-iso-date"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid date in 'seen'"):
        load(target)


def test_save_validates_state_before_writing(tmp_path: Path):
    target = tmp_path / "state.json"
    valid = State(seen={"t3_ok": "2026-11-08"})
    save(valid, target)

    # Attempt to save state with invalid field
    bad_state = State(seen="not_a_dict")  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        save(bad_state, target)

    # Ensure previous valid state was not overwritten or corrupted
    loaded = load(target)
    assert loaded == valid


def test_save_non_state_raises(tmp_path: Path):
    target = tmp_path / "state.json"
    with pytest.raises(TypeError, match="Expected State instance"):
        save({"seen": {}}, target)  # type: ignore


def test_save_directory_raises(tmp_path: Path):
    dir_path = tmp_path / "target_dir"
    dir_path.mkdir()
    with pytest.raises(IsADirectoryError):
        save(State(), dir_path)


def test_save_handles_transient_lock_retry(tmp_path: Path, monkeypatch):
    import os
    target = tmp_path / "state.json"
    save(State(history_since=1), target)

    original_replace = os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("[WinError 5] Access is denied")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    save(State(history_since=2), target)

    assert len(calls) == 3
    loaded = load(target)
    assert loaded.history_since == 2


def test_prune_negative_days_raises():
    s = State(seen={"t3_x": "2026-11-08"})
    with pytest.raises(ValueError, match="'days' must be non-negative"):
        prune(s, today=date(2026, 11, 8), days=-1)


def test_prune_non_state_raises():
    with pytest.raises(TypeError, match="Expected State instance"):
        prune("not_a_state", today=date(2026, 11, 8))  # type: ignore


def test_prune_iso_date_with_z_suffix():
    s = State(seen={"t3_z": "2026-11-08Z", "t3_old": "2026-09-01Z"})
    prune(s, today=date(2026, 11, 8), days=30)
    assert "t3_z" in s.seen
    assert "t3_old" not in s.seen


def test_prune_date_with_whitespace():
    s = State(seen={"t3_ws": "  2026-11-08  "})
    prune(s, today=date(2026, 11, 8), days=30)
    assert "t3_ws" in s.seen


def test_save_trailing_newline(tmp_path: Path):
    target = tmp_path / "state.json"
    save(State(), target)
    content = target.read_bytes()
    assert content.endswith(b"\n")

