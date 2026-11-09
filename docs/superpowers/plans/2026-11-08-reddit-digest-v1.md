# Reddit Digest v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A nightly Windows job that pulls new posts from followed subreddits (RSS) plus Reddit posts I viewed in Waterfox, has Gemini (agy) sort them into sections, writes `digests/YYYY-MM-DD.md`, and learns from my `[x]`/`[-]` marks.

**Architecture:** Plain Python package `digest/`, stdlib only. Network goes through `curl.exe --doh-url` (the only DoH path verified on this machine). Every side effect (curl, agy, clock, sleep) is injected so all logic is unit-tested offline against real captured RSS. One CLI: `python -m digest run|review`.

**Tech Stack:** Python 3.13 stdlib (`sqlite3`, `xml.etree`, `html`, `json`, `subprocess`), pytest 9, Windows `curl.exe`, Git Bash for `agy-run-win.sh`, Task Scheduler.

**Spec:** `docs/spec.md`

## Global Constraints

- Repo: `C:\Users\d\Documents\Github\reddit-digest`. `work/` is gitignored and holds all private data (state, history extracts, agy work files).
- No third-party Python deps.
- Every Reddit request: `curl.exe -s --doh-url https://cloudflare-dns.com/dns-query -A "reddit-digest/0.1"`. No browser User-Agent.
- Feed URL: `https://www.reddit.com/r/<A+B+…>/new/.rss?limit=100[&after=t3_<id>]`.
- Rate limit: when `x-ratelimit-remaining < 1`, sleep `x-ratelimit-reset + 2` s; on 429 sleep `max(reset, 60) + 2` s and retry (max 3 retries per request).
- Pagination (per feed): follow `after` until reaching the feed's `last_id` from the previous run, the page has < 100 entries, or 10 pages (~1000 posts). A feed with no `last_id` (first run, newly added feed) fetches **one page only**.
- Run deadline: 45 min after start (Task Scheduler kills at 60). Past the deadline: no new requests; remaining feeds are skipped with a warning; classify/render/save still run.
- Never open the live `places.sqlite`; copy it plus `-wal` to `work/tmp/`, read, delete.
- agy: `bash ~/.claude/skills/agy/agy-run-win.sh low <repo> <label>` read-only, then `--cleanup <label>`.
- Sections (exact keys → headings):
  `repo`→"Repo / Tool", `showcase`→"Project / Showcase", `knowledge`→"Useful knowledge", `money`→"Money / content with AI", `career`→"IT career / abroad", `game`→"Game", `qa_tools`→"Q&A about my tools", `other`→"Other", `drop`→(not rendered).
  Digest renders sections **in this order** (ranked by engagement in calibration, see below).
- Marks: `[x]`/`[X]` keep, `[-]` reject, `[ ]` neutral.

## Spec deviations (approved 2026-11-08)

1. **No flair in v1.** Unauthenticated RSS carries no flair and `.json` is 403 (probe). Spec §6 "drop memes by flair" and flair in output/feedback/review are dropped; meme dropping is left to the LLM (`drop`). Feedback and review group by sub + section only.
2. **Viewed posts are title-only.** `moz_places.description` is empty for all 440 Reddit posts checked, and fetching `<url>.rss` per post costs ~1 min each. Calibration showed title + sub is enough to classify.

## Calibration (2026-11-08, agy low, 434 viewed posts, title-only, blind)

- 434/434 answered, 0 bad JSON, ~50 s per 150 posts.
- Engaged (read >= 60 s, revisited, or clicked out) share per section: repo 59%, money 50%, knowledge 44%, showcase 44%, career 34%, game 28%, other 26%, qa_tools 19%, drop 18%. repo + showcase got 48 of 67 outbound clicks.
- Real false drops ~5-6 / 147 engaged, all vague titles in followed tech subs ("Qwen 4", "Qwhen ?"). -> rule: for `source == "followed"`, `drop` only when confidence >= 0.9, else `other`.
- Labels are weak (memes also get long reads; only opened posts are labeled). Daily `[x]`/`[-]` marks are the real metric.

## Review Focus

