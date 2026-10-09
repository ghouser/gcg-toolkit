"""Typed models for Gundam meta data: tournament events and decks, online ranking snapshots, example decks, eras, and the derived stats.

See tools/gundam_meta/design.md. Card identity is always the card number; names live in the gundam_cards catalog.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from shared.basetypes import CardNumber, FrozenModel, NonEmptyStr, SetCode


class EventId(NonEmptyStr):
    """A source's own id for an event (DuelFrontier slug, EGM uuid)."""

    label = "event id"


class DeckId(NonEmptyStr):
    """A source's own id for a deck (DuelFrontier deck slug, EGM result id)."""

    label = "deck id"


class EraId(NonEmptyStr):
    """`gd05`, `gd05_5`, `gd06`."""

    label = "era id"


class Source(StrEnum):
    """Tournament data sources. Kept separate: one real event can appear in more than one."""

    DUELFRONTIER = "duelfrontier"
    EGM = "egm"


class Tier(StrEnum):
    MAJOR = "major"  # regional, world championship (+ qualifiers), large/small official events
    LOCAL = "local"  # store championships, Newtype Challenge, unofficial events
    OTHER = "other"  # unrecognized event types: stored, never counted


class EventType(StrEnum):
    # DuelFrontier
    REGIONAL = "regional"
    WORLD_CHAMPIONSHIP = "world_championship"  # includes WCQ qualifiers
    STORE_CHAMPIONSHIP = "store_championship"
    NEWTYPE_CHALLENGE = "newtype_challenge"
    # EGM
    LARGE_OFFICIAL = "large_official"
    SMALL_OFFICIAL = "small_official"  # EGM's plain "Official Event"
    UNOFFICIAL = "unofficial"
    OTHER = "other"  # anything new; the raw label is kept on the event

    @property
    def tier(self) -> Tier:
        return _TIERS[self]


_TIERS = {
    EventType.REGIONAL: Tier.MAJOR,
    EventType.WORLD_CHAMPIONSHIP: Tier.MAJOR,
    EventType.LARGE_OFFICIAL: Tier.MAJOR,
    EventType.SMALL_OFFICIAL: Tier.MAJOR,
    EventType.STORE_CHAMPIONSHIP: Tier.LOCAL,
    EventType.NEWTYPE_CHALLENGE: Tier.LOCAL,
    EventType.UNOFFICIAL: Tier.LOCAL,
    EventType.OTHER: Tier.OTHER,
}


class DeckCard(FrozenModel):
    card_number: CardNumber
    qty: int = Field(ge=1)


class Deck(FrozenModel):
    id: DeckId
    player_name: str
    placement: int
    name: str | None  # archetype or deck name when the source gives one
    available: bool  # False when the source won't show the list (private deck)
    main: tuple[DeckCard, ...]  # main deck (50 cards expected)
    side: tuple[DeckCard, ...]  # sideboard (up to 10); played cards, so counted
    unresolved: tuple[str, ...]  # tokens in the source's list we couldn't interpret; such a deck is not counted

    @property
    def counted(self) -> bool:
        """Only complete, readable decks are counted."""
        return self.available and not self.unresolved and bool(self.main)

    @model_validator(mode="after")
    def _unavailable_decks_have_no_cards(self) -> Deck:
        if not self.available and (self.main or self.side):
            raise ValueError("an unavailable deck can't have cards")
        return self


class Event(FrozenModel):
    """One tournament as one source reports it. Immutable once stored (completed events only)."""

    source: Source
    id: EventId
    name: str
    start_date: date
    end_date: date | None
    country: str | None  # ISO 3166 alpha-2 when the source has it
    city: str | None
    players: int | None  # size of the field; sources can be unreliable (0)
    rounds: int | None
    event_type: EventType
    type_raw: str  # the source's own label/code for the type
    format_label: str | None  # the source's own format/era label, e.g. "GD05 + ST11-14"
    decks: tuple[Deck, ...]  # top cut only
    fetched_at: datetime
    warnings: tuple[str, ...]

    @property
    def tier(self) -> Tier:
        return self.event_type.tier


# ---- Online ranking (MobileSuitArena) -----------------------------------------------------------
class OnlineRankedCard(FrozenModel):
    card_number: CardNumber
    rank: int
    games_observed: int
    appearance_rate_pct: float  # 30.2 means 30.2% of sampled games contain the card (NOT a share of copies)


