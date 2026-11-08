import pathlib
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass

from digest.atom import Post, parse


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: str


@dataclass
class FeedResult:
    name: str
    posts: list[Post]
    newest_id: str | None
    requests: int
    error: str | None


def _parse_headers(raw: str) -> tuple[int, dict[str, str]]:
    status = 0
    headers: dict[str, str] = {}
    blocks = re.split(r"(?:\r?\n){2,}", raw.strip())
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        first_line = lines[0].strip()
        m = re.match(r"^HTTP/\S+\s+(\d+)", first_line)
        if m:
            status = int(m.group(1))
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
    return status, headers


def curl_get(url: str) -> Response:
    with tempfile.TemporaryDirectory() as td:
        body_path = pathlib.Path(td) / "body.tmp"
        cmd = [
            "curl.exe",
            "-s",
            "-L",
            "--max-time",
            "60",
            "--doh-url",
            "https://cloudflare-dns.com/dns-query",
            "-A",
            "reddit-digest/0.1",
            "-D",
            "-",
            "-o",
            str(body_path),
            url,
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=70,
                check=False,
            )
            if res.returncode != 0:
                return Response(status=0, headers={}, body="")
            raw_headers = res.stdout.decode("utf-8", errors="replace")
            status, headers = _parse_headers(raw_headers)
            body = (
                body_path.read_text(encoding="utf-8", errors="replace")
                if body_path.exists()
                else ""
            )
            return Response(status=status, headers=headers, body=body)
        except Exception:
            return Response(status=0, headers={}, body="")


def fetch_feed(
    name: str,
    subs: list[str],
    last_id: str | None,
    deadline: float,
    get=curl_get,
    sleep=time.sleep,
    clock=time.monotonic,
) -> FeedResult:
    if last_id and last_id.strip():
        last_id = last_id.strip()
        if not last_id.startswith("t3_"):
            last_id = f"t3_{last_id}"
    else:
        last_id = None

    clean_subs = [s.strip() for s in subs if s.strip()]
    if not clean_subs:
        return FeedResult(
            name=name,
            posts=[],
            newest_id=last_id,
            requests=0,
            error="no subreddits specified",
        )

    posts: list[Post] = []
    seen_ids: set[str] = set()
    newest_id: str | None = last_id
    requests_count = 0
    error: str | None = None
    page_count = 0
    after_id: str | None = None
    subs_str = "+".join(clean_subs)

    while page_count < 10:
        page_count += 1
        url = f"https://www.reddit.com/r/{subs_str}/new/.rss?limit=100"
        if after_id:
            after_param = (
                after_id if after_id.startswith("t3_") else f"t3_{after_id}"
            )
            url += f"&after={after_param}"

        retries = 0
        response: Response | None = None

        while True:
            if clock() >= deadline:
                error = "deadline"
                break

            requests_count += 1
            response = get(url)

            if response.status == 429:
                if retries < 3:
                    retries += 1
                    reset_str = response.headers.get("x-ratelimit-reset", "60")
                    try:
                        reset_val = float(reset_str)
                    except ValueError:
                        reset_val = 60.0
                    wait_time = max(reset_val, 60.0) + 2.0

                    if clock() + wait_time >= deadline:
                        error = "deadline"
                        break
                    sleep(wait_time)
                    continue
                else:
                    error = "rate limited (429)"
                    break
            else:
                break

        if error is not None:
            break

        if response is None or response.status == 0:
            error = "connection failure"
            break

        if response.status != 200:
            error = f"HTTP {response.status}"
            break

        try:
            page_posts = parse(response.body)
        except Exception as e:
            error = f"parse error: {e}"
            break

        if page_count == 1 and page_posts:
            newest_id = page_posts[0].id

        reached_last_id = False
        for post in page_posts:
            if last_id is not None and post.id == last_id:
                reached_last_id = True
                break
            if post.id not in seen_ids:
                seen_ids.add(post.id)
                posts.append(post)

        if last_id is None:
            # First run / no last_id: 1 page only
            break

        if reached_last_id:
            break

        if len(page_posts) < 100:
            break

        if page_count >= 10:
            break

        new_after = page_posts[-1].id
        if new_after == after_id:
            # Stuck pagination / loop detected
            break
        after_id = new_after

        # Check rate limit before next request
        remaining_str = response.headers.get("x-ratelimit-remaining")
        if remaining_str is not None:
            try:
                remaining = float(remaining_str)
            except ValueError:
                remaining = 100.0

            if remaining < 1.0:
                reset_str = response.headers.get("x-ratelimit-reset", "60")
                try:
                    reset_val = float(reset_str)
                except ValueError:
                    reset_val = 60.0
                wait_time = max(reset_val, 0.0) + 2.0

                if clock() + wait_time >= deadline:
                    error = "deadline"
                    break
                sleep(wait_time)

    return FeedResult(
        name=name,
        posts=posts,
        newest_id=newest_id,
        requests=requests_count,
        error=error,
    )
