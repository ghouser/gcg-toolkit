"""Command rules: the effect is the card, so it must match; the looseness goes into the good-to-haves.

Y shares a core effect with X (scope included), its main number is at most 1 lower, its cost at most 1 higher; Burst, a pilot pairing,
Action timing and X's other core effects are good-to-haves and a net loss of one is fine.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.basetypes import PilotName
from shared.samejob.result import Match, Standing, Verdict
from shared.samejob.vocabulary import COST_SLACK, LOSS_ALLOWED, SIZE_SLACK
from tools.gundam_cards.models import CommandCard, names_of, traits_of

if TYPE_CHECKING:
    from shared.samejob.matcher import Matcher


def pilot_kept(m: Matcher, x: CommandCard, y: CommandCard) -> bool:
    """Whether y's pilot pairing does what x's does: it serves a Link in the deck that x's pilot serves (or x's serves none)."""
    mine = [link for link in m.unit_links if link.satisfied_by_any(tuple(PilotName(n) for n in names_of(x)), frozenset(traits_of(x)))]
    if not mine:
        return True
    names, traits = tuple(PilotName(n) for n in names_of(y)), frozenset(traits_of(y))
    return any(link.satisfied_by_any(names, traits) for link in mine)


def stands_in(m: Matcher, x: CommandCard, y: CommandCard) -> Match:
    px, py = m.profile(x), m.profile(y)
    if not px.core or not py.core:
        return Match(Verdict.DIFFERENT, ("no recognised effect",))
    shared = px.core & py.core
    if not shared:
        return Match(Verdict.DIFFERENT, ("a different effect",))
    reasons: list[str] = []
    if py.cost > px.cost + COST_SLACK:
        reasons.append(f"cost {py.cost} is too far above {px.cost}")
    for name in sorted(shared):
        if name in px.sizes and name in py.sizes and py.sizes[name] < px.sizes[name] - SIZE_SLACK:
            reasons.append(f"{name} {py.sizes[name]} is too far below {px.sizes[name]}")
    have = set(py.good)
    if "pilot" in px.good and "pilot" in have and not pilot_kept(m, x, y):
        have.discard("pilot")  # a pilot pairing for another pilot is not the same bonus
    lost, gained = px.good - have, have - px.good
    if len(lost) - len(gained) > LOSS_ALLOWED:
        reasons.append(f"loses {', '.join(sorted(lost))}")
    if reasons:
        return Match(Verdict.CLOSE, tuple(reasons), None, True)
    bigger = all(py.sizes.get(n, 0) >= px.sizes.get(n, 0) for n in px.sizes)
    equal = have == px.good and py.sizes == px.sizes and py.cost == px.cost
    standing = Standing.EQUAL if equal else Standing.BETTER if px.good <= have and bigger and py.cost <= px.cost else Standing.TRADE_OFF
    return Match(Verdict.SAME_JOB, (), standing, True)
