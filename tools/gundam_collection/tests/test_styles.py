"""Deck style: ratings, plan and colors from a deck's cards (synthetic decks with known answers)."""
from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color
from tools.gundam_collection.decks import Layer, Requirement
from tools.gundam_collection.styles import HIGH, LOW, Plan, Style, beatdown_score, plan_of, scale, style_of
from tools.gundam_collection.suggest import align
from tools.gundam_packages.tests.helpers import base, command, unit

N = CardNumber


def deck(*rows: tuple[CardModel, int, Layer]) -> tuple[list[Requirement], dict[CardNumber, CardModel]]:
    return [Requirement(c.number, layer, need, 1.0, ()) for c, need, layer in rows], {c.number: c for c, _, _ in rows}


def test_scale_maps_an_anchor_pair_to_zero_and_a_hundred_and_clamps() -> None:
    assert [scale(x, (0.0, 0.5)) for x in (-1.0, 0.0, 0.25, 0.5, 2.0)] == [0, 0, 50, 100, 100]


def test_the_plan_is_one_beatdown_to_control_axis_over_four_ratings() -> None:
    assert (HIGH, LOW) == (60, 40)
    assert plan_of(48, 24, 71, 40) is Plan.CONTROL and plan_of(49, 25, 71, 40) is Plan.MIDRANGE  # beatdown 40 is control, 41 is midrange
    assert beatdown_score(100, 100, 0, 0) == 100 and beatdown_score(0, 0, 100, 100) == 0 and beatdown_score(50, 50, 50, 50) == 50
    assert plan_of(90, 80, 10, 10) is Plan.AGGRO and plan_of(20, 10, 90, 80) is Plan.CONTROL and plan_of(50, 50, 50, 50) is Plan.MIDRANGE
    assert plan_of(90, 80, 70, 80) is Plan.MIDRANGE  # fast and pressuring but full of answers and cards: neither pure plan
    # advantage weighs in: the same curve, pressure and interaction is aggro without cards and not with them
    assert plan_of(70, 70, 30, 0) is Plan.AGGRO and plan_of(70, 70, 30, 100) is Plan.MIDRANGE
    assert plan_of(40, 0, 100, 40) is Plan.CONTROL  # an all-blocker deck with a medium curve


def test_cheap_units_with_pressure_keywords_and_no_blockers_are_aggro() -> None:
    cheap = unit("GD01-001", "Cheap Breacher", level=2, text="<Breach 2> (...)", color=Color.RED)
    cheaper = unit("GD01-002", "Cheap Suppressor", level=3, text="<Suppression> (...)", color=Color.RED)
    vanilla = unit("GD01-003", "Vanilla", level=2, color=Color.RED)
    requirements, catalog = deck((cheap, 4, Layer.CORE), (cheaper, 4, Layer.CORE), (vanilla, 4, Layer.CORE))
    st = style_of(requirements, catalog)
    assert st.plan is Plan.AGGRO and st.curve == 100 and st.pressure >= 90 and st.interaction == 0
    assert st.colors == ("R",)


def test_blockers_big_units_and_commands_are_control() -> None:
    wall = unit("GD01-011", "Wall", level=6, ap=2, hp=5, text="<Blocker> (Rest this Unit to change the attack target to it.)", color=Color.WHITE)
    giant = unit("GD01-012", "Giant", level=7, ap=3, hp=6, text="<Blocker> (...)\n【Deploy】Draw 1.", color=Color.WHITE)
    burn = command("GD01-013", "Burn", text="【Main】Choose 1 enemy Unit. Deal 2 damage to it.", color=Color.BLUE)
    answer = command("GD01-014", "Answer", text="【Action】Choose 1 enemy Unit. Return it to its owner's hand.", color=Color.BLUE)
    requirements, catalog = deck((wall, 4, Layer.CORE), (giant, 3, Layer.CORE), (burn, 4, Layer.STAPLE), (answer, 4, Layer.STAPLE))
    st = style_of(requirements, catalog)
    assert st.plan is Plan.CONTROL and st.curve == 0 and st.pressure == 0 and st.interaction >= 60
    assert st.finisher > 0 and set(st.colors) == {"W", "B"}  # Lv7 Giant is a finisher


