"""The buy plan on a small world worked out by hand: cheapest deck first, then incremental costs, premium held back, nothing past 4 copies."""
from __future__ import annotations

from collections.abc import Mapping

from shared.basetypes import CardNumber
from tools.gundam_collection.bands import Band
from tools.gundam_collection.buy import archetype_names, mass_entry, plan_buy
from tools.gundam_collection.decks import Deck, DeckCoverage, Layer, Requirement, coverage, deck_id
from tools.gundam_packages.models import DataSource, PackageId

N = CardNumber
C1, C2, C3, P1 = N("GD01-001"), N("GD01-002"), N("GD01-003"), N("GD01-099")
PRICES = {C1: 100, C2: 200, C3: 100, P1: 2000}  # P1 is premium ($20)


def deck(name: str, archetype: str, *cards: tuple[CardNumber, int], rate: float = 0.05) -> Deck:
    anchors = (str(cards[0][0]),)
    return Deck(name=name, package_refs=((name, DataSource.TOURNAMENT, PackageId(f"pkg:{anchors[0]}")),), rates={DataSource.TOURNAMENT: rate}, low_sample=False,
                requirements=tuple(Requirement(c, Layer.CORE, need, 1.0, (f"core of {name}",)) for c, need in cards), anchors=anchors, id=deck_id(anchors) + f"+{name}", plain_name=name,
                archetype=archetype)  # fmt: skip


def cov(d: Deck, owned: Mapping[CardNumber, int]) -> DeckCoverage:
    return coverage(d, (), owned, PRICES, {})


X = deck("X", "Test aggro", (C1, 4), (C2, 4))
Y = deck("Y", "Test aggro", (C1, 4), (C3, 4))
Z = deck("Z", "Test aggro", (P1, 4), (C3, 4))


def test_the_cheapest_deck_to_make_playable_goes_first_and_the_next_is_priced_incrementally() -> None:
    # X: guard forces 2 C1 + 2 C2, then 2 more of the cheapest (C1): 4 x C1 + 2 x C2 = $8.00. Y: 2 C1 + 2 C3, then 2 more C1 = $6.00.
    plan = plan_buy([X, Y], cov, {})
    assert [s.deck.name for s in plan.steps] == ["Y", "X"] and [s.cost_cents for s in plan.steps] == [600, 400]  # X's C1 copies are already bought for Y
    assert {ln.card: ln.copies for ln in plan.steps[0].lines} == {C1: 4, C3: 2} and {ln.card: ln.copies for ln in plan.steps[1].lines} == {C2: 2}
    assert plan.steps[1].running_cents == 1000


def test_a_step_says_which_other_decks_it_moves_up_and_decks_already_playable_are_not_bought_for() -> None:
    q = deck("Q", "Test aggro", (C1, 4))
    plan = plan_buy([q, X], cov, {}, steps=1)  # Q is $3.00 (3 of C1), X is $8.00: Q first
    assert plan.steps[0].deck.name == "Q" and plan.steps[0].cost_cents == 300
    assert [(name, was, now) for name, was, now in plan.steps[0].also_moves] == [("X", Band.NOT_HAPPENING, Band.LONG_SHOT)]  # the C1 copies also help X
    done = plan_buy([X, Y], cov, {C1: 4, C2: 2}, steps=1)  # X is already playable; Y needs 2 C3 only
    assert [d.name for d, _ in done.already] == ["X"] and [s.deck.name for s in done.steps] == ["Y"] and done.steps[0].cost_cents == 200


def test_a_deck_that_needs_a_premium_copy_stays_in_the_plan_with_the_premium_copies_skipped() -> None:
    plan = plan_buy([Y, Z], cov, {})
    assert [s.deck.name for s in plan.steps] == ["Y", "Z"]  # Z is considered, after the deck that can be finished
    z = plan.steps[1]
    assert [(ln.card, ln.copies) for ln in z.held_back] == [(P1, 2)] and z.held_back[0].premium  # 2 of 4 forced by the guard: skipped
    assert {ln.card: ln.copies for ln in z.lines} == {C3: 2} and z.cost_cents == 200  # Y already bought 2 C3; the guard's 2 premium are skipped, so 2 more cheapest copies are planned; no premium in the cost
    assert all(ln.card != P1 for s in plan.steps for ln in s.lines)  # a skipped copy is never in the lines to buy
    included = plan_buy([Y, Z], cov, {}, include_premium=True)
    assert {s.deck.name for s in included.steps} == {"Y", "Z"} and all(not s.held_back for s in included.steps)  # approved: planned like any other