1. agy returns malformed / partial output → every post still appears (unclassified ones go to `other`), never silently lost. Test in Task 5.
2. First run, or a feed added later → one page for that feed only, no 10-page catch-up. Test in Task 2.
3. Reddit keeps returning 429 → gives up that feed after 3 retries, logs it, digest still written with a warning. Test in Task 2.
4. Waterfox profile missing or file locked → history section skipped with warning, followed-subs digest still written. Test in Task 4.
5. I edit the digest loosely (`[X]`, extra spaces, deleted lines, digest missing) → parser still reads marks by the `<!-- id -->` tag; missing digest = no feedback, no crash. Test in Task 6.

---

### Task 1: Scaffold, feed config, Atom parser

**Files:**
- Create: `digest/__init__.py`, `digest/config.py`, `digest/atom.py`
- Create: `tests/fixtures/multi_sub.rss` (copy of `work/probe/multi_sub.body`, public data)
- Test: `tests/test_atom.py`

**Interfaces:**
- Produces:
  - `config.FEEDS: list[tuple[str, list[str]]]` — `(name, subs)`, the 13 feeds from spec §4.1 in that order: 4 solo feeds named after their sub (`LocalLLaMA`, `LocalLLM`, `ClaudeCode`, `ClaudeAI`) + 9 multi feeds `local-ai`, `ai-agents`, `hardware`, `game-3d`, `repos`, `ai-media`, `career`, `security`, `learning`.
  - `config.WORK`, `config.DIGESTS: pathlib.Path` (`work/`, `digests/` under repo root).
  - `atom.Post` dataclass: `id: str` (`t3_…`), `sub: str`, `title: str`, `url: str` (reddit permalink), `link: str | None`, `body: str` (plain text, max 600 chars), `published: str` (ISO, from `<published>`, fallback `<updated>`).
  - `link` rule: the `[link]` anchor href if it is external; if it points to the permalink, `i.redd.it`, `v.redd.it`, `preview.redd.it` or `reddit.com/gallery/` (36 of 100 fixture posts are media), use the first external `href` inside `<div class="md">` instead; else `None`. "External" = host not ending in `reddit.com` / `redd.it`.
  - `atom.parse(xml: str) -> list[Post]`

