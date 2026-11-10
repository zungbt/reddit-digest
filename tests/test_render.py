import datetime
import pytest

from digest.classify import Item, SECTIONS
from digest.render import render
from digest.feedback import Mark, read_marks


def _make_item(
    id: str = "t3_test1",
    sub: str = "LocalLLaMA",
    title: str = "Sample Title",
    url: str = "https://www.reddit.com/r/LocalLLaMA/comments/test1/sample/",
    link: str | None = None,
    section: str = "repo",
    summary: str = "Sample 1-sentence summary.",
    source: str = "followed",
    score: int | None = None,
) -> Item:
    return Item(
        id=id,
        sub=sub,
        title=title,
        url=url,
        link=link,
        section=section,
        summary=summary,
        source=source,
        score=score,
    )


def test_render_item_line_without_link():
    item = _make_item(
        id="t3_1xqxv0m",
        sub="FPGA",
        title="IMC Hardware Engineering role - Interview",
        summary="Preparation tips for upcoming interview",
        url="https://www.reddit.com/r/FPGA/comments/1xqxv0m/imc_hardware_engineering_role_interview/",
        link=None,
        section="career",
        source="followed",
    )
    rendered = render([item])
    expected_line = (
        "- [ ] **IMC Hardware Engineering role - Interview** — Preparation tips for upcoming interview — "
        "[post](https://www.reddit.com/r/FPGA/comments/1xqxv0m/imc_hardware_engineering_role_interview/) "
        "`r/FPGA` <!-- id:t3_1xqxv0m section:career -->"
    )
    assert expected_line in rendered


def test_render_item_line_with_link():
    item = _make_item(
        id="t3_link1",
        sub="LocalLLaMA",
        title="vLLM new release with FP8 support",
        summary="Major speedups on modern GPUs",
        url="https://www.reddit.com/r/LocalLLaMA/comments/link1/vllm/",
        link="https://github.com/vllm-project/vllm",
        section="repo",
        source="followed",
    )
    rendered = render([item])
    expected_line = (
        "- [ ] **vLLM new release with FP8 support** — Major speedups on modern GPUs — "
        "[post](https://www.reddit.com/r/LocalLLaMA/comments/link1/vllm/) · "
        "[link](https://github.com/vllm-project/vllm) "
        "`r/LocalLLaMA` <!-- id:t3_link1 section:repo -->"
    )
    assert expected_line in rendered


def test_render_omits_drop_section():
    item_drop = _make_item(id="t3_drop1", section="drop", title="Meme post")
    item_repo = _make_item(id="t3_repo1", section="repo", title="Cool repo")
    rendered = render([item_drop, item_repo])
    assert "t3_drop1" not in rendered
    assert "Meme post" not in rendered
    assert "(not rendered)" not in rendered
    assert "t3_repo1" in rendered


def test_render_omits_empty_sections():
    item_game = _make_item(id="t3_game1", section="game", title="New Indie Game")
    rendered = render([item_game])
    assert "### Game" in rendered
    assert "### Repo / Tool" not in rendered
    assert "### Project / Showcase" not in rendered
    assert "### Useful knowledge" not in rendered
    assert "### Money / content with AI" not in rendered
    assert "### IT career / abroad" not in rendered
    assert "### Q&A about my tools" not in rendered
    assert "### Other" not in rendered


