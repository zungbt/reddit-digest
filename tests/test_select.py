import pytest
from digest.classify import Item
from digest.select import select


def _make_item(id: str, sub: str = "LocalLLaMA", score: int | None = None, source: str = "followed", section: str = "repo") -> Item:
    return Item(
        id=id,
        sub=sub,
        title=f"Title {id}",
        url=f"https://reddit.com/r/{sub}/comments/{id}",
        link=None,
        section=section,
        summary=f"Summary {id}",
        source=source,
        score=score,
    )


def test_select_hides_below_min_score():
    items = [
        _make_item("t3_1", score=9),
        _make_item("t3_2", score=7),
        _make_item("t3_3", score=6),
        _make_item("t3_4", score=0),
    ]
    shown, hidden = select(items, min_score=7)
    assert [it.id for it in shown] == ["t3_1", "t3_2"]
    assert [it.id for it in hidden] == ["t3_3", "t3_4"]


def test_select_keeps_none_score():
    item = _make_item("t3_none", score=None)
    shown, hidden = select([item], min_score=10, max_per_sub=0)
    assert [it.id for it in shown] == ["t3_none"]
    assert hidden == []


def test_select_caps_per_sub_by_score():
    # 20 items same sub, scores 7..10 cycling, max_per_sub=15
    # -> 15 shown, all with score >= the lowest shown, 5 hidden; cap is separate per source.
    scores = [7, 8, 9, 10] * 5  # 20 items
    items = [_make_item(f"t3_f_{i}", sub="LocalLLaMA", score=scores[i], source="followed") for i in range(20)]
    # Also 2 items from viewed in same sub to test separation
    items.extend([
        _make_item("t3_v_1", sub="LocalLLaMA", score=8, source="viewed"),
        _make_item("t3_v_2", sub="LocalLLaMA", score=9, source="viewed"),
    ])

    shown, hidden = select(items, min_score=7, max_per_sub=15)
    followed_shown = [it for it in shown if it.source == "followed"]
    followed_hidden = [it for it in hidden if it.source == "followed"]
    viewed_shown = [it for it in shown if it.source == "viewed"]

    assert len(followed_shown) == 15
    assert len(followed_hidden) == 5
    assert len(viewed_shown) == 2

    min_shown_score = min(it.score for it in followed_shown)
    for it in followed_hidden:
        assert it.score <= min_shown_score

    # Input order preserved in shown
    shown_indices = [int(it.id.split("_")[2]) for it in followed_shown]
    assert shown_indices == sorted(shown_indices)


def test_select_empty_and_small_inputs():
    assert select([]) == ([], [])
    items = [_make_item(f"t3_{i}", sub="embedded", score=8) for i in range(3)]
    shown, hidden = select(items, max_per_sub=15)
    assert shown == items
    assert hidden == []


def test_select_omits_drop_items():
    items = [
        _make_item("t3_1", section="drop", score=9),
        _make_item("t3_2", section="DROP", score=10),
        _make_item("t3_3", section="repo", score=8),
    ]
    shown, hidden = select(items)
    assert [it.id for it in shown] == ["t3_3"]
    assert hidden == []


def test_select_negative_max_per_sub():
    items = [
        _make_item("t3_1", score=9),
        _make_item("t3_none", score=None),
    ]
    shown, hidden = select(items, max_per_sub=-1)
    assert [it.id for it in shown] == ["t3_none"]
    assert [it.id for it in hidden] == ["t3_1"]


def test_select_normalizes_sub_with_prefix():
    items = [
        _make_item("t3_1", sub="LocalLLaMA", score=9),
        _make_item("t3_2", sub="r/LocalLLaMA", score=8),
        _make_item("t3_3", sub="/r/LocalLLaMA", score=7),
    ]
    shown, hidden = select(items, max_per_sub=2)
    assert [it.id for it in shown] == ["t3_1", "t3_2"]
    assert [it.id for it in hidden] == ["t3_3"]


def test_select_ties_broken_by_input_order():
    items = [
        _make_item("t3_first", score=8),
        _make_item("t3_second", score=8),
        _make_item("t3_third", score=8),
    ]
    shown, hidden = select(items, max_per_sub=2)
    assert [it.id for it in shown] == ["t3_first", "t3_second"]
    assert [it.id for it in hidden] == ["t3_third"]
