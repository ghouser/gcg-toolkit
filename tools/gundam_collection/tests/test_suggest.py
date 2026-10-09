"""Hypothetical decks: an exact 50 from the package core, found lists and plan fit, on a synthetic world with known answers."""
from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color, color_of
from tools.gundam_collection.decks import Deck, Layer, Requirement, deck_id
from tools.gundam_collection.styles import Plan, card_signals
from tools.gundam_collection.suggest import Prefer, align, build_suggestion
from tools.gundam_packages.models import DataSource, PackageId
from tools.gundam_packages.tests.helpers import catalog, command, pilot, unit

N = CardNumber
T = DataSource.TOURNAMENT
BREACH = "<Breach 2> (When this Unit's attack destroys an enemy Unit, deal the specified amount of damage to the first card in that opponent's shield area.)"
BLOCKER = "<Blocker> (Rest this Unit to change the attack target to it.)"

CORE = unit("GD01-001", "Core Unit", level=2, ap=4, hp=2, link="Pilot X", color=Color.RED)
CORE_PILOT = pilot("GD01-002", "Pilot X", color=Color.RED)
RUNNERS = [unit(f"GD02-{i:03}", f"Runner {i}", level=2, ap=4, hp=2, text=BREACH if i % 2 else "", color=Color.BLUE if i % 3 else Color.RED) for i in range(1, 15)]
WALLS = [unit(f"GD03-{i:03}", f"Wall {i}", level=6, ap=2, hp=5, text=BLOCKER + ("\n【Deploy】Draw 1." if i % 2 else ""), color=Color.BLUE) for i in range(1, 9)]
ANSWERS = [command(f"GD04-{i:03}", f"Answer {i}", text="【Action】Choose 1 enemy Unit. Return it to its owner's hand.", color=Color.BLUE) for i in range(1, 7)]
STRANGER = unit("GD05-001", "Needs A Stranger", level=2, ap=4, hp=2, link="Nobody Here", color=Color.RED)
STRANGER_PILOT = pilot("GD05-002", "Unrelated Pilot", color=Color.RED)
GREEN = unit("GD05-003", "Green Unit", level=2, ap=4, hp=2, color=Color.GREEN)
CARDS: dict[CardNumber, CardModel] = catalog(CORE, CORE_PILOT, *RUNNERS, *WALLS, *ANSWERS, STRANGER, STRANGER_PILOT, GREEN)
CORE_COPIES = {CORE.number: 4, CORE_PILOT.number: 4}


def found(name: str, cards: list[CardModel], rate: float = 0.1) -> Deck:
    reqs = tuple(Requirement(c.number, Layer.STAPLE, 4, 0.9, ()) for c in cards)
    anchors = (str(CORE.number),)
    return Deck(name=name, package_refs=((name, T, PackageId(f"pkg:{anchors[0]}")),), rates={T: rate}, low_sample=False, requirements=reqs, anchors=anchors,
                id=deck_id(anchors) + name, plain_name=name)  # fmt: skip


AGGRO_REF = found("Aggro ref", [CORE, CORE_PILOT, *RUNNERS])
CONTROL_REF = found("Control ref", [CORE, CORE_PILOT, *WALLS, *ANSWERS])


def build(plan: Plan = Plan.AGGRO, colors: frozenset[str] = frozenset({"R", "B"}), refs: list[Deck] | None = None, **kw: object) -> object:
    return build_suggestion(package="Core", core=CORE_COPIES, plan=plan, colors=colors, references=refs if refs is not None else [AGGRO_REF], plan_decks=[],
                            catalog=CARDS, owned=kw.pop("owned", {}), prices=kw.pop("prices", {}), **kw)  # type: ignore[arg-type]  # fmt: skip


def test_the_deck_is_an_exact_fifty_with_the_core_locked_and_never_more_than_four_of_a_card() -> None:
    sug = build()
    assert sug.copies == 50 and all(p.copies <= 4 for p in sug.picks)  # type: ignore[attr-defined]
    core = {p.card: p.copies for p in sug.picks if p.role == "core"}  # type: ignore[attr-defined]
    assert core == CORE_COPIES  # the package's core is locked at its real copy counts


def test_only_cards_of_the_chosen_colors_are_used() -> None:
    sug = build()
    assert all(color_of(CARDS[p.card]) is not Color.GREEN for p in sug.picks)  # type: ignore[attr-defined]
    assert N("GD05-003") not in {p.card for p in sug.picks}  # type: ignore[attr-defined]


