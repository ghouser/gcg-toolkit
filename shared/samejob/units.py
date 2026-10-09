"""Unit rules: Link-ness and critical keywords are gates, the AP/HP band is a limit, and a lost good-to-have needs one back.

For a Unit the ability is a bonus ("we want *an* ability, not necessarily the same one"), so any gained good-to-have pays for any lost one.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.samejob.result import Match, Standing, Verdict
from shared.samejob.vocabulary import STAT_SLACK
from tools.gundam_cards.models import UnitCard

if TYPE_CHECKING:
    from shared.samejob.matcher import Matcher


def stands_in(m: Matcher, x: UnitCard, y: UnitCard) -> Match:
    ok, why = m.link_gate(x, y)
    if not ok:
        return Match(Verdict.DIFFERENT, (why,))
    linked = x.link is not None
    px, py = m.profile(x), m.profile(y)
    lost_critical = px.critical - py.critical
    if lost_critical:
        return Match(Verdict.DIFFERENT, (f"lacks {', '.join(sorted(lost_critical))}",))
    informative = linked or bool((px.good & py.good) or (px.critical & py.critical))
    reasons: list[str] = []
    if py.ap < px.ap - STAT_SLACK or py.hp < px.hp - STAT_SLACK:
        reasons.append(f"stats {py.ap}/{py.hp} too far below {px.ap}/{px.hp}")
    lost = px.good - py.good
    gained = (py.good | py.critical) - (px.good | px.critical)
    if lost and len(gained) < len(lost):
        reasons.append(f"gives up {', '.join(sorted(lost))} without getting enough back")
    if reasons:
        return Match(Verdict.CLOSE, tuple(reasons), None, informative)
    better_stats = py.ap >= px.ap and py.hp >= px.hp
    superset = px.good <= py.good and px.critical <= py.critical
    same = (py.ap, py.hp, py.good, py.critical) == (px.ap, px.hp, px.good, px.critical)
    standing = Standing.EQUAL if same else Standing.BETTER if better_stats and superset else Standing.TRADE_OFF
    return Match(Verdict.SAME_JOB, (), standing, informative)
