# Digest Scoring & Two-Pass Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the ~700-posts/day digest into something readable in 30 seconds: every post gets a 0–10 `score`; the digest opens with a short **Top ideas** block of the standout posts, then the remaining good posts as side information in the usual sections, sorted by score; the model is steered by the user's own past rejects.

**Architecture:** `classify` asks the model for a `score` next to `section`. A new pure `select` step hides low-score posts and caps posts per sub; hidden posts go to the existing `work/dropped/<date>.jsonl`. A cheap `low` screening pass scores everything, then a `high` pass re-scores only the top K with full body. Few-shot examples from `work/feedback.jsonl` are appended to the brief.

**Tech Stack:** Python 3.13 stdlib only, pytest, existing `agy` runner.

**Spec:** No separate design doc. The request is the user's message of 2026-11-10 selecting items 1–4 of the "analyze 2k posts" proposal (hard filters, `score` field, feedback few-shot, two-pass), plus their answer about the morning read: "in the first 30 seconds I want the standout ideas, then side information; that's all". Decisions marked **(my call)** below were not stated by the user.

## Global Constraints

- Python 3.13, standard library only; tests run with `python -m pytest -q` (177 pass today and must stay green).
- `Deps.run_agy` stays a 2-argument callable `(brief: str, label: str) -> tuple[int, str]`; 32 test usages depend on it.
- Old `work/dropped/*.jsonl` lines (no `score` key) must still load via `Item(**d)`.
- `docs/calib-brief.txt` overrides `DEFAULT_BRIEF` in `digest/classify.py`; both must carry identical prompt text.
- Digest item line keeps the `<!-- id:... section:... -->` tag shape that `feedback.read_marks` parses; new data may only be appended inside that tag as `score:N`.
- No post may be silently lost: any post the model fails to score is shown, never hidden.
- New constants live in `digest/config.py`: `MIN_SCORE = 7`, `MAX_PER_SUB = 15`, `TOP_N = 10`, `TOP_MIN_SCORE = 9`, `SCREEN_TOP_K = 300`, `FEWSHOT_N = 15`.
- Do not commit; the user commits on request.
- **(my call)** Per-sub cap is applied after scoring (top `MAX_PER_SUB` by score per sub per source), not before the model, so good posts are not cut by arrival order.
- **(my call)** Posts with `score is None` are exempt from both the threshold and the cap.
- **(my call)** "Standout ideas" = the `TOP_N` highest-scored shown posts with `score >= TOP_MIN_SCORE`; "side information" = every other shown post, in the existing sections. A post appears once: top posts are moved out of their section, not duplicated (duplicates would double-count marks in `read_marks`).
- **(my call)** Hidden low-score posts reuse `work/dropped/<date>.jsonl` (they feed `feedback.apply` as `auto-drop`); no new file.

## Review Focus

1. Model omits or garbles `score` (missing, `"8/10"`, `7.5`, `11`, `-2`, `"high"`) → clamped to an int 0–10 or `None`; a `None` post is still shown. Tests in Task 1 and Task 2.
2. Old `dropped.jsonl` lines without `score` → still load. Test in Task 1.
3. `work/feedback.jsonl` missing, empty, or containing a corrupt line → brief has no examples block and nothing crashes. Test in Task 4.
4. Screening batch fails (`rc != 0`) → its posts get `section="other"`, `score=None`, are still shown, and still go to the high pass. Test in Task 5.
5. A sub with fewer posts than `MAX_PER_SUB`, or all posts below `MIN_SCORE` → nothing breaks, digest may be empty of that sub. Test in Task 2.
6. No post reaches `TOP_MIN_SCORE` (or all scores are `None`) → no empty "Top ideas" heading is rendered and the digest looks like today's. Test in Task 2.
7. A top post carries the same id tag as before, so `[-]`/`[x]` marks on it are still read exactly once. Test in Task 2.
8. A followed `drop` the model is unsure about (confidence < 0.9) with a low score → stays visible as `other`. Test in Task 1.
9. The high pass fails for a batch → the post keeps its screening section and score. Test in Task 5.

