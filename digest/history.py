import os
import pathlib
import re
import shutil
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass

from digest.config import WORK

_APPDATA = os.environ.get("APPDATA")
if _APPDATA:
    PROFILE: pathlib.Path = pathlib.Path(_APPDATA) / "Waterfox" / "Profiles" / "s4mt22a6.default-release"
else:
    PROFILE = pathlib.Path.home() / "AppData" / "Roaming" / "Waterfox" / "Profiles" / "s4mt22a6.default-release"


@dataclass
class Viewed:
    id: str
    sub: str
    title: str
    url: str
    visited: int


def parse_reddit_comment_url(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:
        return None

    if parts.scheme not in ("http", "https"):
        return None

    hostname = parts.hostname
    if not hostname:
        return None
    hostname = hostname.lower()
    if hostname != "reddit.com" and not hostname.endswith(".reddit.com"):
        return None

    m = re.match(r"^/r/([A-Za-z0-9_]{2,30})/comments/((?:t3_)?[A-Za-z0-9]+)", parts.path)
    if not m:
        return None

    sub = m.group(1)
    raw_id = m.group(2).lower()
    post_id = raw_id[3:] if raw_id.startswith("t3_") else raw_id
    return sub, post_id


def clean_title(title: str | None, sub: str) -> str:
    if not title:
        return ""
    t = re.sub(r"\s+", " ", title).strip()
    suffix = f" : r/{sub}"
    if t.lower().endswith(suffix.lower()):
        return t[: -len(suffix)].strip()
    m = re.search(r"\s*:\s*r/\w+$", t, re.IGNORECASE)
    if m:
        return t[: m.start()].strip()
    return t


def viewed_since(
    since_us: int,
    profile: pathlib.Path | str = PROFILE,
    tmp: pathlib.Path | str = WORK / "tmp",
    max_age_days: int | None = None,
) -> tuple[list[Viewed], dict[str, int], int]:
    if isinstance(since_us, bool) or not isinstance(since_us, int) or since_us < 0:
        raise ValueError(f"'since_us' must be a non-negative int, got {since_us!r}")

    query_cutoff = since_us
    if max_age_days is not None and max_age_days > 0:
        now_us = int(time.time() * 1_000_000)
        min_allowed_us = now_us - int(max_age_days * 86400 * 1_000_000)
        if query_cutoff < min_allowed_us:
            query_cutoff = min_allowed_us

    profile_path = pathlib.Path(profile)
    if profile_path.is_file() or profile_path.suffix.lower() in (".sqlite", ".db"):
        src_db = profile_path
        profile_dir = profile_path.parent
    else:
        src_db = profile_path / "places.sqlite"
        profile_dir = profile_path

    if not src_db.exists():
        raise FileNotFoundError(f"Database file not found: {src_db}")

    src_wal = profile_dir / f"{src_db.name}-wal"

    tmp_dir = pathlib.Path(tmp)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    dest_db = tmp_dir / src_db.name
    dest_wal = tmp_dir / f"{src_db.name}-wal"
    dest_shm = tmp_dir / f"{src_db.name}-shm"
    dest_journal = tmp_dir / f"{src_db.name}-journal"

    # Clean up any leftover artifacts from a previous crashed or interrupted run
    for p in (dest_db, dest_wal, dest_shm, dest_journal):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    conn: sqlite3.Connection | None = None
    try:
        # Copy places.sqlite with exponential backoff retry in case of transient lock
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                shutil.copy2(src_db, dest_db)
                break
            except PermissionError:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.05 * (2**attempt))

        if src_wal.exists():
            for attempt in range(max_attempts):
                try:
                    shutil.copy2(src_wal, dest_wal)
                    break
                except (PermissionError, FileNotFoundError):
                    if attempt == max_attempts - 1:
                        if not src_wal.exists():
                            break
                        raise
                    time.sleep(0.05 * (2**attempt))

        conn = sqlite3.connect(dest_db)
        cursor = conn.cursor()
        query = (
            "SELECT p.url, p.title, v.visit_date "
            "FROM moz_places p "
            "JOIN moz_historyvisits v ON p.id = v.place_id "
            "WHERE v.visit_date > ? "
            "  AND p.url LIKE '%reddit.com/r/%/comments%' "
            "ORDER BY v.visit_date ASC"
        )
        cursor.execute(query, (query_cutoff,))

        posts_by_id: dict[str, Viewed] = {}
        counts: dict[str, int] = {}
        max_us = max(since_us, query_cutoff)

        for url, title, visit_date in cursor.fetchall():
            parsed = parse_reddit_comment_url(url)
            if parsed is None:
                continue

            sub, raw_id = parsed
            post_id = f"t3_{raw_id}"
            cleaned_title = clean_title(title, sub)

            counts[sub] = counts.get(sub, 0) + 1

            if visit_date > max_us:
                max_us = visit_date

            if not cleaned_title and post_id in posts_by_id and posts_by_id[post_id].title:
                cleaned_title = posts_by_id[post_id].title

            posts_by_id[post_id] = Viewed(
                id=post_id,
                sub=sub,
                title=cleaned_title,
                url=url,
                visited=visit_date,
            )

        viewed_posts = sorted(posts_by_id.values(), key=lambda p: (p.visited, p.id), reverse=True)
        return viewed_posts, counts, max_us

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

        for p in (dest_db, dest_wal, dest_shm, dest_journal):
            if p.exists():
                for _ in range(5):
                    try:
                        p.unlink()
                        break
                    except OSError:
                        time.sleep(0.05)
