"""Which decks my collection supports, which it is close to, and what to get for one (see tools/gundam_collection/design.md, "Deck report").

A deck is an archetype: the set of packages real decks run together. Its cards come from the archetype's card table (rates files) in
three layers: **core** (core package members and the bridges between its packages), **staples** (cards at least half of its lists
run) and **options** (optional members and cards in a quarter to half of its lists). A deck is *supported* when I own every core
and staple copy (the cards I need for a working deck), *close* when I own at least CLOSE_MIN_OWNED of them, and *far* otherwise.

The same deck in tournament and online decks (its packages match by the cards they share) is one deck; a card is critical if it
is critical in either source, at the larger copy count. Everything joins on the card number. Pure functions: no files, no network.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from shared.basetypes import CardNumber
from shared.overlap import match_groups
from tools.gundam_cards.legality import Rules
from tools.gundam_cards.models import CardModel, color_of
from tools.gundam_collection.models import Stage
from tools.gundam_collection.alternatives import slot_alternatives
from tools.gundam_collection.bands import GUARDED, Band, Need, NextBand, ahead, band_of, next_band
from tools.gundam_packages.models import (
    ArchetypeCard,
    ArchetypeRate,
    ArchetypeRole,
    DataSource,
    PackageId,
    PackagesFile,
    RatesFile,
    Squad,
)

MIN_PLAY_RATE = 0.05  # a deck played in less than this share of decks in every source is left out
STAPLE_MIN_SHARE = 0.5  # a card at least this share of a deck's lists run is a staple
OPTION_MIN_SHARE = 0.25  # a card in at least this share (below the staple line) is an option
PREMIUM_CENTS = 1000  # a pick priced at least this is flagged (never skipped)
DECK_SIZE = 50  # a deck is 50 cards: core plus staples never need more than this many copies

SourceData = tuple[PackagesFile, RatesFile]


class Layer(StrEnum):
    CORE = "core"
    STAPLE = "staple"
    OPTION = "option"


LAYERS = (Layer.CORE, Layer.STAPLE, Layer.OPTION)
_RANK = {layer: i for i, layer in enumerate(LAYERS)}
_LETTER = {"red": "R", "blue": "B", "green": "G", "white": "W", "purple": "P"}  # a color in a package name, only where it tells packages apart


@dataclass(frozen=True)
class Requirement:
    """A card a deck wants, in a layer, at a copy count (merged across the sources that have the deck)."""

    card: CardNumber
    layer: Layer
    need: int  # copies: the majority copy count in the deck's lists (the larger of the sources')
    share: float  # the share of the deck's lists that run it (the larger of the sources')
    why: tuple[str, ...]  # "core of Tekkadan", "bridge between A and B", "in 87% of its lists"


@dataclass(frozen=True)
class Deck:
    name: str
    package_refs: tuple[tuple[str, DataSource, PackageId], ...]  # each package: its name, and the source and id it is known by
    rates: Mapping[DataSource, float]  # how often the deck is played, in each source that has it
    low_sample: bool
    requirements: tuple[Requirement, ...]
    anchors: tuple[str, ...] = ()  # the anchor card of each package (aligned with package_refs), the same for a package found in both sources
    package_labels: tuple[str, ...] = ()  # each package's name as shown in the deck's name, with a color letter where it tells packages apart (aligned with package_refs)
    package_rates: tuple[float, ...] = ()  # how often each package is played (aligned with package_refs): its mean rate in the sources this deck is played in
    id: str = ""  # stable: the anchor cards of its packages, like GD02-054+ST11-001 (see deck_id)
    plain_name: str = ""  # the generated name, before a nickname or a qualifier (set by label_decks)
    nickname: str | None = None
    illegal: tuple[str, ...] = ()  # why it is not a legal deck under the current banned / restricted list (a found deck can predate the list)
    archetype: str = ""  # its primary package and plan: "Kira Strike Freedom control" (set by assign_archetypes)
    archetype_rates: Mapping[DataSource, float] = field(default_factory=dict)  # how often the whole archetype is played, per source

    @property
    def top_rate(self) -> float:
        return max(self.rates.values())

    @property
    def primary(self) -> int:
        """Index (in package_refs) of the deck's primary package: the most-played one, ties to the lower anchor card. Raw data, no judgement."""
        order = sorted(range(len(self.package_refs)), key=lambda i: (-(self.package_rates[i] if i < len(self.package_rates) else 0.0), self.anchors[i] if i < len(self.anchors) else ""))
        return order[0] if order else 0