def test_advantage_and_resilience_are_rated_but_do_not_change_the_plan() -> None:
    drawer = unit("GD01-021", "Drawer", level=3, text="【Deploy】Draw 1.", color=Color.GREEN)
    plain = unit("GD01-022", "Plain", level=3, color=Color.GREEN)
    fort = base("GD01-023", "Fort", text="【Burst】Deploy this card.\n【Deploy】Add 1 of your Shields to your hand.", color=Color.GREEN)
    requirements, catalog = deck((drawer, 4, Layer.CORE), (plain, 4, Layer.CORE), (fort, 2, Layer.STAPLE))
    st = style_of(requirements, catalog)
    assert st.advantage > 0 and st.resilience > 0
    requirements2, catalog2 = deck((plain, 4, Layer.CORE), (fort, 2, Layer.STAPLE))
    assert style_of(requirements2, catalog2).plan is st.plan  # advantage is shown, not scored into the plan


def test_options_count_half_and_a_deck_without_units_does_not_crash() -> None:
    a = unit("GD01-031", "A", level=2, text="<Breach 2> (...)", color=Color.RED)
    b = unit("GD01-032", "B", level=2, color=Color.RED)
    full, cat = deck((a, 4, Layer.CORE), (b, 4, Layer.CORE))
    half, cat2 = deck((a, 4, Layer.CORE), (b, 4, Layer.OPTION))
    assert style_of(half, cat2).facts["AP>HP or pressure keyword"] > style_of(full, cat).facts["AP>HP or pressure keyword"]  # the option copies weigh less
    none = style_of([], {})
    assert none.colors == () and none.plan in Plan and none.curve >= 0


def test_pressure_rises_with_ap_over_hp_and_pressure_keywords_and_falls_with_ap_under_hp() -> None:
    glass = unit("GD01-041", "Glass Cannon", level=3, ap=5, hp=2, color=Color.RED)
    tank = unit("GD01-042", "Tank", level=3, ap=2, hp=5, color=Color.RED)
    breacher = unit("GD01-043", "Sturdy Breacher", level=3, ap=2, hp=5, text="<Breach 2> (...)", color=Color.RED)
    even = unit("GD01-044", "Even", level=3, ap=3, hp=3, color=Color.RED)

    def rq(*cs: CardModel) -> Style:
        return style_of(*deck(*((c, 4, Layer.CORE) for c in cs)))

    assert rq(glass).pressure == 100 and rq(tank).pressure == 0 and rq(even).pressure == 50  # all glass cannons / all tanks / neutral
    assert rq(glass, tank).pressure == 50  # half and half cancel
    assert rq(breacher).pressure == 50  # a pressure keyword counts as pushing; the AP<HP counts against: net neutral


def test_blockers_and_unit_abilities_are_interaction_not_pressure() -> None:
    wall = unit("GD01-051", "Wall", level=4, ap=3, hp=3, text="<Blocker> (Rest this Unit to change the attack target to it.)", color=Color.WHITE)
    pinger = unit("GD01-052", "Pinger", level=4, ap=3, hp=3, text="【Deploy】Choose 1 enemy Unit. Deal 1 damage to it.", color=Color.WHITE)
    vanilla = unit("GD01-053", "Vanilla", level=4, ap=3, hp=3, color=Color.WHITE)
    walls = style_of(*deck((wall, 4, Layer.CORE)))
    assert walls.pressure == 50 and walls.interaction == 100  # a Blocker does not lower pressure; it raises interaction
    assert style_of(*deck((pinger, 4, Layer.CORE))).interaction == 100  # a Unit whose ability hits the board counts in full
    assert style_of(*deck((vanilla, 4, Layer.CORE))).interaction == 0  # turn it sideways


def test_a_bases_baseline_shield_to_hand_is_not_card_advantage() -> None:
    plain_base = base("GD01-061", "Plain Base", text="【Burst】Deploy this card.\n【Deploy】Add 1 of your Shields to your hand.", color=Color.BLUE)
    drawing_base = base("GD01-062", "Drawing Base", text="【Burst】Deploy this card.\n【Deploy】Add 1 of your Shields to your hand.\n【Main】Draw 1.", color=Color.BLUE)
    assert style_of(*deck((plain_base, 4, Layer.CORE))).advantage == 0  # nothing but the baseline
    assert style_of(*deck((drawing_base, 4, Layer.CORE))).advantage == 100  # a Base that actually draws


