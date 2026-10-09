"""Typed models for the Gundam card catalog. See tools/gundam_cards/design.md ("Data Models") for the rationale.

Terminology follows the game's Comprehensive Rules: trait, keyword, Link Unit, Pilot.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from shared.basetypes import (
    CardNumber,
    FrozenModel,
    PackageId,
    PilotName,
    PrintingId,
    ProductId,
    SetCode,
    SortedFrozenSet,
    SourceTitle,
    Trait,
)

SCHEMA_VERSION = 1


# ---- closed vocabularies -----------------------------------------------------------------------
class CardKind(StrEnum):
    UNIT = "unit"
    PILOT = "pilot"
    COMMAND = "command"
    BASE = "base"
    EX_BASE = "ex_base"
    RESOURCE = "resource"
    EX_RESOURCE = "ex_resource"
    UNIT_TOKEN = "unit_token"

    @property
    def is_deck_card(self) -> bool:
        return self in (CardKind.UNIT, CardKind.PILOT, CardKind.COMMAND, CardKind.BASE)


class Color(StrEnum):
    BLUE = "blue"
    GREEN = "green"
    WHITE = "white"
    RED = "red"
    PURPLE = "purple"


class Zone(StrEnum):
    SPACE = "space"
    EARTH = "earth"


class Rarity(StrEnum):
    C = "C"
    U = "U"
    R = "R"
    LR = "LR"
    P = "P"  # promo
    # An "LK" prefix (LKC, LKU, LKR) is Printing.link_art, and a trailing "+" / "++" is Printing.alt_art_level:
    # neither is part of the rarity itself.


class Block(StrEnum):
    """Bandai's block icon: the rules era a printing belongs to. Unknown values fail the parse on purpose."""

    BETA = "β"
    ONE = "1"
    TWO = "2"

    @property
    def rank(self) -> int:
        return _BLOCK_RANK[self]


_BLOCK_RANK = {Block.BETA: 0, Block.ONE: 1, Block.TWO: 2}


class Keyword(StrEnum):
    """Exactly the vocabulary of Comprehensive Rules section 13 (v1.9.0). No values: Repair 2 is Repair."""

    # 13-1 Keyword Effects: <...> syntax
    REPAIR = "repair"
    BREACH = "breach"
    SUPPORT = "support"
    BLOCKER = "blocker"
    FIRST_STRIKE = "first_strike"
    HIGH_MANEUVER = "high_maneuver"
    SUPPRESSION = "suppression"
    DEVELOPMENT = "development"
    # 13-2 Keywords: 【...】 syntax
    ACTIVATE_MAIN = "activate_main"
    ACTIVATE_ACTION = "activate_action"
    MAIN = "main"
    ACTION = "action"
    BURST = "burst"
    DEPLOY = "deploy"
    ATTACK = "attack"
    DESTROYED = "destroyed"
    WHEN_PAIRED = "when_paired"
    DURING_PAIR = "during_pair"
    WHEN_LINKED = "when_linked"
    DURING_LINK = "during_link"
    ONCE_PER_TURN = "once_per_turn"

    @property
    def is_keyword_effect(self) -> bool:
        """True for the rules' 13-1 group (`<...>` syntax), False for the 13-2 group (`【...】`)."""
        return self in _KEYWORD_EFFECTS


_KEYWORD_EFFECTS = frozenset(
    {
        Keyword.REPAIR,
        Keyword.BREACH,
        Keyword.SUPPORT,
        Keyword.BLOCKER,
        Keyword.FIRST_STRIKE,
        Keyword.HIGH_MANEUVER,
        Keyword.SUPPRESSION,
        Keyword.DEVELOPMENT,
    }
)


# ---- link condition (Units only; rules 2-12, 3-2-6) --------------------------------------------
class PilotNameLink(FrozenModel):
    """`[Amuro Ray]`: satisfied when the pilot's card name *contains* this text (rules 3-2-6-4)."""

    kind: Literal["pilot_name"] = "pilot_name"
    fragment: PilotName


class TraitLink(FrozenModel):
    """`(G Generation) Trait`: satisfied when the pilot has this trait."""

    kind: Literal["trait"] = "trait"
    trait: Trait


LinkRequirement = Annotated[PilotNameLink | TraitLink, Field(discriminator="kind")]


