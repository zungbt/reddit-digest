from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
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
from digest.examples import feedback_examples

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

SECTION_ALIASES: dict[str, str] = {
    "repo": "repo",
    "showcase": "showcase",
    "knowledge": "knowledge",
    "money": "money",
    "career": "career",
    "game": "game",
    "qa_tools": "qa_tools",
    "other": "other",
    "drop": "drop",
    # Headings and common variants from model output
    "repo / tool": "repo",
    "repo/tool": "repo",
    "tool": "repo",
    "tools": "repo",
    "project / showcase": "showcase",
    "project/showcase": "showcase",
    "project": "showcase",
    "useful knowledge": "knowledge",
    "money / content with ai": "money",
    "money / content": "money",
    "money/content": "money",
    "it career / abroad": "career",
    "it career": "career",
    "career / abroad": "career",
    "career/abroad": "career",
    "games": "game",
    "qa_tool": "qa_tools",
    "qa-tools": "qa_tools",
    "qa-tool": "qa_tools",
    "qa tools": "qa_tools",
    "qatools": "qa_tools",
    "q&a about my tools": "qa_tools",
    "q&a about tools": "qa_tools",
    "q&a tools": "qa_tools",
    "q&a": "qa_tools",
}

BATCH_SIZE = 50
AGY_LEVEL = "high"
MAX_WORKERS = 5
CALIB_BRIEF_PATH = ROOT / "docs" / "calib-brief.txt"
AGY_SCRIPT = pathlib.Path.home() / ".claude" / "skills" / "agy" / "agy-run-win.sh"

