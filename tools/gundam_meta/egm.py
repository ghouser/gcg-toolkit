"""EGM Events deck builder (https://deckbuilder.egmanevents.com): tournament results with decklists.

One request (`/api/tournaments/gundam`, ~600 KB) returns every tournament with its results, and each result's deck is
encoded in a URL: `...?deck=ST11-001:4,ST11-003:4,...`. Event types: Large Official and Official (small official) are
the major tier; Unofficial is the local tier. EGM also lists "Total Color Breakdown" rows, which are aggregates, not events.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, TypeAdapter

from shared.basetypes import CardNumber
from shared.fetch import TextFetcher
from tools.gundam_meta.models import Deck, DeckCard, DeckId, Event, EventId, EventType, Source

TOURNAMENTS_URL = "https://deckbuilder.egmanevents.com/api/tournaments/gundam"
EXPECTED_MAIN_DECK = 50
MAX_SIDEBOARD = 10

_EVENT_TYPES = {
    "Large Official Event": EventType.LARGE_OFFICIAL,
    "Official Event": EventType.SMALL_OFFICIAL,
    "Unofficial Event": EventType.UNOFFICIAL,
}
NOT_AN_EVENT = "Total Color Breakdown"


class _Wire(BaseModel):
    """Only the fields we use; a missing or mistyped one fails loudly."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)


class _Result(_Wire):
    id: str
    placement: int
    player_name: str
    deck_type: str | None
    deck_list_url: tuple[str, ...]


class _Tournament(_Wire):
    id: str
    tournament_name: str
    format: str | None
    start_date: date
    player_count: int | None
    rounds: int | None
    event_type: str
    tournament_results: tuple[_Result, ...]


_TOKEN = re.compile(r"([A-Z]+\d*-\d{3}):(\d+)")


@dataclass(frozen=True)
class ParsedDeckList:
    main: tuple[DeckCard, ...]
    side: tuple[DeckCard, ...]
    unresolved: tuple[str, ...]  # tokens we can't interpret; such a deck is not counted


def _cards(tokens: list[str]) -> tuple[tuple[DeckCard, ...], list[str]]:
    counts: Counter[str] = Counter()
    bad: list[str] = []
    for token in tokens:
        match = _TOKEN.fullmatch(token)
        if match is None:
            bad.append(token)
        else:
            counts[match.group(1)] += int(match.group(2))
    return tuple(DeckCard(card_number=CardNumber(n), qty=q) for n, q in counts.items() if q > 0), bad


def _total(cards: tuple[DeckCard, ...]) -> int:
    return sum(c.qty for c in cards)


def parse_deck_url(url: str) -> ParsedDeckList:
    """`...?deck=CARD:qty,CARD:qty` -> main deck cards.

    One `A:n|B:m` token marks the **main/sideboard boundary** (best-of-3 events): `A` is the last main-deck entry and `B` the
    first sideboard entry. Evidence: in all 25 decks that have one, the main entries up to and including `A` total exactly 50 and
    `B` plus everything after it totals exactly 10. The reading is accepted only when that arithmetic holds; otherwise the
    deck is left unresolved. Anything else that isn't `CARD:qty` is unresolved too, never guessed.
    """
    values = parse_qs(urlparse(url).query).get("deck")
    if not values or not values[0]:
        return ParsedDeckList((), (), (url,))
    tokens = values[0].split(",")
    pipes = [i for i, token in enumerate(tokens) if "|" in token]
    if not pipes:
        main, bad = _cards(tokens)
        return ParsedDeckList(main, (), tuple(bad))
    if len(pipes) != 1 or tokens[pipes[0]].count("|") != 1:
        return ParsedDeckList((), (), tuple(tokens[i] for i in pipes))
    i = pipes[0]
    last_main, first_side = tokens[i].split("|")
    main, bad_main = _cards([*tokens[:i], last_main])
    side, bad_side = _cards([first_side, *tokens[i + 1 :]])
    if bad_main or bad_side or _total(main) != EXPECTED_MAIN_DECK or _total(side) > MAX_SIDEBOARD:
        return ParsedDeckList((), (), (tokens[i],))  # the boundary reading doesn't add up: don't guess
    return ParsedDeckList(main, side, ())


@dataclass(frozen=True)
class EgmParse:
    events: tuple[Event, ...]
    skipped: tuple[str, ...]  # names of rows that are not events
    fetched_at: datetime


def egm_raw_path(raw_dir: Path, fetched_at: datetime) -> Path:
    """Where the raw response fetched at this instant is kept; events parsed from it carry the same `fetched_at`."""
    return raw_dir / "egm" / f"{fetched_at.astimezone(UTC):%Y-%m-%dT%H%M%S.%fZ}.json"


def parse_tournaments(text: str, fetched_at: datetime) -> EgmParse:
    tournaments = TypeAdapter(tuple[_Tournament, ...]).validate_json(text)
    events: list[Event] = []
    skipped: list[str] = []
    for t in tournaments:
        if t.event_type == NOT_AN_EVENT:
            skipped.append(t.tournament_name)
            continue
        event_type = _EVENT_TYPES.get(t.event_type, EventType.OTHER)
        warnings: list[str] = []
        if event_type is EventType.OTHER:
            warnings.append(f"unrecognized event type {t.event_type!r}")
        decks = []
        for result in sorted(t.tournament_results, key=lambda r: r.placement):
            if len(result.deck_list_url) != 1:
                parsed = ParsedDeckList((), (), tuple(result.deck_list_url) or ("(no deck list)",))
            else:
                parsed = parse_deck_url(result.deck_list_url[0])
            size = _total(parsed.main)
            if parsed.main and not parsed.unresolved and size != EXPECTED_MAIN_DECK:
                warnings.append(f"{result.player_name} (place {result.placement}): main deck has {size} cards")
            decks.append(
                Deck(
                    id=DeckId(result.id),
                    player_name=result.player_name,
                    placement=result.placement,
                    name=result.deck_type,
                    available=True,
                    main=parsed.main,
                    side=parsed.side,
                    unresolved=parsed.unresolved,
                )
            )
        events.append(
            Event(
                source=Source.EGM,
                id=EventId(t.id),
                name=t.tournament_name,
                start_date=t.start_date,
                end_date=None,
                country=None,
                city=None,
                players=t.player_count,
                rounds=t.rounds,
                event_type=event_type,
                type_raw=t.event_type,
                format_label=t.format,
                decks=tuple(decks),
                fetched_at=fetched_at,
                warnings=tuple(warnings),
            )
        )
    return EgmParse(tuple(events), tuple(skipped), fetched_at)


def fetch_tournaments(fetcher: TextFetcher) -> tuple[str, EgmParse]:
    """One request for every tournament. Returns the raw response text and the parsed events."""
    response = fetcher.get_text(TOURNAMENTS_URL)
    return response.text, parse_tournaments(response.text, response.fetched_at)
