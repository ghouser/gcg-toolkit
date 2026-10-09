"""Linking my collection to the card data, the prices and the associations (see tools/gundam_collection/design.md).

Everything joins on the card number. Pure functions over already-loaded data (no files, no network):

- a **slot** is a place in a package that needs some copies of one card. A card number is a card, and same-job cards are **redundant,
  not substitutes** (alternatives.py): each required card is its own slot; a stand-in counts only toward an *optional* member that real decks
  play less often, and every other same-job card is a *similar* suggestion that is not counted.
- copies **needed** for a card is the majority copy count: the most copies at least half of the package's decks run.
- a package's **critical** copies are its core members' (goal 1); optional members are layer 3.
- the **cost to complete** prices each missing copy at the cheapest printing of the slot's card (goal 2: the cheapest acceptable one).
- a package is **home** when I own at least `HOME_MIN_OWNED` of its critical copies, **adjacent** when it shares a critical card
  or bridge with a home package, and **new** otherwise.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel
from tools.gundam_collection.models import Stage
from tools.gundam_collection.alternatives import slot_alternatives
from tools.gundam_collection.bands import THRESHOLDS, Band, Need, NextBand, ahead, band_of, next_band
from tools.gundam_packages.models import PackageId, PackageRates, RatesFile, Squad, Role

HOME_MIN_OWNED = THRESHOLDS[Band.REACHABLE]  # home = Reachable or better


@dataclass(frozen=True)
class Slot:
    members: tuple[CardNumber, ...]  # the required card of this slot (always one)
    alternates: tuple[CardNumber, ...]  # same-job stand-ins that count toward it (optional members only)
    similar: tuple[CardNumber, ...]  # other same-job peers: suggestions, not counted
    critical_need: int  # copies the core member needs
    optional_need: int  # copies the optional member needs
    owned: int  # copies I own across the member and the counted alternates (any printing)
    option: CardNumber | None  # the cheapest of them to buy
    unit_cents: int | None  # its price

    @property
    def critical_have(self) -> int:
        return min(self.owned, self.critical_need)

    @property
    def optional_have(self) -> int:
        return min(max(self.owned - self.critical_need, 0), self.optional_need)

    @property
    def critical_missing(self) -> int:
        return self.critical_need - self.critical_have

    @property
    def optional_missing(self) -> int:
        return self.optional_need - self.optional_have


@dataclass(frozen=True)
class PackageCoverage:
    package: PackageId
    name: str
    slots: tuple[Slot, ...]

    @property
    def critical_need(self) -> int:
        return sum(s.critical_need for s in self.slots)

    @property
    def critical_have(self) -> int:
        return sum(s.critical_have for s in self.slots)

    @property
    def share(self) -> float:
        """Share of the critical copies I own (1.0 for a package with no critical copies)."""
        return self.critical_have / self.critical_need if self.critical_need else 1.0

    @property
    def needs(self) -> tuple[Need, ...]:
        """One row per critical card (all key cards) for the completeness band."""
        return tuple(Need(s.members[0], s.critical_need, s.critical_have, s.unit_cents, True) for s in self.slots if s.critical_need)

    @property
    def band(self) -> Band:
        return band_of(self.needs)

    @property
    def next_band(self) -> NextBand | None:
        """The cheapest purchases that reach the next band up (None when Perfect)."""
        return next_band(self.needs)

    @property
    def ahead(self) -> tuple[NextBand, ...]:
        """Cost to the next band (and the one after, for Reachable and Playable)."""
        return ahead(self.needs)

    @property
    def cost_cents(self) -> int:
        """The price of the missing critical copies that have a price."""
        return sum(s.critical_missing * s.unit_cents for s in self.slots if s.unit_cents is not None)

    @property
    def unpriced_missing(self) -> int:
        """Missing critical copies with no price (so the cost above is a minimum)."""
        return sum(s.critical_missing for s in self.slots if s.unit_cents is None)


def package_coverage(
    package: PackageRates,
    groups: Sequence[Squad],
    owned: Mapping[CardNumber, int],
    prices: Mapping[CardNumber, int],
    catalog: Mapping[CardNumber, CardModel],
) -> PackageCoverage:
    """How much of a package's cards I have, slot by slot."""
    by_number = {m.card_number: m for m in package.members}
    alternatives = slot_alternatives(list(by_number), frozenset(n for n, m in by_number.items() if m.role is Role.OPTIONAL), groups, catalog)
    slots: list[Slot] = []
    for n, member in by_number.items():
        found = alternatives[n]
        counted = (n, *found.counted)
        priced = sorted((prices[c], c) for c in counted if c in prices)
        slots.append(
            Slot(
                members=(n,),
                alternates=found.counted,
                similar=found.similar,
                critical_need=member.majority_copies if member.role is Role.CORE else 0,
                optional_need=member.majority_copies if member.role is Role.OPTIONAL else 0,
                owned=sum(owned.get(c, 0) for c in counted),
                option=priced[0][1] if priced else None,
                unit_cents=priced[0][0] if priced else None,
            )
        )
    return PackageCoverage(package.package, package.name, tuple(sorted(slots, key=lambda s: s.members)))