---

### Task 1: `score` field, parsing, and prompt

**Files:**
- Modify: `digest/classify.py` (`Item`, `_parse_entry_dict`, `parse_reply`, `classify`, `DEFAULT_BRIEF`)
- Modify: `docs/calib-brief.txt`
- Modify: `tests/test_classify.py` (the five `parse_reply` assertions that compare 3-tuples; `Item(...)` round-trip at the `asdict` test)
- Test: `tests/test_classify.py`

**Interfaces:**
- Produces:
  - `Item.score: int | None = None` (last field, default `None`).
  - `_parse_entry_dict(data) -> tuple[str, tuple[str, float, str, int | None]] | None`
  - `parse_reply(text) -> dict[str, tuple[str, float, str, int | None]]` — fourth element is the score.
  - `_parse_score(raw: object) -> int | None` — `int`/`float` → rounded and clamped to 0–10; `"8/10"` or `"8"` → 8; anything else → `None`.
  - `classify(...) -> list[Item]` sets `Item.score` from the parsed reply (`None` when the id is missing or the reply is unusable). When the existing rule at `classify.py:422` downgrades a followed `drop` with confidence < 0.9 to `other`, it also sets `score=None`, so the "when unsure, don't drop" safety net is not defeated by a low score hiding the post in `select`.

- [ ] **Step 1: Write failing tests** in `tests/test_classify.py`:
  - `test_parse_score_variants`: `_parse_score(8)==8`, `(7.5)==8`, `(11)==10`, `(-2)==0`, `("8/10")==8`, `("high") is None`, `(None) is None`.
  - `test_parse_reply_includes_score`: a reply line with `"score": 9` gives `parsed["t3_x"] == ("repo", 0.9, "s", 9)`; a line without `score` gives fourth element `None`.
  - `test_item_loads_without_score`: `Item(**{...all old fields, no score...}).score is None`.
  - `test_classify_sets_score`: fake `run_agy` returning one JSON line with `"score": 6` → returned `Item.score == 6`; id absent from reply → `Item.score is None`.
  - `test_unsure_drop_becomes_other_unscored`: followed post, reply `{"section":"drop","confidence":0.6,"score":1}` → `section == "other"` and `score is None`; with confidence 0.95 it stays `drop`.
  - `test_briefs_in_sync`: the text of `DEFAULT_BRIEF` equals the contents of `docs/calib-brief.txt` after replacing the `Input:` path token, and both contain the word `score`.
- [ ] **Step 2: Run** `python -m pytest tests/test_classify.py -q` → new tests FAIL; the old 3-tuple assertions are updated to 4-tuples (`..., None`) in the same step.
- [ ] **Step 3: Implement** the interfaces above. Output schema line in both prompts becomes `{"id":"t3_...","section":"...","confidence":0.0-1.0,"score":0-10,"summary":"..."}`. Add a rubric paragraph to both prompts: score 9–10 = usable today with real substance (repo/tool with docs, reusable workflow, measured results with method); 7–8 = solid and relevant; 4–6 = relevant but thin; 0–3 = low value for this reader; relevance means coding agents, embedded/FPGA/PCB, game dev/3D, security, IT career. Keep the existing drop and effort paragraphs unchanged.
- [ ] **Step 4: Run** `python -m pytest -q` → all pass.

### Task 2: `select` step, Top ideas block, ranked render, wiring

**Files:**
- Create: `digest/select.py`
- Modify: `digest/render.py` (`_format_item_line`, `_render_group`), `digest/run.py` (after classify, before render), `digest/config.py`
- Test: `tests/test_select.py`, `tests/test_render.py`, `tests/test_run.py`

