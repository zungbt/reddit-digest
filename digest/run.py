from collections.abc import Callable
import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import os
import pathlib
import re
import time
from typing import Any

from digest.atom import Post
from digest.classify import Item, agy_run, classify
from digest.config import DIGESTS, FEEDS, ROOT, WORK
from digest.feedback import apply, read_marks
from digest.fetch import FeedResult, Response, curl_get, fetch_feed
from digest.history import PROFILE, Viewed, viewed_since
from digest.render import render
from digest.state import State, load, prune, save


def _log(path: pathlib.Path | None, message: str) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(message.rstrip("\n") + "\n")
    except OSError:
        pass


def _parse_iso(s: str) -> datetime | None:
    if not s or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@dataclass
class Deps:
    get: Callable[[str], Response] = curl_get
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    run_agy: Callable[[str, str], tuple[int, str]] = agy_run
    viewed: Callable[..., tuple[list[Viewed], dict[str, int], int]] = viewed_since
    feeds: list[tuple[str, list[str]]] = field(default_factory=lambda: list(FEEDS))
    work_dir: pathlib.Path = WORK
    digests_dir: pathlib.Path = DIGESTS
    state_path: pathlib.Path | None = None
    saved_path: pathlib.Path | None = None
    feedback_path: pathlib.Path | None = None
    log_path: pathlib.Path | None = None
    dropped_dir: pathlib.Path | None = None
    waterfox_profile: pathlib.Path = PROFILE
    tmp_dir: pathlib.Path | None = None
    deadline_seconds: float = 45 * 60.0

    def __post_init__(self) -> None:
        self.work_dir = pathlib.Path(self.work_dir)
        self.digests_dir = pathlib.Path(self.digests_dir)
        self.waterfox_profile = pathlib.Path(self.waterfox_profile)
        if self.state_path is None:
            self.state_path = self.work_dir / "state.json"
        else:
            self.state_path = pathlib.Path(self.state_path)
        if self.saved_path is None:
            self.saved_path = self.work_dir / "saved.md"
        else:
            self.saved_path = pathlib.Path(self.saved_path)
        if self.feedback_path is None:
            self.feedback_path = self.work_dir / "feedback.jsonl"
        else:
            self.feedback_path = pathlib.Path(self.feedback_path)
        if self.log_path is None:
            self.log_path = self.work_dir / "log.txt"
        else:
            self.log_path = pathlib.Path(self.log_path)
        if self.dropped_dir is None:
            self.dropped_dir = self.work_dir / "dropped"
        else:
            self.dropped_dir = pathlib.Path(self.dropped_dir)
        if self.tmp_dir is None:
            self.tmp_dir = self.work_dir / "tmp"
        else:
            self.tmp_dir = pathlib.Path(self.tmp_dir)


