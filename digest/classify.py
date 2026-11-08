from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any
import uuid

from digest.config import ROOT, WORK

SECTIONS: dict[str, str] = {
    "repo": "Repo / Tool",
    "showcase": "Project / Showcase",
    "knowledge": "Useful knowledge",
    "money": "Money / content with AI",
    "career": "IT career / abroad",
    "game": "Game",
    "qa_tools": "Q&A about my tools",
    "other": "Other",
    "drop": "(not rendered)",
}

BATCH_SIZE = 150
CALIB_BRIEF_PATH = ROOT / "docs" / "calib-brief.txt"
AGY_SCRIPT = pathlib.Path.home() / ".claude" / "skills" / "agy" / "agy-run-win.sh"

DEFAULT_BRIEF = """Read-only run. Do NOT write files, commit, or push. Use built-in read tools only (no shell).

Task: classify Reddit posts for a personal "idea digest" of a Vietnamese developer (local LLMs, AI coding agents like Claude Code/Antigravity, game dev/3D, embedded/FPGA/PCB, security, IT career).

Input: work/calib/batchN.jsonl — one JSON per line: id, sub, title, body (body may be empty; then judge from title + sub).

Sections (pick exactly one per post):
- repo: a repo, tool, library, model or app release
- game: a game or game-dev showcase
- showcase: "I built X" / project the author made (non-game)
- knowledge: benchmark, comparison, workflow experiment, technique, explanation
- qa_tools: question/answer about tools the user uses (quantization, local models, coding agents, hardware setup) — KEEP these
- career: IT career, job market, working/living abroad
- money: making money or content with AI (UGC ads, faceless YouTube, digital products)
- other: does not fit above but is not noise
- drop: ONLY memes, jokes, info-less rants, hiring/self-promo spam, unrelated entertainment
When unsure between drop and anything else, do NOT drop — use other.

Output: ONLY JSON lines, one per input id, nothing else:
{"id":"t3_...","section":"...","confidence":0.0-1.0,"summary":"1 sentence, same language as the title"}
Every input id must appear exactly once."""


@dataclass
class Item:
    id: str
    sub: str
    title: str
    url: str
    link: str | None
    section: str
    summary: str
    source: str