def test_render_sections_in_global_constraints_order():
    # Global Constraints order:
    # 1. repo ("Repo / Tool")
    # 2. showcase ("Project / Showcase")
    # 3. knowledge ("Useful knowledge")
    # 4. money ("Money / content with AI")
    # 5. career ("IT career / abroad")
    # 6. game ("Game")
    # 7. qa_tools ("Q&A about my tools")
    # 8. other ("Other")
    items = [
        _make_item(id="t3_other", section="other", title="Other Item"),
        _make_item(id="t3_qa", section="qa_tools", title="QA Item"),
        _make_item(id="t3_game", section="game", title="Game Item"),
        _make_item(id="t3_career", section="career", title="Career Item"),
        _make_item(id="t3_money", section="money", title="Money Item"),
        _make_item(id="t3_knowledge", section="knowledge", title="Knowledge Item"),
        _make_item(id="t3_showcase", section="showcase", title="Showcase Item"),
        _make_item(id="t3_repo", section="repo", title="Repo Item"),
    ]
    rendered = render(items)

    pos_repo = rendered.index("### Repo / Tool")
    pos_showcase = rendered.index("### Project / Showcase")
    pos_knowledge = rendered.index("### Useful knowledge")
    pos_money = rendered.index("### Money / content with AI")
    pos_career = rendered.index("### IT career / abroad")
    pos_game = rendered.index("### Game")
    pos_qa = rendered.index("### Q&A about my tools")
    pos_other = rendered.index("### Other")

    assert pos_repo < pos_showcase < pos_knowledge < pos_money < pos_career < pos_game < pos_qa < pos_other


def test_render_groups_followed_and_viewed():
    item_fol = _make_item(id="t3_fol1", section="repo", title="Followed Repo", source="followed")
    item_view = _make_item(id="t3_view1", section="knowledge", title="Viewed Article", source="viewed")

    rendered = render([item_fol, item_view])
    assert "## From followed subs" in rendered
    assert "## From posts you viewed" in rendered

    pos_fol = rendered.index("## From followed subs")
    pos_view = rendered.index("## From posts you viewed")
    assert pos_fol < pos_view

    # Verify item_fol is under followed and item_view is under viewed
    pos_item_fol = rendered.index("t3_fol1")
    pos_item_view = rendered.index("t3_view1")
    assert pos_fol < pos_item_fol < pos_view
    assert pos_view < pos_item_view


def test_render_omits_followed_or_viewed_heading_when_empty():
    item_view = _make_item(id="t3_view1", section="repo", source="viewed")
    rendered = render([item_view])
    assert "## From followed subs" not in rendered
    assert "## From posts you viewed" in rendered

    item_fol = _make_item(id="t3_fol1", section="repo", source="followed")
    rendered_fol = render([item_fol])
    assert "## From followed subs" in rendered_fol
    assert "## From posts you viewed" not in rendered_fol


def test_render_warnings_at_top():
    item = _make_item(id="t3_1", section="repo")
    warnings = ["Rate limit reached on feed hardware", "History database locked"]
    rendered = render([item], warnings=warnings)

    lines = rendered.strip().splitlines()
    assert lines[0] == "> Rate limit reached on feed hardware"
    assert lines[1] == "> History database locked"
    assert "## From followed subs" in rendered


def test_render_suggestions_at_bottom():
    item = _make_item(id="t3_1", section="repo")
    suggestions = [("singularity", 5), ("r/rust", 2)]
    rendered = render([item], suggestions=suggestions)

    assert "## Sub suggestions" in rendered
    assert "- r/singularity — opened 5 times since last run" in rendered
    assert "- r/rust — opened 2 times since last run" in rendered
    assert rendered.index("## Sub suggestions") > rendered.index("## From followed subs")


def test_render_empty_inputs():
    assert render([]) == ""
    assert render([], warnings=[], suggestions=[]) == ""


def test_render_read_marks_roundtrip():
    items = [
        _make_item(id="t3_r1", sub="LocalLLaMA", title="vLLM release", link="https://github.com/vllm", section="repo", source="followed"),
        _make_item(id="t3_r2", sub="FPGA", title="FPGA career", link=None, section="career", source="followed"),
        _make_item(id="t3_r3", sub="singularity", title="AGI discussion", link=None, section="knowledge", source="viewed"),
    ]
    rendered = render(items, day=datetime.date(2026, 11, 8))
    marks = read_marks(rendered)

    assert len(marks) == 3
    assert [m.id for m in marks] == ["t3_r1", "t3_r2", "t3_r3"]
    assert [m.decision for m in marks] == ["neutral", "neutral", "neutral"]
    assert marks[0].sub == "LocalLLaMA"
    assert marks[0].section == "repo"
    assert marks[0].title == "vLLM release"
    assert marks[0].url == items[0].url

    assert marks[1].sub == "FPGA"
    assert marks[1].section == "career"
    assert marks[1].title == "FPGA career"

    assert marks[2].sub == "singularity"
    assert marks[2].section == "knowledge"
    assert marks[2].title == "AGI discussion"


