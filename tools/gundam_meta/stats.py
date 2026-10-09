"""Part-over-whole card shares from stored tournament events, and the derived popularity file.

For one source and tier over a window of events:
  whole = every deck-card copy in the counted decks (main deck plus sideboard),
  part  = copies of one card, share = part / whole.
Resources, EX cards and tokens are excluded from both whole and parts (decided by the card catalog's `kind`).
Private or unreadable decks are not counted. Windows pool all their events: big events weigh more, by design.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardKind
from tools.gundam_meta.dedupe import combined_events
from tools.gundam_meta.buckets import bucket_for
from tools.gundam_meta.models import (
    CardShare,
    Era,
    EraId,
    Event,
    OnlineRankingSnapshot,
    MsaCardStat,
    MsaStats,
    PopularityFile,
    Source,
    Tier,
    TournamentStats,
)


@dataclass(frozen=True)
class StatsResult:
    stats: TournamentStats
    unknown_cards: frozenset[CardNumber]  # in a deck but missing from the card catalog; excluded and reported


def events_in_window(events: Iterable[Event], source: Source | None, tier: Tier, start: date, end: date | None) -> list[Event]:
    """Events of one tier in [start, end). `source=None` means every source: pass events already run through
    `combined_events` so that an event both sources report is counted once."""
    return [
        e
        for e in events
        if (source is None or e.source is source) and e.tier is tier and start <= e.start_date and (end is None or e.start_date < end)
    ]


def compute_stats(
    events: Iterable[Event],
    kinds: Mapping[CardNumber, CardKind],
    *,
    source: Source | None,
    tier: Tier,
    era: EraId | None,
    start: date,
    end: date | None,
) -> StatsResult:
    chosen = events_in_window(events, source, tier, start, end)
    copies: Counter[CardNumber] = Counter()
    decks_with: Counter[CardNumber] = Counter()
    unknown: set[CardNumber] = set()
    excluded = counted = not_counted = 0
    for event in chosen:
        for deck in event.decks:
            if not deck.counted:
                not_counted += 1
                continue
            counted += 1
            per_deck: Counter[CardNumber] = Counter()
            for card in (*deck.main, *deck.side):
                kind = kinds.get(card.card_number)
                if kind is None:
                    unknown.add(card.card_number)
                elif kind.is_deck_card:
                    per_deck[card.card_number] += card.qty
                else:
                    excluded += card.qty
            copies.update(per_deck)
            decks_with.update(per_deck.keys())
    whole = sum(copies.values())
    cards = tuple(
        CardShare(card_number=n, copies=c, decks=decks_with[n], share=c / whole)
        for n, c in sorted(copies.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    stats = TournamentStats(
        source=source,
        tier=tier,
        era=era,
        start=start,
        end=end,
        events=len(chosen),
        decks=counted,
        decks_not_counted=not_counted,
        total_copies=whole,
        excluded_copies=excluded,
        cards=cards,
    )
    return StatsResult(stats, frozenset(unknown))


def msa_stats(snapshot: OnlineRankingSnapshot) -> MsaStats:
    return MsaStats(
        snapshot=snapshot.generated_at,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        games=snapshot.eligible_player_games,
        cards=tuple(
            MsaCardStat(
                card_number=c.card_number,
                rank=c.rank,
                appearance_rate_pct=c.appearance_rate_pct,
                bucket=bucket_for(c.appearance_rate_pct),
            )
            for c in snapshot.cards
        ),
    )


@dataclass(frozen=True)
class PopularityBuild:
    popularity: PopularityFile
    unknown_cards: frozenset[CardNumber]


def build_popularity(
    events: Sequence[Event],
    snapshots: Sequence[OnlineRankingSnapshot],
    kinds: Mapping[CardNumber, CardKind],
    eras: Sequence[Era],
    today: date,
    generated_at: datetime,
) -> PopularityBuild:
    """MobileSuitArena from the newest snapshot; tournaments for every era that has started, per source and tier."""
    latest = max(snapshots, key=lambda s: s.generated_at) if snapshots else None
    combined = combined_events(events)
    tournaments: list[TournamentStats] = []
    unknown: set[CardNumber] = set()
    for era in eras:
        if era.start > today:
            continue
        for source in (None, *Source):  # None first: the combined, de-duplicated view
            for tier in (Tier.MAJOR, Tier.LOCAL):
                result = compute_stats(
                    combined if source is None else events, kinds, source=source, tier=tier, era=era.id, start=era.start, end=era.end
                )
                unknown |= result.unknown_cards
                if result.stats.events:
                    tournaments.append(result.stats)
    popularity = PopularityFile(
        generated_at=generated_at, msa=msa_stats(latest) if latest else None, tournaments=tuple(tournaments)
    )
    return PopularityBuild(popularity, frozenset(unknown))
