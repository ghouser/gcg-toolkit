"""What a same-job check returns, and the small value types it works with."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from shared.basetypes import PilotName, Trait


class Verdict(StrEnum):
    SAME_JOB = "same job"
    CLOSE = "close"
    DIFFERENT = "different"


class Standing(StrEnum):
    BETTER = "better"
    EQUAL = "equal"
    TRADE_OFF = "trade-off"


@dataclass(frozen=True)
class Match:
    verdict: Verdict
    reasons: tuple[str, ...]
    standing: Standing | None = None  # only for SAME_JOB
    informative: bool = False  # the pair shares something real (a Link, a keyword or an effect), not just a stat line


@dataclass(frozen=True)
class Pilot:
    """A pilot a deck can pair: every name it answers to, and its traits."""

    names: tuple[PilotName, ...]
    traits: frozenset[Trait]


@dataclass(frozen=True)
class Profile:
    critical: frozenset[str]
    good: frozenset[str]  # Units: good-to-have keywords and effect features. Commands: burst / pilot / action and the core effects. Bases: the effects.
    core: frozenset[str] = frozenset()  # Commands and Bases: the effects of the card's own text
    sizes: dict[str, int] = field(default_factory=dict)  # Commands: the main number of each sized core effect
    ap: int = 0
    hp: int = 0
    cost: int = 0
