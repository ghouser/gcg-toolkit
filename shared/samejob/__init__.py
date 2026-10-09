"""Same job: can card Y stand in for card X in a deck, *almost as well or better*? (design: tools/gundam_packages/design.md, "Same job".)

The one body of code for that question. Pure functions over card models; no I/O. Public entry points:

    from shared.samejob import Matcher, pilots_from, link_traits_of, Verdict, Standing
    matcher = Matcher(pilots_from(cards), unit_links, link_traits_of(cards))
    result = matcher.stands_in(x, y)        # Match(verdict, reasons, standing, informative); directional

The rules live one module per kind of card: `units`, `commands`, `pilots`, `bases`, on a shared `vocabulary`. Color is never part of the
match (a deck decides which colors it can use).
"""
from __future__ import annotations

from shared.samejob.matcher import Matcher, link_traits_of, pilots_from, profile, stands_in
from shared.samejob.result import Match, Pilot, Profile, Standing, Verdict
from shared.samejob.vocabulary import effect_features, native_keywords

__all__ = [
    "Match",
    "Matcher",
    "Pilot",
    "Profile",
    "Standing",
    "Verdict",
    "effect_features",
    "link_traits_of",
    "native_keywords",
    "pilots_from",
    "profile",
    "stands_in",
]
