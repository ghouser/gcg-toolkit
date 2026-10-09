"""Base rules: like Commands, matched on effect only (a Base that lets me draw is replaced by another that lets me draw).

HP, the size of the effect's number, and cost are ignored (decided 2026-10-08). Y shares a core effect with X (scope included) and a net
loss of one good-to-have (X's other core effects) is fine. The baseline every Base has is not an effect.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.samejob.result import Match, Standing, Verdict
from shared.samejob.vocabulary import LOSS_ALLOWED
from tools.gundam_cards.models import BaseCard

if TYPE_CHECKING:
    from shared.samejob.matcher import Matcher


def stands_in(m: Matcher, x: BaseCard, y: BaseCard) -> Match:
    px, py = m.profile(x), m.profile(y)
    if not px.core or not py.core:
        return Match(Verdict.DIFFERENT, ("no recognised effect",))
    if not px.core & py.core:
        return Match(Verdict.DIFFERENT, ("a different effect",))
    lost, gained = px.good - py.good, py.good - px.good
    if len(lost) - len(gained) > LOSS_ALLOWED:
        return Match(Verdict.CLOSE, (f"loses {', '.join(sorted(lost))}",), None, True)
    standing = Standing.EQUAL if px.good == py.good else Standing.BETTER if px.good <= py.good else Standing.TRADE_OFF
    return Match(Verdict.SAME_JOB, (), standing, True)