# ---- building decks from the sources ----------------------------------------------------------------------------------
def _layer(card: ArchetypeCard) -> Layer | None:
    if card.role in (ArchetypeRole.CORE, ArchetypeRole.BRIDGE):
        return Layer.CORE
    if card.role is ArchetypeRole.OPTIONAL:
        return Layer.OPTION
    if card.share >= STAPLE_MIN_SHARE:
        return Layer.STAPLE
    return Layer.OPTION if card.share >= OPTION_MIN_SHARE else None


def _why(card: ArchetypeCard, layer: Layer, names: Mapping[PackageId, str], rates: RatesFile, signature: Sequence[PackageId]) -> str:
    if card.role is ArchetypeRole.CORE:
        owner = rates.card_index.get(card.card_number)
        return f"core of {names[owner]}" if owner is not None and owner in names else "core"
    if card.role is ArchetypeRole.BRIDGE:
        pairs = [
            f"{names[x.package]} and {names[w.package]}"
            for x in rates.packages
            if x.package in signature
            for w in x.partners
            if w.package in signature and x.package < w.package and any(b.card_number == card.card_number for b in w.bridges)
        ]
        return f"bridge between {pairs[0]}" if pairs else "bridge"
    if card.role is ArchetypeRole.OPTIONAL:
        return "optional package card"
    return f"in {card.share:.0%} of its lists"


def _collapse(req: Requirement) -> Requirement:
    """One "in N% of its lists" (the larger share) instead of one per source; the structural reasons (core of ..., bridge ...) stay."""
    structural = tuple(w for w in req.why if not w.startswith("in "))
    why = structural or (f"in {req.share:.0%} of its lists",)
    return Requirement(req.card, req.layer, req.need, req.share, why)


def fit_to_deck(requirements: Sequence[Requirement], size: int = DECK_SIZE) -> tuple[Requirement, ...]:
    """Keep the core, then let the staples fill the room that is left, most-run first. A staple that fits only in part needs fewer
    copies; a staple that does not fit at all becomes an option (every staple together can need more than 50 cards, but a deck cannot)."""
    room = max(size - sum(r.need for r in requirements if r.layer is Layer.CORE), 0)
    fitted: list[Requirement] = []
    for r in requirements:
        if r.layer is not Layer.STAPLE:
            fitted.append(r)
            continue
        take = min(r.need, room)
        room -= take
        if take == r.need:
            fitted.append(r)
        elif take > 0:
            fitted.append(Requirement(r.card, r.layer, take, r.share, r.why))
        else:
            fitted.append(Requirement(r.card, Layer.OPTION, r.need, r.share, r.why))
    return tuple(sorted(fitted, key=lambda r: (_RANK[r.layer], -r.share, r.card)))


def _shared_package_ids(sources: Mapping[DataSource, SourceData]) -> dict[tuple[DataSource, PackageId], str]:
    """Each package's id in one shared namespace: a package found in both sources gets the first source's id."""
    ordered = list(sources)
    members = {s: {p.package: frozenset(m.card_number for m in p.members) for p in rates.packages} for s, (_, rates) in sources.items()}
    shared = {(s, pid): (str(pid) if i == 0 else f"{s.value}:{pid}") for i, s in enumerate(ordered) for pid in members[s]}
    if len(ordered) == 2:
        pairs, _, _ = match_groups(members[ordered[0]], members[ordered[1]])
        for first_id, second_id, _ in pairs:
            shared[(ordered[1], second_id)] = shared[(ordered[0], first_id)]
    return shared


def build_decks(sources: Mapping[DataSource, SourceData], min_rate: float = MIN_PLAY_RATE, rules: Rules | None = None) -> tuple[Deck, ...]:
    """Every deck played in at least `min_rate` of decks in some source, with the same deck in both sources merged into one."""
    shared = _shared_package_ids(sources)
    found: dict[frozenset[str], dict[DataSource, ArchetypeRate]] = {}
    for source, (_, rates) in sources.items():
        for arch in rates.archetypes:
            if arch.packages:  # decks that run no package have no card table
                found.setdefault(frozenset(shared[(source, p)] for p in arch.packages), {})[source] = arch
    decks = [_merge(by_source, sources, shared, rules) for by_source in found.values() if any(a.rate >= min_rate for a in by_source.values())]
    return tuple(sorted(decks, key=lambda d: (-d.top_rate, d.name)))


