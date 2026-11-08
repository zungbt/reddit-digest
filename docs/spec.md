# Reddit Digest — Spec

Status: approved scope, 2026-11-08. Per-sub flair rules (§6) still TBD.

## 1. Goal

Follow the subreddits I care about and pull out ideas (repos, tools, games, useful things), so I read them **once, in one sitting**, instead of checking Reddit all day.

Success = one evening digest replaces scattered Reddit browsing; no post from a followed sub is silently missed.

## 2. Non-goals (v1)

- Ranking.
- Comments (posts only).
- Notifications (they pull attention back during the day).
- Docker / server deployment.
- OAuth / Reddit API login.

## 3. Constraints (measured 2026-11-08)

| Fact | Evidence |
|---|---|
| VNPT DNS blocks reddit.com (NXDOMAIN) | `nslookup www.reddit.com` |
| Resolving via DoH works | `curl.exe --doh-url https://cloudflare-dns.com/dns-query` → 200 atom |
| Unauthenticated RSS works; `?limit=100` returns 100 entries | probe |
| Unauthenticated `.json` is blocked (403) → no score/flair fields | probe |
| Rate limit ≈ 1 request/min (`x-ratelimit-remaining: 0`, `reset` ≤ 60 s) | probe |
| Multi-sub feed `r/A+B+C/new/.rss` works, entries split by volume | probe: embedded/esp32/FPGA = 40/35/25 over 78 h |
| Flair search via RSS works | `r/LocalLLaMA/search.rss?q=flair:"New Model"&restrict_sr=1&sort=new` → 100 posts / 17 days |
| `/domain/github.com` feed is too noisy | 100 posts / 12 h, mostly off-topic |
| r/LocalLLaMA (busiest followed sub) ≈ 50 posts/day | 100 newest posts span 47.8 h |

## 4. Sources

### 4.1 Followed subs (RSS)

Follow list = subs I joined (except r/announcements) + subs my Waterfox history shows I open often (5165 Reddit posts opened, 2026-02-21..2026-11-08). Number = posts I opened.

| Feed | Subs (clicks) |
|---|---|
| solo | LocalLLaMA (518) |
| solo | LocalLLM (209) |
| solo | ClaudeCode (70) |
| solo | ClaudeAI (60) |
| multi: local AI | DeepSeek (120) + Qwen_AI (76) + unsloth (70) |
| multi: AI agents | GeminiAI (72) + google_antigravity (38) + CommandCode (37) + opencodeCLI (33) + PiCodingAgent (14) + claudeskills (11) + claude (7) + Claudeopus (4) |
| multi: hardware | embedded (43) + esp32 (12) + IOT (9) + FPGA (4) + PCB (1) + KiCad (1) + CheapYellowDisplay (1) + PrintedCircuitBoard (0) + electronics (0) |
| multi: game/3D | blender (33) + IndieDev (25) + TopologyAI (21) + aigamedev (10) + mocap (6) + threejs (3) + SoloDevelopment (2) + DestroyMyGame (1) |
| multi: repos | SideProject (18) + BestGitHubRepos (14) + coolgithubprojects (6) |
| multi: AI media / creator | StableDiffusion (7) + AI_UGC_Marketing (6) + YT_Faceless (1) + DigitalProductSellers (1) |
| multi: career | softwareengineer (6) + cscareerquestions (3) + EngineeringResumes (0) |
| multi: security | netsecstudents (25) + SecurityCareerAdvice (9) + AskNetsec (3) |
| multi: learning | compsci (2) + Learning (2) + learnpython (1) |

Additions from the second history pass (read time, outbound clicks, sub pages opened directly): ClaudeAI, claude, Claudeopus, StableDiffusion (5 of 67 outbound clicks), CheapYellowDisplay, SoloDevelopment, IOT, career subs, AI media subs, security subs (sub pages opened directly 17×).

Excluded: r/announcements (no ideas), r/vozforums (398 opens, but mostly life topics — decided to drop).

Feeds that turn out too busy for one multi feed (newest entry window shorter than the run interval) get split.

### 4.2 Viewed posts (Waterfox history)