def test_polish_takes_the_chosen_decks_to_complete_and_counts_owned_copies() -> None:
    plan = plan_buy([Y], cov, {}, steps=1, polish=True)
    assert plan.steps[0].cost_cents == 600 and len(plan.polish) == 1 and plan.polish[0].deck.name == "Y"
    assert all(ln.copies > 0 for ln in plan.polish[0].lines)  # only what is still missing after the Playable step


def test_mass_entry_lines_add_up_copies_across_steps_and_leave_out_held_back_premium() -> None:
    plan = plan_buy([X, Y, Z], cov, {}, polish=True)
    meta = {C1: ("Char's Gelgoog", "GD01"), C2: ("Second", "GD01_b")}
    lines = mass_entry(plan, meta, {C1: "x", C2: "y", C3: "Third", P1: "Premium"})
    assert "4 Char's Gelgoog [GD01]" in lines and any(ln.endswith("[GD01_b]") for ln in lines) and "Third" in " ".join(lines)
    assert all("Premium" not in ln for ln in lines)  # held back: needs approval
    assert all(int(ln.split()[0]) <= 4 for ln in lines)  # never more than 4 of a card


def test_archetype_names_match_every_word_and_never_guess() -> None:
    a = deck("A", "Suletta Aerial midrange", (C1, 4))
    b = deck("B", "Suletta Aerial control", (C2, 4))
    c = deck("C", "Kira control", (C3, 4))
    assert archetype_names([a, b, c], "suletta") == ["Suletta Aerial midrange", "Suletta Aerial control"]
    assert archetype_names([a, b, c], "suletta control") == ["Suletta Aerial control"] and archetype_names([a, b, c], "nothing") == []
    assert plan_buy([a], cov, {C1: 4}).already == ((a, Band.PERFECT),)


def test_polish_also_covers_a_deck_that_was_already_playable_and_counts_shared_copies_once() -> None:
    plan = plan_buy([X, Y], cov, {C1: 4, C2: 2}, polish=True)  # X is already playable (6 of 8); Y becomes playable in step 1 (it needs 2 C3)
    assert [d.name for d, _ in plan.already] == ["X"] and [s.deck.name for s in plan.steps] == ["Y"]
    polished = {s.deck.name: s for s in plan.polish}
    assert set(polished) == {"X", "Y"}  # the already-playable deck is no longer left out of the path to Complete
    assert {ln.card: ln.copies for ln in polished["X"].lines} == {C2: 2} and polished["X"].cost_cents == 400  # the last 2 of C2
    assert sum(s.cost_cents for s in plan.steps) + sum(s.cost_cents for s in plan.polish) == plan.polish[-1].running_cents  # one running total


def test_decks_are_found_by_a_package_in_any_role_by_anchor_or_by_its_name_as_shown() -> None:
    from dataclasses import replace

    a = replace(deck("A", "Barbatos aggro", (C1, 4)), anchors=("GD02-054", "ST11-001"), package_labels=("Mikazuki Barbatos", "Char Aznable (B)"))
    b = replace(deck("B", "Amuro aggro", (C2, 4)), anchors=("ST01-001", "ST11-001"), package_labels=("Amuro Ray", "Char Aznable (B)"))
    c = replace(deck("C", "Char aggro", (C3, 4)), anchors=("GD01-026",), package_labels=("Char Aznable (G)",))
    from tools.gundam_collection.buy import decks_with_package

    assert [d.name for d in decks_with_package([a, b, c], "char aznable (b)")] == ["A", "B"]  # both decks that contain the blue package, whatever its role
    assert [d.name for d in decks_with_package([a, b, c], "ST11-001")] == ["A", "B"] and [d.name for d in decks_with_package([a, b, c], "pkg:GD01-026")] == ["C"]
    assert decks_with_package([a, b, c], "char aznable (b) (g)") == [] and decks_with_package([a, b, c], "  ") == []