def write_input(posts: Sequence[Any], path: pathlib.Path | str) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for post in posts:
            if isinstance(post, dict):
                post_id = post.get("id", "")
                sub = post.get("sub", "")
                title = post.get("title", "")
                body = post.get("body", "") or ""
            else:
                post_id = getattr(post, "id", "")
                sub = getattr(post, "sub", "")
                title = getattr(post, "title", "")
                body = getattr(post, "body", "") or ""

            entry = {
                "id": str(post_id),
                "sub": str(sub),
                "title": str(title),
                "body": str(body)[:600],
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def brief(input_rel: str) -> str:
    template = DEFAULT_BRIEF
    if CALIB_BRIEF_PATH.exists():
        try:
            template = CALIB_BRIEF_PATH.read_text(encoding="utf-8")
        except OSError:
            pass

    normalized_input = str(input_rel).replace("\\", "/")
    res = template.replace("work/calib/batchN.jsonl", normalized_input)
    if len(res.encode("utf-8")) > 30000:
        raise ValueError(f"Brief size exceeds 30000 bytes: {len(res.encode('utf-8'))}")
    return res


def _parse_entry_dict(data: Any) -> tuple[str, tuple[str, float, str]] | None:
    if not isinstance(data, dict):
        return None
    raw_id = data.get("id")
    if raw_id is None:
        return None
    post_id = str(raw_id).strip()
    if not post_id:
        return None

    raw_sec = data.get("section")
    sec = str(raw_sec).strip().lower() if raw_sec is not None else "other"
    if sec not in SECTIONS:
        sec = "other"

    raw_conf = data.get("confidence")
    try:
        conf = float(raw_conf) if raw_conf is not None else 0.0
    except (ValueError, TypeError):
        conf = 0.0

    raw_sum = data.get("summary")
    summary = str(raw_sum).strip() if raw_sum is not None else ""

    return post_id, (sec, conf, summary)


def parse_reply(text: str) -> dict[str, tuple[str, float, str]]:
    if not text or not text.strip():
        return {}

    results: dict[str, tuple[str, float, str]] = {}
    cleaned = text.strip()

    if cleaned.startswith("[") and cleaned.endswith("]"):
        try:
            arr = json.loads(cleaned)
            if isinstance(arr, list):
                for item in arr:
                    entry = _parse_entry_dict(item)
                    if entry is not None:
                        results[entry[0]] = entry[1]
                return results
        except Exception:
            pass

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        parsed_data = None
        try:
            parsed_data = json.loads(line)
        except Exception:
            start = line.find("{")
            end = line.rfind("}")
            if start != -1 and end > start:
                candidate = line[start : end + 1]
                try:
                    parsed_data = json.loads(candidate)
                except Exception:
                    pass

        if parsed_data is not None:
            entry = _parse_entry_dict(parsed_data)
            if entry is not None:
                results[entry[0]] = entry[1]

    return results


def _find_bash() -> str:
    which = shutil.which("bash")
    if which:
        return which
    candidates = [
        pathlib.Path("C:/Program Files/Git/bin/bash.exe"),
        pathlib.Path("C:/Program Files/Git/usr/bin/bash.exe"),
        pathlib.Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Git" / "bin" / "bash.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "bash"


def agy_run(brief: str, label: str) -> tuple[int, str]:
    clean_label = re.sub(r"[^a-z0-9-]", "", label.lower())
    if not clean_label:
        clean_label = f"digest-{int(time.time())}"

    bash_bin = _find_bash()
    if not AGY_SCRIPT.exists():
        return 1, f"Script not found: {AGY_SCRIPT}"

    cmd = [
        bash_bin,
        str(AGY_SCRIPT.as_posix()),
        "low",
        str(ROOT.as_posix()),
        clean_label,
    ]

    rc = 1
    reply = ""
    try:
        proc = subprocess.run(
            cmd,
            input=brief.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
        rc = proc.returncode
        stdout_text = proc.stdout.decode("utf-8", errors="replace")

        temp_dir = pathlib.Path(tempfile.gettempdir())
        reply_file = temp_dir / f"agy-{clean_label}" / "reply.txt"
        if reply_file.exists():
            try:
                reply = reply_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                reply = ""

        if not reply and stdout_text:
            m = re.search(r"^out=.*?\r?\n\r?\n(.*)", stdout_text, re.DOTALL | re.MULTILINE)
            if m:
                reply = m.group(1).strip()
            else:
                reply = stdout_text.strip()
    except Exception as e:
        rc = 1
        reply = str(e)
    finally:
        try:
            subprocess.run(
                [bash_bin, str(AGY_SCRIPT.as_posix()), "--cleanup", clean_label],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except Exception:
            pass

    return rc, reply


def classify(
    posts: Sequence[Any],
    source: str,
    run_agy: Callable[[str, str], tuple[int, str]] = agy_run,
) -> list[Item]:
    if not posts:
        return []

    items: list[Item] = []
    tmp_dir = WORK / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for i in range(0, len(posts), BATCH_SIZE):
        batch = posts[i : i + BATCH_SIZE]
        batch_idx = i // BATCH_SIZE
        label = f"classify-{source}-{batch_idx}-{uuid.uuid4().hex[:8]}"

        batch_file = tmp_dir / f"{label}.jsonl"
        try:
            write_input(batch, batch_file)
            try:
                rel_path = batch_file.relative_to(ROOT).as_posix()
            except ValueError:
                rel_path = os.path.relpath(batch_file, ROOT).replace("\\", "/")

            brief_text = brief(rel_path)
            try:
                rc, reply = run_agy(brief_text, label)
            except Exception:
                rc, reply = 1, ""
        finally:
            try:
                batch_file.unlink(missing_ok=True)
            except OSError:
                pass

        if rc != 0:
            parsed: dict[str, tuple[str, float, str]] = {}
        else:
            parsed = parse_reply(reply)

        for post in batch:
            if isinstance(post, dict):
                p_id = str(post.get("id", ""))
                p_sub = str(post.get("sub", ""))
                p_title = str(post.get("title", ""))
                raw_body = post.get("body", "") or ""
                p_url = str(post.get("url", ""))
                p_link = post.get("link")
            else:
                p_id = str(getattr(post, "id", ""))
                p_sub = str(getattr(post, "sub", ""))
                p_title = str(getattr(post, "title", ""))
                raw_body = getattr(post, "body", "") or ""
                p_url = str(getattr(post, "url", ""))
                p_link = getattr(post, "link", None)

            clean_body = str(raw_body).strip()
            clean_title = p_title.strip()
            fallback_summary = clean_body[:200] if clean_body else clean_title

            if p_id in parsed:
                sec, conf, summ = parsed[p_id]
                if source == "followed" and sec == "drop" and conf < 0.9:
                    sec = "other"
                if not summ or not summ.strip():
                    summ = fallback_summary
                else:
                    summ = summ.strip()
            else:
                sec = "other"
                summ = fallback_summary

            items.append(
                Item(
                    id=p_id,
                    sub=p_sub,
                    title=p_title,
                    url=p_url,
                    link=p_link,
                    section=sec,
                    summary=summ,
                    source=source,
                )
            )

    return items