def run(today: date | datetime | str | None = None, deps: Deps | None = None) -> pathlib.Path:
    if deps is None:
        deps = Deps()

    if today is None:
        today_date = date.today()
    elif isinstance(today, datetime):
        today_date = today.date()
    elif isinstance(today, str):
        today_date = date.fromisoformat(today)
    else:
        today_date = today

    date_str = today_date.isoformat()

    # 1. Start deadline clock (45 min)
    start_time = deps.clock()
    deadline = start_time + deps.deadline_seconds

    # 2. Load state
    state = load(deps.state_path)

    # 3. If state.last_digest not in state.applied:
    #    apply its marks (+ work/dropped/<its date>.jsonl), add to applied
    if state.last_digest and state.last_digest not in state.applied:
        last_path = pathlib.Path(state.last_digest)
        if not last_path.is_absolute() and not last_path.exists():
            if (deps.digests_dir / last_path.name).exists():
                last_path = deps.digests_dir / last_path.name
            elif (ROOT / last_path).exists():
                last_path = ROOT / last_path

        m_day = re.search(r"(\d{4}-\d{2}-\d{2})", last_path.name)
        last_date_str = m_day.group(1) if m_day else date_str

        marks = read_marks(last_path) if last_path.exists() else []

        dropped_file = deps.dropped_dir / f"{last_date_str}.jsonl"
        dropped_items: list[Item] = []
        if dropped_file.exists():
            try:
                with open(dropped_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            d = json.loads(line)
                            dropped_items.append(Item(**d))
            except Exception as e:
                _log(deps.log_path, f"Error reading dropped file {dropped_file}: {e}")

        apply(
            marks=marks,
            digest_day=last_date_str,
            saved=deps.saved_path,
            log=deps.feedback_path,
            dropped=dropped_items,
        )
        state.applied.append(state.last_digest)

    # 4. Fetch all feeds with state.last_ids[name] (log requests/posts per feed to work/log.txt)
    warnings: list[str] = []
    feed_results: list[FeedResult] = []
    all_fetched_posts: list[Post] = []

    for name, subs in deps.feeds:
        last_id = state.last_ids.get(name)
        res = fetch_feed(
            name=name,
            subs=subs,
            last_id=last_id,
            deadline=deadline,
            get=deps.get,
            sleep=deps.sleep,
            clock=deps.clock,
        )
        feed_results.append(res)
        all_fetched_posts.extend(res.posts)

        log_msg = f"{date_str} feed={name} requests={res.requests} posts={len(res.posts)}"
        if res.error:
            log_msg += f" error={res.error}"
            warnings.append(f"Feed '{name}': {res.error}")
        _log(deps.log_path, log_msg)

    # 5. Viewed posts since state.history_since
    try:
        viewed_posts, sub_counts, max_us = deps.viewed(
            state.history_since,
            profile=deps.waterfox_profile,
            tmp=deps.tmp_dir,
        )
    except Exception as e:
        viewed_posts, sub_counts, max_us = [], {}, state.history_since
        warn_msg = f"Waterfox history unavailable: {e}"
        warnings.append(warn_msg)
        _log(deps.log_path, f"{date_str} {warn_msg}")

    # 6. Drop ids in state.seen, then viewed ids already in followed
    filtered_followed: list[Post] = []
    seen_this_run: set[str] = set()

    for post in all_fetched_posts:
        if not post.id:
            continue
        if post.id in state.seen:
            continue
        if post.id in seen_this_run:
            continue
        seen_this_run.add(post.id)
        filtered_followed.append(post)

    filtered_viewed: list[Viewed] = []
    for v in viewed_posts:
        if not v.id:
            continue
        if v.id in state.seen:
            continue
        if v.id in seen_this_run:
            continue
        seen_this_run.add(v.id)
        filtered_viewed.append(v)

    # 7. Classify
    agy_errors: list[int] = []

    def tracking_run_agy(brief_text: str, label: str) -> tuple[int, str]:
        try:
            rc, reply = deps.run_agy(brief_text, label)
            if rc != 0:
                agy_errors.append(rc)
                _log(deps.log_path, f"{date_str} agy error label={label} rc={rc}")
            return rc, reply
        except Exception as ex:
            agy_errors.append(1)
            _log(deps.log_path, f"{date_str} agy exception label={label}: {ex}")
            return 1, ""

    followed_items = classify(filtered_followed, source="followed", run_agy=tracking_run_agy)
    viewed_items = classify(filtered_viewed, source="viewed", run_agy=tracking_run_agy)

    all_items = followed_items + viewed_items

    # 8. Warnings:
    # agy errors
    if agy_errors:
        unique_rcs = sorted(set(agy_errors))
        rc_str = ", ".join(str(rc) for rc in unique_rcs)
        warnings.append(f"agy error (rc={rc_str}): unclassified posts placed in Other")

    # check any sub with > 500 posts whose published is within the last 24 h
    sub_posts_24h: dict[str, int] = {}
    ref_dt = datetime.combine(today_date, datetime.max.time(), tzinfo=timezone.utc)
    cutoff_dt = ref_dt - timedelta(hours=24)

    for post in all_fetched_posts:
        if not post.published:
            continue
        p_dt = _parse_iso(post.published)
        if p_dt is not None and cutoff_dt <= p_dt <= ref_dt:
            s_clean = post.sub.strip().lstrip("/").removeprefix("r/").strip()
            sub_posts_24h[s_clean] = sub_posts_24h.get(s_clean, 0) + 1

    for sub_name, count in sorted(sub_posts_24h.items()):
        if count > 500:
            warnings.append(f"r/{sub_name} exceeded 500 posts in the last 24h ({count} posts)")

    # 9. Sub suggestions (viewed sub counts for subs not in FEEDS, top 10)
    followed_subs: set[str] = set()
    for _, subs in deps.feeds:
        for s in subs:
            followed_subs.add(s.strip().lstrip("/").removeprefix("r/").strip().lower())

    suggestions: list[tuple[str, int]] = []
    for s_name, count in sub_counts.items():
        clean_s = s_name.strip().lstrip("/").removeprefix("r/").strip()
        if clean_s and clean_s.lower() not in followed_subs:
            suggestions.append((clean_s, count))

    suggestions.sort(key=lambda x: (-x[1], x[0].lower()))
    suggestions = suggestions[:10]

    # 10. Render
    rendered_md = render(
        items=all_items,
        warnings=warnings,
        suggestions=suggestions,
        day=today_date,
    )

    # 11. Write digests/<date>.md and work/dropped/<date>.jsonl
    digest_path = deps.digests_dir / f"{date_str}.md"
    deps.digests_dir.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(rendered_md, encoding="utf-8")

    dropped_items = [it for it in all_items if it.section == "drop"]
    dropped_path = deps.dropped_dir / f"{date_str}.jsonl"
    deps.dropped_dir.mkdir(parents=True, exist_ok=True)
    with open(dropped_path, "w", encoding="utf-8") as f:
        for it in dropped_items:
            f.write(json.dumps(dataclasses.asdict(it), ensure_ascii=False) + "\n")

    # 12. Update seen, last_ids (from FeedResult.newest_id), history_since (max visit), last_digest; prune; save state last
    for p in all_fetched_posts:
        if p.id and p.id not in state.seen:
            state.seen[p.id] = date_str

    for v in viewed_posts:
        if v.id and v.id not in state.seen:
            state.seen[v.id] = date_str

    for res in feed_results:
        if res.newest_id:
            state.last_ids[res.name] = res.newest_id

    if max_us > state.history_since:
        state.history_since = max_us

    state.last_digest = str(digest_path)

    prune(state, today=today_date, days=30)
    save(state, deps.state_path)

    return digest_path
