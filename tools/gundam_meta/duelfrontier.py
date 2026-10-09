"""DuelFrontier (https://duelfrontier.com): tournament events and top-cut decklists, via its public API.

- `GET /v1/events?PageNumber=N&PageSize=M`: every event, newest first.
- `GET /v1/events/<slug>?Include=Players`: one event with its top-cut players and their deck slugs.
- `GET /v1/decks/<slug>?Include=Cards`: a deck, one entry per copy; `section` 0 is the main deck, 1 the sideboard.
  Private decks answer HTTP 200 with `succeeded: false` ("not authorized to view this deck"); they are recorded, never bypassed.
The numeric-id event route needs auth and is not used.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from shared.basetypes import CardNumber
from shared.fetch import FetchError, TextFetcher
from tools.gundam_meta.common import is_complete
from tools.gundam_meta.models import Deck, DeckCard, DeckId, Event, EventId, EventType, Source

API = "https://api.duelfrontier.com/v1"
LIST_PAGE_SIZE = 100
EXPECTED_MAIN_DECK = 50
MAX_SIDEBOARD = 10
EMPTY_EVENT_GRACE_DAYS = 30  # an event with no decks yet is kept only once this old (results may still be coming)

_EVENT_TYPES = {
    8: EventType.STORE_CHAMPIONSHIP,
    16: EventType.REGIONAL,
    64: EventType.WORLD_CHAMPIONSHIP,  # includes WCQ qualifiers
    128: EventType.NEWTYPE_CHALLENGE,
}


class _Wire(BaseModel):
    """Only the fields we use; a missing or mistyped one fails loudly."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)


class _ListEvent(_Wire):
    slug: str
    startDate: datetime
    endDate: datetime
    type: int


class _EventPage(_Wire):
    data: tuple[_ListEvent, ...]
    totalPages: int
    succeeded: bool


class _Player(_Wire):
    name: str
    standing: int
    deckSlug: str


class _EventDetail(_Wire):
    name: str
    slug: str
    startDate: datetime
    endDate: datetime
    country: str | None = None
    city: str | None = None
    participants: int | None = None
    type: int
    players: tuple[_Player, ...]


class _EventResponse(_Wire):
    data: _EventDetail
    succeeded: bool


class _CardRef(_Wire):
    code: str


class _DeckCard(_Wire):
    card: _CardRef
    section: int


class _DeckData(_Wire):
    name: str
    cards: tuple[_DeckCard, ...]


class _DeckResponse(_Wire):
    data: _DeckData | None = None
    succeeded: bool
    messages: tuple[str, ...] = ()


# ---- listing -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ListedEvent:
    slug: EventId
    start_date: date
    end_date: date
    type_code: int


def parse_event_page(text: str) -> tuple[tuple[ListedEvent, ...], int]:
    """Events on one list page, and the total number of pages."""
    page = _EventPage.model_validate_json(text)
    if not page.succeeded:
        raise ValueError("DuelFrontier event list reported failure")
    return tuple(ListedEvent(EventId(e.slug), e.startDate.date(), e.endDate.date(), e.type) for e in page.data), page.totalPages


def list_events(fetcher: TextFetcher) -> tuple[ListedEvent, ...]:
    """Every event DuelFrontier lists (two requests at the current size)."""
    events: list[ListedEvent] = []
    page, pages = 1, 1
    while page <= pages:
        response = fetcher.get_text(f"{API}/events?PageNumber={page}&PageSize={LIST_PAGE_SIZE}")
        batch, pages = parse_event_page(response.text)
        events.extend(batch)
        page += 1
    return tuple(events)


# ---- decks and events ------------------------------------------------------------------------------------
def is_private(response: _DeckResponse) -> bool:
    return not response.succeeded and any("not authorized" in m.lower() for m in response.messages)


def parse_deck(player: _Player, deck_text: str | None) -> Deck:
    """A player's deck. `deck_text` is the raw `/v1/decks/<slug>` response (None if it could not be obtained)."""
    deck_id = DeckId(player.deckSlug)
    hidden = Deck(id=deck_id, player_name=player.name, placement=player.standing, name=None, available=False, main=(), side=(), unresolved=())
    if deck_text is None:
        return hidden
    response = _DeckResponse.model_validate_json(deck_text)
    if is_private(response):
        return hidden
    if not response.succeeded or response.data is None:
        raise ValueError(f"deck {player.deckSlug}: unexpected response {response.messages}")
    main: Counter[str] = Counter()
    side: Counter[str] = Counter()
    unresolved: list[str] = []
    for entry in response.data.cards:
        code = entry.card.code
        try:
            CardNumber(code)
        except ValueError:
            unresolved.append(f"card {code!r}")
            continue
        if entry.section == 0:
            main[code] += 1
        elif entry.section == 1:
            side[code] += 1
        else:
            unresolved.append(f"{code} in unknown section {entry.section}")
    return Deck(
        id=deck_id,
        player_name=player.name,
        placement=player.standing,
        name=response.data.name,
        available=True,
        main=tuple(DeckCard(card_number=CardNumber(c), qty=n) for c, n in main.items()),
        side=tuple(DeckCard(card_number=CardNumber(c), qty=n) for c, n in side.items()),
        unresolved=tuple(dict.fromkeys(unresolved)),
    )


