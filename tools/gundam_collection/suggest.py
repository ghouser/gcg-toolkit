"""Hypothetical decks: the shape from real decks, the cards chosen by the ratings (design.md, "Deck suggestions").

Pure functions over decks, the card catalog, what I own and prices; no I/O. Given a package, a plan and a color pair it builds an exact 50 (so it can be rated
like any deck) and a pool of the next best cards. Deterministic and explainable; every pick says why.

1. The package's **core** is locked at its real copy counts.
2. **Known cards** (cards that real decks with this package and these colors run, plus plan staples from decks of the same plan in these colors) are added,
   most known and best aligned with the plan first, within the **shape** real decks of the plan have (Units / Pilots / Commands / Bases) and 4 copies.
3. A Linked Unit is only in the deck with a pilot that satisfies its Link.
4. If the deck still rates as the wrong plan, the least aligned non-core cards are swapped for better aligned ones: known elsewhere, or **novel** (in no found
   list), with only a few novel swaps (`novelty`), each labeled.
5. The pool is the best cards left over, by kind.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from shared.basetypes import CardNumber
from tools.gundam_cards.legality import NO_RULES, Rules
from tools.gundam_cards.models import CardKind, CardModel, PilotCard, UnitCard
from tools.gundam_collection.decks import DECK_SIZE, Deck, Layer, Requirement
from tools.gundam_collection.styles import CardSignals, Plan, Style, card_signals, link_pairs, satisfies, style_of

MAX_COPIES = 4
KINDS = (CardKind.UNIT, CardKind.PILOT, CardKind.COMMAND, CardKind.BASE)
KIND_SLACK = 3  # a kind may exceed its target by this many copies
PLAN_SCORE = {Plan.AGGRO: 70, Plan.MIDRANGE: 50, Plan.CONTROL: 30}  # the beatdown score a plan aims for (inside its band, with room)
MAX_SWAPS = 14
MAX_BUNDLES = 2  # partner packages brought in whole
BUNDLE_MIN = 0.15  # a partner package must be this strong (its share of the reference decks, plus fit) to be brought in
PILOT_UNITS = 5  # an other pilot is ranked by the plan fit of the best Units it Links, however they are not in the deck yet
PAIRED_HASTE = 0.2  # a Linked Unit with its pilot is usable the turn it is played: worth something to every plan
MIN_PILOT_PAIRS = 2  # a pilot picked on its own (not with a partner package) must make at least this many Link pairs ...
PILOT_KEEP = 0.3  # ... or push the plan itself this much (align), else it is a filler slot and is left out
PILOT_EXTRA = 4  # pilots that make Link pairs may exceed the usual pilot count by this many
LINK_BONUS = 0.25  # a Linked Unit with its pilot in the deck, or a pilot that Links Units in the deck
UNLINKED_PENALTY = 0.1  # a Linked Unit with no pilot for it: a weaker body, but real decks run them
POOL_SIZE = 8
FILL_FLOOR = -0.25  # a known card this badly aligned with the plan is only added to reach 50, after the better ones
DEFAULT_SHAPE = {Plan.AGGRO: (38, 9, 2, 1), Plan.MIDRANGE: (30, 10, 8, 2), Plan.CONTROL: (24, 8, 14, 4)}  # Units, Pilots, Commands, Bases, when no found deck says


class Prefer(StrEnum):
    FIT = "fit"  # the ratings decide
    OWNED = "owned"  # cards I own win near-ties: the most buildable deck
    COST = "cost"  # cheaper cards win near-ties


@dataclass(frozen=True)
class Pick:
    card: CardNumber
    copies: int
    role: str  # core | known | novel
    known: float  # 0..1: how often found decks run it
    align: float  # -1..1: how well it fits the plan
    why: str
    group: str = ""  # the partner package it came in with (a pilot and its Units are added together)


@dataclass(frozen=True)
class PoolCard:
    card: CardNumber
    known: float
    align: float
    role: str  # known | novel


@dataclass(frozen=True)
class PilotOption:
    """A pilot worth a look: how many Linked Unit copies already in the deck it would pair with, and Units it Links that are not in the deck."""

    card: CardNumber
    pairs_in_deck: int
    units: tuple[CardNumber, ...]  # Units it Links that are not in the deck, best first
    known: float
    fit: float = 0.0  # how well the Units it Links suit this plan (the best few, plus the pairs it makes now)


@dataclass(frozen=True)
class Suggestion:
    package: str
    plan: Plan
    colors: tuple[str, ...]
    picks: tuple[Pick, ...]
    pool: Mapping[CardKind, tuple[PoolCard, ...]]
    references: tuple[str, ...]  # names of the found decks the known cards came from
    style: Style
    notes: tuple[str, ...]
    pairs: tuple[int, int, int] = (0, 0, 0)  # Link pairs possible, Linked Unit copies, pilot copies
    pilot_options: tuple[PilotOption, ...] = ()

    @property
    def copies(self) -> int:
        return sum(p.copies for p in self.picks)

    def requirements(self) -> tuple[Requirement, ...]:
        """The 50 as a card table (the package core is core, the rest staples) so it can be rated and priced like any deck."""
        return tuple(Requirement(p.card, Layer.CORE if p.role == "core" else Layer.STAPLE, p.copies, max(p.known, 0.01), (p.why,)) for p in self.picks)


def align(sig: CardSignals, plan: Plan) -> float:
    """How well a card fits a plan, -1 to 1. Aggro: cheap, hard-hitting Units that do not interact or draw. Control: the opposite, with card advantage welcome.
    Midrange: a clear role either way, and finishers."""
    if sig.is_unit:
        aggro = 0.4 * sig.low + 0.4 * sig.pushing - 0.3 * sig.sturdy - 0.4 * sig.interactive - 0.3 * sig.advantage
    elif sig.is_command:
        aggro = -0.4 - 0.3 * sig.advantage
    elif sig.is_base:  # like a body: cheap and a token with AP over HP are aggro, a Base that hits the board is not (Corsica Base is aggro; Gundam Fight is not)
        aggro = 0.4 * sig.low + 0.4 * sig.pushing - 0.3 * sig.sturdy - 0.4 * sig.interactive - 0.3 * sig.advantage
    else:  # a pilot: its effect is a bonus, its stats are what the Unit gets; judged by advantage only
        aggro = -0.3 * sig.advantage
    if plan is Plan.AGGRO:
        return max(-1.0, min(1.0, aggro))
    if plan is Plan.CONTROL:
        return max(-1.0, min(1.0, -aggro + 0.6 * sig.advantage + 0.3 * sig.finisher))
    return max(-1.0, min(1.0, min(abs(aggro), 0.5) + 0.3 * sig.finisher - 0.2 * (1 if sig.is_command else 0)))


def _known(decks: Sequence[Deck], colors: frozenset[str], signals: Mapping[CardNumber, CardSignals | None]) -> dict[CardNumber, tuple[float, int]]:
    """Per card: how often these decks run it (weighted by how played each deck is) and the copy count they usually run."""
    total = sum(d.top_rate for d in decks)
    seen: dict[CardNumber, float] = {}
    copies: dict[CardNumber, list[tuple[float, int]]] = {}
    for d in decks:
        for r in d.requirements:
            sig = signals.get(r.card)
            if sig is None or (sig.letter is not None and sig.letter not in colors):
                continue
            seen[r.card] = seen.get(r.card, 0.0) + d.top_rate * min(1.0, r.share)
            copies.setdefault(r.card, []).append((d.top_rate, r.need))
    out: dict[CardNumber, tuple[float, int]] = {}
    for card, weight in seen.items():
        pairs = copies[card]
        mass = sum(w for w, _ in pairs)
        out[card] = (weight / total if total else 0.0, max(1, min(MAX_COPIES, round(sum(w * n for w, n in pairs) / mass))))
    return out


def _shape(decks: Sequence[Deck], catalog: Mapping[CardNumber, CardModel], plan: Plan) -> dict[CardKind, int]:
    """The Units / Pilots / Commands / Bases a deck of this plan has: the play-weighted average over found decks, scaled to the deck size."""
    sums = dict.fromkeys(KINDS, 0.0)
    weight = 0.0
    for d in decks:
        counts = dict.fromkeys(KINDS, 0)
        for r in d.requirements:
            card = catalog.get(r.card)
            if card is not None and card.kind in counts and r.layer is not Layer.OPTION:
                counts[card.kind] += r.need
        deck_total = sum(counts.values())
        if deck_total:
            weight += d.top_rate
            for k in KINDS:
                sums[k] += d.top_rate * counts[k] / deck_total
    if weight == 0:
        return dict(zip(KINDS, DEFAULT_SHAPE[plan], strict=True))
    raw = {k: sums[k] / weight * DECK_SIZE for k in KINDS}
    return {k: round(v) for k, v in raw.items()}


def _pilot_serves(card: CardModel, chosen: Mapping[CardNumber, int], catalog: Mapping[CardNumber, CardModel]) -> int:
    """For a Pilot card: how many copies of Units already in the deck have a Link it satisfies."""
    if not isinstance(card, PilotCard):
        return 0
    return sum(n for c, n in chosen.items() if satisfies(catalog[c], card))


def pairs_for(pilot: CardNumber, chosen: Mapping[CardNumber, int], catalog: Mapping[CardNumber, CardModel]) -> list[tuple[CardNumber, int]]:
    """The Linked Units in the deck that a pilot's Link is satisfied by, with their copies."""
    return [(c, n) for c, n in sorted(chosen.items()) if satisfies(catalog[c], catalog[pilot])]