def _merge(
    by_source: Mapping[DataSource, ArchetypeRate], sources: Mapping[DataSource, SourceData], shared: Mapping[tuple[DataSource, PackageId], str], rules: Rules | None = None
) -> Deck:
    best: dict[CardNumber, Requirement] = {}
    refs: tuple[tuple[str, DataSource, PackageId], ...] = ()
    anchors: tuple[str, ...] = ()
    rates_by_source: dict[DataSource, float] = {}
    name = ""
    low = False
    for source in sources:
        arch = by_source.get(source)
        if arch is None:
            continue
        rates = sources[source][1]
        names = {p.package: p.name for p in rates.packages}
        rates_by_source[source] = arch.rate
        low = low or arch.low_sample
        name = name or arch.name
        refs = refs or tuple((names[p], source, p) for p in arch.packages)
        anchors = anchors or tuple(anchor_of(shared[(source, p)]) for p in arch.packages)
        for card in arch.cards:
            layer = _layer(card)
            need = card.majority_copies or card.typical_copies  # a card under half the lists has no majority: use what its decks run most
            if layer is None or need == 0:
                continue
            req = Requirement(card.card_number, layer, need, card.share, (_why(card, layer, names, rates, arch.packages),))
            old = best.get(card.card_number)
            if old is None:
                best[card.card_number] = req
                continue
            keep = req if _RANK[req.layer] < _RANK[old.layer] else old  # critical in either source wins
            best[card.card_number] = Requirement(
                card.card_number, keep.layer, max(old.need, req.need), max(old.share, req.share), tuple(dict.fromkeys((*keep.why, *old.why, *req.why)))
            )
    ordered = sorted((_collapse(r) for r in best.values()), key=lambda r: (_RANK[r.layer], -r.share, r.card))
    if rules is not None:  # the banned / restricted list: a banned card is not needed at all, a restricted one only up to its limit
        ordered = [replace(r, need=min(r.need, rules.copy_limit(r.card))) for r in ordered if rules.copy_limit(r.card) > 0]
    package_rate = {(src, shared[(src, pk.package)]): pk.rate for src, (_, rate_file) in sources.items() for pk in rate_file.packages}
    popularity = tuple(
        sum(package_rate.get((src, shared[(ref_source, pid)]), 0.0) for src in by_source) / len(by_source) for _, ref_source, pid in refs
    )  # a package's rate in each source the deck is played in, averaged: the same package found in both sources counts in both
    table = fit_to_deck(ordered)
    illegal = rules.violations({r.card: r.need for r in table if r.layer is not Layer.OPTION}) if rules is not None else ()
    return Deck(name=name, package_refs=refs, rates=rates_by_source, low_sample=low, requirements=table, anchors=anchors,
                package_rates=popularity, id=deck_id(anchors), plain_name=name, illegal=illegal)  # fmt: skip


# ---- identifiers, names and lookup -------------------------------------------------------------------------------------
def anchor_of(package: object) -> str:
    """The card a package is named after: `pkg:GD02-054` (or a shared id like `online:pkg:ST11-001`) -> `GD02-054`."""
    return str(package).split("pkg:")[-1]


def deck_id(anchors: Sequence[str]) -> str:
    """A stable identifier: the anchor cards of the deck's packages, sorted and joined: `GD02-054+ST11-001`."""
    return "+".join(sorted(set(anchors)))


def normalize_id(text: str) -> str:
    """Case, dashes, plus signs, spaces and commas do not matter: `gd02-054 + st11-001` -> `GD02054ST11001`."""
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def id_tokens(text: str) -> frozenset[str]:
    """The anchor cards named in a text, in any order and with any punctuation: `gd02-054 + st11-001` and `ST11001GD02054` -> {GD02054, ST11001}."""
    return frozenset(re.findall(r"[A-Z]+\d+", re.sub(r"[-\s+,]", "", text).upper()))