def player_deck_slugs(event_text: str) -> tuple[str, ...]:
    """The deck slugs of an event's top-cut players (in the raw `?Include=Players` response)."""
    return tuple(p.deckSlug for p in _EventResponse.model_validate_json(event_text).data.players)


def parse_event(event_text: str, deck_texts: Mapping[str, str | None], fetched_at: datetime) -> Event:
    """Build an Event from the raw event response and the raw deck responses (by deck slug)."""
    response = _EventResponse.model_validate_json(event_text)
    if not response.succeeded:
        raise ValueError("DuelFrontier event response reported failure")
    e = response.data
    event_type = _EVENT_TYPES.get(e.type, EventType.OTHER)
    warnings: list[str] = []
    if event_type is EventType.OTHER:
        warnings.append(f"unrecognized event type code {e.type}")
    decks = []
    for player in sorted(e.players, key=lambda p: p.standing):
        deck = parse_deck(player, deck_texts.get(player.deckSlug))
        main_size, side_size = sum(c.qty for c in deck.main), sum(c.qty for c in deck.side)
        if deck.available and not deck.unresolved and main_size != EXPECTED_MAIN_DECK:
            warnings.append(f"{player.name} (place {player.standing}): main deck has {main_size} cards")
        if side_size > MAX_SIDEBOARD:
            warnings.append(f"{player.name} (place {player.standing}): sideboard has {side_size} cards")
        decks.append(deck)
    return Event(
        source=Source.DUELFRONTIER,
        id=EventId(e.slug),
        name=e.name,
        start_date=e.startDate.date(),
        end_date=e.endDate.date(),
        country=e.country,
        city=e.city,
        players=e.participants or None,  # 0 means unknown
        rounds=None,
        event_type=event_type,
        type_raw=str(e.type),
        format_label=None,
        decks=tuple(decks),
        fetched_at=fetched_at,
        warnings=tuple(warnings),
    )


# ---- syncing -----------------------------------------------------------------------------------------------
def event_key(slug: EventId) -> str:
    return f"duelfrontier/events/{slug}.json"


def deck_key(slug: str) -> str:
    return f"duelfrontier/decks/{slug}.json"


@dataclass(frozen=True)
class SyncResult:
    events: tuple[Event, ...]  # newly built events, ready to store
    listed: int
    already_stored: int
    not_complete_yet: int
    waiting_for_results: int  # complete, but no decks yet and too recent to keep as empty
    failures: tuple[tuple[EventId, str], ...]


def sync_events(
    fetcher: TextFetcher,
    raw_dir: Path,
    listed: tuple[ListedEvent, ...],
    stored: frozenset[EventId],
    today: date,
    progress: Callable[[str], None] = lambda _: None,
) -> SyncResult:
    """Fetch every listed event that is complete and not stored yet, with all its decks. Pages are cached under raw_dir."""
    todo = [e for e in listed if e.slug not in stored and is_complete(e.end_date, today)]
    new: list[Event] = []
    failures: list[tuple[EventId, str]] = []
    waiting = 0
    for n, listing in enumerate(todo, start=1):
        try:
            response = fetcher.get_text(f"{API}/events/{listing.slug}?Include=Players", cache_key=event_key(listing.slug))
            players = _EventResponse.model_validate_json(response.text).data.players
            deck_texts: dict[str, str | None] = {}
            for player in players:
                deck_texts[player.deckSlug] = fetcher.get_text(
                    f"{API}/decks/{player.deckSlug}?Include=Cards", cache_key=deck_key(player.deckSlug)
                ).text
            event = parse_event(response.text, deck_texts, response.fetched_at)
        except (FetchError, ValueError) as e:  # ValueError includes pydantic's ValidationError
            failures.append((listing.slug, str(e)[:300]))  # one bad event must not stop the sync
            continue
        if not event.decks and listing.end_date + timedelta(days=EMPTY_EVENT_GRACE_DAYS) > today:
            waiting += 1  # no results yet; try again on a later sync (the cached event page will be refetched then)
            (raw_dir / event_key(listing.slug)).unlink(missing_ok=True)
            continue
        new.append(event)
        if n % 10 == 0 or n == len(todo):
            progress(f"{n}/{len(todo)} events fetched ({len(failures)} failed)")
    skipped_incomplete = sum(1 for e in listed if e.slug not in stored and not is_complete(e.end_date, today))
    return SyncResult(tuple(new), len(listed), sum(1 for e in listed if e.slug in stored), skipped_incomplete, waiting, tuple(failures))