@dataclass(frozen=True)
class Bundle:
    """A partner package from the reference decks: a pilot and its Units come in together."""

    name: str
    cards: Mapping[CardNumber, int]
    weight: float  # the share of the reference decks that run it


def _bundles(references: Sequence[Deck], colors: frozenset[str], signals: Mapping[CardNumber, CardSignals | None], own_package: str) -> list[Bundle]:
    total = sum(d.top_rate for d in references)
    found: dict[str, dict[CardNumber, int]] = {}
    weight: dict[str, float] = {}
    for d in references:
        names = {r.why[0].removeprefix("core of ").split(";")[0] for r in d.requirements if r.why and r.why[0].startswith("core of ")}
        for name in names - {own_package}:
            members: dict[CardNumber, int] = {}
            for r in d.requirements:
                sig = signals.get(r.card)
                if r.why and r.why[0].removeprefix("core of ").split(";")[0] == name and sig is not None and (sig.letter is None or sig.letter in colors):
                    members[r.card] = r.need
            if len(members) >= 2:
                weight[name] = weight.get(name, 0.0) + d.top_rate
                for card, need in members.items():
                    found.setdefault(name, {})[card] = max(found.get(name, {}).get(card, 0), need)
    return sorted((Bundle(n, c, weight[n] / total if total else 0.0) for n, c in found.items()), key=lambda b: (-b.weight, b.name))


