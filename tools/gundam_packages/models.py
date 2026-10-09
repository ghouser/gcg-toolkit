"""Typed models for packages, archetypes and drift. See tools/gundam_packages/design.md.

Vocabulary: a **package** is a group of cards of **one color** with real synergy that are also played together; **synergy**
cards have a structural tie to a package and are usually in its decks; **free floating** cards are good on their own. **Package
synergy** is two packages that work together (a tie between them, or a bridge card tied to both). An **archetype** is a
combination of packages that decks run together.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from shared.basetypes import CardNumber, FrozenModel, NonEmptyStr
from tools.gundam_cards.models import Color
from tools.gundam_meta.models import EraId, Tier

SCHEMA_VERSION = 1


class PackageId(NonEmptyStr):
    """`pkg:GD02-054`: the lowest card number among the package's members, so it is stable across rebuilds."""

    label = "package id"


class Relation(StrEnum):
    """How two cards relate. A package is made of cards tied by any of these (plus co-play)."""

    COMBO = "combo"  # must be played together: an ability that only works with another card, names it, or needs a specific pilot
    SYNERGY = "synergy"  # work better together: similar keywords, similar abilities, or abilities that work together
    FUNCTIONAL_REPRINT = "functional_reprint"  # basically the same thing at a similar level and cost (play 4 of A and 4 of B)


class SynergyKind(StrEnum):
    LINK_PILOT = "link_pilot"  # a Unit's named Link `[Mikazuki Augus]` needs a specific Pilot (Barbatos <- Mikazuki)
    NAME_REFERENCE = "name_reference"  # card text names another card: `a Unit with "Master Gundam" in its card name`
    LINK_TRAIT = "link_trait"  # a Unit's trait Link is satisfied by a Pilot with that trait
    TRAIT_REFERENCE = "trait_reference"  # an ability that needs OTHER cards with a trait (Tekkadan from your trash)
    SIMILAR_ABILITY = "similar_ability"  # the same or a contained effect, at a different level/cost (Tekkadan's "1 damage to both")
    SHARED_KEYWORD = "shared_keyword"  # the same native keyword (Blocker), at a different level/cost
    FUNCTIONAL_EFFECT = "functional_effect"  # the same or a contained effect, same color, similar level and cost
    FUNCTIONAL_ROLE = "functional_role"  # the same native keyword, same color, similar level and cost

    @property
    def relation(self) -> Relation:
        return _RELATIONS[self]


_RELATIONS = {
    SynergyKind.LINK_PILOT: Relation.COMBO,
    SynergyKind.NAME_REFERENCE: Relation.COMBO,
    SynergyKind.LINK_TRAIT: Relation.SYNERGY,
    SynergyKind.TRAIT_REFERENCE: Relation.SYNERGY,
    SynergyKind.SIMILAR_ABILITY: Relation.SYNERGY,
    SynergyKind.SHARED_KEYWORD: Relation.SYNERGY,
    SynergyKind.FUNCTIONAL_EFFECT: Relation.FUNCTIONAL_REPRINT,
    SynergyKind.FUNCTIONAL_ROLE: Relation.FUNCTIONAL_REPRINT,
}


class SynergyEdge(FrozenModel):
    """A structural tie between two cards, read from the card catalog (not from decks)."""

    a: CardNumber
    b: CardNumber
    kind: SynergyKind
    detail: str  # e.g. "Mikazuki Augus", "Master Gundam", "Tekkadan", "same effect", "blocker"


class Role(StrEnum):
    CORE = "core"  # in nearly every deck that runs the package
    OPTIONAL = "optional"


class PackageMember(FrozenModel):
    card_number: CardNumber
    role: Role
    decks: int  # decks running the package that include this card
    share: float  # decks / decks running the package


class Variant(FrozenModel):
    """Which optional members come with the core, and how many decks played that exact combination."""

    optional_members: tuple[CardNumber, ...]
    decks: int


class Package(FrozenModel):
    id: PackageId
    name: str
    members: tuple[PackageMember, ...] = Field(min_length=2)
    edges: tuple[SynergyEdge, ...]  # the structural ties among its members
    decks_running: int  # decks that run the package (see Params.run_share)
    decks_running_all: int  # decks that run every member
    deck_share: float  # decks_running / decks in the window
    colors: tuple[Color, ...]
    variants: tuple[Variant, ...]  # most played first