def test_read_marks_decisions():
    text = """
- [x] **Post One** — Summary — [post](https://reddit.com/1) `r/sub1` <!-- id:t3_1 section:repo -->
- [X] **Post Two** — Summary — [post](https://reddit.com/2) `r/sub2` <!-- id:t3_2 section:showcase -->
- [-] **Post Three** — Summary — [post](https://reddit.com/3) `r/sub3` <!-- id:t3_3 section:career -->
- [ ] **Post Four** — Summary — [post](https://reddit.com/4) `r/sub4` <!-- id:t3_4 section:other -->
"""
    marks = read_marks(text)
    assert len(marks) == 4
    assert marks[0].decision == "keep"
    assert marks[1].decision == "keep"
    assert marks[2].decision == "reject"
    assert marks[3].decision == "neutral"


def test_read_marks_extra_spaces_and_formatting():
    text = """
-   [x]   **Spaced Keep** — Summary — [post](https://reddit.com/1) `r/sub1` <!-- id:t3_sp1 section:repo -->
- [ X ] **Inner Spaced Keep** — Summary — [post](https://reddit.com/2) `r/sub2` <!-- id:t3_sp2 section:repo -->
- [ - ] **Inner Spaced Reject** — Summary — [post](https://reddit.com/3) `r/sub3` <!-- id:t3_sp3 section:game -->
-[x] **No Space Before Box** — Summary — [post](https://reddit.com/4) `r/sub4` <!-- id:t3_sp4 section:knowledge -->
- [   ] **Lots of spaces inside neutral** — Summary — [post](https://reddit.com/5) `r/sub5` <!-- id:t3_sp5 section:other -->
"""
    marks = read_marks(text)
    assert len(marks) == 5
    assert marks[0].decision == "keep"
    assert marks[1].decision == "keep"
    assert marks[2].decision == "reject"
    assert marks[3].decision == "keep"
    assert marks[4].decision == "neutral"


def test_read_marks_ignores_lines_without_id_tag():
    text = """
> Warning line
## From followed subs
### Repo / Tool
- [ ] Some bullet without id tag
## Sub suggestions
- r/singularity — opened 5 times since last run
<!-- general html comment without id -->
- [x] **Real Post** — Summary — [post](https://reddit.com/real) `r/real` <!-- id:t3_real section:repo -->
"""
    marks = read_marks(text)
    assert len(marks) == 1
    assert marks[0].id == "t3_real"


def test_read_marks_empty_or_whitespace():
    assert read_marks("") == []
    assert read_marks("   \n\n\t  ") == []


def test_read_marks_loose_editing():
    # User edited summary, deleted middle dot, changed sub backticks
    text = (
        "- [X] **Hand-edited Title** — [post](https://reddit.com/edited) "
        "r/LocalLLaMA <!-- id:t3_edit1 section:tools -->"
    )
    marks = read_marks(text)
    assert len(marks) == 1
    assert marks[0].id == "t3_edit1"
    assert marks[0].decision == "keep"
    assert marks[0].title == "Hand-edited Title"
    assert marks[0].url == "https://reddit.com/edited"


def test_render_section_aliases_mapped_correctly():
    item1 = _make_item(id="t3_al1", section="Repo / Tool", title="Alias Repo")
    item2 = _make_item(id="t3_al2", section="qa-tools", title="Alias QA")
    item3 = _make_item(id="t3_al3", section="unknown_stuff", title="Unknown Section")

    rendered = render([item1, item2, item3])
    assert "### Repo / Tool" in rendered
    assert "### Q&A about my tools" in rendered
    assert "### Other" in rendered