def build_suggestion(
    *,
    package: str,
    core: Mapping[CardNumber, int],
    plan: Plan,
    colors: frozenset[str],
    references: Sequence[Deck],
    plan_decks: Sequence[Deck],
    catalog: Mapping[CardNumber, CardModel],
    owned: Mapping[CardNumber, int],
    prices: Mapping[CardNumber, int],
    prefer: Prefer = Prefer.FIT,
    novelty: float = 0.2,
    rules: Rules = NO_RULES,
) -> Suggestion:
    signals: dict[CardNumber, CardSignals | None] = {n: card_signals(c) for n, c in catalog.items()}
    notes: list[str] = []
    same_plan = [d for d in references if style_of(d.requirements, catalog, signals).plan is plan]
    if same_plan and len(same_plan) < len(references):
        notes.append(f"{len(references) - len(same_plan)} found deck(s) with this package are another plan and were not used for known cards")
        references = same_plan
    elif references and not same_plan:
        notes.append(f"no found deck with this package in these colors plays {plan.value}; the known cards come from its other plans and the plan staples")
    ref_known = _known(references, colors, signals)
    plan_known = _known(plan_decks, colors, signals)
    known: dict[CardNumber, tuple[float, int]] = {}
    for card in {*ref_known, *plan_known}:
        a, ac = ref_known.get(card, (0.0, 0))
        b, bc = plan_known.get(card, (0.0, 0))
        known[card] = (min(1.0, a + 0.5 * b), ac or bc)
    shape = _shape([*references, *plan_decks], catalog, plan)

    def score(card: CardNumber) -> float:
        sig = signals[card]
        assert sig is not None
        base = known.get(card, (0.0, 0))[0] + 0.5 * align(sig, plan)
        if prefer is Prefer.OWNED:
            base += 0.15 * min(1.0, owned.get(card, 0) / MAX_COPIES)
        elif prefer is Prefer.COST:
            base -= 0.3 * min(1.0, prices.get(card, 0) / 1000)
        return base

    chosen: dict[CardNumber, int] = {}
    role: dict[CardNumber, str] = {}
    group: dict[CardNumber, str] = {}
    kind_count = dict.fromkeys(KINDS, 0)

    def link_bonus(card: CardNumber) -> float:
        """A Link is worth having: the pilot's stats and the Unit usable the turn it is played. A Linked Unit with its pilot in the deck, or a pilot
        that pairs with Linked Units in the deck, scores higher; a Linked Unit with no pilot is a weaker body (not excluded: real decks run them)."""
        c = catalog[card]
        if isinstance(c, UnitCard) and c.link is not None:
            return LINK_BONUS if any(isinstance(catalog[x], PilotCard) and satisfies(c, catalog[x]) for x in chosen) else -UNLINKED_PENALTY
        if isinstance(c, PilotCard):
            served = _pilot_serves(c, chosen, catalog)
            return LINK_BONUS * min(1.0, served / MAX_COPIES) + 0.1 * (c.ap_bonus + c.hp_bonus) / 4
        return 0.0

    def add(card: CardNumber, copies: int, why: str, bundle: str = "") -> None:
        chosen[card] = chosen.get(card, 0) + copies
        role[card] = why
        if bundle:
            group[card] = bundle
        kind_count[catalog[card].kind] += copies

    for card, copies in sorted(core.items()):
        if card not in catalog or signals.get(card) is None or rules.copy_limit(card) == 0:
            continue
        clash = rules.conflicts(card, chosen)
        if clash:
            notes.append(f"core card {card} left out: {clash[0]}")
            continue
        add(card, min(copies, MAX_COPIES, rules.copy_limit(card)), "core")
    locked = set(chosen)
    universe = [n for n, sig in signals.items() if sig is not None and (sig.letter is None or sig.letter in colors) and n not in locked and rules.copy_limit(n) > 0]

    strict = [True]  # while True, a kind may not take the slots the other kinds still need for their own shape; relaxed at the end so the deck reaches 50

    def room(kind: CardKind, extra: int = 0) -> int:
        """How many more of a kind fit: its shape plus slack, and (while strict) never so many that the other kinds cannot reach their own shape within 50."""
        reserved = sum(max(0, shape.get(k, 0) - kind_count.get(k, 0)) for k in KINDS if k is not kind) if strict[0] else 0
        return min(shape.get(kind, 0) + KIND_SLACK + extra - kind_count.get(kind, 0), DECK_SIZE - sum(kind_count.values()) - reserved)

    def total() -> int:
        return sum(chosen.values())

    def fill(candidates: Sequence[CardNumber], tag: str, cap: int) -> None:
        for card in sorted(candidates, key=lambda c: (-(score(c) + link_bonus(c)), c)):  # the Link bonus depends on what is in the deck so far
            if total() >= DECK_SIZE or card in chosen:
                continue
            sig = signals[card]
            assert sig is not None
            kind = catalog[card].kind
            want = known.get(card, (0.0, 0))[1] or cap
            served = _pilot_serves(catalog[card], chosen, catalog)
            if kind is CardKind.PILOT:  # a pilot that pairs with Linked Units in the deck may go beyond the usual pilot count; one that pairs with nothing is only a stat bonus
                limit = min(want, served) if served else (1 if known.get(card, (0.0, 0))[0] >= 0.25 else 0)
                copies = min(MAX_COPIES, limit, DECK_SIZE - total(), room(kind, PILOT_EXTRA if served else 0), rules.copy_limit(card))
            else:
                copies = min(MAX_COPIES, want, DECK_SIZE - total(), room(kind), rules.copy_limit(card))
            if kind is CardKind.PILOT and copies < MIN_PILOT_PAIRS and align(sig, plan) < PILOT_KEEP:
                continue  # a single stat bonus with no pull toward the plan: a filler slot
            if copies <= 0 or rules.conflicts(card, chosen):
                continue
            add(card, copies, tag)

    def fill_by_kind(candidates: Sequence[CardNumber], tag: str, cap: int) -> None:
        for kind in (CardKind.UNIT, CardKind.PILOT, CardKind.COMMAND, CardKind.BASE):  # Units first, then the pilots that pair with them
            fill([c for c in candidates if catalog[c].kind is kind], tag, cap)

    def bring_in_bundles() -> None:
        """Partner packages from the reference decks, whole: a pilot arrives with the Units it Links (Char Aznable with Char's Z'Gok)."""
        brought = 0
        strict[0] = False  # a partner package comes in whole; the reservation for the other kinds applies to the cards chosen one by one
        for bundle in _bundles(references, colors, signals, package):
            if brought >= MAX_BUNDLES or bundle.weight < BUNDLE_MIN:
                continue
            members = [c for c in bundle.cards if c in catalog and c not in chosen and rules.copy_limit(c) > 0]
            units = [signals[c] for c in members if isinstance(catalog[c], UnitCard)]
            fit = sum(align(u, plan) for u in units if u is not None) / len(units) if units else 0.0
            if bundle.weight + 0.3 * fit < BUNDLE_MIN or any(rules.conflicts(c, chosen) for c in members):
                continue
            added = 0
            for c in sorted(members, key=lambda c: (catalog[c].kind is not CardKind.PILOT, c)):  # the pilot first, so its Units are paired
                copies = min(bundle.cards[c], MAX_COPIES, rules.copy_limit(c), DECK_SIZE - total(), room(catalog[c].kind, PILOT_EXTRA if catalog[c].kind is CardKind.PILOT else 0))
                if copies > 0 and not rules.conflicts(c, chosen):
                    add(c, copies, "known", bundle.name)
                    added += 1
            brought += 1 if added else 0
        strict[0] = True

    bring_in_bundles()
    by_score = sorted(universe, key=lambda c: (-score(c), c))
    good = [c for c in by_score if c in known and align(signals[c], plan) > FILL_FLOOR]  # type: ignore[arg-type]
    rest = [c for c in by_score if c in known and c not in good]
    for _ in range(2):  # a second pass lets a pilot that arrived late satisfy a Unit that was skipped
        fill_by_kind(good, "known", MAX_COPIES)
    fill_by_kind(rest, "known", MAX_COPIES)
    strict[0] = False  # the rest only has to reach 50
    fill_by_kind(good, "known", MAX_COPIES)
    fill_by_kind(rest, "known", MAX_COPIES)
    novel_pool = [c for c in by_score if c not in known]
    if total() < DECK_SIZE:
        notes.append(f"only {total()} cards were in found lists for these colors; the rest are novel picks by plan fit")
        fill_by_kind(novel_pool, "novel", 3)
    if total() < DECK_SIZE:  # still short (a tiny catalog): relax the shape
        shape = {k: DECK_SIZE for k in KINDS}
        fill_by_kind(by_score, "known", 4)

    def requirements() -> list[Requirement]:
        return [Requirement(c, Layer.CORE if role[c] == "core" else Layer.STAPLE, n, max(known.get(c, (0.01, 0))[0], 0.01), (role[c],)) for c, n in chosen.items()]

    style = style_of(requirements(), catalog, signals)
    novel_budget = round(novelty * 10)
    swaps = 0

    def reached(st: Style) -> bool:
        return st.plan is plan

    def miss(st: Style) -> int:
        return abs(st.beatdown - PLAN_SCORE[plan])

    while not reached(style) and swaps < MAX_SWAPS:
        novel_used = sum(1 for c in chosen if role[c] == "novel")
        best: tuple[int, CardNumber, CardNumber] | None = None
        weakest = sorted((c for c in chosen if c not in locked), key=lambda c: (align(signals[c], plan), -known.get(c, (0.0, 0))[0], c))[:12]  # type: ignore[arg-type]
        for out_card in weakest:
            out_kind = catalog[out_card].kind
            for in_card in by_score:
                if in_card in chosen or catalog[in_card].kind is not out_kind:
                    continue
                novel = in_card not in known
                if novel and novel_used >= novel_budget:
                    continue
                if align(signals[in_card], plan) <= align(signals[out_card], plan) + 0.15:  # type: ignore[arg-type]
                    continue
                trial = {**chosen}
                copies = trial.pop(out_card)
                if rules.conflicts(in_card, trial):
                    continue
                trial[in_card] = min(copies, MAX_COPIES, rules.copy_limit(in_card))
                rows = [Requirement(c, Layer.CORE if role.get(c) == "core" else Layer.STAPLE, n, 0.5, ()) for c, n in trial.items()]
                after = style_of(rows, catalog, signals)
                gain = miss(style) - miss(after)
                if gain > 0 and (best is None or gain > best[0]):
                    best = (gain, out_card, in_card)
        if best is None:
            break
        _, out_card, in_card = best
        copies = chosen.pop(out_card)
        kind_count[catalog[out_card].kind] -= copies
        role.pop(out_card)
        add(in_card, min(copies, MAX_COPIES, rules.copy_limit(in_card)), "known" if in_card in known else "novel")
        style = style_of(requirements(), catalog, signals)
        swaps += 1
    broken = rules.violations(chosen)
    if broken:
        notes.append("not legal: " + "; ".join(broken))
    if not reached(style):
        notes.append(f"stayed {style.plan.value} (beatdown {style.beatdown / 10:.1f}) instead of {plan.value}: no swap within the novelty budget moved it closer")

    picks = tuple(
        Pick(c, n, role[c], known.get(c, (0.0, 0))[0], align(signals[c], plan), _why(c, role[c], known, signals, plan, group.get(c, "")), group.get(c, ""))  # type: ignore[arg-type]
        for c, n in sorted(chosen.items(), key=lambda kv: (role[kv[0]] != "core", role[kv[0]] == "novel", group.get(kv[0], "~") == "~", group.get(kv[0], ""), -known.get(kv[0], (0.0, 0))[0], kv[0]))
    )
    def paired_fit(unit: CardNumber, pilot: PilotCard) -> float:
        """How well a Unit suits the plan once this pilot is on it: the pilot's stats added, plus a flat bonus for being usable the turn it is played."""
        base = catalog[unit]
        assert isinstance(base, UnitCard)
        paired = base.model_copy(update={"ap": (base.ap or 0) + pilot.ap_bonus, "hp": (base.hp or 0) + pilot.hp_bonus})
        sig = card_signals(paired)
        return max(0.0, align(sig, plan) if sig is not None else 0.0) + PAIRED_HASTE

    options: list[PilotOption] = []
    for c in by_score:
        pilot_card = catalog[c]
        if c in chosen or not isinstance(pilot_card, PilotCard) or rules.conflicts(c, chosen):
            continue
        linked = [u for u in by_score if isinstance(catalog[u], UnitCard) and satisfies(catalog[u], pilot_card)]
        in_deck = sum(chosen[u] for u in linked if u in chosen)
        fits = sorted((paired_fit(u, pilot_card) + known.get(u, (0.0, 0))[0] for u in linked), reverse=True)
        fit = sum(fits[:PILOT_UNITS]) + 0.1 * in_deck + 0.1 * (pilot_card.ap_bonus + pilot_card.hp_bonus) / 4
        options.append(PilotOption(c, in_deck, tuple(u for u in linked if u not in chosen)[:3], known.get(c, (0.0, 0))[0], fit))
    options.sort(key=lambda o: (-o.fit, -o.pairs_in_deck, o.card))
    pool: dict[CardKind, tuple[PoolCard, ...]] = {}
    for kind in KINDS:
        cards = [c for c in by_score if c not in chosen and catalog[c].kind is kind and not rules.conflicts(c, chosen)]
        pool[kind] = tuple(PoolCard(c, known.get(c, (0.0, 0))[0], align(signals[c], plan), "known" if c in known else "novel") for c in cards[:POOL_SIZE])  # type: ignore[arg-type]
    return Suggestion(package, plan, tuple(sorted(colors)), picks, pool, tuple(d.name for d in references), style, tuple(notes), link_pairs(chosen, catalog), tuple(options))


def _why(card: CardNumber, role: str, known: Mapping[CardNumber, tuple[float, int]], signals: Mapping[CardNumber, CardSignals | None], plan: Plan, bundle: str = "") -> str:
    if role == "core":
        return "the package's core"
    if bundle:
        return f"partner package {bundle}: in {known[card][0]:.0%} of the reference decks" if card in known else f"partner package {bundle}"
    sig = signals[card]
    fit = align(sig, plan) if sig is not None else 0.0
    return (f"in {known[card][0]:.0%} of the reference decks" if card in known else "in no found list") + f"; {plan.value} fit {fit:+.1f}"