class SynergyCard(FrozenModel):
    """A card outside the package with a structural tie to it, played in most of its decks (e.g. Darkness Finger with Master Asia)."""

    card_number: CardNumber
    package: PackageId
    decks: int
    share: float  # of the package's decks
    edges: tuple[SynergyEdge, ...]


class Bridge(FrozenModel):
    """A card outside both packages with a tie to each, played in most decks that run both (Strike Rouge between Strike Freedom and Tekkadan)."""

    card_number: CardNumber
    decks: int
    share: float  # of the decks that run both packages
    edges_a: tuple[SynergyEdge, ...]  # ties to package_a's members
    edges_b: tuple[SynergyEdge, ...]


class PackageSynergy(FrozenModel):
    """Two (single-color) packages that work together: a tie between their members and/or a bridge card, and decks that run both."""

    package_a: PackageId
    package_b: PackageId
    decks_both: int
    share_of_a: float  # of package_a's decks that also run package_b
    share_of_b: float
    edges: tuple[SynergyEdge, ...]  # direct ties between the packages' members
    bridges: tuple[Bridge, ...]


class Affinity(FrozenModel):
    package: PackageId
    share: float  # of that package's decks that run this card


class FreeFloater(FrozenModel):
    """A card that is good on its own. Affinities are information, not synergy (no structural tie)."""

    card_number: CardNumber
    decks: int
    deck_share: float
    affinities: tuple[Affinity, ...]  # packages it is most often played with


class SquadCard(FrozenModel):
    card_number: CardNumber
    decks: int


class Squad(FrozenModel):
    """A set of cards in which every pair are peers (they do the same job), so players run some of each (4 of A and 4 of B).

    A card can be in several squads. Peers are not substitutes: each keeps its own role and copy need (see design.md, "Same job")."""

    cards: tuple[SquadCard, ...] = Field(min_length=2)
    decks_with_any: int
    share_with_any: float  # of all decks in the window
    kinds: tuple[SynergyKind, ...]  # why the pairs in it count as peers


class CardRate(FrozenModel):
    card_number: CardNumber
    share: float


class Archetype(FrozenModel):
    """The set of packages a deck runs. `packages` is empty for decks that run none."""

    packages: tuple[PackageId, ...]
    name: str
    decks: int
    share: float  # of all decks in the window
    synergy_cards: tuple[CardRate, ...]  # synergy cards in at least half of these decks
    free_floating: tuple[CardRate, ...]  # free-floating cards in at least half of these decks


class Params(FrozenModel):
    min_decks: int  # a card must be in this many decks to be considered
    mutual_threshold: float  # each card must imply the other in this share of decks to be linked
    run_share: float  # a deck runs a package when it has at least this share of its members (and at least 2)
    bridge_share: float  # share of the decks running two packages a card must be in to bridge them; also the share for a package pair and an affinity


class DataSource(StrEnum):
    """Where a set of decks comes from. Online decks are the example decks: curated lists weighted by how much of the online field they match."""

    TOURNAMENT = "tournament"
    ONLINE = "online"


class Window(FrozenModel):
    era: EraId | None
    start: date
    end: date | None  # exclusive
    tiers: tuple[Tier, ...]
    events: int
    decks: int  # counted decks used
    decks_not_counted: int


class PackagesFile(FrozenModel):
    """`shared/data/gundam_packages/packages.json`: packages, synergy and free-floating cards, squads and archetypes for one window."""

    schema_version: Literal[2] = 2  # 2: `reprints` groups became `squads` (every pair peers; a card may be in several)
    generated_at: datetime
    source: DataSource = DataSource.TOURNAMENT
    window: Window
    params: Params
    packages: tuple[Package, ...]
    synergy_cards: tuple[SynergyCard, ...]
    free_floating: tuple[FreeFloater, ...]
    archetypes: tuple[Archetype, ...]
    squads: tuple[Squad, ...]
    package_synergies: tuple[PackageSynergy, ...]
    rare_cards: int  # cards seen in too few decks to classify


class NamesFile(FrozenModel):
    """`names.json` (hand-maintained): nicknames that override a package's generated name, by package id."""

    schema_version: Literal[1] = 1
    data: dict[PackageId, str]


# ---- appearance rates: why cards are played (see appearance-rates.md) -----------------------------------------------
MAX_COPIES = 4  # the rules cap a card at 4 copies per deck
RATE_TOLERANCE = 1e-9