def test_render_collapses_newlines_in_title_and_summary():
    item = _make_item(
        id="t3_nl",
        title="Title\nWith\nNewlines",
        summary="Summary\nWith\nNewlines",
        section="repo",
    )
    rendered = render([item])
    # Should be on a single line
    line = [l for l in rendered.splitlines() if "t3_nl" in l][0]
    assert "Title With Newlines" in line
    assert "Summary With Newlines" in line
    assert "\n" not in line


def test_render_reexports_mark_and_read_marks():
    from digest.render import Mark as RenderMark, read_marks as render_read_marks
    assert RenderMark is Mark
    assert render_read_marks is read_marks


def test_render_and_read_marks_summary_with_bold_and_dash():
    item = _make_item(
        id="t3_bld1",
        title="Title With Bold Summary",
        summary="Summary with **bold note** — extra information",
        section="repo",
    )
    rendered = render([item])
    marks = read_marks(rendered)
    assert len(marks) == 1
    assert marks[0].id == "t3_bld1"
    assert marks[0].title == "Title With Bold Summary"


def test_read_marks_multiple_comments_on_line():
    line = "<!-- pinned --> - [x] **My Tool** — Summary — [post](https://reddit.com/tool) `r/LocalLLaMA` <!-- id:t3_multi_c section:repo -->"
    marks = read_marks(line)
    assert len(marks) == 1
    assert marks[0].id == "t3_multi_c"
    assert marks[0].decision == "keep"
    assert marks[0].title == "My Tool"


def test_read_marks_title_with_brackets_not_misidentified_as_decision():
    # When task checkbox is omitted, brackets in title should not be mistaken for decision
    line = "- **[X] New Game Release** — Summary — [post](https://reddit.com/game) `r/game` <!-- id:t3_brk1 section:game -->"
    marks = read_marks(line)
    assert len(marks) == 1
    assert marks[0].decision == "neutral"


def test_render_slash_r_sub_normalization():
    item = _make_item(id="t3_sub1", sub="/r/LocalLLaMA", section="repo")
    suggestions = [("/r/singularity", 7), ("r/rust", 3)]
    rendered = render([item], suggestions=suggestions)

    assert "`r/LocalLLaMA`" in rendered
    assert "`r//r/LocalLLaMA`" not in rendered
    assert "- r/singularity — opened 7 times since last run" in rendered
    assert "- r//r/singularity" not in rendered


def test_render_empty_summary_omits_double_dash():
    item = _make_item(id="t3_nosum", title="Title Only", summary="", section="repo")
    rendered = render([item])
    assert "—  —" not in rendered
    assert "- [ ] **Title Only** — [post](" in rendered


def test_render_multiline_and_prequoted_warnings():
    warnings = ["> Already quoted", "Multi-line\nwarning message"]
    rendered = render(warnings=warnings)
    assert "> Already quoted" in rendered
    assert "> > Already quoted" not in rendered
    assert "> Multi-line\n> warning message" in rendered


def test_read_marks_sub_fallback_from_url_and_unquoted_backticks():
    # User edited sub to unquoted or removed r/, or removed sub entirely from line
    line1 = "- [x] **Post 1** — S — [post](https://reddit.com/1) `FPGA` <!-- id:t3_f1 section:repo -->"
    line2 = "- [x] **Post 2** — S — [post](https://reddit.com/r/LocalLLaMA/comments/2) <!-- id:t3_f2 section:repo -->"
    marks = read_marks(f"{line1}\n{line2}")
    assert len(marks) == 2
    assert marks[0].sub == "FPGA"
    assert marks[1].sub == "LocalLLaMA"


