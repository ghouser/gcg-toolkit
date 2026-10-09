"""Peer ties between cards for the synergy graph (and from them, squads): functional reprints in one color, same-job synergy across colors.

The matching is `shared/samejob` (Units, Commands, Pilots, Bases; see "Same job" in design.md). Two cards are **peers**, and tied, when:
- Units: either can stand in for the other *and* their AP and HP are each within 1 in both directions (a 5/4 with an ability is a peer of
  another big Unit with an ability, not of a 3/4 vanilla one);
- Commands and Bases: each can stand in for the other;
- Pilots (Pilot cards and Commands with a Pilot effect): either can stand in for the other (they serve the same Links).
Every tie must be informative (they share a Link, a keyword, an effect, or a pilot identity). With no deck to ask, the Link check uses every
pilot in the catalog. Same color: FUNCTIONAL_EFFECT (a functional reprint); another color: SIMILAR_ABILITY (a deck may use both, so it is
synergy to the package graph) - both say "same job" and both feed squads.

One more tie, kept from the earlier graph: Units with the same set of native role keywords (every Blocker, Breach...) are
**shared-keyword synergy** whatever their Link, color or stats. A Linked Blocker (Aile Strike) and a plain one (Gundam Lfrith) are not
peers, but decks run them together as a Blocker package.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations

from shared.samejob import Matcher, Verdict, link_traits_of, native_keywords, pilots_from
from shared.samejob.pilots import is_pilot
from shared.samejob.result import Match
from tools.gundam_cards.models import CardKind, CardModel, Keyword, UnitCard, color_of
from tools.gundam_packages.models import SynergyEdge, SynergyKind

ROLE_KEYWORDS = frozenset(
    {Keyword.BLOCKER, Keyword.BREACH, Keyword.REPAIR, Keyword.SUPPORT, Keyword.FIRST_STRIKE, Keyword.HIGH_MANEUVER, Keyword.SUPPRESSION}
)
PEER_STAT_SLACK = 1  # Units: AP and HP each within this of each other, both ways


def _kind_of(card: CardModel) -> str:
    return "pilot" if is_pilot(card) and card.kind is not CardKind.COMMAND else card.kind.value


def _same_job(m: Match) -> bool:
    return m.verdict is Verdict.SAME_JOB and m.informative


def functional_edges(cards: Sequence[CardModel]) -> list[SynergyEdge]:
    """Peer ties between cards that do the same job, and the shared-keyword synergy between Units."""
    matcher = Matcher(pilots_from(cards), (), link_traits_of(cards))
    groups: dict[str, list[CardModel]] = defaultdict(list)
    for card in cards:
        if card.kind in (CardKind.UNIT, CardKind.COMMAND, CardKind.BASE, CardKind.PILOT):
            groups[_kind_of(card)].append(card)
    roles = {c.number: native_keywords(c.text) & ROLE_KEYWORDS for c in cards if isinstance(c, UnitCard)}
    edges: list[SynergyEdge] = []
    for kind, group in groups.items():
        for a, b in combinations(group, 2):
            forward, backward = matcher.stands_in(a, b), matcher.stands_in(b, a)
            if kind == "unit":
                pa, pb = matcher.profile(a), matcher.profile(b)
                peers = (_same_job(forward) or _same_job(backward)) and abs(pa.ap - pb.ap) <= PEER_STAT_SLACK and abs(pa.hp - pb.hp) <= PEER_STAT_SLACK
            elif kind == "pilot":
                peers = _same_job(forward) or _same_job(backward)
            else:
                peers = _same_job(forward) and _same_job(backward)
            if peers:
                same_color = color_of(a) is not None and color_of(a) == color_of(b)
                edges.append(SynergyEdge(a=a.number, b=b.number, kind=SynergyKind.FUNCTIONAL_EFFECT if same_color else SynergyKind.SIMILAR_ABILITY,
                                         detail="same job" if same_color else "same job, other color"))  # fmt: skip
            elif isinstance(a, UnitCard) and isinstance(b, UnitCard) and roles[a.number] and roles[a.number] == roles[b.number]:
                edges.append(SynergyEdge(a=a.number, b=b.number, kind=SynergyKind.SHARED_KEYWORD, detail="/".join(sorted(k.value for k in roles[a.number]))))
    return edges
