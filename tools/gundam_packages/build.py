"""From stored tournament events to a `PackagesFile`: choose the window's decks, discover, describe."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color, color_of
from tools.gundam_meta.models import Era, Event, ExampleDecksSnapshot, Tier
from tools.gundam_packages.discover import DEFAULT_PARAMS, Deck, Discovery, discover
from tools.gundam_packages.models import DataSource, PackageId, PackagesFile, Params, Window
from tools.gundam_packages.naming import PackageNamer
from tools.gundam_packages.synergy import SynergyGraph, build_graph

ALL_TIERS = (Tier.MAJOR, Tier.LOCAL)
ONLINE_TOTAL = 10_000  # online decks are counted in whole "pseudo-decks" per this many (so each is 0.01% of the field)
ONLINE_PARAMS = Params(min_decks=50, mutual_threshold=0.8, run_share=0.75, bridge_share=0.5)  # 50 of 10,000 = a card in 0.5% of the field


def window_events(events: Sequence[Event], era: Era, tiers: Sequence[Tier]) -> list[Event]:
    return [e for e in events if e.tier in tiers and era.contains(e.start_date)]


def copy_decks(events: Sequence[Event], cards: Mapping[CardNumber, CardModel]) -> tuple[list[Mapping[CardNumber, int]], int]:
    """Each counted deck's **main deck** as card -> copies (resources, EX cards and tokens left out), and the number of decks that
    couldn't be counted. Sideboards are separate tech and are not part of a deck's identity here."""
    decks: list[Mapping[CardNumber, int]] = []
    not_counted = 0
    for event in events:
        for deck in event.decks:
            if not deck.counted:
                not_counted += 1
                continue
            copies: dict[CardNumber, int] = {}
            for c in deck.main:
                if c.card_number in cards and cards[c.card_number].kind.is_deck_card:
                    copies[c.card_number] = copies.get(c.card_number, 0) + c.qty
            decks.append(copies)
    return decks, not_counted


def deck_sets(events: Sequence[Event], cards: Mapping[CardNumber, CardModel]) -> tuple[list[Deck], int]:
    """The same decks as sets of cards (copies ignored), for package discovery."""
    decks, not_counted = copy_decks(events, cards)
    return [frozenset(d) for d in decks], not_counted


def make_window(era: Era, tiers: Sequence[Tier], events: Sequence[Event], decks: int, not_counted: int) -> Window:
    return Window(era=era.id, start=era.start, end=era.end, tiers=tuple(tiers), events=len(events), decks=decks, decks_not_counted=not_counted)


def card_colors(cards: Mapping[CardNumber, CardModel]) -> dict[CardNumber, Color | None]:
    return {n: color_of(c) for n, c in cards.items()}


def apportion(weights: Sequence[float], total: int) -> list[int]:
    """Whole numbers in proportion to `weights` that add up to exactly `total` (largest remainder; ties go to the earlier item)."""
    scale = sum(weights)
    if scale <= 0:
        raise ValueError("no weight to apportion")
    raw = [w / scale * total for w in weights]
    counts = [int(x) for x in raw]
    by_remainder = sorted(range(len(raw)), key=lambda i: (-(raw[i] - counts[i]), i))
    for i in by_remainder[: total - sum(counts)]:
        counts[i] += 1
    return counts


def online_copy_decks(
    snapshot: ExampleDecksSnapshot, cards: Mapping[CardNumber, CardModel], total: int = ONLINE_TOTAL
) -> tuple[list[Mapping[CardNumber, int]], int]:
    """The weighted example lists as `total` whole decks (each list repeated in proportion to its weight), and how many lists have weight.

    A list's weight is its archetype's games times its share of that archetype (its measured share of online decks); lists with no share have no
    weight. Cards are filtered to deck cards like tournament decks are. The result is exactly `total` decks, so every count and
    threshold downstream reads as "out of 10,000 online decks"."""
    listed = [(a, lst) for a in snapshot.archetypes if a.sides_analyzed is not None for lst in a.lists if lst.share]
    counts = apportion([a.games * (lst.share or 0.0) for a, lst in listed], total)
    decks: list[Mapping[CardNumber, int]] = []
    used = 0
    for (_, lst), n in zip(listed, counts, strict=True):
        if n == 0:
            continue
        used += 1
        mapping = {c.card_number: c.qty for c in lst.cards if c.card_number in cards and cards[c.card_number].kind.is_deck_card}
        decks.extend([mapping] * n)
    return decks, used


def online_window(snapshot: ExampleDecksSnapshot, decks: int) -> Window:
    return Window(era=None, start=snapshot.fetched_at.date() - timedelta(days=snapshot.window_days), end=None, tiers=(), events=0, decks=decks, decks_not_counted=0)


def build_packages(
    all_events: Sequence[Event],
    cards: Mapping[CardNumber, CardModel],
    era: Era,
    tiers: Sequence[Tier] = ALL_TIERS,
    params: Params = DEFAULT_PARAMS,
    overrides: Mapping[PackageId, str] | None = None,
    generated_at: datetime | None = None,
    graph: SynergyGraph | None = None,
) -> tuple[PackagesFile, Discovery]:
    """Packages, synergy and free-floating cards, and archetypes for one era. `all_events` should already be de-duplicated."""
    events = window_events(all_events, era, tiers)
    decks, not_counted = deck_sets(events, cards)
    return build_from_decks(decks, make_window(era, tiers, events, len(decks), not_counted), cards, params, overrides, generated_at, graph)


def build_from_decks(
    decks: Sequence[Deck],
    window: Window,
    cards: Mapping[CardNumber, CardModel],
    params: Params = DEFAULT_PARAMS,
    overrides: Mapping[PackageId, str] | None = None,
    generated_at: datetime | None = None,
    graph: SynergyGraph | None = None,
    source: DataSource = DataSource.TOURNAMENT,
) -> tuple[PackagesFile, Discovery]:
    """Packages, synergy and free-floating cards, and archetypes for any set of decks (tournament or online)."""
    synergy = graph or build_graph(list(cards.values()))
    namer = PackageNamer(cards, overrides)
    result = discover(decks, synergy, params, card_colors(cards), namer)
    file = PackagesFile(
        generated_at=generated_at or datetime.now().astimezone(),
        source=source,
        window=window,
        params=params,
        packages=result.packages,
        synergy_cards=result.synergy_cards,
        free_floating=result.free_floating,
        archetypes=result.archetypes,
        squads=result.squads,
        package_synergies=result.package_synergies,
        rare_cards=result.rare_cards,
    )
    return file, result
