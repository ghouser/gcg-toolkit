"""What to buy to play more of an archetype (design.md, "Buy recommendations").

Pure functions over decks and a `coverage_of(deck, owned)` function (so a purchase can be tried on paper). The plan is greedy and deterministic: the deck
of the archetype that is cheapest to make **Playable** goes first; its copies count as bought; the next deck is chosen by its *incremental* cost (cards
the first deck already needs are free); and so on. Premium cards ($10 or more) are always considered but never included unless asked: a deck that needs
one stays in the plan with its regular copies, the premium copies are **skipped** (not bought, not in the totals), and it is marked as not reaching Playable
until they are approved; such decks come after the decks that can be finished. Nothing here buys or fetches anything.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from shared.basetypes import CardNumber
from tools.gundam_collection.bands import Band, NextBand, cost_to
from tools.gundam_collection.decks import PREMIUM_CENTS, Deck, DeckCoverage

CoverageOf = Callable[[Deck, Mapping[CardNumber, int]], DeckCoverage]


@dataclass(frozen=True)
class Line:
    """Copies of one card to buy for a deck, and why."""

    card: CardNumber
    copies: int
    unit_cents: int | None
    why: tuple[str, ...]
    also: tuple[str, ...]  # the other decks of the archetype that need more of it too

    @property
    def line_cents(self) -> int | None:
        return None if self.unit_cents is None else self.copies * self.unit_cents

    @property
    def premium(self) -> bool:
        return self.unit_cents is not None and self.unit_cents >= PREMIUM_CENTS


@dataclass(frozen=True)
class Step:
    deck: Deck
    lines: tuple[Line, ...]  # to buy
    held_back: tuple[Line, ...]  # premium copies this deck needs: skipped (not in the cost, not counted as bought), they need approval
    cost_cents: int
    unpriced: int  # copies with no price (so the cost is a minimum)
    running_cents: int  # the total so far, this step included
    also_moves: tuple[tuple[str, Band, Band], ...]  # other decks of the archetype this step moves up: name, from, to


@dataclass(frozen=True)
class BuyPlan:
    already: tuple[tuple[Deck, Band], ...]  # decks of the archetype I can already play
    steps: tuple[Step, ...]
    polish: tuple[Step, ...]  # to take every Playable deck (already, or from the steps) to Complete (only with polish)


def archetype_names(decks: Sequence[Deck], text: str) -> list[str]:
    """The archetypes whose name has every word of `text`, in the order of their first deck."""
    words = text.casefold().split()
    seen: list[str] = []
    for deck in decks:
        if deck.archetype and deck.archetype not in seen and all(w in deck.archetype.casefold() for w in words):
            seen.append(deck.archetype)
    return seen


def decks_with_package(decks: Sequence[Deck], text: str) -> list[Deck]:
    """The decks that contain a package, in any role: a package's anchor card (`ST11-001` or `pkg:ST11-001`) or words of its name as the decks show it
    (`char aznable (b)`)."""
    query = text.strip().casefold()
    anchor = re.fullmatch(r"(?:pkg:)?([a-z]+\d+-\d+)", query)
    found = []
    for deck in decks:
        if anchor and anchor.group(1).upper() in {a.upper() for a in deck.anchors}:
            found.append(deck)
        elif not anchor and query and any(query in label.casefold() for label in (deck.package_labels or (deck.plain_name,))):
            found.append(deck)
    return found


def _lines(cov: DeckCoverage, up: NextBand, others: Sequence[DeckCoverage]) -> list[Line]:
    reasons = {r.card: r.why for r in cov.deck.requirements}
    lines: list[Line] = []
    for card, copies in up.buys:
        price = next((n.unit_cents for n in cov.needs() if n.card == card), None)
        also = tuple(sorted(o.deck.name for o in others if any(n.card == card and n.have < n.need for n in o.needs())))
        lines.append(Line(card, copies, price, reasons.get(card, ()), also))
    return lines


def _split(lines: Sequence[Line], include_premium: bool) -> tuple[list[Line], list[Line]]:
    held = [] if include_premium else [ln for ln in lines if ln.premium]
    return [ln for ln in lines if ln not in held], held


def _cost(lines: Sequence[Line]) -> tuple[int, int]:
    return sum(ln.line_cents or 0 for ln in lines), sum(ln.copies for ln in lines if ln.unit_cents is None)


def plan_buy(
    decks: Sequence[Deck],
    coverage_of: CoverageOf,
    owned: Mapping[CardNumber, int],
    *,
    include_premium: bool = False,
    steps: int = 3,
    polish: bool = False,
) -> BuyPlan:
    have = dict(owned)
    current = {d.id: coverage_of(d, have) for d in decks}
    already = tuple((d, current[d.id].band) for d in decks if current[d.id].playable)
    todo = [d for d in decks if not current[d.id].playable]
    chosen: list[Deck] = []
    out: list[Step] = []
    running = 0
    for _ in range(steps):
        options: list[tuple[tuple[object, ...], Deck, list[Line], list[Line], tuple[int, int]]] = []
        for d in todo:
            cov = coverage_of(d, have)
            if cov.playable:
                continue
            others = [coverage_of(o, have) for o in decks if o.id != d.id]
            lines = _lines(cov, cost_to(cov.needs(), Band.PLAYABLE), others)
            regular, held = _split(lines, include_premium)
            cents, unpriced = _cost(regular)
            options.append((((bool(held), unpriced > 0, cents, -d.top_rate, d.name)), d, regular, held, (cents, unpriced)))  # decks that can be finished come first
        if not options:
            break
        _, deck, lines, held, (cents, unpriced) = min(options, key=lambda o: o[0])
        before = {o.id: coverage_of(o, have).band for o in decks}
        for ln in lines:
            have[ln.card] = have.get(ln.card, 0) + ln.copies
        running += cents
        moved = tuple((o.name, before[o.id], coverage_of(o, have).band) for o in decks if o.id != deck.id and coverage_of(o, have).band != before[o.id])
        out.append(Step(deck, tuple(lines), tuple(held), cents, unpriced, running, moved))
        chosen.append(deck)
        todo = [d for d in todo if d.id != deck.id]
    extra: list[Step] = []
    if polish:  # every deck that is Playable (already, or from the steps) and not yet Complete, cheapest first, shared copies counted once
        pending = [d for d in decks if coverage_of(d, have).band is Band.PLAYABLE]
        while pending:
            options = []
            for d in pending:
                cov = coverage_of(d, have)
                regular, held = _split(_lines(cov, cost_to(cov.needs(), Band.COMPLETE), []), include_premium)
                cents, unpriced = _cost(regular)
                options.append(((bool(held), unpriced > 0, cents, -d.top_rate, d.name), d, regular, held, (cents, unpriced)))
            _, deck, regular, held, (cents, unpriced) = min(options, key=lambda o: o[0])
            for ln in regular:
                have[ln.card] = have.get(ln.card, 0) + ln.copies
            running += cents
            extra.append(Step(deck, tuple(regular), tuple(held), cents, unpriced, running, ()))
            pending = [d for d in pending if d.id != deck.id]
    return BuyPlan(already, tuple(out), tuple(extra))


def mass_entry(plan: BuyPlan, meta: Mapping[CardNumber, tuple[str, str]], names: Mapping[CardNumber, str]) -> list[str]:
    """TCGPlayer Mass Entry lines, `4 Char's Gelgoog [GD01]`, one per card, copies added up across the steps (premium held-back cards are not in them)."""
    total: dict[CardNumber, int] = {}
    for step in (*plan.steps, *plan.polish):
        for ln in step.lines:
            total[ln.card] = total.get(ln.card, 0) + ln.copies
    lines = []
    for card, copies in sorted(total.items(), key=lambda kv: (names.get(kv[0], str(kv[0])).casefold(), kv[0])):
        name, set_code = meta.get(card, (names.get(card, str(card)), str(card).split("-")[0]))
        lines.append(f"{copies} {name} [{set_code}]")
    return lines

