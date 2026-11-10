from collections.abc import Sequence

from digest.classify import Item
from digest.config import MAX_PER_SUB, MIN_SCORE


def select(
    items: Sequence[Item],
    min_score: int = MIN_SCORE,
    max_per_sub: int = MAX_PER_SUB,
) -> tuple[list[Item], list[Item]]:
    shown_indices: set[int] = set()
    hidden_indices: set[int] = set()

    # Per (source, sub.lower()) grouping for candidates
    # A candidate is a non-drop item with score is not None and score >= min_score
    groups: dict[tuple[str, str], list[tuple[int, Item]]] = {}

    cap = max(0, max_per_sub)

    for idx, it in enumerate(items):
        sec = str(it.section or "").strip().lower()
        if sec == "drop":
            continue
        if it.score is None:
            shown_indices.add(idx)
            continue
        if it.score < min_score:
            hidden_indices.add(idx)
            continue

        # Candidate
        sub_key = str(it.sub or "").strip().lstrip("/").removeprefix("r/").strip().lower()
        source_key = str(it.source or "").strip().lower()
        group_key = (source_key, sub_key)
        groups.setdefault(group_key, []).append((idx, it))

    for group_items in groups.values():
        # Sort by score descending; ties by input order (idx ascending)
        sorted_candidates = sorted(group_items, key=lambda pair: (-pair[1].score, pair[0]))
        kept = sorted_candidates[:cap]
        cut = sorted_candidates[cap:]

        for idx, _ in kept:
            shown_indices.add(idx)
        for idx, _ in cut:
            hidden_indices.add(idx)

    shown = [items[i] for i in range(len(items)) if i in shown_indices]
    hidden = [items[i] for i in range(len(items)) if i in hidden_indices]
    return shown, hidden
