"""Matching groups of items across two sets by the items they share (used for packages found in tournament and in online decks)."""
from __future__ import annotations

from collections.abc import Hashable, Mapping

MIN_OVERLAP = 0.5  # two groups are the same group when at least this share of their combined items is shared (Jaccard)


def overlap[T: Hashable](a: frozenset[T], b: frozenset[T]) -> float:
    """Shared items over all items in either group (1.0 = identical)."""
    return len(a & b) / len(a | b) if a | b else 0.0


def match_groups[K: Hashable, L: Hashable, T: Hashable](
    left: Mapping[K, frozenset[T]], right: Mapping[L, frozenset[T]], minimum: float = MIN_OVERLAP
) -> tuple[tuple[tuple[K, L, float], ...], tuple[K, ...], tuple[L, ...]]:
    """Pair each group on the left with the one on the right it shares the most items with (best pairs first, each group once, at
    least `minimum`). Returns the pairs, the left keys with no match, and the right keys with no match. Ties break by key, so it is deterministic."""
    candidates = sorted(
        ((overlap(ml, mr), lk, rk) for lk, ml in left.items() for rk, mr in right.items() if overlap(ml, mr) >= minimum),
        key=lambda c: (-c[0], str(c[1]), str(c[2])),
    )
    used_left: set[K] = set()
    used_right: set[L] = set()
    pairs: list[tuple[K, L, float]] = []
    for score, lk, rk in candidates:
        if lk in used_left or rk in used_right:
            continue
        used_left.add(lk)
        used_right.add(rk)
        pairs.append((lk, rk, score))
    return tuple(pairs), tuple(k for k in left if k not in used_left), tuple(k for k in right if k not in used_right)
