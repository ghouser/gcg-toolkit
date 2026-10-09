"""Finding packages, synergy cards, free-floating cards and archetypes in a set of decks.

Input is a list of decks, each the set of cards in its **main deck** (sideboards are separate tech, not used here).

1. Two cards are *linked* when each implies the other in at least `mutual_threshold` of the decks that run it
   (strength = the smaller of P(a given b) and P(b given a)). The minimum keeps staples out: a staple is in the decks of
   everything it goes with, but those cards are rarely in the staple's decks.
2. Linked cards form groups. A group is a **package** only if its members are also tied by real synergy in the card
   catalog (a Link, a name reference, a narrow trait); members with no tie to the rest fall out of the group.
   A package is **one color**: a linked group is split by color first (a Domon package of red and white cards is two packages).
3. A card outside every package is a **synergy** card of a package if it has a structural tie to a member and appears in any of
   the decks that run the package (a card in a deck is there for a reason); the share of those decks is its score. Everything else is
   **free floating**. When its only reason to appear with package P is that P's decks also run a package Q it is tied to (it is rare in P's decks
   without Q), it is reported as a **bridge** between P and Q instead.
4. Two packages are **synergistic** when they are tied (a direct tie between members, or a bridge card tied to both) and decks run both.
5. A deck *runs* a package when it has at least `run_share` of its members (and at least two). An **archetype** is the set
   of packages a deck runs.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from shared.basetypes import CardNumber
from tools.gundam_cards.models import Color
from tools.gundam_packages.models import (
    Affinity,
    Archetype,
    CardRate,
    Bridge,
    PackageSynergy,
    SquadCard,
    Squad,
    FreeFloater,
    SynergyCard,
    Package,
    PackageId,
    PackageMember,
    Params,
    Relation,
    Role,
    SynergyEdge,
    SynergyKind,
    Variant,
)
from tools.gundam_packages.synergy import SynergyGraph

DEFAULT_PARAMS = Params(min_decks=6, mutual_threshold=0.8, run_share=0.75, bridge_share=0.5)
CORE_SHARE = 0.9  # a member is core when it is in at least this share of the decks that run the package
MIN_BRIDGE_DECKS = 3
MIN_CONTROL_DECKS = 3  # decks needed to say a card is carried by another package (it is rare in the rest of the package's decks)
TYPICAL_SHARE = 0.5  # a card is typical of an archetype when it is in at least this share of its decks
MAX_AFFINITIES = 3
MAX_VARIANTS = 8

Namer = Callable[[PackageId, Sequence[PackageMember], Sequence[SynergyEdge]], str]
Deck = frozenset[CardNumber]


@dataclass(frozen=True)
class Discovery:
    packages: tuple[Package, ...]
    synergy_cards: tuple[SynergyCard, ...]
    free_floating: tuple[FreeFloater, ...]
    archetypes: tuple[Archetype, ...]
    squads: tuple[Squad, ...]
    package_synergies: tuple[PackageSynergy, ...]
    rare_cards: int


def package_id(members: Sequence[CardNumber]) -> PackageId:
    return PackageId("pkg:" + min(members))


def runs_package(deck: Deck, members: Sequence[CardNumber], run_share: float) -> bool:
    need = max(2, math.ceil(run_share * len(members)))
    return sum(1 for m in members if m in deck) >= need


def _split_by_color(group: Sequence[CardNumber], colors: Mapping[CardNumber, Color | None]) -> list[list[CardNumber]]:
    """A package is one color: the pieces (of at least two cards) of `group` that share a color."""
    buckets: dict[Color | None, list[CardNumber]] = defaultdict(list)
    for card in group:
        buckets[colors.get(card)].append(card)
    return [sorted(b) for b in buckets.values() if len(b) >= 2]


def _components(cards: Sequence[CardNumber], linked: Sequence[tuple[CardNumber, CardNumber]]) -> list[list[CardNumber]]:
    parent = {c: c for c in cards}

    def find(x: CardNumber) -> CardNumber:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in linked:
        parent[find(a)] = find(b)
    groups: dict[CardNumber, list[CardNumber]] = defaultdict(list)
    for card in cards:
        groups[find(card)].append(card)
    return [sorted(g) for g in groups.values() if len(g) >= 2]


def _structural_parts(group: Sequence[CardNumber], graph: SynergyGraph) -> list[list[CardNumber]]:
    """The connected pieces (of at least two cards) of `group` under structural ties."""
    inside = set(group)
    adjacent: dict[CardNumber, set[CardNumber]] = {c: {n for n in graph.neighbors(c) if n in inside} for c in group}
    seen: set[CardNumber] = set()
    parts: list[list[CardNumber]] = []
    for start in group:
        if start in seen or not adjacent[start]:
            continue
        stack, part = [start], set()
        while stack:
            card = stack.pop()
            if card in part:
                continue
            part.add(card)
            stack.extend(adjacent[card] - part)
        seen |= part
        parts.append(sorted(part))
    return parts


def discover(
    decks: Sequence[Deck],
    graph: SynergyGraph,
    params: Params,
    colors: Mapping[CardNumber, Color | None],
    namer: Namer,
) -> Discovery:
    total = len(decks)
    frequency: Counter[CardNumber] = Counter(c for d in decks for c in d)
    eligible = sorted(c for c, n in frequency.items() if n >= params.min_decks)
    eligible_set = set(eligible)

    together: Counter[tuple[CardNumber, CardNumber]] = Counter()
    for deck in decks:
        for a, b in combinations(sorted(c for c in deck if c in eligible_set), 2):
            together[(a, b)] += 1
    linked = [
        pair
        for pair, n in together.items()
        if min(n / frequency[pair[0]], n / frequency[pair[1]]) >= params.mutual_threshold
    ]

    # ---- packages
    member_lists: list[list[CardNumber]] = []
    for group in _components(eligible, linked):
        for part in _structural_parts(group, graph):
            for single_color in _split_by_color(part, colors):
                member_lists.extend(_structural_parts(single_color, graph))
    packages: list[Package] = []
    packaged: set[CardNumber] = set()
    running: dict[PackageId, list[Deck]] = {}
    for members in member_lists:
        pid = package_id(members)
        decks_running = [d for d in decks if runs_package(d, members, params.run_share)]
        if not decks_running:
            continue
        running[pid] = decks_running
        packaged.update(members)
        counts = {m: sum(1 for d in decks_running if m in d) for m in members}
        built = [
            PackageMember(
                card_number=m,
                role=Role.CORE if counts[m] / len(decks_running) >= CORE_SHARE else Role.OPTIONAL,
                decks=counts[m],
                share=counts[m] / len(decks_running),
            )
            for m in sorted(members, key=lambda m: (-counts[m], m))
        ]
        optional = [m.card_number for m in built if m.role is Role.OPTIONAL]
        variant_counts: Counter[tuple[CardNumber, ...]] = Counter(
            tuple(sorted(o for o in optional if o in d)) for d in decks_running
        )
        edges = graph.edges_among(members)
        pkg_colors = tuple(sorted({c for m in members if (c := colors.get(m)) is not None}, key=lambda c: c.value))
        packages.append(
            Package(
                id=pid,
                name=namer(pid, built, edges),
                members=tuple(built),
                edges=edges,
                decks_running=len(decks_running),
                decks_running_all=sum(1 for d in decks_running if all(m in d for m in members)),
                deck_share=len(decks_running) / total if total else 0.0,
                colors=pkg_colors,
                variants=tuple(
                    Variant(optional_members=opt, decks=n) for opt, n in sorted(variant_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_VARIANTS]
                ),
            )
        )
    packages.sort(key=lambda p: (-p.decks_running, p.id))
    members_of = {p.id: [m.card_number for m in p.members] for p in packages}

    # ---- synergy and free floating
    synergy_list, package_synergies = classify_synergy(
        [p.id for p in packages], members_of, running, graph, packaged, params
    )
    synergy_cards = {h.card_number for h in synergy_list} | {b.card_number for s in package_synergies for b in s.bridges}

    free_floating: list[FreeFloater] = []
    for card in eligible:
        if card in packaged or card in synergy_cards:
            continue
        affinities = sorted(
            (
                Affinity(package=p.id, share=sum(1 for d in running[p.id] if card in d) / len(running[p.id]))
                for p in packages
            ),
            key=lambda a: (-a.share, a.package),
        )
        free_floating.append(
            FreeFloater(
                card_number=card,
                decks=frequency[card],
                deck_share=frequency[card] / total,
                affinities=tuple(a for a in affinities if a.share >= params.bridge_share)[:MAX_AFFINITIES],
            )
        )
    free_floating.sort(key=lambda f: (-f.decks, f.card_number))
    floating_cards = {f.card_number for f in free_floating}
    rare = sum(1 for c, n in frequency.items() if n < params.min_decks and c not in packaged and c not in synergy_cards)

    # ---- archetypes
    names = {p.id: p.name for p in packages}
    signatures: dict[tuple[PackageId, ...], list[Deck]] = defaultdict(list)
    for deck in decks:
        signature = tuple(p.id for p in packages if runs_package(deck, members_of[p.id], params.run_share))
        signatures[signature].append(deck)
    archetypes: list[Archetype] = []
    for signature, members_decks in signatures.items():
        n = len(members_decks)
        seen_cards: Counter[CardNumber] = Counter(c for d in members_decks for c in d)
        archetypes.append(
            Archetype(
                packages=signature,
                name=" + ".join(names[p] for p in signature) or "No package",
                decks=n,
                share=n / total if total else 0.0,
                synergy_cards=_typical(seen_cards, n, synergy_cards),
                free_floating=_typical(seen_cards, n, floating_cards),
            )
        )
    archetypes.sort(key=lambda a: (-a.decks, a.packages))
    squads = _squads(eligible, frequency, decks, graph)
    return Discovery(tuple(packages), tuple(synergy_list), tuple(free_floating), tuple(archetypes), squads, package_synergies, rare)


def classify_synergy(
    package_ids: Sequence[PackageId],
    members_of: Mapping[PackageId, Sequence[CardNumber]],
    running: Mapping[PackageId, Sequence[Deck]],
    graph: SynergyGraph,
    packaged: set[CardNumber],
    params: Params,
) -> tuple[list[SynergyCard], tuple[PackageSynergy, ...]]:
    """Synergy cards and package synergies for packages and the decks that run them (shared by discovery and drift).

    A card outside every package is a **synergy card** of a package when it has a structural tie to a member and appears in any deck
    that runs the package; its share of those decks is its score. If a card is in a package's decks mainly because those decks also run
    a package it is tied to (below `bridge_share` of that package's decks without the other one, in at least MIN_CONTROL_DECKS of
    them), it is a **bridge** between the two packages instead.
    """
    candidates: dict[tuple[CardNumber, PackageId], SynergyCard] = {}
    for pid in package_ids:
        decks_running = running[pid]
        if not decks_running:
            continue
        counts = Counter(c for d in decks_running for c in d if c not in packaged)
        for card, n in counts.items():
            ties = graph.ties_to(card, members_of[pid])
            if ties:
                candidates[(card, pid)] = SynergyCard(card_number=card, package=pid, decks=n, share=n / len(decks_running), edges=ties)

    package_synergies = _package_synergies(package_ids, members_of, running, graph, packaged, params)
    for synergy in package_synergies:
        for bridge in synergy.bridges:
            for own, other in ((synergy.package_a, synergy.package_b), (synergy.package_b, synergy.package_a)):
                if (bridge.card_number, own) not in candidates:
                    continue
                without = [d for d in running[own] if not runs_package(d, members_of[other], params.run_share)]
                if len(without) >= MIN_CONTROL_DECKS and sum(1 for d in without if bridge.card_number in d) / len(without) < params.bridge_share:
                    del candidates[(bridge.card_number, own)]
    return sorted(candidates.values(), key=lambda h: (h.package, -h.share, h.card_number)), package_synergies


def _package_synergies(
    package_ids: Sequence[PackageId],
    members_of: Mapping[PackageId, Sequence[CardNumber]],
    running: Mapping[PackageId, Sequence[Deck]],
    graph: SynergyGraph,
    packaged: set[CardNumber],
    params: Params,
) -> tuple[PackageSynergy, ...]:
    """Pairs of packages that are tied (directly, or through a bridge card) and run together in at least `bridge_share` of the smaller one's decks."""
    found: list[PackageSynergy] = []
    for a, b in combinations(package_ids, 2):
        both = [d for d in running[a] if runs_package(d, members_of[b], params.run_share)]
        if len(both) < MIN_BRIDGE_DECKS:
            continue
        share_a, share_b = len(both) / len(running[a]), len(both) / len(running[b])
        if max(share_a, share_b) < params.bridge_share:
            continue
        counts = Counter(c for d in both for c in d if c not in packaged)
        bridges: list[Bridge] = []
        for card, n in counts.items():
            ties_a, ties_b = graph.ties_to(card, members_of[a]), graph.ties_to(card, members_of[b])
            if n >= MIN_BRIDGE_DECKS and n / len(both) >= params.bridge_share and ties_a and ties_b:
                bridges.append(Bridge(card_number=card, decks=n, share=n / len(both), edges_a=ties_a, edges_b=ties_b))
        edges = graph.edges_across(members_of[a], members_of[b])
        if edges or bridges:
            found.append(
                PackageSynergy(
                    package_a=a,
                    package_b=b,
                    decks_both=len(both),
                    share_of_a=share_a,
                    share_of_b=share_b,
                    edges=edges,
                    bridges=tuple(sorted(bridges, key=lambda x: (-x.share, x.card_number))),
                )
            )
    return tuple(sorted(found, key=lambda s: (-s.decks_both, s.package_a, s.package_b)))