- [ ] **Step 1: Write failing tests** — `test_parse_fixture_count` (100 posts), `test_first_post_fields` (`id == "t3_1xqxv0m"`, `sub == "FPGA"`, title starts `"IMC Hardware Engineering role"`, `body` starts `"Hello ! I am in the process"`, no HTML tags, `len(body) <= 600`), `test_self_post_link_is_none`, `test_media_link_is_not_external` (no post's `link` host ends in `redd.it` or contains `/gallery/`), `test_github_links_found` (>= 2 posts with `link` on `github.com`), `test_body_has_no_table_text` (body of a post whose content has a `<table>` preview contains no `submitted by` / `[link]` / `[comments]`), `test_feed_config` (13 feeds; every sub of spec §4.1 present exactly once; `vozforums`, `announcements` absent).
- [ ] **Step 2: Run** `python -m pytest tests/test_atom.py -v` → FAIL (import error).
- [ ] **Step 3: Implement** with `xml.etree.ElementTree` (Atom ns `http://www.w3.org/2005/Atom`); `sub` from `category@term`; body = text of `<div class="md">` only (between `<!-- SC_OFF -->` and `<!-- SC_ON -->`; 44/100 fixture posts wrap it in a preview `<table>`), parsed with `html.parser.HTMLParser`, whitespace collapsed; empty string for link/media posts without text.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: feed config and atom parser`.

### Task 2: Fetcher with DoH, rate limit, pagination

**Files:**
- Create: `digest/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `atom.parse`, `atom.Post`, `config.FEEDS`.
- Produces:
  - `Response` dataclass: `status: int`, `headers: dict[str, str]` (lower-cased keys), `body: str`.
  - `curl_get(url: str) -> Response` — real `curl.exe` call (`-D -` headers to stdout file, body to temp file); status `0` on connection failure.
  - `fetch_feed(name: str, subs: list[str], last_id: str | None, deadline: float, get=curl_get, sleep=time.sleep, clock=time.monotonic) -> FeedResult`
  - `FeedResult` dataclass: `name: str`, `posts: list[Post]` (newer than `last_id`, newest first), `newest_id: str | None` (first post id of page 1, else the old `last_id`), `requests: int`, `error: str | None`.
  - Cross-feed duplicates are removed later by `State.seen` (Task 7), not here.

- [ ] **Step 1: Write failing tests** with a fake `get` returning scripted `Response`s and a recording `sleep`:
  - `test_no_last_id_single_page`: `last_id=None`, page of 100 → 1 request, 100 posts, `newest_id` = first post id.
  - `test_paginates_until_last_id`: page1 100 posts without `last_id`, page2 contains `last_id` → 2 requests, page2 URL has `after=<last id of page1>`, result stops before `last_id`.
  - `test_deadline_stops_requests`: clock past `deadline` before page 2 → 1 request, `error == "deadline"`, page-1 posts kept.
  - `test_no_new_posts`: page1 starts with `last_id` → 0 posts, `newest_id == last_id`.
  - `test_stops_at_10_pages`.
  - `test_waits_on_ratelimit`: headers `x-ratelimit-remaining: 0.0`, `x-ratelimit-reset: 20` → `sleep(22)` before next request.
  - `test_429_retries_then_gives_up`: four 429s with reset 60 → 3 sleeps of 62, `error` set, `posts == []`.
  - `test_connection_failure`: status 0 → `error` set, no crash.
  - `test_url_format`: first URL == `https://www.reddit.com/r/embedded+FPGA/new/.rss?limit=100`.
- [ ] **Step 2: Run** `python -m pytest tests/test_fetch.py -v` → FAIL.
- [ ] **Step 3: Implement.** Deadline check before every request and before every sleep (a sleep that would cross the deadline is skipped and ends the feed).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Live smoke (user runs, my shell has no network):** `python -c "from digest.fetch import *; import time; r=fetch_feed('t', ['FPGA'], None, time.monotonic()+300); print(len(r.posts), r.requests, r.error)"` → `~100 1 None`.
- [ ] **Step 6: Commit** `feat: rss fetcher with doh, rate limit, pagination`.

### Task 3: State

**Files:**
- Create: `digest/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `State` dataclass: `seen: dict[str, str]` (post id → ISO date first seen), `last_ids: dict[str, str]` (feed name → newest post id), `history_since: int` (Waterfox µs timestamp, 0 = never), `last_digest: str | None` (path), `applied: list[str]` (digest paths whose marks were already logged; keep last 60). `load(path) -> State` (missing file → empty), `save(state, path)` (write temp then replace), `prune(state, today: date, days=30)`.

- [ ] **Step 1: Failing tests** — roundtrip (all 5 fields); missing file → empty; prune drops ids older than 30 days; corrupt JSON → raises (do not silently reset `seen`, that would re-flood the digest).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: state persistence`.

### Task 4: Waterfox viewed posts

**Files:**
- Create: `digest/history.py`
- Test: `tests/test_history.py` (builds a tiny `places.sqlite` with `moz_places` + `moz_historyvisits` in `tmp_path`)

**Interfaces:**
- Produces:
  - `PROFILE = %APPDATA%\Waterfox\Profiles\s4mt22a6.default-release`
  - `Viewed` dataclass: `id: str` (`t3_` + id from URL), `sub`, `title` (without ` : r/<sub>` suffix), `url`, `visited: int` (µs). No body (title-only, see Spec deviations).
  - `viewed_since(since_us: int, profile: Path = PROFILE, tmp: Path = WORK/"tmp") -> tuple[list[Viewed], dict[str, int], int]` — posts visited after `since_us` (one row per post, latest visit), open counts per sub, and max `visit_date` seen (= `since_us` when none).
- [ ] **Step 1: Failing tests** — only `/r/*/comments/*` URLs returned (a github URL and an `/r/x/` listing URL in the fixture are ignored); `since` filter; title suffix stripped; per-sub counts; returned max visit time equals the newest fixture visit (and equals `since_us` when nothing new); copy in `tmp` deleted afterwards; missing profile → raises `FileNotFoundError` (caller turns it into a warning, Task 7).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (copy `places.sqlite` and `-wal` if present, `try/finally` delete). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: waterfox viewed reddit posts`.

### Task 5: Classifier via agy

**Files:**
- Create: `digest/classify.py`
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: `atom.Post`, `history.Viewed` (both have `id`, `sub`, `title`, body/description).
- Produces:
  - `SECTIONS: dict[str, str]` (key → heading, from Global Constraints).
  - `Item` dataclass: `id`, `sub`, `title`, `url`, `link: str | None`, `section: str`, `summary: str`, `source: "followed" | "viewed"`.
  - `write_input(posts, path: Path)` — one JSON object per line: `id, sub, title, body` (body ≤ 600 chars; `""` for `Viewed`).
  - `brief(input_rel: str) -> str` — the agy brief (≤ 30000 bytes).
  - `parse_reply(text: str) -> dict[str, tuple[str, float, str]]` — id → (section, confidence, summary).
  - `classify(posts, source, run_agy=agy_run) -> list[Item]`; `agy_run(brief: str, label: str) -> tuple[int, str]` (rc, reply), runs Git Bash `agy-run-win.sh low <repo> <label>`, then `--cleanup <label>`.
- Brief = the calibration brief that scored 434/434 (saved as `docs/calib-brief.txt` in this task): read-only; input path; reader profile (Vietnamese dev: local LLMs, AI coding agents, game dev/3D, embedded/FPGA/PCB, security, IT career); the 9 section definitions; "body may be empty — judge from title + sub"; "when unsure between drop and anything else, use other"; output **only** JSON lines `{"id","section","confidence","summary"}` (summary 1 sentence, same language as the title), every id exactly once. Batch: <= 150 posts per agy call.
- Drop gate: for `source == "followed"`, `drop` with confidence < 0.9 becomes `other`. Viewed posts keep the model's `drop` as is.
- [ ] **Step 1: Failing tests:**
  - `test_parse_reply_ignores_noise` (prose, code fences, blank lines around JSON lines).
  - `test_unknown_section_becomes_other`.
  - `test_missing_ids_become_other` (Review Focus 1: agy answered 2 of 3 → 3 items, third is `other`, summary = first 200 chars of body, or the title when body is empty).
  - `test_low_confidence_drop_kept_for_followed` (followed, drop 0.7 → `other`; followed, drop 0.95 → `drop`; viewed, drop 0.7 → `drop`).
  - `test_agy_failure_all_other` (rc=11 → every post `other`, nothing lost).
  - `test_batches_of_150` (320 posts → 3 `run_agy` calls).
  - `test_brief_size` (< 30000 bytes).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Real check (me):** run `classify` on the 100 fixture posts with real agy; open the result; confirm 100/100 answered and spot-check 10 sections by hand. Re-score `work/calib/` (labels.json + batches) with the final brief; repo/showcase/knowledge must stay above other/qa_tools in engaged share. Record rc / seconds in the commit message.
- [ ] **Step 6: Commit** `feat: agy classifier`.

### Task 6: Render digest, read marks, saved.md, feedback.jsonl

**Files:**
- Create: `digest/render.py`, `digest/feedback.py`
- Test: `tests/test_render.py`, `tests/test_feedback.py`

**Interfaces:**
- Consumes: `classify.Item`, `classify.SECTIONS`.
- Produces:
  - `render(items, warnings: list[str], suggestions: list[tuple[str, int]], day: date) -> str`. Layout = spec §7. Item line exactly:
    `- [ ] **{title}** — {summary} — [post]({url}){ · [link]({link}) if link} \`r/{sub}\` <!-- id:{id} section:{section} -->`
    `drop` items are not rendered. Empty sections omitted. Sections in the Global Constraints order.
  - `read_marks(md: str) -> list[Mark]`; `Mark`: `id, sub, section, title, url, decision: "keep"|"reject"|"neutral"`.
  - `apply(marks, digest_day: date, saved: Path, log: Path, dropped: list[Item])` — `digest_day` is the date of the digest the marks came from (parsed from its filename), not today. Append `keep` to `saved.md` (dedupe by id), append every mark + every dropped item (`decision: "auto-drop"`) to `feedback.jsonl` as `{date, id, sub, section, title, decision}`.
- [ ] **Step 1: Failing tests:** render → read_marks roundtrip gives same ids; `[X]`, `[x]`, `[-]`, `[ ]` and extra spaces parsed; line without id tag ignored; keep written to saved.md once even if `apply` runs twice; feedback line per mark + per auto-drop; render omits empty sections and `drop`; sections appear in Global Constraints order.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: digest render and feedback marks`.

### Task 7: `run` pipeline + CLI

**Files:**
- Create: `digest/run.py`, `digest/__main__.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run(today: date, deps: Deps) -> Path` (digest path); `Deps` dataclass bundles `get`, `sleep`, `run_agy`, `viewed` (= `history.viewed_since`), paths. `python -m digest run` builds real deps.
- Order: start deadline clock (45 min) → load state → if `state.last_digest` not in `state.applied`: `apply` its marks (+ `work/dropped/<its date>.jsonl`), add to `applied` → fetch all feeds with `state.last_ids[name]` (log requests/posts per feed to `work/log.txt`) → viewed posts since `state.history_since` → drop ids in `state.seen`, then viewed ids already in followed → classify → warnings (feed errors incl. `deadline`, agy rc ≠ 0, history unavailable, any sub with > 500 posts whose `published` is within the last 24 h) → sub suggestions (viewed sub counts for subs not in `FEEDS`, top 10) → render → write `digests/<date>.md` and `work/dropped/<date>.jsonl` → update `seen`, `last_ids` (from `FeedResult.newest_id`), `history_since` (max visit), `last_digest`; prune; save state **last** (a crash mid-run must not mark posts seen).
- Same-day re-run overwrites `digests/<date>.md`; marks of the previous digest are not logged twice (`applied`).
- [ ] **Step 1: Failing tests (all fakes):** happy path writes digest with both parts and suggestions; feed error → warning line, other feeds still present; history `FileNotFoundError` → warning, digest written (Review Focus 4); agy rc=11 → warning, all items under Other (Review Focus 1); crash in render → state file unchanged; second run applies marks from first digest; third run with the same `last_digest` logs nothing new; a feed missing from `last_ids` fetches one page; deadline reached during fetch → warning, digest still written.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run full suite** `python -m pytest -v` → all PASS.
- [ ] **Step 5: Real run (user, in a normal PowerShell):** `cd C:\Users\d\Documents\Github\reddit-digest; python -m digest run` → expect ~13–15 min, a file in `digests/`. I then read the digest + `work/log.txt` and check: every feed has posts or a warning; 5 random links open the right post; sections look sane.
- [ ] **Step 6: Commit** `feat: run pipeline and cli`.

### Task 8: `review` command

**Files:**
- Create: `digest/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Produces: `summarize(lines: list[dict]) -> str` (markdown) and `python -m digest review` (prints it).
- Report (v1 groups by sub and by section only — no flair): per sub and per section: keep / reject / neutral / auto-drop counts; groups with ≥ 10 marks and 0 keeps listed as **proposed drop rules**; auto-dropped titles from the last 14 days listed for wrong-drop check. Proposals only — no rule file is written.
- [x] **Step 1: Failing tests:** counts per group; proposal appears for 12 rejects / 0 keeps; no proposal for 12 rejects / 1 keep; empty log → "no feedback yet".
- [x] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [x] **Step 5: Commit** `feat: review command`.

### Task 9: Nightly schedule

**Files:**
- Create: `scripts/run-digest.ps1` (cd repo, `python -m digest run`, append stdout/stderr to `work/log.txt`), `scripts/install-task.ps1`
- Modify: `README.md` (create: how to run, mark, review, install task)

- `install-task.ps1`: `Register-ScheduledTask -TaskName "reddit-digest"` daily 21:00, current user, `-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1))`, action `powershell -ExecutionPolicy Bypass -File <repo>\scripts\run-digest.ps1`.
- [x] **Step 1:** Parse-check both scripts with `[System.Management.Automation.Language.Parser]::ParseFile` → 0 errors.
- [x] **Step 2 (user):** run `install-task.ps1`, then `Start-ScheduledTask reddit-digest`; after it ends, `Get-ScheduledTaskInfo reddit-digest` shows `LastTaskResult 0` and a new digest exists.
- [x] **Step 3: Commit** `feat: nightly task scheduler job`.