def label_decks(decks: Sequence[Deck], catalog: Mapping[CardNumber, CardModel], nicknames: Mapping[str, str]) -> tuple[Deck, ...]:
    """Give every deck a name that is unique and readable, an id, and its nickname if it has one.

    A package name shared by different packages (two Char Aznable packages) gets its color letter (R/B/G/W/P) in the decks that use it; two decks that
    still have the same name get the card each is anchored on, in brackets. A nickname replaces the whole name. Names are worked out over all the
    decks given, so give them all (before any play-rate floor) and the labels do not change with the floor."""
    anchors_by_name: dict[str, set[str]] = {}
    for deck in decks:
        for (name, _, _), anchor in zip(deck.package_refs, deck.anchors, strict=False):
            anchors_by_name.setdefault(name, set()).add(anchor)

    def tagged(name: str, anchor_number: str) -> str:
        if len(anchors_by_name[name]) < 2:
            return name
        anchor = catalog.get(CardNumber(anchor_number))
        color = color_of(anchor) if anchor is not None else None
        return f"{name} ({_LETTER[color.value]})" if color is not None else name

    labels = [" + ".join(tagged(name, a) for (name, _, _), a in zip(deck.package_refs, deck.anchors, strict=False)) if deck.package_refs else deck.name for deck in decks]
    by_label: dict[str, list[int]] = {}
    for i, label in enumerate(labels):
        by_label.setdefault(label, []).append(i)
    for label, indexes in by_label.items():
        if len(indexes) > 1:
            anchor_sets = [set(decks[i].anchors) for i in indexes]
            common = set.intersection(*anchor_sets)
            for i, mine in zip(indexes, anchor_sets, strict=True):
                names = [catalog[CardNumber(a)].name if CardNumber(a) in catalog else a for a in sorted(mine - common)]
                labels[i] = f"{label} ({', '.join(names)})" if names else label
    out: list[Deck] = []
    for deck, label in zip(decks, labels, strict=True):
        nick = nicknames.get(deck.id)
        shown = tuple(tagged(name, a) for (name, _, _), a in zip(deck.package_refs, deck.anchors, strict=False))
        out.append(replace(deck, name=nick or label, plain_name=deck.plain_name or deck.name, nickname=nick, package_labels=shown))
    return tuple(out)


VARIANT_SHARE = 0.2  # a variant of a played archetype must itself reach this share of the floor


def is_played(deck: Deck, floor: float) -> bool:
    """Not fringe: the deck's own play rate reaches the floor in some source, or it is a real variant of an archetype that does (its own rate is at
    least a fifth of the floor), so a 2% deck in a 12% archetype is kept at the default 5% floor and a 0% one is not."""
    archetype = max(deck.archetype_rates.values(), default=0.0)
    return deck.top_rate >= floor or (archetype >= floor and deck.top_rate >= floor * VARIANT_SHARE)


def find_decks(decks: Sequence[Deck], text: str) -> list[Deck]:
    """The decks a typed text means, best kind of match first: an id (any punctuation), a nickname, an exact name, every word of a name,
    then digits only (`0205411001`). Returns every deck at the first level that matches anything; the caller refuses to guess among several."""
    wanted, lowered = normalize_id(text), text.strip().casefold()
    if not wanted:
        return []
    typed = id_tokens(text)
    by_id = [d for d in decks if d.id and typed and id_tokens(d.id) == typed]
    if by_id:
        return by_id
    by_nickname = [d for d in decks if d.nickname and d.nickname.casefold() == lowered]
    if by_nickname:
        return by_nickname
    exact = [d for d in decks if lowered in (d.name.casefold(), d.plain_name.casefold())]
    if exact:
        return exact
    tokens = [t for t in re.split(r"[\s+,]+", text.casefold()) if t]

    def matches(d: Deck) -> bool:
        words = f"{d.name} {d.plain_name} {d.nickname or ''}".casefold()
        mine = id_tokens(d.id)
        return all(t in words or (bool(id_tokens(t)) and id_tokens(t) <= mine) for t in tokens)

    named = [d for d in decks if matches(d)]
    if named:
        return named
    if wanted.isdigit():
        return [d for d in decks if wanted in re.sub(r"\D", "", d.id)]
    return []