def test_read_marks_accepts_pathlib_path(tmp_path):
    p = tmp_path / "digest.md"
    p.write_text("- [x] **P** — S — [post](u) `r/sub` <!-- id:t3_path1 section:repo -->\n", encoding="utf-8")
    marks = read_marks(p)
    assert len(marks) == 1
    assert marks[0].id == "t3_path1"


def test_render_sorts_by_score_and_tags():
    it7 = _make_item(id="t3_7", section="repo", score=7)
    it9 = _make_item(id="t3_9", section="repo", score=9)
    it_none = _make_item(id="t3_none", section="repo", score=None)
    # Even if TOP_MIN_SCORE would catch 9, let's test within a section without Top ideas:
    # (or when monkeypatching TOP_MIN_SCORE=11 so none goes to Top ideas)
    from digest import config
    rendered = render([it7, it_none, it9])
    # 9 renders first, then 7, then none
    pos9 = rendered.find("id:t3_9")
    pos7 = rendered.find("id:t3_7")
    pos_none = rendered.find("id:t3_none")
    assert pos9 != -1 and pos7 != -1 and pos_none != -1
    assert pos9 < pos7 < pos_none
    assert "score:9" in rendered
    assert "score:7" in rendered
    assert "score:" not in rendered.split("id:t3_none")[1].split("-->")[0]
    marks = read_marks(rendered)
    mark_ids = [m.id for m in marks]
    assert "t3_9" in mark_ids
    assert "t3_7" in mark_ids
    assert "t3_none" in mark_ids


def test_render_top_ideas_block_first(monkeypatch):
    from digest import config
    it10 = _make_item(id="t3_10", score=10, section="repo")
    it9 = _make_item(id="t3_9", score=9, section="knowledge")
    it8 = _make_item(id="t3_8", score=8, section="repo")
    rendered = render([it10, it9, it8])

    assert "## Top ideas" in rendered
    assert rendered.find("## Top ideas") < rendered.find("## From followed subs")
    # 10 and 9 in Top ideas
    top_block = rendered.split("## From followed subs")[0]
    sec_block = rendered.split("## From followed subs")[1]
    assert "id:t3_10" in top_block
    assert "id:t3_9" in top_block
    assert "id:t3_8" not in top_block
    assert "id:t3_10" not in sec_block
    assert "id:t3_9" not in sec_block
    assert "id:t3_8" in sec_block

    # TOP_N monkeypatched to 1 -> only 10 in Top ideas, 9 returns to its section
    monkeypatch.setattr(config, "TOP_N", 1)
    rendered2 = render([it10, it9, it8])
    top_block2 = rendered2.split("## From followed subs")[0]
    sec_block2 = rendered2.split("## From followed subs")[1]
    assert "id:t3_10" in top_block2
    assert "id:t3_9" not in top_block2
    assert "id:t3_9" in sec_block2


def test_render_no_top_block_without_high_scores():
    it8 = _make_item(id="t3_8", score=8)
    it_none = _make_item(id="t3_none", score=None)
    rendered = render([it8, it_none])
    assert "## Top ideas" not in rendered


def test_top_item_marks_still_read_once():
    it10 = _make_item(id="t3_top", score=10)
    rendered = render([it10])
    marked = rendered.replace("- [ ] **Sample Title**", "- [-] **Sample Title**")
    marks = read_marks(marked)
    top_marks = [m for m in marks if m.id == "t3_top"]
    assert len(top_marks) == 1
    assert top_marks[0].decision == "reject"


def test_render_no_top_block_when_top_n_zero_or_negative(monkeypatch):
    from digest import config
    it10 = _make_item(id="t3_top10", score=10, section="repo")
    
    monkeypatch.setattr(config, "TOP_N", 0)
    rendered_zero = render([it10])
    assert "## Top ideas" not in rendered_zero
    assert "id:t3_top10" in rendered_zero
    assert "### Repo / Tool" in rendered_zero

    monkeypatch.setattr(config, "TOP_N", -1)
    rendered_neg = render([it10])
    assert "## Top ideas" not in rendered_neg
    assert "id:t3_top10" in rendered_neg