**Interfaces:**
- Consumes: `Item` with `score` (Task 1).
- Produces:
  - `config.MIN_SCORE: int = 7`, `config.MAX_PER_SUB: int = 15`.
  - `select.select(items: Sequence[Item], min_score: int = MIN_SCORE, max_per_sub: int = MAX_PER_SUB) -> tuple[list[Item], list[Item]]` returning `(shown, hidden)`. `shown` keeps input order. Items with `section == "drop"` are in neither list (renderer already skips them; run keeps them in the dropped file separately). Cap groups by `(source, sub.lower())` and keeps the highest scores, ties by input order.
  - `config.TOP_N: int = 10`, `config.TOP_MIN_SCORE: int = 9`.
  - Render: if at least one shown item has `score >= TOP_MIN_SCORE`, the digest starts (after warnings) with `## Top ideas` listing up to `TOP_N` of them, highest score first, as ordinary item lines; those items are removed from the sections below. Items inside a section are sorted by `score` descending (stable; `None` last). The tag becomes `<!-- id:{id} section:{sec} score:{n} -->` when `score` is not `None`, unchanged otherwise.

- [ ] **Step 1: Write failing tests**
  - `test_select_hides_below_min_score`: scores `[9, 7, 6, 0]` → shown ids are the first two, hidden the other two.
  - `test_select_keeps_none_score`: `score=None` item is in `shown` even with `min_score=10` and `max_per_sub=0`.
  - `test_select_caps_per_sub_by_score`: 20 items same sub, scores 7..10 cycling, `max_per_sub=15` → 15 shown, all with score ≥ the lowest shown, 5 hidden; cap is separate per `source`.
  - `test_select_empty_and_small_inputs`: `select([]) == ([], [])`; one sub with 3 items and `max_per_sub=15` → all 3 shown.
  - `test_render_sorts_by_score_and_tags`: two items in one section, scores 7 and 9 → the 9 is rendered first; line contains `score:9`; an item with `score=None` has no `score:` in its tag and renders after scored ones; `read_marks` on the rendered text still returns both ids.
  - `test_render_top_ideas_block_first`: items scored 10, 9, 8, 3(hidden earlier) → output has `## Top ideas` before `## From followed subs`; the 10 and the 9 appear only under Top ideas, the 8 only in its section; `TOP_N` monkeypatched to 1 → only the 10 is in Top ideas and the 9 returns to its section.
  - `test_render_no_top_block_without_high_scores`: all scores below 9 or `None` → output contains no `## Top ideas`.
  - `test_top_item_marks_still_read_once`: a `[-]`-marked line inside Top ideas is returned by `read_marks` exactly once.
  - `test_run_hides_low_score_into_dropped_file`: fake agy returns scores 9 and 3 → digest contains only the 9, `work/dropped/<date>.jsonl` contains the 3 with `"score": 3`.
- [ ] **Step 2: Run** `python -m pytest tests/test_select.py tests/test_render.py tests/test_run.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** `select`, the render changes, and in `run.run`: `shown, hidden = select(all_items)`; `render(items=shown, ...)`; the dropped file is `[it for it in all_items if it.section == "drop"] + hidden`. Keep the existing `feedback.apply` path unchanged.
- [ ] **Step 4: Run** `python -m pytest -q` → all pass.

### Task 3: Language pre-filter

**Files:**
- Create: `digest/prefilter.py`
- Modify: `digest/run.py` (in the dedupe loops for followed and viewed, after the age checks)
- Test: `tests/test_prefilter.py`, `tests/test_run.py`

**Interfaces:**
- Produces: `prefilter.language_ok(title: str) -> bool` — `True` for English or Vietnamese (with or without diacritics) and for anything ambiguous; `False` for titles with letters from a non-Latin script, or whose Latin-script foreign words/diacritics clearly outnumber English stopwords.

- [ ] **Step 1: Write failing tests** `test_language_ok_rejects_foreign`: each of these returns `False`: `"Помогите , как с чего начать?"`, `"När fick du ditt första jobb inom Cybersäkerhet"`, `"Jakie czujniki temperatury i wilgotności polecasz"`, `"Est ce que l'intelligence artificielle va nous remplacer ?"`, `"Hay empresas que te contraten para aprender a programar actualmente?"`, `"Das Steam Next Fest hat mich umgehauen"`, `"¿Qué hace que un desafío de plataformas sea satisfactorio?"`. `test_language_ok_keeps_en_vi_and_ambiguous`: each returns `True`: `"A whole city in three.js: isometric pixel-art Bielsko-Biała with live buses"`, `"Công thức tiết kiệm của ông bà cha mẹ thời xưa"`, `"Anyone tried this yet?"`, `"Llama.cpp"`, `""`. `test_run_skips_foreign_titles`: a feed post with a Russian title never reaches the fake agy input and is absent from digest and from the dropped file.
- [ ] **Step 2: Run** `python -m pytest tests/test_prefilter.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `language_ok` (stdlib only: `unicodedata` or character ranges plus small English/foreign stopword sets) and call it in `run.run` for both `filtered_followed` and `filtered_viewed` before a post is queued.
- [ ] **Step 4: Run** `python -m pytest -q` → all pass.