def test_a_link_is_a_bonus_not_a_gate_a_unit_without_its_pilot_ranks_lower_and_an_unrelated_pilot_is_only_a_stat_bonus() -> None:
    sug = build(refs=[found("Ref", [CORE, CORE_PILOT, STRANGER, STRANGER_PILOT, *RUNNERS])])
    chosen = {p.card: p.copies for p in sug.picks}  # type: ignore[attr-defined]
    assert STRANGER.number not in chosen  # same fit as a runner but its Link has no pilot: a weaker body, so it loses the slot to an equal runner
    assert chosen.get(STRANGER_PILOT.number, 0) <= 1  # an unrelated pilot pairs with no Linked Unit: at most a single stat-bonus copy
    pairs, linked, pilots = sug.pairs  # type: ignore[attr-defined]
    assert pairs >= 4 and linked >= 4  # the core Unit and its 4 pilot copies pair up


def test_a_lone_pilot_copy_with_no_pull_toward_the_plan_is_a_filler_slot_and_is_left_out() -> None:
    filler = pilot("GD07-001", "Filler Pilot", color=Color.RED)
    one_link = unit("GD07-002", "One Link", level=2, ap=4, hp=2, link="Filler Pilot", color=Color.RED)
    cards = catalog(CORE, CORE_PILOT, *RUNNERS, *WALLS, *ANSWERS, filler, one_link)
    sug = build_suggestion(package="Core", core={CORE.number: 4, CORE_PILOT.number: 4}, plan=Plan.AGGRO, colors=frozenset({"R", "B"}),
                           references=[found("Ref", [CORE, CORE_PILOT, filler, one_link, *RUNNERS])], plan_decks=[], catalog=cards, owned={}, prices={})  # fmt: skip
    chosen = {p.card: p.copies for p in sug.picks}
    assert chosen.get(filler.number, 0) == 0 or chosen[filler.number] >= 2  # never a single stat-bonus copy picked up on its own


def test_pairs_are_counted_by_pilot_copies_and_the_linked_units_they_satisfy() -> None:
    from tools.gundam_collection.styles import link_pairs

    chosen = {CORE.number: 4, CORE_PILOT.number: 3, STRANGER.number: 2, STRANGER_PILOT.number: 2}
    assert link_pairs(chosen, CARDS) == (3, 6, 5)  # 3 of the 4 core Units get a pilot; the stranger's Link has none; 5 pilot copies in all


def test_a_partner_package_from_the_reference_decks_comes_in_whole_a_pilot_with_its_units() -> None:
    p_unit = unit("GD06-001", "Partner Unit", level=2, ap=4, hp=2, link="Partner Pilot", color=Color.BLUE, text=BREACH)
    p_pilot = pilot("GD06-002", "Partner Pilot", color=Color.BLUE)
    cards = catalog(CORE, CORE_PILOT, *RUNNERS, *WALLS, *ANSWERS, p_unit, p_pilot)
    reqs = (
        *(Requirement(c.number, Layer.CORE, 4, 1.0, ("core of Core",)) for c in (CORE, CORE_PILOT)),
        *(Requirement(c.number, Layer.CORE, 4, 1.0, ("core of Partner Package",)) for c in (p_unit, p_pilot)),
        *(Requirement(c.number, Layer.STAPLE, 4, 0.9, ("in 90% of its lists",)) for c in RUNNERS),
    )
    anchors = (str(CORE.number),)
    ref = Deck(name="Ref", package_refs=(("Ref", T, PackageId(f"pkg:{anchors[0]}")),), rates={T: 0.05}, low_sample=False, requirements=reqs, anchors=anchors, id="x", plain_name="Ref")
    sug = build_suggestion(package="Core", core=CORE_COPIES, plan=Plan.AGGRO, colors=frozenset({"R", "B"}), references=[ref], plan_decks=[], catalog=cards, owned={}, prices={})
    grouped = {p.card: p.group for p in sug.picks if p.group}
    assert grouped == {p_unit.number: "Partner Package", p_pilot.number: "Partner Package"}  # the pilot and its Unit, together, labeled with their package
    assert {p.card: p.copies for p in sug.picks}[p_pilot.number] == 4 and sug.pairs[0] >= 8  # 4 core pairs and 4 partner pairs


def test_other_pilots_are_listed_with_the_units_they_would_link_and_the_pairs_they_make_in_the_deck() -> None:
    sug = build()
    options = {o.card: o for o in sug.pilot_options}  # type: ignore[attr-defined]
    assert STRANGER_PILOT.number in options or CORE_PILOT.number not in options  # pilots in the deck are not offered again
    assert all(o.card not in {p.card for p in sug.picks} for o in sug.pilot_options)  # type: ignore[attr-defined]