# ---- slots and coverage -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DeckSlot:
    """A place in a deck that needs copies of one card. Same-job cards are redundant, not substitutes (alternatives.py): only an option
    card can have counted stand-ins; for a core or staple card every same-job card is a suggestion."""

    members: tuple[CardNumber, ...]  # the required card of this slot (always one)
    alternates: tuple[CardNumber, ...]  # same-job stand-ins that count toward it (option cards only)
    similar: tuple[CardNumber, ...]  # other same-job peers: suggestions, not counted
    needs: tuple[int, int, int]  # copies needed in core, staple and option (LAYERS order)
    owned: int  # copies I own across the member and the counted alternates (any printing)
    option: CardNumber | None  # the cheapest of them to buy
    unit_cents: int | None  # its price
    share: float  # the highest share of the deck's lists that run a member
    why: Mapping[Layer, tuple[str, ...]]

    def have(self, layer: Layer) -> int:
        """Copies that count toward a layer: what I own fills core first, then staples, then options."""
        left = self.owned
        for current in LAYERS:
            got = min(left, self.needs[_RANK[current]])
            if current is layer:
                return got
            left -= got
        return 0

    def need(self, layer: Layer) -> int:
        return self.needs[_RANK[layer]]

    def missing(self, layer: Layer) -> int:
        return self.need(layer) - self.have(layer)


def deck_slots(
    deck: Deck,
    groups: Sequence[Squad],
    owned: Mapping[CardNumber, int],
    prices: Mapping[CardNumber, int],
    catalog: Mapping[CardNumber, CardModel],
) -> tuple[DeckSlot, ...]:
    by_card = {r.card: r for r in deck.requirements}
    alternatives = slot_alternatives(list(by_card), frozenset(r.card for r in deck.requirements if r.layer is Layer.OPTION), groups, catalog)
    slots: list[DeckSlot] = []
    for n, req in by_card.items():
        found = alternatives[n]
        counted = (n, *found.counted)
        priced = sorted((prices[c], c) for c in counted if c in prices)
        needs = tuple(req.need if req.layer is layer else 0 for layer in LAYERS)
        slots.append(
            DeckSlot(
                members=(n,),
                alternates=found.counted,
                similar=found.similar,
                needs=(needs[0], needs[1], needs[2]),
                owned=sum(owned.get(c, 0) for c in counted),
                option=priced[0][1] if priced else None,
                unit_cents=priced[0][0] if priced else None,
                share=req.share,
                why={layer: req.why if req.layer is layer else () for layer in LAYERS},
            )
        )
    return tuple(sorted(slots, key=lambda s: (min(_RANK[layer] for layer in LAYERS if s.need(layer)), -s.share, s.members)))


@dataclass(frozen=True)
class DeckCoverage:
    deck: Deck
    slots: tuple[DeckSlot, ...]

    def need(self, *layers: Layer) -> int:
        return sum(s.need(layer) for s in self.slots for layer in layers)

    def have(self, *layers: Layer) -> int:
        return sum(s.have(layer) for s in self.slots for layer in layers)

    def cost_cents(self, *layers: Layer) -> int:
        """The price of the missing copies in these layers that have a price."""
        return sum(s.missing(layer) * s.unit_cents for s in self.slots for layer in layers if s.unit_cents is not None)

    def unpriced_missing(self, *layers: Layer) -> int:
        return sum(s.missing(layer) for s in self.slots for layer in layers if s.unit_cents is None)

    @property
    def working_share(self) -> float:
        """Share of the core and staple copies I own (1.0 when the deck needs none)."""
        need = self.need(Layer.CORE, Layer.STAPLE)
        return self.have(Layer.CORE, Layer.STAPLE) / need if need else 1.0

    def needs(self) -> tuple[Need, ...]:
        """One row per card for the completeness band: core cards are key cards, staples are not."""
        rows: list[Need] = []
        for s in self.slots:
            for layer in (Layer.CORE, Layer.STAPLE):
                if s.need(layer):
                    rows.append(Need(s.members[0], s.need(layer), s.have(layer), s.unit_cents, layer is Layer.CORE))
        return tuple(rows)

    @property
    def band(self) -> Band:
        return band_of(self.needs())

    @property
    def next_band(self) -> NextBand | None:
        """The cheapest purchases that reach the next band up (None when Perfect)."""
        return next_band(self.needs())

    @property
    def ahead(self) -> tuple[NextBand, ...]:
        """Cost to the next band (and the one after, for Reachable and Playable)."""
        return ahead(self.needs())

    @property
    def playable(self) -> bool:
        """Playable or better (I would sleeve it)."""
        return self.band in GUARDED


