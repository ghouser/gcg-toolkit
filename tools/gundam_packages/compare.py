"""Matching the packages found in two sets of decks (tournament and online) by the cards they share. The matching itself is in
`shared/overlap.py` (the collection tool needs it too)."""
from __future__ import annotations

from collections.abc import Mapping

from shared.basetypes import CardNumber
from shared.overlap import MIN_OVERLAP, match_groups, overlap
from tools.gundam_packages.models import PackageId

__all__ = ["MIN_OVERLAP", "match_packages", "overlap"]


def match_packages(
    left: Mapping[PackageId, frozenset[CardNumber]], right: Mapping[PackageId, frozenset[CardNumber]]
) -> tuple[tuple[tuple[PackageId, PackageId, float], ...], tuple[PackageId, ...], tuple[PackageId, ...]]:
    """Pair each package on the left with the one on the right it shares the most cards with (see `shared.overlap.match_groups`)."""
    return match_groups(left, right)
