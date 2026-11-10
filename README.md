# Reddit Digest

A nightly personal digest tool that pulls new posts from followed subreddits (via public unauthenticated Atom feeds) plus Reddit posts you viewed in Waterfox, classifies them into categorized sections using Gemini via `agy`, writes daily markdown digests (`digests/YYYY-MM-DD.md`), and learns from your keep/reject marks.

## Features

- **Followed Subreddits (RSS)**: Pulls newest posts across 13 feeds (4 solo, 9 multi-sub combinations) using Cloudflare DNS-over-HTTPS (DoH) via `curl.exe`.
- **Waterfox History Integration**: Safely reads `/r/*/comments/*` visits from a copied temporary SQLite database to include posts you actually visited.
- **AI Classification**: Leverages Gemini (`agy low`) to organize posts into ranked categories (`Repo / Tool`, `Project / Showcase`, `Useful knowledge`, `Money / content with AI`, `IT career / abroad`, `Game`, `Q&A about my tools`, `Other`), filtering noise and auto-dropping spam.
- **Scoring & Two-Pass Triage**: Posts are scored 0–10 based on substance and relevance. A fast screening pass (`agy low` with truncated bodies) evaluates all followed posts, followed by a high pass (`agy high`) on up to `SCREEN_TOP_K` (300) top candidates. Posts below `MIN_SCORE` (7) are hidden into `work/dropped/` and each subreddit is capped at `MAX_PER_SUB` (15) posts. Standout posts (`score >= 9`) lead the digest under `## Top ideas`, and past keep/reject marks from `work/feedback.jsonl` are injected as few-shot examples into the prompt.
- **Feedback & Learning**:
  - `[x]` / `[X]` **Keep**: Automatically collected and deduplicated into `work/saved.md`.
  - `[-]` **Reject**: Logged to `work/feedback.jsonl`.
  - `[ ]` **Neutral**: Left untouched.
- **Review & Drop Rule Proposals**: `python -m digest review` summarizes engagement and proposes drop rules for high-reject, zero-keep groups.
- **Offline & Resilient**: Side-effect injection for complete offline unit test coverage; handles rate limits (`429`), network interruptions, and transient file locks.

## Requirements

- Python 3.13+ (standard library only; no external runtime dependencies).
- Windows `curl.exe` with DoH support.
- Waterfox (reads `places.sqlite` from `%APPDATA%\Waterfox\Profiles`).
- Git Bash + Antigravity CLI (`agy`) for AI classification.
- `pytest` (for running tests).

## Usage

### 1. Daily Run

To generate today's digest:
```powershell
python -m digest run
```

To run for a specific target date:
```powershell
python -m digest run --date 2026-11-09
```

Output is written to `digests/YYYY-MM-DD.md`. Dropped items for the run are archived in `work/dropped/YYYY-MM-DD.jsonl`.

### 2. Marking Digests

Open `digests/YYYY-MM-DD.md` in any markdown editor or viewer and mark checkboxes:
- `- [x]` to save a post.
- `- [-]` to mark a post as rejected.
- `- [ ]` to leave a post as neutral.

On the next run, marked decisions are processed automatically: keeps are appended to `work/saved.md` and feedback records are written to `work/feedback.jsonl`.

### 3. Reviewing Feedback

Summarize your feedback history and inspect proposed drop rules:
```powershell
python -m digest review
```

This displays:
- Per-subreddit and per-section counts for keep, reject, neutral, and auto-drops.
- Proposed drop rules for subreddits or sections with $\ge 10$ marks and 0 keeps.
- Auto-dropped post titles from the last 14 days for wrong-drop checks.

### 4. Windows Nightly Task Scheduler

To schedule the digest to run every night at 21:00:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1
```

To run the scheduled task immediately or check its status:
```powershell
Start-ScheduledTask -TaskName "reddit-digest"
Get-ScheduledTaskInfo -TaskName "reddit-digest"
```

Logs are appended to `work/log.txt`.

## Running Tests

Run the test suite:
```powershell
python -m pytest -v
```