def coverage(
    deck: Deck,
    groups: Sequence[Squad],
    owned: Mapping[CardNumber, int],
    prices: Mapping[CardNumber, int],
    catalog: Mapping[CardNumber, CardModel],
) -> DeckCoverage:
    return DeckCoverage(deck, deck_slots(deck, groups, owned, prices, catalog))


def overview(coverages: Sequence[DeckCoverage], sort: str = "cost") -> dict[Band, list[DeckCoverage]]:
    """Decks by completeness band. Perfect is most played first; every other band is cheapest to move up first (`sort="cost"`, the
    default) or most played first (`sort="played"`, meta coverage), with the other as the tie-break."""
    out: dict[Band, list[DeckCoverage]] = {band: [] for band in Band}
    for c in coverages:
        out[c.band].append(c)

    def next_cost(c: DeckCoverage) -> tuple[bool, int]:
        up = c.next_band
        return (up is not None and up.unpriced > 0, up.cost_cents if up else 0)

    for band, rows in out.items():
        if sort == "archetype":
            rows.sort(key=lambda c: (-max(c.deck.archetype_rates.values(), default=0.0), -c.deck.top_rate, c.deck.name))
        elif band is Band.PERFECT or sort == "played":
            rows.sort(key=lambda c: (-c.deck.top_rate, *next_cost(c), c.deck.name))
        else:
            rows.sort(key=lambda c: (*next_cost(c), -c.deck.top_rate, c.deck.name))
    return out


def package_stages(deck: Deck, stages: Mapping[DataSource, Mapping[PackageId, Stage]]) -> tuple[tuple[str, Stage], ...]:
    """Each of the deck's packages with whether it is home, adjacent or new for me (known in the source the deck came from)."""
    return tuple((name, stages[source][pid]) for name, source, pid in deck.package_refs)


# ---- durability and picks -----------------------------------------------------------------------------------------------
def needed_by(coverages: Sequence[DeckCoverage]) -> dict[CardNumber, tuple[tuple[str, float], ...]]:
    """For each card, the decks that are Playable or better that need it (core or staple), most played first, with their play rates."""
    found: dict[CardNumber, list[tuple[str, float]]] = {}
    for c in coverages:
        if not c.playable:
            continue
        for s in c.slots:
            if s.need(Layer.CORE) or s.need(Layer.STAPLE):
                for member in s.members:
                    found.setdefault(member, []).append((c.deck.name, c.deck.top_rate))
    return {card: tuple(sorted(rows, key=lambda r: (-r[1], r[0]))) for card, rows in found.items()}


@dataclass(frozen=True)
class Pick:
    """One line of the buy list: copies of a card to get for a deck, and why."""

    layer: Layer
    card: CardNumber  # the number to buy (the cheapest printing of the card)
    members: tuple[CardNumber, ...]
    copies: int
    unit_cents: int | None
    share: float
    why: tuple[str, ...]
    also_needed_by: tuple[str, ...]  # other supported or close decks that need it
    similar: tuple[CardNumber, ...]  # suggestions, not counted

    @property
    def line_cents(self) -> int | None:
        return None if self.unit_cents is None else self.copies * self.unit_cents

    @property
    def premium(self) -> bool:
        return self.unit_cents is not None and self.unit_cents >= PREMIUM_CENTS


def picks(cov: DeckCoverage, durable: Mapping[CardNumber, tuple[tuple[str, float], ...]]) -> tuple[Pick, ...]:
    """What to get for a deck, in order: core first, then staples (most-run first), then options; inside a layer, cards other decks
    I support or am close to also need come first; then the cheapest. Every missing copy is in exactly one pick."""
    found: list[tuple[tuple[object, ...], Pick]] = []
    for s in cov.slots:
        others = [(n, r) for member in s.members for n, r in durable.get(member, ()) if n != cov.deck.name]
        others = sorted(set(others), key=lambda x: (-x[1], x[0]))
        for layer in LAYERS:
            missing = s.missing(layer)
            if not missing:
                continue
            card = s.option or s.members[0]
            pick = Pick(layer, card, s.members, missing, s.unit_cents, s.share, s.why[layer], tuple(n for n, _ in others), s.similar)
            price = s.unit_cents if s.unit_cents is not None else 10**9
            key: tuple[object, ...] = (_RANK[layer], -s.share if layer is Layer.STAPLE else 0.0, -len(others), -sum(r for _, r in others), price, card)
            found.append((key, pick))
    return tuple(p for _, p in sorted(found, key=lambda kv: kv[0]))
