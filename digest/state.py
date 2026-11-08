import json
import os
import pathlib
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass
class State:
    seen: dict[str, str] = field(default_factory=dict)
    last_ids: dict[str, str] = field(default_factory=dict)
    history_since: int = 0
    last_digest: str | None = None
    applied: list[str] = field(default_factory=list)


def _parse_iso_date(val: str | date | datetime) -> date:
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            raise ValueError("Date string cannot be empty")
        if s.endswith("Z") and "T" not in s and " " not in s:
            s = s[:-1]
        return datetime.fromisoformat(s).date()
    raise TypeError(f"Expected str, date, or datetime, got {type(val).__name__}")


def validate_state(state: State) -> None:
    if not isinstance(state, State):
        raise TypeError(f"Expected State instance, got {type(state).__name__}")

    if not isinstance(state.seen, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in state.seen.items()
    ):
        raise ValueError("'seen' must be a dict[str, str]")
    for k, v in state.seen.items():
        try:
            _parse_iso_date(v)
        except Exception as e:
            raise ValueError(f"Invalid date in 'seen' for key {k!r}: {v!r}") from e

    if not isinstance(state.last_ids, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in state.last_ids.items()
    ):
        raise ValueError("'last_ids' must be a dict[str, str]")

    if (
        isinstance(state.history_since, bool)
        or not isinstance(state.history_since, int)
        or state.history_since < 0
    ):
        raise ValueError(
            f"'history_since' must be a non-negative int, got {state.history_since!r}"
        )

    if state.last_digest is not None and not isinstance(state.last_digest, str):
        raise ValueError(f"'last_digest' must be str or None, got {type(state.last_digest).__name__}")

    if not isinstance(state.applied, list) or not all(isinstance(x, str) for x in state.applied):
        raise ValueError("'applied' must be a list[str]")


def load(path: pathlib.Path | str) -> State:
    p = pathlib.Path(path)
    if not p.exists():
        return State()
    if p.is_dir():
        raise IsADirectoryError(f"Expected a file, found directory: {p}")

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"State file must contain a JSON object, got {type(data).__name__}")

    seen = data.get("seen", {})
    last_ids = data.get("last_ids", {})
    history_since = data.get("history_since", 0)
    last_digest = data.get("last_digest", None)
    applied = data.get("applied", [])

    st = State(
        seen=seen,
        last_ids=last_ids,
        history_since=history_since,
        last_digest=last_digest,
        applied=applied,
    )
    validate_state(st)
    return st


def save(state: State, path: pathlib.Path | str) -> None:
    validate_state(state)

    p = pathlib.Path(path)
    if p.is_dir():
        raise IsADirectoryError(f"Target path is a directory: {p}")

    p.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "seen": state.seen,
        "last_ids": state.last_ids,
        "history_since": state.history_since,
        "last_digest": state.last_digest,
        "applied": state.applied,
    }

    tmp_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=p.parent,
            prefix=f"{p.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = pathlib.Path(f.name)
            json.dump(payload, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                os.replace(tmp_path, p)
                break
            except PermissionError:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.05)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def prune(state: State, today: date, days: int = 30) -> None:
    if not isinstance(state, State):
        raise TypeError(f"Expected State instance, got {type(state).__name__}")
    if days < 0:
        raise ValueError(f"'days' must be non-negative, got {days}")

    current_date = _parse_iso_date(today)
    cutoff = current_date - timedelta(days=days)

    to_drop = [
        post_id
        for post_id, date_str in state.seen.items()
        if _parse_iso_date(date_str) < cutoff
    ]
    for post_id in to_drop:
        del state.seen[post_id]

    if len(state.applied) > 60:
        state.applied[:] = state.applied[-60:]