### Task 4: Few-shot taste examples from feedback

**Files:**
- Create: `digest/examples.py`
- Modify: `digest/classify.py` (`brief()`), `digest/config.py`
- Test: `tests/test_examples.py`, `tests/test_classify.py`

**Interfaces:**
- Produces:
  - `config.FEWSHOT_N: int = 15`.
  - `examples.feedback_examples(path: pathlib.Path, n: int = FEWSHOT_N) -> str` — returns `""` when the file is missing, empty, unreadable, or has no `reject`/`keep` lines; otherwise a block starting with the line `Examples of this reader's taste (from past marks):` followed by up to `n` most recent `REJECT | r/{sub} | {title}` lines and up to `n` most recent `KEEP | r/{sub} | {title}` lines. Corrupt JSON lines are skipped. Titles are collapsed to single spaces and cut at 140 characters.
  - `classify.brief(input_rel: str) -> str` appends `feedback_examples(WORK / "feedback.jsonl")` after the template when non-empty; the 30000-byte limit check still applies to the final text.

- [ ] **Step 1: Write failing tests**
  - `test_examples_missing_file_returns_empty`, `test_examples_empty_file_returns_empty`.
  - `test_examples_skips_corrupt_lines_and_neutral`: file with a corrupt line, a `neutral`, an `auto-drop`, 2 rejects, 1 keep → block lists exactly those 3 lines, rejects labelled `REJECT`, keep labelled `KEEP`.
  - `test_examples_limits_to_n_most_recent`: 40 reject lines → exactly `n` `REJECT` lines and they are the last `n` in the file.
  - `test_brief_appends_examples`: with `WORK` monkeypatched to a temp dir holding a feedback file, `brief("x")` ends with the examples block; with no file the output equals the template alone.