- Copy `%APPDATA%\Waterfox\Profiles\s4mt22a6.default-release\places.sqlite` + `-wal` to a temp dir, read the copy, delete it. Never open the live file.
- Read only URLs matching `reddit.com/r/*/comments/*` visited since the last run. Nothing else is read or stored.
- Fetch each post via `<post-url>.rss`.
- Count opens per sub; subs opened often but not followed are listed as **suggestions** at the end of the digest (never auto-added).

## 5. Fetch

- One run per day, **21:00**, via Windows Task Scheduler ("run as soon as possible after a missed start" on).
- Each feed: `new/.rss?limit=100`; paginate with `after=t3_<id>` until reaching the newest post from the previous run. Hard stop at ~1000 posts/feed (Reddit's listing cap).
- Between requests: wait `x-ratelimit-reset` + 2 s when `remaining < 1`; on 429 wait max(reset, 60) + 2 s and retry.
- DNS via DoH (Cloudflare). User-Agent `reddit-digest/0.1`. No browser spoofing.
- Dedupe by post ID; state (last seen ID per feed, seen IDs, last history timestamp) in `state.json`.
- Log per run: requests, posts per feed, posts/day per sub. If a sub exceeds ~500 posts/day, put a warning line at the top of the digest.
- Expected run time: 13 feeds ≈ 13–15 min.

## 6. Filter

**Principle: start broad, close in from my reject data.** v1 drops only obvious noise; rules get tighter only when daily rejects show a pattern (§8).

1. **Rules (before LLM), v1 = minimal:** drop only memes/shitposts by flair and exact duplicates/crossposts. No title-pattern drops in v1.
2. **LLM (Gemini via `agy-run-win.sh low`, read-only):** put each post in a section, never silently drop except clear noise:
   - repo/tool
   - game
   - project/showcase ("I built X")
   - useful knowledge (benchmark, workflow experiment, technique)
   - Q&A about tools I use (quant choice, agent setup, token optimizers…) — kept: I revisit these (e.g. "How to decide which quant to pick?" opened 3×)
   - IT career / working abroad (I read these longest, e.g. "Con đường xuất ngoại cho dân IT" opened 3×)
   - making money / content with AI (AI UGC, faceless YT, digital products)
   - other (doesn't fit, but not noise)
   - drop: memes, rants with no info, hiring/self-promo spam

Basis: history pass 2 (read time since 2026-09-20 on 440 posts, 67 outbound clicks, revisits). Outbound clicks go mostly to github.com (32) and huggingface.co (7).

## 7. Output

`digests/YYYY-MM-DD.md`:

```
> warnings (if any)

## From followed subs
### Repo / Tool
- [ ] **Title** — 1–2 line summary — [link] `r/sub · flair`
### Game
### Project / Showcase
### Useful knowledge
### Q&A about my tools
### IT career / abroad
### Money / content with AI
### Other

## From posts you viewed
(same sections)

## Sub suggestions
- r/X — opened N times since last run
```

## 8. Saving and reject feedback

Each item has a checkbox. In the digest I mark:
- `[x]` keep → collected into `saved.md` on the next run
- `[-]` reject (not interesting) → logged as reject
- `[ ]` untouched → read, neutral

Next run parses the previous digest and appends one line per marked item to `feedback.jsonl`: date, sub, flair, section, title, decision. Drop-stage posts are also logged (decision `auto-drop`) so I can spot wrong drops.

Closing in: after ~2 weeks of data (or on demand), a `review` command summarizes rejects by sub / flair / section / title pattern and **proposes** rule changes (e.g. "r/X flair Discussion: 18 rejected, 0 kept → drop"). Rules change only after I approve.

## 9. Risks

- agy login token may expire → run fails with rc=11; logged in `log.txt` and shown as a warning in the next digest.
- Reddit may tighten unauthenticated RSS → fallback is OAuth (app may need approval).
- Browser history only records posts whose page I opened, not posts I scrolled past.
- Titles/URLs of viewed posts are sent to Gemini (Google) for classification.
- Rate limit ~1 req/min: adding many feeds adds minutes per run.
