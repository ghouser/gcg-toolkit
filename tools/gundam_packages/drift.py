"""Drift: how a later era changes the packages found in an earlier one.

New cards (introduced after the base era) adjust packages: Char is old, but new Zaku units he pairs with change the Char
package over time. This takes the base era's packages as given and looks at the new era's decks:

- how many of them still run each package, and which core members fell out;
- new cards that now go with a package, and existing cards newly tied to one: the same synergy rules as the base window (a structural tie and any appearance in its decks, with bridge cards between packages that run together);
- every new card seen, with the package it mainly goes with (if any);
- **emerging** packages: groups found in the new era's decks that contain a new card and share fewer than two cards with any existing package (sharing two or more means an existing package growing, reported as joined cards).
The new era is small right after a release, so thresholds are relaxed and results are flagged `low_sample`.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime

from shared.basetypes import CardNumber, SetCode
from tools.gundam_cards.models import CardModel, Color
from tools.gundam_packages.discover import Deck, Namer, classify_synergy, discover, runs_package
from tools.gundam_packages.models import (
    DriftFile,
    EmergingPackage,
    SynergyCard,
    NewCard,
    PackageDrift,
    PackagesFile,
    Params,
    Role,
    Window,
)
from tools.gundam_packages.synergy import SynergyGraph

MIN_DRIFT_DECKS = 2  # a package needs this many decks in the new window to be assessed
MIN_NEW_CARD_DECKS = 2
DRIFT_MIN_DECKS = 3  # relaxed min_decks when discovering emerging packages in a small window
LOW_SAMPLE_DECKS = 100
DROPPED_BELOW = 0.5


def introduced_dates(cards: Mapping[CardNumber, CardModel], release_dates: Mapping[SetCode, date]) -> dict[CardNumber, date]:
    """When each card first became available: its earliest printing from a set with a known release date."""
    result: dict[CardNumber, date] = {}
    for number, card in cards.items():
        dates = [release_dates[p.set_code] for p in card.printings if p.set_code is not None and p.set_code in release_dates]
        if dates:
            result[number] = min(dates)
    return result


def compute_drift(
    base: PackagesFile,
    new_decks: Sequence[Deck],
    new_window: Window,
    graph: SynergyGraph,
    introduced: Mapping[CardNumber, date],
    colors: Mapping[CardNumber, Color | None],
    namer: Namer,
    generated_at: datetime,
) -> DriftFile:
    """Compare the new era's decks with the packages found in the base era."""
    params = base.params
    total = len(new_decks)
    base_end = base.window.end
    is_new = {c for c, d in introduced.items() if base_end is not None and d >= base_end}
    packaged_before = {m.card_number for p in base.packages for m in p.members}
    base_synergy = {(h.package, h.card_number) for h in base.synergy_cards}

    members_of = {p.id: [m.card_number for m in p.members] for p in base.packages}
    running = {pid: [d for d in new_decks if runs_package(d, members, params.run_share)] for pid, members in members_of.items()}
    usable = [pid for pid in members_of if len(running[pid]) >= MIN_DRIFT_DECKS]
    in_new, _ = classify_synergy(usable, members_of, running, graph, packaged_before, params)  # the same rules as the base window

    drifts: list[PackageDrift] = []
    for package in base.packages:
        members = members_of[package.id]
        decks_running = running[package.id]
        share_after = len(decks_running) / total if total else 0.0
        dropped: list[CardNumber] = []
        joined: list[SynergyCard] = []
        newly: list[SynergyCard] = []
        if package.id in usable:
            dropped = [
                m.card_number
                for m in package.members
                if m.role is Role.CORE and sum(1 for d in decks_running if m.card_number in d) / len(decks_running) < DROPPED_BELOW
            ]
            for entry in (h for h in in_new if h.package == package.id):
                if entry.card_number in is_new:
                    joined.append(entry)
                elif (package.id, entry.card_number) not in base_synergy:
                    newly.append(entry)
        drifts.append(
            PackageDrift(
                package=package.id,
                name=package.name,
                share_before=package.deck_share,
                share_after=share_after,
                dropped=tuple(sorted(dropped)),
                joined=tuple(sorted(joined, key=lambda h: (-h.share, h.card_number))),
                new_synergy_cards=tuple(sorted(newly, key=lambda h: (-h.share, h.card_number))),
            )
        )

    # every new card seen, with the package it mainly goes with
    frequency: Counter[CardNumber] = Counter(c for d in new_decks for c in d)
    new_cards: list[NewCard] = []
    best_package: dict[CardNumber, SynergyCard] = {}
    for entry in in_new:
        if entry.card_number not in best_package or entry.share > best_package[entry.card_number].share:
            best_package[entry.card_number] = entry
    for card in sorted(c for c in frequency if c in is_new and frequency[c] >= MIN_NEW_CARD_DECKS):
        new_cards.append(
            NewCard(
                card_number=card,
                introduced=introduced[card],
                decks=frequency[card],
                deck_share=frequency[card] / total,
                package=best_package[card].package if card in best_package else None,
            )
        )
    new_cards.sort(key=lambda n: (-n.decks, n.card_number))

    # emerging packages: found in the new decks, contain a new card, and aren't (parts of) existing packages
    relaxed = Params(
        min_decks=DRIFT_MIN_DECKS,
        mutual_threshold=params.mutual_threshold,
        run_share=params.run_share,
        bridge_share=params.bridge_share,
    )
    found = discover(new_decks, graph, relaxed, colors, namer)
    old_member_sets = [frozenset(m.card_number for m in p.members) for p in base.packages]
    emerging: list[EmergingPackage] = []
    for package in found.packages:
        member_set = frozenset(m.card_number for m in package.members)
        fresh = tuple(sorted(c for c in member_set if c in is_new))
        if fresh and not any(len(member_set & old) >= 2 for old in old_member_sets):  # sharing 2+ cards = an existing package growing
            emerging.append(EmergingPackage(package=package, new_cards=fresh, low_sample=total < LOW_SAMPLE_DECKS))

    return DriftFile(
        generated_at=generated_at,
        base=base.window,
        new=new_window,
        params=relaxed,
        packages=tuple(drifts),
        new_cards=tuple(new_cards),
        emerging=tuple(emerging),
    )