- [ ] **Step 2: Run** `python -m pytest tests/test_examples.py tests/test_classify.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** `feedback_examples` and the `brief()` change.
- [ ] **Step 4: Run** `python -m pytest -q` → all pass.

### Task 5: Two-pass screening

**Files:**
- Modify: `digest/run.py` (`Deps`, classify step), `digest/classify.py` (add `body_limit` to `write_input`/`classify`), `digest/__main__.py`, `digest/config.py`, `README.md`
- Test: `tests/test_run.py`, `tests/test_classify.py`

**Interfaces:**
- Produces:
  - `config.SCREEN_TOP_K: int = 300`.
  - `Deps.run_agy_screen: Callable[[str, str], tuple[int, str]] | None = None`. `None` means single pass with `run_agy` (all existing tests unchanged).
  - `classify(posts, source, run_agy=..., batch_size=..., max_workers=..., body_limit: int | None = None) -> list[Item]` — `body_limit` truncates `body` in the batch input file only (not elsewhere).
  - `__main__.main` builds `Deps(run_agy_screen=functools.partial(agy_run, level="low"))` so production uses two passes.
- Behavior in `run.run` when `deps.run_agy_screen` is set, for the followed list only:
  1. Pass 1 = `classify(filtered_followed, "followed", run_agy=<tracked screen>, body_limit=600)`. The screen callable is wrapped by the same error tracking as `tracking_run_agy` (feeds `agy_errors`, the log line and the digest warning).
  2. Pass-2 candidates = pass-1 items whose section is not `drop`, ordered: `score is None` first, then `score` descending; take the first `SCREEN_TOP_K`. Pass-1 `drop` items stay dropped and are never sent to pass 2.
  3. Pass 2 = `classify` of the original `Post` objects for those ids with `run_agy` (high, full body).
  4. Merge by id: a pass-2 item replaces its pass-1 item only when the pass-2 `score` is not `None`; otherwise the pass-1 item is kept (a failed or garbled high batch must not erase a good screening result).
  Viewed posts are always single pass with `run_agy`.

- [ ] **Step 1: Write failing tests**
  - `test_write_input_body_limit`: a 700-char body with `body_limit=100` writes a 100-char body; `None` keeps 700.
  - `test_run_two_pass_rescoring`: 5 followed posts, fake screen scores them `[9,8,7,6,5]`, `SCREEN_TOP_K` monkeypatched to 2, fake high agy returns score 10 for whatever ids it receives → high agy received exactly the 2 top ids; final digest items for those two have score 10, the other three keep their pass-1 scores.
  - `test_run_single_pass_when_screen_is_none`: with `run_agy_screen=None` the fake high agy receives all posts once (existing behavior).
  - `test_run_screen_failure_keeps_posts`: screen returns `(1, "")` for a batch → those posts have `section="other"`, `score=None`, are sent to the high pass first, and appear in the digest; the digest carries the `agy error` warning.
  - `test_run_failed_high_pass_keeps_screen_result`: screen scores a post 8 as `repo`; the high agy returns `(1, "")` → final item is still `repo` with score 8.
  - `test_run_screen_drop_not_sent_to_high_pass`: a post the screen marks `drop` (confidence 0.95) is absent from the high agy input and is in the dropped file.
  - `test_run_high_pass_input_bounded_by_top_k`: 5 unscored plus 5 scored posts with `SCREEN_TOP_K=3` → the high agy receives exactly 3 ids, all from the unscored group.
- [ ] **Step 2: Run** `python -m pytest tests/test_run.py tests/test_classify.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** the interfaces and behavior above; wire `__main__`; add one README paragraph describing scoring, `MIN_SCORE`, `MAX_PER_SUB`, the two passes, and the feedback examples.
- [ ] **Step 4: Run** `python -m pytest -q` → all pass.
- [ ] **Step 5: Real-data check** (no tests substitute for this): run `python -m digest run --date <fresh date>` against a copy of `work/` (state backed up first), and confirm the digest count drops well below the current ~750 and `work/dropped/<date>.jsonl` contains rows with `score`. Report the count and ten sample hidden titles to the user; do not claim success from the unit tests alone.

---

## Known Risks (accepted, check in Task 5 step 5)

- **Score inflation:** if the model scores most posts 7+, the fixed `MIN_SCORE` hides little and the digest stays large. The real-data check measures this; the fallback is a total cap or a percentile threshold, not in this plan.
- **Cap-hidden good posts are gone for good:** posts hidden by `MAX_PER_SUB` are added to `state.seen`, so they never return the next day. They stay visible in the "Auto-dropped (last 14 days)" list of `python -m digest review`, which only displays auto-drops and never feeds drop proposals (`review.py` proposes rules from rejects and keeps only).
- **Few-shot is weak today:** `feedback.jsonl` has only a handful of rejects and zero keeps because `[x]` is never used; the examples block will mostly be negatives.

## Self-Review Notes

- **Coverage:** user items 1 (hard filters → Tasks 2 cap, 3 language; age/dedupe already exist), 2 (score → Tasks 1–2), 3 (few-shot → Task 4), 4 (two-pass → Task 5).
- **Not included (my call):** no "junk sub" blocklist (`FEEDS` already controls subs); no topic clustering (item 5 of the proposal, not selected); no `review` command changes to report keep-rate by score.
- **Proportion:** signatures and assertions only; bodies left to the implementer.