def test_other_pilots_are_ranked_by_the_plan_fit_of_the_units_they_link_with_their_stats_added() -> None:
    sug = build()
    fits = [o.fit for o in sug.pilot_options]  # type: ignore[attr-defined]
    assert fits == sorted(fits, reverse=True) and all(f >= 0 for f in fits)  # best first, whether or not it pairs with anything in the deck yet


def test_an_aggro_request_gives_an_aggro_deck_and_a_control_request_a_control_one() -> None:
    aggro = build(Plan.AGGRO, refs=[AGGRO_REF, CONTROL_REF])
    control = build(Plan.CONTROL, refs=[AGGRO_REF, CONTROL_REF])
    assert aggro.style.plan is Plan.AGGRO and aggro.style.curve > control.style.curve  # type: ignore[attr-defined]
    assert control.style.plan is Plan.CONTROL and control.style.beatdown <= 40 and aggro.style.beatdown > 60  # type: ignore[attr-defined]
    assert N("GD03-001") not in {p.card for p in aggro.picks}  # type: ignore[attr-defined]  # a Lv6 Blocker is not in the aggro build


def test_found_decks_of_another_plan_do_not_feed_the_known_cards_and_it_says_so() -> None:
    sug = build(Plan.AGGRO, refs=[AGGRO_REF, CONTROL_REF])
    assert any("another plan" in n for n in sug.notes)  # type: ignore[attr-defined]
    assert not any(p.card in {w.number for w in WALLS} and p.role == "known" for p in sug.picks)  # type: ignore[attr-defined]


def test_cards_in_no_found_list_are_labeled_novel_and_zero_novelty_only_uses_them_to_reach_fifty() -> None:
    sparse = found("Sparse", [CORE, CORE_PILOT, *RUNNERS[:3]])  # too few known cards to make 50
    sug = build(refs=[sparse], novelty=0.0)
    assert sug.copies == 50 and any(p.role == "novel" for p in sug.picks)  # type: ignore[attr-defined]
    assert any("novel" in n for n in sug.notes)  # type: ignore[attr-defined]


def test_prefer_owned_breaks_near_ties_toward_cards_i_have() -> None:
    sparse = found("Sparse", [CORE, CORE_PILOT])  # nothing known: every pick is fit-ranked, so ties are everywhere
    tail = {RUNNERS[12].number, RUNNERS[13].number}  # the last two runners: left out of the plain build, which fills in card-number order
    owned = dict.fromkeys(tail, 4)
    plain = build(refs=[sparse], novelty=1.0)
    mine = build(refs=[sparse], novelty=1.0, owned=owned, prefer=Prefer.OWNED)
    assert not (tail & {p.card for p in plain.picks}) and tail <= {p.card for p in mine.picks}  # type: ignore[attr-defined]
    assert plain.copies == mine.copies == 50  # type: ignore[attr-defined]


def test_prefer_cost_drops_pricey_cards_when_cheaper_ones_fit_equally() -> None:
    sparse = found("Sparse", [CORE, CORE_PILOT])
    expensive = {r.number for r in RUNNERS[:6]}
    prices = dict.fromkeys(expensive, 5000)
    plain = {p.card for p in build(refs=[sparse], novelty=1.0).picks}  # type: ignore[attr-defined]
    cheap = {p.card for p in build(refs=[sparse], novelty=1.0, prices=prices, prefer=Prefer.COST).picks}  # type: ignore[attr-defined]
    assert expensive <= plain and len(expensive & cheap) < len(expensive)  # the default takes all six; preferring cost leaves some out


def test_the_pool_holds_the_best_cards_not_chosen_and_never_a_card_in_the_deck() -> None:
    sug = build()
    chosen = {p.card for p in sug.picks}  # type: ignore[attr-defined]
    pooled = [c.card for cards in sug.pool.values() for c in cards]  # type: ignore[attr-defined]
    assert pooled and not (set(pooled) & chosen)


def test_alignment_rewards_cheap_hard_hitting_units_for_aggro_and_blockers_for_control() -> None:
    runner, wall = card_signals(RUNNERS[0]), card_signals(WALLS[1])
    assert runner is not None and wall is not None
    assert align(runner, Plan.AGGRO) > 0.5 > align(wall, Plan.AGGRO) and align(wall, Plan.CONTROL) > align(runner, Plan.CONTROL)
