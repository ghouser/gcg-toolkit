"""Finding events that two sources both report, so a tournament is only counted once.

DuelFrontier and EGM often cover the same event under different names and dates one or two days apart
("Regional Santiago 2026" and "PlayLATAM's Chile Regionals"). Names and dates are unreliable, so the evidence is the decks:

- Two decks are *confirmed* when they have the same main-deck card list and the same player name.
- Two events (from different sources, within `MAX_DAYS_APART`) are the same event when their confirmed decks are at least
  half of the smaller event's counted decks (and at least one). A stricter fallback accepts identical lists alone
  (>= 5 of them and >= 75%) in case the sources spell player names differently.
Coincidental matches (the same popular list at unrelated events) don't share player names, so they don't qualify.

When an event is duplicated, one copy is kept (the one with more counted decks; DuelFrontier on a tie, since it also records
sideboards), and any deck it couldn't read (private, or EGM's unreadable slots) is filled in from the other copy.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from shared.basetypes import CardNumber
from tools.gundam_meta.models import Deck, Event, EventId, Source

MAX_DAYS_APART = 3
CONFIRMED_SHARE = 0.5
LIST_ONLY_MIN_DECKS = 5
LIST_ONLY_SHARE = 0.75

DeckPrint = tuple[tuple[CardNumber, int], ...]


def deck_print(deck: Deck) -> DeckPrint:
    """The main-deck card list, order-independent. (Sideboards aren't compared: EGM doesn't record them.)"""
    return tuple(sorted((c.card_number, c.qty) for c in deck.main))


def normalize_player(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


@dataclass(frozen=True)
class Match:
    a: Event
    b: Event
    confirmed: int  # decks with the same list and the same player
    identical: int  # decks with the same list (any player)
    smaller: int  # counted decks in the smaller of the two events
    days_apart: int

    @property
    def evidence(self) -> str:
        return f"{self.confirmed} of {self.smaller} decks identical with the same player ({self.identical} identical lists), {self.days_apart} day(s) apart"

    @property
    def score(self) -> tuple[int, int]:
        return (self.confirmed, self.identical)


@dataclass(frozen=True)
class DuplicateGroup:
    canonical: Event  # the copy that is kept
    others: tuple[Event, ...]
    evidence: str
    borrowed: tuple[str, ...]  # players whose deck was filled in from another copy


def match_events(a: Event, b: Event) -> Match | None:
    """Evidence that two events from different sources are the same tournament, or None."""
    if a.source is b.source:
        return None
    days = abs((a.start_date - b.start_date).days)
    if days > MAX_DAYS_APART:
        return None
    decks_a = [d for d in a.decks if d.counted]
    decks_b = [d for d in b.decks if d.counted]
    smaller = min(len(decks_a), len(decks_b))
    if smaller == 0:
        return None
    by_print_b: dict[DeckPrint, list[Deck]] = {}
    for d in decks_b:
        by_print_b.setdefault(deck_print(d), []).append(d)
    confirmed = identical = 0
    for da in decks_a:
        same_list = by_print_b.get(deck_print(da), [])
        if same_list:
            identical += 1
            if any(normalize_player(da.player_name) == normalize_player(db.player_name) for db in same_list):
                confirmed += 1
    is_match = (confirmed >= 1 and confirmed >= CONFIRMED_SHARE * smaller) or (
        identical >= LIST_ONLY_MIN_DECKS and identical >= LIST_ONLY_SHARE * smaller
    )
    return Match(a, b, confirmed, identical, smaller, days) if is_match else None


def _canonical(a: Event, b: Event) -> tuple[Event, Event]:
    """(kept, other): more counted decks wins; DuelFrontier on a tie."""
    ca, cb = sum(d.counted for d in a.decks), sum(d.counted for d in b.decks)
    if ca != cb:
        return (a, b) if ca > cb else (b, a)
    return (a, b) if a.source is Source.DUELFRONTIER else (b, a)


def _fill_unreadable_decks(kept: Event, other: Event) -> tuple[Event, tuple[str, ...]]:
    donors: dict[str, Deck] = {normalize_player(d.player_name): d for d in other.decks if d.counted}
    borrowed: list[str] = []
    decks: list[Deck] = []
    for deck in kept.decks:
        donor = donors.get(normalize_player(deck.player_name))
        if not deck.counted and donor is not None:
            decks.append(deck.model_copy(update={"available": True, "main": donor.main, "side": donor.side, "unresolved": (), "name": deck.name or donor.name}))
            borrowed.append(deck.player_name)
        else:
            decks.append(deck)
    if not borrowed:
        return kept, ()
    note = f"filled in {len(borrowed)} deck(s) from {other.source.value}:{other.id}: {', '.join(borrowed)}"
    return kept.model_copy(update={"decks": tuple(decks), "warnings": (*kept.warnings, note)}), tuple(borrowed)


def find_duplicate_groups(events: Sequence[Event]) -> tuple[DuplicateGroup, ...]:
    """Pair up events across sources, best evidence first, each event used at most once."""
    candidates: list[Match] = []
    for i, a in enumerate(events):
        for b in events[i + 1 :]:
            match = match_events(a, b)
            if match is not None:
                candidates.append(match)
    used: set[tuple[Source, EventId]] = set()
    groups: list[DuplicateGroup] = []
    for match in sorted(candidates, key=lambda m: (m.score, -m.days_apart), reverse=True):
        keys = [(e.source, e.id) for e in (match.a, match.b)]
        if any(k in used for k in keys):
            continue
        used.update(keys)
        kept, other = _canonical(match.a, match.b)
        merged, borrowed = _fill_unreadable_decks(kept, other)
        groups.append(DuplicateGroup(merged, (other,), match.evidence, borrowed))
    return tuple(sorted(groups, key=lambda g: (g.canonical.start_date, str(g.canonical.id))))


def combined_events(events: Sequence[Event]) -> tuple[Event, ...]:
    """Every real event exactly once: duplicates collapsed to one copy (with unreadable decks filled in)."""
    groups = find_duplicate_groups(events)
    dropped = {(o.source, o.id) for g in groups for o in g.others}
    replaced = {(g.canonical.source, g.canonical.id): g.canonical for g in groups}
    result = [replaced.get((e.source, e.id), e) for e in events if (e.source, e.id) not in dropped]
    return tuple(sorted(result, key=lambda e: (e.start_date, e.source.value, str(e.id))))