class OnlineRankingSnapshot(FrozenModel):
    """`online_rankings/<generated_at>.json`: one snapshot of the rolling 14-day ranking."""

    generated_at: datetime
    window_start: datetime
    window_end: datetime
    window_days: int
    eligible_player_games: int
    cards_observed: int  # cards seen at all; only ranked ones are in `cards`
    stale: bool
    fetched_at: datetime
    cards: tuple[OnlineRankedCard, ...]


class MsaBucket(StrEnum):
    CORE_META = "core_meta"  # >= 10%
    OFTEN_PLAYED = "often_played"  # >= 3%
    PLAYED = "played"  # >= 1%
    SOMETIMES_PLAYED = "sometimes_played"  # >= 0.4%
    NICHE = "niche"  # ranked, but < 0.4%. Cards the ranking doesn't rank have NO bucket.


# ---- Example decks: curated lists with weights -------------------------------------------------
class ExampleList(FrozenModel):
    """One example deck list of an archetype (a tournament deck), and how much of the online field it matches."""

    url: str  # the EGM deck-builder link the list was published as
    cards: tuple[DeckCard, ...]  # main deck, parsed from the link
    share: float | None = Field(default=None, ge=0, le=1)  # share of the archetype's analysed decks matching this list; None if unknown


class ExampleArchetype(FrozenModel):
    slug: str
    name: str
    games: int  # games played by this archetype in the window (stats.metaBreakdown)
    lists: tuple[ExampleList, ...]
    sides_analyzed: int | None  # how many decks the shares were computed from; None if unknown


class ExampleDecksSnapshot(FrozenModel):
    """`example_decks/<fetched_at>.json`: the example lists of every archetype with their weights (see design.md, "Example decks")."""

    fetched_at: datetime
    window_days: int
    season: str
    archetypes: tuple[ExampleArchetype, ...]
    slugs_without_archetype: tuple[str, ...]  # list slugs with no matching archetype in the breakdown (reported, never guessed)
    unresolved_lists: tuple[str, ...]  # list links we could not parse into a main deck


class DecksSnapshotFile(FrozenModel):
    """`example_decks/<fetched_at>.json`."""

    schema_version: Literal[1] = 1
    data: ExampleDecksSnapshot


# ---- eras ---------------------------------------------------------------------------------------
class EraDef(FrozenModel):
    """`eras.json`, hand-maintained: an era starts when the latest of its anchor sets is released."""

    id: EraId
    label: str
    anchor_sets: tuple[SetCode, ...] = Field(min_length=1)


class Era(FrozenModel):
    """An era resolved against release dates at read time. Never stored."""

    definition: EraDef
    start: date
    end: date | None  # exclusive: the next era's start; None while it's the latest

    @property
    def id(self) -> EraId:
        return self.definition.id

    def contains(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day < self.end)


class ErasFile(FrozenModel):
    schema_version: Literal[1] = 1
    data: tuple[EraDef, ...]


# ---- stored files ---------------------------------------------------------------------------------
class EventFile(FrozenModel):
    """`events/<source>/<id>.json`: immutable once written."""

    schema_version: Literal[1] = 1
    data: Event


class SnapshotFile(FrozenModel):
    """`online_rankings/<generated_at>.json`."""

    schema_version: Literal[1] = 1
    data: OnlineRankingSnapshot


# ---- derived stats ------------------------------------------------------------------------------
class CardShare(FrozenModel):
    card_number: CardNumber
    copies: int  # the "part": copies of this card across counted decks (main + side)
    decks: int  # decks with at least one copy
    share: float  # copies / total_copies


class TournamentStats(FrozenModel):
    """Part-over-whole card shares for one source and tier over a window of events."""

    source: Source | None  # None = all sources combined, with events both report counted once
    tier: Tier
    era: EraId | None  # None for an ad-hoc date range
    start: date
    end: date | None  # exclusive
    events: int
    decks: int  # counted decks
    decks_not_counted: int  # private or unreadable decks in these events
    total_copies: int  # the "whole": deck-card copies across counted decks
    excluded_copies: int  # copies of non-deck cards (resources, EX cards, tokens) left out of both parts and whole
    cards: tuple[CardShare, ...]  # most played first


class MsaCardStat(FrozenModel):
    card_number: CardNumber
    rank: int
    appearance_rate_pct: float
    bucket: MsaBucket


class MsaStats(FrozenModel):
    snapshot: datetime  # the snapshot's generated_at
    window_start: datetime
    window_end: datetime
    games: int
    cards: tuple[MsaCardStat, ...]


class PopularityFile(FrozenModel):
    """`shared/data/gundam_meta/popularity.json`. The three metas are never merged into one score."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    msa: MsaStats | None
    tournaments: tuple[TournamentStats, ...]