class LinkCondition(FrozenModel):
    """Alternatives: any one satisfies the link (`/` means "or", rules 5-19)."""

    any_of: tuple[LinkRequirement, ...] = Field(min_length=1)

    def satisfied_by(self, pilot_name: PilotName, pilot_traits: frozenset[Trait]) -> bool:
        """True if a Pilot with this card name and these traits satisfies the link (making a Link Unit)."""
        for requirement in self.any_of:
            if isinstance(requirement, PilotNameLink):
                if requirement.fragment in pilot_name:
                    return True
            elif requirement.trait in pilot_traits:
                return True
        return False

    def satisfied_by_any(self, pilot_names: tuple[PilotName, ...], pilot_traits: frozenset[Trait]) -> bool:
        """Like `satisfied_by`, for a Pilot that answers to several names (see `pilot_names_of`)."""
        return any(self.satisfied_by(name, pilot_traits) for name in pilot_names)


class PilotProfile(FrozenModel):
    """A Command's `【Pilot】[Name]` effect (rules 3-4-6): it can be paired as a Pilot instead of being played."""

    name: PilotName
    ap_bonus: int
    hp_bonus: int


# ---- printings, text versions, FAQ -------------------------------------------------------------
class Printing(FrozenModel):
    id: PrintingId
    variant: int | None  # N of `_pN`; None for the base printing
    rarity: Rarity
    alt_art_level: int = Field(ge=0, le=2)  # "+" marks after the rarity: 0 normal, 1 "+", 2 "++"
    link_art: bool  # "LK" prefix (LKC+, LKR+, ...): an alt art that shows the linked pilot with the Unit
    block: Block | None
    source_title: SourceTitle | None  # per printing: alt arts often show a different series
    where_to_get: str  # raw free text
    set_code: SetCode | None  # parsed from "[CODE]" in where_to_get; None for promos/events
    package_ids: tuple[PackageId, ...]
    image_url: str | None

    @property
    def alt_art(self) -> bool:
        """Any alt art, including Link art (LK printings always carry a "+")."""
        return self.alt_art_level > 0 or self.link_art

    @model_validator(mode="after")
    def _variant_matches_id(self) -> Printing:
        if self.variant != self.id.variant:
            raise ValueError(f"variant {self.variant} does not match printing id {self.id}")
        return self


class TextVersion(FrozenModel):
    """One distinct wording of a card's text. Printings can differ, like MTG Oracle updates."""

    text: str
    printing_ids: tuple[PrintingId, ...] = Field(min_length=1)
    block: Block | None  # newest block among those printings
    as_of: date | None  # newest set release date among those printings; None when none are dated
    substantive: bool  # differs from the current version beyond reminder text


class Faq(FrozenModel):
    id: str  # opaque Bandai id, e.g. "Q113"
    updated: date
    question: str
    answer: str


# ---- cards: one variant per kind, discriminated on `kind` ---------------------------------------
class CardBase(FrozenModel):
    number: CardNumber
    name: str
    text_versions: tuple[TextVersion, ...] = Field(min_length=1)  # NEWEST FIRST
    keywords: SortedFrozenSet[Keyword]  # from the current text, reminder text excluded; no values
    referenced_traits: SortedFrozenSet[Trait]  # traits mentioned in the current text
    printings: tuple[Printing, ...] = Field(min_length=1)  # base printing first, then by variant
    faq: tuple[Faq, ...]
    unknown_tags: tuple[str, ...]  # the one quarantine: <...>/【...】 tokens outside the Keyword enum
    fetched_at: datetime

    @property
    def text(self) -> str:
        """The current (newest) wording."""
        return self.text_versions[0].text

    @property
    def source_title(self) -> SourceTitle | None:
        """The reference printing's series (alt arts can show a different one; see `Printing.source_title`)."""
        return self.printings[0].source_title

    @model_validator(mode="after")
    def _printings_belong_to_card(self) -> CardBase:
        # The first printing is the reference one: the base printing, or (for the few card numbers Bandai only
        # lists as alt arts, e.g. R-001) the lowest-numbered alt art.
        variants = [p.variant for p in self.printings]
        if variants != sorted(variants, key=lambda v: -1 if v is None else v):
            raise ValueError(f"printings must be ordered base first, then by variant: {[str(p.id) for p in self.printings]}")
        for printing in self.printings:
            if printing.id.card_number != self.number:
                raise ValueError(f"printing {printing.id} does not belong to {self.number}")
        return self