def critical_cards(package: PackageRates) -> frozenset[CardNumber]:
    """The cards a package cannot do without: its core members and the bridges to the packages it is played with."""
    core = {m.card_number for m in package.members if m.role is Role.CORE}
    bridges = {b.card_number for w in package.partners if w.synergistic for b in w.bridges}
    return frozenset(core | bridges)


def classify(coverages: Mapping[PackageId, PackageCoverage], rates: RatesFile) -> dict[PackageId, Stage]:
    """Home, adjacent or new for every package."""
    home = {pid for pid, c in coverages.items() if c.critical_need and c.share >= HOME_MIN_OWNED}
    by_id = {p.package: p for p in rates.packages}
    home_cards = frozenset(card for pid in home for card in critical_cards(by_id[pid]))
    stages: dict[PackageId, Stage] = {}
    for pid in coverages:
        if pid in home:
            stages[pid] = Stage.HOME
        elif critical_cards(by_id[pid]) & home_cards:
            stages[pid] = Stage.ADJACENT
        else:
            stages[pid] = Stage.NEW
    return stages


@dataclass(frozen=True)
class Associated:
    """A card associated with another through a package, with what I need to know to act on it."""

    card: CardNumber
    why: str  # "its package", "with <package>", "bridge to <package>", "synergy", "free floating", "other"
    rate: float  # how often it is played alongside, from the perspective package
    needed: int | None  # majority copy count where known (package members and partners' cards)
    owned: int
    price_cents: int | None


def associated_cards(
    package: PackageRates,
    names: Mapping[PackageId, str],
    owned: Mapping[CardNumber, int],
    prices: Mapping[CardNumber, int],
    *,
    limit: int,
    skip: CardNumber | None = None,
) -> tuple[Associated, ...]:
    """Every card played with a package, from its perspective: its own cards, each linked package's cards and bridges, then stand-alone cards."""
    rows: list[Associated] = []

    def add(card: CardNumber, why: str, rate: float, needed: int | None) -> None:
        if card != skip:
            rows.append(Associated(card, why, rate, needed, owned.get(card, 0), prices.get(card)))

    for m in package.members:
        add(m.card_number, f"its package ({m.role.value})", m.rate, m.majority_copies)
    for w in [w for w in package.partners if w.combined_rate >= 0.05][:6]:
        for c in sorted(w.cards, key=lambda c: -c.rate_from_x)[:limit]:
            add(c.card_number, f"with {names[w.package]}", c.rate_from_x, c.majority_copies)
        for b in w.bridges:
            add(b.card_number, f"bridge to {names[w.package]}", b.rate_from_x, b.majority_copies)
    for role, label in (("synergy", "synergy"), ("free_floating", "free floating"), ("other", "other")):
        for o in [o for o in package.others if o.role.value == role][:limit]:
            add(o.card_number, label, o.rate, None)
    return tuple(rows)