class OtherRole(StrEnum):
    SYNERGY = "synergy"  # tied to the package (any appearance)
    FREE_FLOATING = "free_floating"  # no tie: how often it is played with the package, not a claim of synergy
    OTHER = "other"  # anything else seen in the package's decks


class RatedCard(FrozenModel):
    """`copies` of a card out of `possible` (4 per deck) in a set of decks; `rate` = copies / possible."""

    card_number: CardNumber
    copies: int = Field(ge=0)
    possible: int = Field(gt=0)
    rate: float

    @model_validator(mode="after")
    def _rate_is_copies_over_possible(self) -> RatedCard:
        if self.copies > self.possible or abs(self.rate - self.copies / self.possible) > RATE_TOLERANCE:
            raise ValueError(f"{self.card_number}: rate {self.rate} is not {self.copies}/{self.possible}")
        return self


Histogram = tuple[int, int, int, int, int]  # decks that play 0, 1, 2, 3 and 4 copies of a card


def majority_copies(histogram: Histogram) -> int:
    """The most copies that at least half of the decks run: the largest n (1 to 4) with at least half the decks playing n or more; 0 if none."""
    total = sum(histogram)
    return next((n for n in (4, 3, 2, 1) if 2 * sum(histogram[n:]) >= total > 0), 0)


def typical_copies(histogram: Histogram) -> int:
    """The most common copy count among the decks that run the card at all (a tie goes to the larger count); 0 if none run it."""
    best = max(range(1, 5), key=lambda n: (histogram[n], n))
    return best if histogram[best] else 0


class MemberRate(RatedCard):
    role: Role  # core / optional in its package
    histogram: Histogram  # decks running the package that play 0..4 copies of it

    @model_validator(mode="after")
    def _histogram_matches_the_copies(self) -> MemberRate:
        if sum(n * d for n, d in enumerate(self.histogram)) != self.copies:
            raise ValueError(f"{self.card_number}: histogram {self.histogram} does not add up to {self.copies} copies")
        return self

    @property
    def majority_copies(self) -> int:
        return majority_copies(self.histogram)


class ComboCard(FrozenModel):
    """A partner package's card (or a bridge card), measured inside the decks that play both packages."""

    card_number: CardNumber
    copies: int = Field(ge=0)
    possible: int = Field(gt=0)  # 4 x pair_decks
    rate_in_combo: float  # copies / possible
    rate_from_x: float  # combined package rate x rate_in_combo = copies / (4 x the perspective package's decks)
    histogram: Histogram  # pair decks (decks running both packages) that play 0..4 copies of it

    @model_validator(mode="after")
    def _rate_is_copies_over_possible(self) -> ComboCard:
        if self.copies > self.possible or abs(self.rate_in_combo - self.copies / self.possible) > RATE_TOLERANCE:
            raise ValueError(f"{self.card_number}: rate {self.rate_in_combo} is not {self.copies}/{self.possible}")
        if sum(n * d for n, d in enumerate(self.histogram)) != self.copies or sum(self.histogram) * MAX_COPIES != self.possible:
            raise ValueError(f"{self.card_number}: histogram {self.histogram} does not match {self.copies} of {self.possible}")
        return self

    @property
    def majority_copies(self) -> int:
        return majority_copies(self.histogram)


class PartnerRates(FrozenModel):
    """Package X played with package W: how often, and the rates of W's cards and the bridge cards from X's perspective."""

    package: PackageId  # W
    synergistic: bool  # the pair is a package synergy (tied, and run together often enough)
    pair_decks: int = Field(ge=1)  # YY: decks that play both X and W (the pair)
    combined_rate: float  # pair_decks / package_decks (YY / Y)
    joint_rate: float  # pair_decks / total_decks (YY / Z)
    cards: tuple[ComboCard, ...]  # W's members
    bridges: tuple[ComboCard, ...]


class OtherCard(RatedCard):
    role: OtherRole
    belongs_to: PackageId | None  # a package this card is a member of, when it wasn't played as that package