class UnitCard(CardBase):
    kind: Literal[CardKind.UNIT] = CardKind.UNIT
    color: Color
    level: int
    cost: int
    ap: int | None  # Bandai shows "-" on a few units
    hp: int
    zones: SortedFrozenSet[Zone]
    traits: tuple[Trait, ...]
    link: LinkCondition | None


class PilotCard(CardBase):
    kind: Literal[CardKind.PILOT] = CardKind.PILOT
    color: Color
    level: int
    cost: int
    ap_bonus: int
    hp_bonus: int
    traits: tuple[Trait, ...]  # not gained by the paired Unit (rules 2-5-5)


class CommandCard(CardBase):
    kind: Literal[CardKind.COMMAND] = CardKind.COMMAND
    color: Color
    level: int
    cost: int
    traits: tuple[Trait, ...]  # the pilot effect's traits when `pilot` is set
    pilot: PilotProfile | None  # set for Command/Pilot hybrids


class BaseCard(CardBase):
    kind: Literal[CardKind.BASE] = CardKind.BASE
    color: Color
    level: int
    cost: int
    hp: int
    zones: SortedFrozenSet[Zone]
    traits: tuple[Trait, ...]


class ExBaseCard(CardBase):
    kind: Literal[CardKind.EX_BASE] = CardKind.EX_BASE
    hp: int


class ResourceCard(CardBase):
    kind: Literal[CardKind.RESOURCE] = CardKind.RESOURCE


class ExResourceCard(CardBase):
    kind: Literal[CardKind.EX_RESOURCE] = CardKind.EX_RESOURCE


class UnitTokenCard(CardBase):
    kind: Literal[CardKind.UNIT_TOKEN] = CardKind.UNIT_TOKEN
    ap: int | None
    hp: int
    traits: tuple[Trait, ...]


Card = Annotated[
    UnitCard | PilotCard | CommandCard | BaseCard | ExBaseCard | ResourceCard | ExResourceCard | UnitTokenCard,
    Field(discriminator="kind"),
]

CardModel = UnitCard | PilotCard | CommandCard | BaseCard | ExBaseCard | ResourceCard | ExResourceCard | UnitTokenCard
"""Union of the concrete card classes, for type annotations (use `Card` when validating)."""


_HAS_STATS_LINE = UnitCard | PilotCard | CommandCard | BaseCard  # kinds with a color, level and cost


def color_of(card: CardModel) -> Color | None:
    return card.color if isinstance(card, _HAS_STATS_LINE) else None


def level_of(card: CardModel) -> int | None:
    return card.level if isinstance(card, _HAS_STATS_LINE) else None


def cost_of(card: CardModel) -> int | None:
    return card.cost if isinstance(card, _HAS_STATS_LINE) else None


def traits_of(card: CardModel) -> tuple[Trait, ...]:
    """The card's own traits (empty for kinds that have none)."""
    if isinstance(card, UnitCard | PilotCard | CommandCard | BaseCard | UnitTokenCard):
        return card.traits
    return ()


def is_pilot(card: CardModel) -> bool:
    """A Pilot card, or a Command card with a pilot effect."""
    return isinstance(card, PilotCard) or (isinstance(card, CommandCard) and card.pilot is not None)


# ---- sets ----------------------------------------------------------------------------------------
class SetKind(StrEnum):
    BOOSTER = "booster"  # GDxx
    STARTER = "starter"  # STxx
    EXTRA_BOOSTER = "extra_booster"  # EBxx
    DECK_BUILD_BOX = "deck_build_box"  # SCxx
    PROMO = "promo"
    BETA = "beta"
    OTHER = "other"  # accessories, premium products, basic cards, and anything else with a code

    @property
    def introduces_cards(self) -> bool:
        """Kinds whose release starts a meta era (new cards enter the game)."""
        return self in (SetKind.BOOSTER, SetKind.STARTER, SetKind.EXTRA_BOOSTER)


