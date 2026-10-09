"""Completeness bands: how much of a package or deck I own, and what it costs to reach the next band (design.md, "Completeness bands").

Pure functions over *needs*: one row per card with the copies it needs, the copies I own, its price, and whether it is a key (core) card.
A package is measured on its critical copies, a deck on its core + staple copies; both use the same ladder.

    Perfect 100% | Complete 90% | Playable 75% | Reachable 50% | Long shot 25% | Not happening

Playable and better also need the **key-card guard**: every key card is owned at least half its needed copies (2 of 4); otherwise the band
is capped at Reachable. The cost to the next band is the cheapest set of missing copies that reaches the next threshold: the copies the
guard forces first, then the cheapest remaining ones (a copy with no price is counted separately, so the cost is a minimum).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from shared.basetypes import CardNumber


class Band(StrEnum):
    PERFECT = "perfect"
    COMPLETE = "complete"
    PLAYABLE = "playable"
    REACHABLE = "reachable"
    LONG_SHOT = "long shot"
    NOT_HAPPENING = "not happening"


BANDS = (Band.PERFECT, Band.COMPLETE, Band.PLAYABLE, Band.REACHABLE, Band.LONG_SHOT, Band.NOT_HAPPENING)  # best first
THRESHOLDS: dict[Band, float] = {Band.PERFECT: 1.0, Band.COMPLETE: 0.90, Band.PLAYABLE: 0.75, Band.REACHABLE: 0.50, Band.LONG_SHOT: 0.25, Band.NOT_HAPPENING: 0.0}
GUARDED = (Band.PERFECT, Band.COMPLETE, Band.PLAYABLE)  # bands that need the key-card guard
KEY_SHARE = 0.5  # a key card needs at least this share of its copies (2 of 4)
EPSILON = 1e-9


@dataclass(frozen=True)
class Need:
    card: CardNumber
    need: int
    have: int
    unit_cents: int | None
    key: bool  # a core card: the guard applies


@dataclass(frozen=True)
class NextBand:
    band: Band  # the band these purchases reach
    copies: int
    cost_cents: int  # the priced copies
    unpriced: int  # copies with no price (so the cost is a minimum)
    buys: tuple[tuple[CardNumber, int], ...]  # card and copies, in the order to buy them


def key_minimum(need: int) -> int:
    """The copies of a key card that must be owned for Playable or better: half of what it needs, rounded up (2 of 4, 2 of 3, 1 of 2)."""
    return math.ceil(need * KEY_SHARE - EPSILON)


def share(needs: Sequence[Need]) -> float:
    total = sum(n.need for n in needs)
    return sum(min(n.have, n.need) for n in needs) / total if total else 1.0


def guard_ok(needs: Sequence[Need]) -> bool:
    return all(n.have >= key_minimum(n.need) for n in needs if n.key)


def band_of(needs: Sequence[Need]) -> Band:
    got = share(needs)
    for band in BANDS:
        if got + EPSILON >= THRESHOLDS[band]:
            if band in GUARDED and not guard_ok(needs) and got + EPSILON < 1.0:
                continue  # fails the guard: no better than Reachable
            return band
    return Band.NOT_HAPPENING


def _target_copies(total: int, band: Band) -> int:
    return total if band is Band.PERFECT else math.ceil(total * THRESHOLDS[band] - EPSILON)


def cost_to(needs: Sequence[Need], target: Band) -> NextBand:
    """The cheapest purchases that reach `target` from what I own now (the guard's copies first, then the cheapest missing copies)."""
    total = sum(n.need for n in needs)
    wanted = _target_copies(total, target)
    owned = {n.card: min(n.have, n.need) for n in needs}
    buys: dict[CardNumber, int] = {}
    if target in GUARDED:  # the guard's copies are forced first
        for n in needs:
            short = key_minimum(n.need) - owned[n.card] if n.key else 0
            if short > 0:
                buys[n.card] = short
                owned[n.card] += short
    have = sum(owned.values())
    if target is Band.PERFECT:
        for n in needs:
            if n.need > owned[n.card]:
                buys[n.card] = buys.get(n.card, 0) + n.need - owned[n.card]
    else:
        by_price = sorted((n for n in needs if n.need > owned[n.card]), key=lambda n: (n.unit_cents is None, n.unit_cents or 0, n.card))
        for n in by_price:
            if have >= wanted:
                break
            take = min(n.need - owned[n.card], wanted - have)
            buys[n.card] = buys.get(n.card, 0) + take
            have += take
    price = {n.card: n.unit_cents for n in needs}
    cost = sum(c * (price[card] or 0) for card, c in buys.items() if price[card] is not None)
    unpriced = sum(c for card, c in buys.items() if price[card] is None)
    ordered = tuple(sorted(buys.items(), key=lambda kv: (price[kv[0]] is None, price[kv[0]] or 0, kv[0])))
    return NextBand(target, sum(buys.values()), cost, unpriced, ordered)


def next_band(needs: Sequence[Need]) -> NextBand | None:
    """The cheapest purchases that reach the next band up (None when already Perfect)."""
    current = band_of(needs)
    return None if current is Band.PERFECT else cost_to(needs, BANDS[BANDS.index(current) - 1])


AHEAD = 2  # bands shown ahead for Reachable and Playable; every other band shows only the next one
_WIDE = (Band.REACHABLE, Band.PLAYABLE)


def ahead(needs: Sequence[Need]) -> tuple[NextBand, ...]:
    """The cost to the next band, and for a Reachable or Playable one also to the band after (each from what I own now, not stacked):
    Reachable -> playable, complete; Playable -> complete, perfect; every other band -> the next band only."""
    current = band_of(needs)
    if current is Band.PERFECT:
        return ()
    nearer = BANDS.index(current) - 1
    count = AHEAD if current in _WIDE else 1
    return tuple(cost_to(needs, BANDS[i]) for i in range(nearer, max(nearer - count, -1), -1))
