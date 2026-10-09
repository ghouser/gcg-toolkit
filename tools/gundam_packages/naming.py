"""Package names: the pilot and the unit it is built around (`Kira Strike Freedom`, `Mikazuki Barbatos`).

The pair is the strongest Link tie among the package's members. The name is the pilot's given name plus the unit's core name
(its name without "Gundam", parentheses and form suffixes shared across its variants). When the two share a word
(Master Asia / Master Gundam, Char Aznable / Char's Zaku II) the pilot's full name is used instead, so it never reads "Master
Master". `names.json` can override any name by package id (nicknames). Duplicate names get the package's colors appended.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel
from tools.gundam_packages.models import PackageId, PackageMember, SynergyEdge, SynergyKind
from tools.gundam_packages.synergy import pilot_identity

NAMES_PATH = Path(__file__).parent / "names.json"
_FILLER_WORDS = {"gundam"}


def _words(text: str) -> list[str]:
    text = re.sub(r"\([^)]*\)", " ", text)  # drop "(Unicorn Mode)"
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _stem(word: str) -> str:
    return re.sub(r"['’]s$", "", word).casefold()  # Char's -> char


def unit_core(unit_names: Sequence[str]) -> list[str]:
    """The words shared at the start of every unit name, without "Gundam" (Barbatos 1st Form + Barbatos Adapt -> Barbatos)."""
    cores = [[w for w in _words(n) if w.casefold() not in _FILLER_WORDS] for n in unit_names]
    cores = [c for c in cores if c]
    if not cores:
        return []
    shared: list[str] = []
    for words in zip(*cores, strict=False):
        if len({w.casefold() for w in words}) != 1:
            break
        shared.append(words[0])
    return shared or cores[0]


def pilot_unit_name(pilot_name: str, unit_names: Sequence[str]) -> str | None:
    """`Kira Yamato` + `Strike Freedom Gundam` -> `Kira Strike Freedom`; shared word -> the pilot's full name."""
    pilot_words = _words(pilot_name)
    core = unit_core(unit_names)
    if not pilot_words:
        return None
    if not core or {_stem(w) for w in pilot_words} & {_stem(w) for w in core}:
        return " ".join(pilot_words)
    return f"{pilot_words[0]} {' '.join(core)}"


class PackageNamer:
    """Callable used by discovery. Stateful only to keep names unique within one build."""

    def __init__(self, cards: Mapping[CardNumber, CardModel], overrides: Mapping[PackageId, str] | None = None) -> None:
        self._cards = cards
        self._overrides = overrides or {}
        self._used: set[str] = set()

    def __call__(self, pid: PackageId, members: Sequence[PackageMember], edges: Sequence[SynergyEdge]) -> str:
        name = self._overrides.get(pid) or self._derive(members, edges) or self._cards[members[0].card_number].name
        return self._unique(name, pid, members)

    def _derive(self, members: Sequence[PackageMember], edges: Sequence[SynergyEdge]) -> str | None:
        decks = {m.card_number: m.decks for m in members}
        links = [e for e in edges if e.kind is SynergyKind.LINK_PILOT]
        if not links:
            # No pilot at the center (e.g. a trait package like Tekkadan): name it after what its members' ties share most.
            # ("same job" ties say nothing about what the package is about, so they never name it.)
            details = Counter(e.detail for e in edges if not e.detail.startswith("same job"))
            return details.most_common(1)[0][0] if details else None
        # Best pilot: the one tied to the most-played units; then its units give the unit name.
        by_pilot: dict[CardNumber, list[CardNumber]] = {}
        for e in links:
            by_pilot.setdefault(e.b, []).append(e.a)
        pilot = max(by_pilot, key=lambda p: (decks.get(p, 0) + sum(decks.get(u, 0) for u in by_pilot[p]), p))
        identity = pilot_identity(self._cards[pilot])
        if identity is None:
            return None
        unit_names = [self._cards[u].name for u in sorted(by_pilot[pilot], key=lambda u: (-decks.get(u, 0), u))]
        return pilot_unit_name(str(identity[0]), unit_names)

    def _unique(self, name: str, pid: PackageId, members: Sequence[PackageMember]) -> str:
        if name in self._used:
            colors = sorted({c.value for m in members if (c := getattr(self._cards[m.card_number], "color", None)) is not None})
            name = f"{name} ({'/'.join(colors)})" if colors else name
        if name in self._used:
            name = f"{name} [{pid}]"
        self._used.add(name)
        return name