class CardSet(FrozenModel):
    """A product or package that cards come from. Release dates can be unknown (`None`) or in the future."""

    code: SetCode  # "GD05", "ST11", "EB01", "SC01", "PB01"; synthetic for non-coded packages: PROMO, BETA, BASIC, OTHER
    name: str  # "Freedom Ascension"
    kind: SetKind
    bandai_package_id: PackageId | None  # None for products that have no card list page (yet)
    release_date: date | None
    product_category_raw: str | None  # "BOOSTER PACK", "STARTER DECK", ...
    product_url: str | None

    def released_on(self, day: date) -> bool:
        """No stored "released" flag (it goes stale): compare the release date to the day you care about."""
        return self.release_date is not None and self.release_date <= day


# ---- files ---------------------------------------------------------------------------------------
class SetsFile(FrozenModel):
    """`shared/data/gundam_cards/sets.json`."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    data: tuple[CardSet, ...]


class CardsFile(FrozenModel):
    """`shared/data/gundam_cards/cards.json`."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    data: tuple[Card, ...]


# ---- prices (tcgcsv) ----------------------------------------------------------------------------------------------
class CardPrice(FrozenModel):
    """The latest TCGPlayer market price for one card. Also exactly one row of a future price history (a time series of these)."""

    card_number: CardNumber  # the join key to the master card model
    price_cents: int = Field(ge=0)  # tcgcsv marketPrice of the cheapest non-alt-art, non-promo product, converted once with round(x * 100)
    product_id: ProductId  # the product that price comes from (audit: which printing)
    name: str = ""  # TCGPlayer's own name for that product ("Char's Gelgoog"): what a Mass Entry line needs
    set_code: str = ""  # that product's set abbreviation ("GD01"; "GD01_b" is the Edition Beta printing)
    fetched_at: datetime  # when we pulled it (UTC)


class PriceFile(FrozenModel):
    """`shared/data/gundam_cards/prices.json`: one row per priced card, sorted by card number. A card with no buyable product has no row."""

    schema_version: Literal[2] = 2  # 2: each price row also carries the product's name and set code (for Mass Entry lines)
    generated_at: datetime
    source_updated_at: datetime  # tcgcsv `last-updated.txt` for the dump these prices come from
    data: tuple[CardPrice, ...]


class PricedCard(FrozenModel):
    """The master card model joined with its latest price. Built when read (`load_cards_with_prices`), never stored."""

    card: Card
    latest_tcg_price: CardPrice | None


class TraitStat(FrozenModel):
    trait: Trait
    card_count: int
    card_numbers: tuple[CardNumber, ...]


class SourceTitleStat(FrozenModel):
    source_title: SourceTitle
    card_count: int


class SourceTitlesFile(FrozenModel):
    """`shared/data/gundam_cards/source_titles.json`: the generated vocabulary of series/games cards come from."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    data: tuple[SourceTitleStat, ...]


class TraitsFile(FrozenModel):
    """`shared/data/gundam_cards/traits.json`: the generated trait vocabulary."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    data: tuple[TraitStat, ...]


_ALSO_NAMED = re.compile(r"This card's name is also treated as \[([^\]]+)\]")


def names_of(card: CardModel) -> tuple[str, ...]:
    """Every name the card answers to: its own, then those from "This card's name is also treated as [X]" (Ple-Twelve is also Marida Cruz)."""
    own = card.pilot.name if isinstance(card, CommandCard) and card.pilot is not None else card.name
    return (str(own), *_ALSO_NAMED.findall(card.text))


# ---- banned and restricted cards (Bandai's announcements) ---------------------------------------
class LimitedCard(FrozenModel):
    card: CardNumber
    copies: int = Field(ge=1, le=3)  # at most this many copies in a deck


class BannedPair(FrozenModel):
    a: CardNumber
    b: CardNumber  # a and b cannot be in the same deck


class Restrictions(FrozenModel):
    banned: tuple[CardNumber, ...]  # no copies
    limited: tuple[LimitedCard, ...]  # restricted: at most N copies
    banned_pairs: tuple[BannedPair, ...]
    vanilla_description: str  # the page's words for the vanilla group
    vanilla_group: tuple[CardNumber, ...]  # the cards the page lists as matching it (the rule is the description, matched against the catalog)
    group_max_copies: int = 4  # of one card of the vanilla group


class RestrictionsFile(FrozenModel):
    """`shared/data/gundam_cards/restrictions.json`: the current banned / restricted list from Bandai's announcement."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    source_url: str
    published: date  # the date on the announcement
    data: Restrictions