class PackageRates(FrozenModel):
    package: PackageId
    name: str
    package_decks: int = Field(ge=1)  # Y: decks that play X
    rate: float  # Y / Z: the package played rate (package_decks / total_decks)
    alone_decks: int  # decks that play X and no other package
    alone_rate: float  # alone_decks / package_decks
    members: tuple[MemberRate, ...]
    partners: tuple[PartnerRates, ...]  # most often together first
    others: tuple[OtherCard, ...]  # highest rate first

    @model_validator(mode="after")
    def _combined_rates_are_over_this_packages_games(self) -> PackageRates:
        for partner in self.partners:
            if abs(partner.combined_rate - partner.pair_decks / self.package_decks) > RATE_TOLERANCE:
                raise ValueError(f"{self.package} with {partner.package}: combined rate is not {partner.pair_decks}/{self.package_decks}")
            for card in (*partner.cards, *partner.bridges):
                if abs(card.rate_from_x - partner.combined_rate * card.rate_in_combo) > RATE_TOLERANCE:
                    raise ValueError(f"{card.card_number}: rate from {self.package} is not combined rate x rate in combo")
        return self


class ArchetypeRole(StrEnum):
    """Why a card is in an archetype's card table (a package member beats a bridge, which beats the rest)."""

    CORE = "core"  # a core member of one of the archetype's packages
    OPTIONAL = "optional"  # an optional member of one of them
    BRIDGE = "bridge"  # a bridge card between two of its packages
    SYNERGY = "synergy"  # tied to one of its packages
    FREE_FLOATING = "free_floating"  # no tie
    OTHER = "other"


class ArchetypeCard(FrozenModel):
    """A card in one archetype's decks: how many of them run it, and in what copy counts."""

    card_number: CardNumber
    role: ArchetypeRole
    decks: int  # the archetype's decks that run it (at least one copy)
    share: float  # decks / the archetype's decks
    histogram: Histogram  # the archetype's decks that play 0..4 copies of it

    @model_validator(mode="after")
    def _decks_are_the_decks_with_a_copy(self) -> ArchetypeCard:
        if self.decks != sum(self.histogram[1:]):
            raise ValueError(f"{self.card_number}: {self.decks} decks but histogram {self.histogram}")
        return self

    @property
    def majority_copies(self) -> int:
        return majority_copies(self.histogram)

    @property
    def typical_copies(self) -> int:
        return typical_copies(self.histogram)


class ArchetypeRate(FrozenModel):
    packages: tuple[PackageId, ...]
    name: str
    decks: int
    rate: float  # decks / all decks; these sum to 1
    cards: tuple[ArchetypeCard, ...] = ()  # every package member and every card in at least a quarter of its decks (none for "no package")
    low_sample: bool = False  # too few decks for the copy counts to be trusted

    @model_validator(mode="after")
    def _card_tables_match_the_decks(self) -> ArchetypeRate:
        for c in self.cards:
            if sum(c.histogram) != self.decks or abs(c.share - c.decks / self.decks) > RATE_TOLERANCE:
                raise ValueError(f"{self.name}: {c.card_number} does not match the archetype's {self.decks} decks")
        return self


class RatesFile(FrozenModel):
    """`shared/data/gundam_packages/rates.json`: appearance rates for one window, built from the same decks as `packages.json`."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    source: DataSource = DataSource.TOURNAMENT
    window: Window
    total_decks: int  # Z: all decks in the window
    packages: tuple[PackageRates, ...]
    archetypes: tuple[ArchetypeRate, ...]
    card_index: dict[CardNumber, PackageId | None]  # every deck card seen -> the package it is a member of


# ---- drift: how a later era changes the packages -------------------------------------------------------------------
class PackageDrift(FrozenModel):
    package: PackageId
    name: str
    share_before: float  # of decks that run it, in the base window
    share_after: float  # in the new window
    dropped: tuple[CardNumber, ...]  # members that fell out of its new decks (below half of them)
    joined: tuple[SynergyCard, ...]  # cards introduced since the base window that now go with it, with a structural tie
    new_synergy_cards: tuple[SynergyCard, ...]  # existing cards newly tied to it (a structural tie and any appearance)


class NewCard(FrozenModel):
    """A card introduced after the base window and seen in the new window's decks."""

    card_number: CardNumber
    introduced: date
    decks: int
    deck_share: float
    package: PackageId | None  # the package it mainly goes with, if it has a structural tie to one


class EmergingPackage(FrozenModel):
    """A package that appears in the new window and wasn't in the base window (it contains at least one new card)."""

    package: Package
    new_cards: tuple[CardNumber, ...]
    low_sample: bool  # true when the new window has few decks


class DriftFile(FrozenModel):
    """`shared/data/gundam_packages/drift.json`."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    base: Window
    new: Window
    params: Params
    packages: tuple[PackageDrift, ...]
    new_cards: tuple[NewCard, ...]
    emerging: tuple[EmergingPackage, ...]