def is_same_job_edge(e: SynergyEdge) -> bool:
    """A tie that says two cards are peers (same job), in the same color or another."""
    return e.kind in (SynergyKind.FUNCTIONAL_EFFECT, SynergyKind.SIMILAR_ABILITY) and e.detail.startswith("same job")


def _maximal_cliques(nodes: Sequence[CardNumber], adjacent: dict[CardNumber, set[CardNumber]]) -> list[list[CardNumber]]:
    """Bron-Kerbosch with pivoting; deterministic (candidates are visited in sorted order)."""
    found: list[list[CardNumber]] = []

    def grow(chosen: list[CardNumber], candidates: set[CardNumber], excluded: set[CardNumber]) -> None:
        if not candidates and not excluded:
            found.append(sorted(chosen))
            return
        pivot = max(candidates | excluded, key=lambda v: (len(candidates & adjacent[v]), v))
        for v in sorted(candidates - adjacent[pivot]):
            grow([*chosen, v], candidates & adjacent[v], excluded & adjacent[v])
            candidates = candidates - {v}
            excluded = excluded | {v}

    grow([], set(nodes), set())
    return found


def _squads(
    eligible: Sequence[CardNumber], frequency: Counter[CardNumber], decks: Sequence[Deck], graph: SynergyGraph
) -> tuple[Squad, ...]:
    """Played cards that do the same job, as squads: sets in which every pair are peers. A card can be in more than one squad."""
    inside = set(eligible)
    adjacent: dict[CardNumber, set[CardNumber]] = {c: set() for c in inside}
    for card in inside:
        for e in graph.edges_of(card):
            if is_same_job_edge(e) and e.a == card and e.b in inside:
                adjacent[e.a].add(e.b)
                adjacent[e.b].add(e.a)
    result: list[Squad] = []
    for group in _maximal_cliques(sorted(c for c in inside if adjacent[c]), adjacent):
        if len(group) < 2:
            continue
        members = set(group)
        kinds = sorted({e.kind for c in group for e in graph.edges_of(c) if is_same_job_edge(e) and {e.a, e.b} <= members}, key=lambda k: k.value)
        with_any = sum(1 for d in decks if members & d)
        result.append(
            Squad(
                cards=tuple(SquadCard(card_number=c, decks=frequency[c]) for c in sorted(group, key=lambda c: (-frequency[c], c))),
                decks_with_any=with_any,
                share_with_any=with_any / len(decks) if decks else 0.0,
                kinds=tuple(kinds),
            )
        )
    return tuple(sorted(result, key=lambda g: (-g.decks_with_any, g.cards[0].card_number)))


def _typical(counts: Counter[CardNumber], decks: int, allowed: set[CardNumber]) -> tuple[CardRate, ...]:
    rated = [CardRate(card_number=c, share=n / decks) for c, n in counts.items() if c in allowed and n / decks >= TYPICAL_SHARE]
    return tuple(sorted(rated, key=lambda r: (-r.share, r.card_number)))