def test_advantage_means_a_card_in_hand_and_a_condition_halves_it() -> None:
    from tools.gundam_collection.styles import advantage_weight as aw

    assert aw("【Main】Draw 2. Then, discard 1.") == 1.0  # draw then discard still puts a card in hand
    assert aw("【Main】Discard 1. If you do, draw 2.") == 1.0  # "if you do" is the cost, not a condition
    assert aw("【When Paired】Draw 1. Then, discard 1. If you discard a (Special Move) Command card with this effect, you may activate its 【Main】.") == 1.0  # the if comes after
    assert aw("【Attack】If this Unit is damaged, draw 1.") == 0.5  # Barbatos 1st Form: conditional
    assert aw("【Main】Choose 1 enemy Unit. Deal 2 damage to it. Then, if you have a Unit with \"Master Gundam\" in play, draw 1.") == 0.5  # Darkness Finger
    assert aw("【When Linked】Look at the top 2 cards of your deck and return 1 to the top. Place the remaining card into your trash. If there is a player with 3 or less Shields, add the card to your hand instead of returning it to your deck.") == 0.5  # Ple-Twelve
    assert aw("【Destroyed】Look at the top 3 cards of your deck. You may reveal 1 (Zeon) Unit card among them and add it to your hand.") == 0.5  # filtered, and only when destroyed
    assert aw("【When Paired】Choose 1 Command card that is Lv.5 or lower from your trash. Add it to your hand.") == 0.5  # needs a target in the trash
    assert aw("【Main】Look at the top 5 cards of your deck. Return them to the bottom of your deck.") == 0.0  # looking is not advantage
    assert aw("【Burst】Add this card to your hand.") == 0.0  # every pilot's baseline
    assert aw("【Main】Choose 1 Unit card from your trash. Deploy it rested.") == 0.0  # deploying from the trash is not a card in hand


def test_ratings_are_shown_out_of_ten_with_one_decimal() -> None:
    from tools.gundam_collection.cli import _r10

    assert [_r10(v).strip() for v in (0, 16, 42, 100)] == ["0.0", "1.6", "4.2", "10.0"]


def test_a_base_counts_toward_curve_pressure_and_interaction_like_a_body() -> None:
    from tools.gundam_collection.styles import card_signals as signals

    baseline = "【Burst】Deploy this card.\n【Deploy】Add 1 of your Shields to your hand."
    corsica = base("ST02-016", "Corsica-like", level=3, text=baseline + " Then, deploy 1 [Tallgeese]((OZ)･AP4･HP2) Unit token.")  # cheap, and a 4/2 body
    wall = base("GD01-081", "Wall Base", level=3, text=baseline + " Then, deploy 1 [Wall]((OZ)･AP1･HP3) Unit token.")  # a sturdy body
    fight = base("GD05-128", "Fight-like", level=3, text=baseline + "\n【Main】Choose 1 enemy Unit. Deal 1 damage to it.")  # hits the board
    heavy = base("GD01-082", "Heavy Base", level=5, text=baseline)
    s_corsica, s_wall, s_fight, s_heavy = signals(corsica), signals(wall), signals(fight), signals(heavy)
    assert s_corsica is not None and s_wall is not None and s_fight is not None and s_heavy is not None
    assert s_corsica.low and s_corsica.pushing and not s_corsica.sturdy and s_corsica.advantage == 0  # the Shield line is not advantage
    assert s_wall.sturdy and not s_wall.pushing and s_fight.interactive and not s_heavy.low
    assert align(s_corsica, Plan.AGGRO) > 0.5 > align(s_fight, Plan.AGGRO)  # Corsica is an aggro card, Gundam Fight is not
    assert style_of(*deck((corsica, 4, Layer.CORE))).pressure == 100 and style_of(*deck((wall, 4, Layer.CORE))).pressure == 0
    assert style_of(*deck((fight, 4, Layer.CORE))).interaction == 100 and style_of(*deck((heavy, 4, Layer.CORE))).interaction == 0


def test_a_burst_effect_that_puts_a_card_in_hand_is_advantage_and_the_pilot_baseline_is_not() -> None:
    from tools.gundam_collection.styles import advantage_weight as aw

    assert aw("【Burst】Draw 1.\n【Main】Choose 1 enemy Unit. Deal 2 damage to it.") == 1.0  # a Burst draw counts
    assert aw("【Burst】If you have 3 or less Shields, draw 1.") == 0.5  # conditional: half
    assert aw("【Burst】Add this card to your hand.") == 0.0  # every pilot has it


def test_link_pairs_are_rated_but_do_not_move_the_plan() -> None:
    from tools.gundam_packages.tests.helpers import pilot

    linked = unit("GD01-001", "Linked", level=3, ap=3, hp=3, link="Partner")
    partner = pilot("GD01-002", "Partner")
    with_pilots, catalog = deck((linked, 4, Layer.CORE), (partner, 4, Layer.CORE))
    cards = {**catalog}
    without = [r for r in with_pilots if r.card != partner.number]
    paired, bare = style_of(with_pilots, cards), style_of(without, cards)
    assert paired.facts["link pairs"] == 4 and bare.facts["link pairs"] == 0
    assert paired.links == scale(4, (0.0, 12.0)) and bare.links == 0
    assert paired.plan is bare.plan  # every plan wants Link pairs: the rating does not feed the plan axis