DEFAULT_BRIEF = """Read-only run. Do NOT write files, commit, or push. Use built-in read tools only (no shell).

Task: classify Reddit posts for a personal "idea digest" of a Vietnamese developer (local LLMs, AI coding agents like Claude Code/Antigravity, game dev/3D, embedded/FPGA/PCB, security, IT career).

Input: work/calib/batchN.jsonl — one JSON per line: id, sub, title, body (body may be empty; then judge from title + sub).

Sections (pick exactly one per post):
- repo: a repo, tool, library or app release (NOT a bare model/checkpoint release)
- game: a game or game-dev showcase
- showcase: "I built X" / project the author made (non-game)
- knowledge: benchmark, comparison, workflow experiment, technique, explanation
- qa_tools: question/answer about coding agents, dev tools or workflows the user uses. Questions about LLM hardware/quantization/"can my GPU run model X" go to drop (see below)
- career: IT career, job market, working/living abroad
- money: making money or content with AI (UGC ads, faceless YouTube, digital products)
- other: does not fit above but is not noise
- drop: memes, jokes, info-less rants, hiring/self-promo spam, unrelated entertainment, AND low-value LLM posts (below)
LLM posts (about LLMs/models themselves, any sub) are kept ONLY if they are an end-user tool/library/app or a practical guide/how-to the reader can apply (coding agents, skills, workflows, apps built on LLMs). Always drop: bare model releases (weights, checkpoints, GGUF/quants, finetunes, Hugging Face model pages, speech/vision/other model announcements) and inference/runtime infrastructure (inference engines, llama.cpp/vLLM/SGLang and engine comparisons, running model X on GPU Y, quantization), even when the post links a repo. Drop LLM posts that are only: benchmarks or speed numbers (tok/s), hardware/GPU comparisons or setup questions, quantization/KV-cache measurements without a usable technique, model news/rumors/drama, or chatter about model behavior. Read title+body and understand the context before dropping; never drop on keywords alone.
Effort filter (all subs): keep only high-effort posts the reader can learn from or reuse: detailed write-ups, repos/tools with docs, reusable workflows, measurements with the method shown. Drop low-effort posts: "made this for fun" demos/games/clips that only show off a model, screenshots or clips with no repo or method, one-line questions, venting, chatter. Exception: if the post links a repo or explains a reusable workflow, keep it even when it is a showcase.
Idea quality & engineering taste filter: reward breakthrough technical ideas or solid engineering solutions that solve a real problem (big or small) with a pragmatic, actionable approach (e.g. guardrails preventing agent breakages, binary patching closed firmware via symbol weakening, hardware/micro-VM sandboxing for agents, reverse engineering closed protocols/hardware microcode into working native clients or tools, novel cache/compression data structures). High scores belong to posts with solid, practical engineering ideas. Demote / cap below 9 (scores 6–8): pure visual tech demos or graphics/engine benchmarks (e.g. rendering 40B triangles, shaders/water toys without engineering tooling), hobby game recompilation/porting projects (e.g. porting old commercial games), experimental WIP toy OS/driver ports, and academic or pure CTF exploit writeups lacking reusable builder utility. Always penalize/drop superficial "ideas": hand-wavy architecture without implementation, 1-prompt vibe-coding claims, generic product teasers, and buzzword-heavy concepts with no technical depth.
When unsure between drop and anything else, do NOT drop — use other.

Score rubric: score 9–10 = standout substance or breakthrough/solid idea solving a practical engineering problem (big or small) with actionable tools/repo/architecture (guardrails, sandboxing, driver/firmware fixes, closed-system reverse engineering); 7–8 = solid and relevant (including complex graphics demos, game ports, CTF writeups, or niche OS ports); 4–6 = relevant but thin or unproven concept; 0–3 = low value, superficial hype, or buzzwords without technical depth; relevance means coding agents, embedded/FPGA/PCB, low-level systems/kernel/reverse-engineering, graphics/shaders, security, IT career.

Output: ONLY JSON lines, one per input id, nothing else:
{"id":"t3_...","section":"...","confidence":0.0-1.0,"score":0-10,"summary":"..."}
Every input id must appear exactly once.
"""


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
    score: int | None = None


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val)


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def write_input(posts: Sequence[Any], path: pathlib.Path | str, body_limit: int | None = None) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for post in posts:
            if isinstance(post, dict):
                post_id = _clean_str(post.get("id"))
                sub = _clean_str(post.get("sub"))
                title = _clean_str(post.get("title"))
                body = _clean_str(post.get("body"))
            else:
                post_id = _clean_str(getattr(post, "id", None))
                sub = _clean_str(getattr(post, "sub", None))
                title = _clean_str(getattr(post, "title", None))
                body = _clean_str(getattr(post, "body", None))

            if body_limit is not None and body:
                limit = max(0, body_limit)
                body = body[:limit]

            entry = {
                "id": post_id,
                "sub": sub,
                "title": title,
                "body": body,
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
    if "work/calib/batchN.jsonl" in template:
        res = template.replace("work/calib/batchN.jsonl", normalized_input)
    else:
        res = re.sub(r"(Input:\s*)\S+", rf"\g<1>{normalized_input}", template)

    examples = feedback_examples(WORK / "feedback.jsonl")
    if examples:
        res = res.rstrip("\n") + "\n\n" + examples

    if len(res.encode("utf-8")) > 30000:
        raise ValueError(f"Brief size exceeds 30000 bytes: {len(res.encode('utf-8'))}")
    return res


def _parse_score(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            val = round(float(raw))
            return max(0, min(10, val))
        except (ValueError, OverflowError):
            return None
    if isinstance(raw, str):
        s = raw.strip()
        m = re.match(r"^([+-]?\d+(?:\.\d+)?)(?:\s*/\s*10)?$", s)
        if m:
            try:
                val = round(float(m.group(1)))
                return max(0, min(10, val))
            except (ValueError, OverflowError):
                return None
    return None


def _parse_entry_dict(data: Any) -> tuple[str, tuple[str, float, str, int | None]] | None:
    if not isinstance(data, dict):
        return None
    raw_id = data.get("id")
    if raw_id is None:
        return None
    post_id = str(raw_id).strip()
    if not post_id:
        return None

    raw_sec = data.get("section")
    sec_candidate = str(raw_sec).strip().lower() if raw_sec is not None else "other"
    sec = SECTION_ALIASES.get(sec_candidate, "other")
    if sec not in SECTIONS:
        sec = "other"

    raw_conf = data.get("confidence")
    if isinstance(raw_conf, str):
        raw_conf = raw_conf.strip().rstrip("%")
    try:
        conf = float(raw_conf) if raw_conf is not None else 0.0
    except (ValueError, TypeError):
        conf = 0.0

    if conf > 1.0 and conf <= 100.0:
        conf = conf / 100.0
    conf = max(0.0, min(1.0, conf))

    raw_sum = data.get("summary")
    summary = _collapse_spaces(str(raw_sum)) if raw_sum is not None else ""
    if summary in ("None", "null"):
        summary = ""

    score = _parse_score(data.get("score"))

    return post_id, (sec, conf, summary, score)


def parse_reply(text: str) -> dict[str, tuple[str, float, str, int | None]]:
    if not text or not text.strip():
        return {}

    results: dict[str, tuple[str, float, str, int | None]] = {}
    cleaned = text.strip()

    # 1. First attempt: Use JSONDecoder to scan for all JSON objects / arrays across the entire text
    decoder = json.JSONDecoder()
    idx = 0
    length = len(cleaned)
    found_any = False

    while idx < length:
        ch = cleaned[idx]
        if ch in ("{", "["):
            try:
                obj, end_idx = decoder.raw_decode(cleaned, idx)
                idx = end_idx
                if isinstance(obj, list):
                    for item in obj:
                        entry = _parse_entry_dict(item)
                        if entry is not None:
                            results[entry[0]] = entry[1]
                            found_any = True
                elif isinstance(obj, dict):
                    entry = _parse_entry_dict(obj)
                    if entry is not None:
                        results[entry[0]] = entry[1]
                        found_any = True
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        idx += 1

    if found_any:
        return results

    # 2. Fallback: line-by-line parsing (for lines with embedded JSON)
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
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(pathlib.Path(local_app_data) / "Programs" / "Git" / "bin" / "bash.exe")
    for c in candidates:
        if c.exists():
            return str(c)
    return "bash"


def agy_run(brief: str, label: str, level: str = AGY_LEVEL) -> tuple[int, str]:
    clean_label = re.sub(r"[^a-z0-9-]", "", label.lower())
    if not clean_label:
        clean_label = f"digest-{int(time.time())}"

    bash_bin = _find_bash()
    if not AGY_SCRIPT.exists():
        return 1, f"Script not found: {AGY_SCRIPT}"

    cmd = [
        bash_bin,
        str(AGY_SCRIPT.as_posix()),
        level,
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
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_WORKERS,
    body_limit: int | None = None,
) -> list[Item]:
    if not posts:
        return []

    norm_source = str(source).strip().lower()
    tmp_dir = WORK / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    batches = [
        (i // batch_size, posts[i : i + batch_size])
        for i in range(0, len(posts), batch_size)
    ]

    def _process_batch(batch_tuple: tuple[int, Sequence[Any]]) -> list[Item]:
        batch_idx, batch = batch_tuple
        label = f"classify-{norm_source}-{batch_idx}-{uuid.uuid4().hex[:8]}"
        batch_file = tmp_dir / f"{label}.jsonl"
        try:
            write_input(batch, batch_file, body_limit=body_limit)
            try:
                rel_path = batch_file.relative_to(ROOT).as_posix()
            except ValueError:
                try:
                    rel_path = os.path.relpath(batch_file, ROOT).replace("\\", "/")
                except ValueError:
                    rel_path = batch_file.as_posix()

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
            parsed: dict[str, tuple[str, float, str, int | None]] = {}
        else:
            parsed = parse_reply(reply)

        batch_items: list[Item] = []
        for post in batch:
            if isinstance(post, dict):
                p_id = _clean_str(post.get("id"))
                p_sub = _clean_str(post.get("sub"))
                p_title = _clean_str(post.get("title"))
                raw_body = _clean_str(post.get("body"))
                p_url = _clean_str(post.get("url"))
                p_link = post.get("link")
            else:
                p_id = _clean_str(getattr(post, "id", None))
                p_sub = _clean_str(getattr(post, "sub", None))
                p_title = _clean_str(getattr(post, "title", None))
                raw_body = _clean_str(getattr(post, "body", None))
                p_url = _clean_str(getattr(post, "url", None))
                p_link = getattr(post, "link", None)

            clean_body = raw_body.replace("\r", " ").replace("\n", " ")
            clean_title = _collapse_spaces(p_title)
            fallback_summary = clean_body[:200] if clean_body.strip() else clean_title

            if p_link is not None:
                p_link_str = str(p_link).strip()
                p_link = p_link_str if p_link_str else None

            if p_id in parsed:
                sec, conf, summ, sc = parsed[p_id]
                if norm_source == "followed" and sec == "drop" and conf < 0.9:
                    sec = "other"
                    sc = None
                if not summ or not summ.strip():
                    summ = fallback_summary
                else:
                    summ = _collapse_spaces(summ)
            else:
                sec = "other"
                sc = None
                summ = fallback_summary

            batch_items.append(
                Item(
                    id=p_id,
                    sub=p_sub,
                    title=clean_title,
                    url=p_url,
                    link=p_link,
                    section=sec,
                    summary=summ,
                    source=norm_source,
                    score=sc,
                )
            )
        return batch_items

    items: list[Item] = []
    if len(batches) <= 1 or max_workers <= 1:
        for b in batches:
            items.extend(_process_batch(b))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for batch_result in executor.map(_process_batch, batches):
                items.extend(batch_result)

    return items
