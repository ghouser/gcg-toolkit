"""Alternatives: same-job cards for a required card, counted only for cards real decks do not play as core or staples."""
from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color
from tools.gundam_collection.alternatives import ALT_MIN_SHARE, candidates, main_colors, owned_alternatives, slot_alternatives
from tools.gundam_packages.models import Squad, SquadCard, SynergyKind
from tools.gundam_packages.tests.helpers import catalog, pilot, unit

N = CardNumber
MARIDA = pilot("GD01-093", "Marida Cruz", traits=("Neo Zeon", "Cyber-Newtype"), color=Color.RED)
BIG = unit("GD01-044", "Kshatriya", link="Marida Cruz", color=Color.RED, ap=5, hp=4, text="【When Paired】Choose 1 enemy Unit. Deal 1 damage to it.")
SMALL = unit("GD01-051", "Kshatriya", link_trait="Cyber-Newtype", color=Color.RED, ap=3, hp=4)
BESSERUNG = unit("GD03-005", "Kshatriya Besserung", link="Marida Cruz", color=Color.BLUE, ap=4, hp=4,
                 text="<Repair 1> (At the end of your turn, this Unit recovers the specified number of HP.)\n【Deploy】Draw 1.")  # fmt: skip
PURPLE = unit("ST12-006", "Banshee", link="Marida Cruz", color=Color.PURPLE, ap=5, hp=4,
              text="【During Pair】【Activate･Main】Exile 4 cards from your trash：This Unit gains <First Strike> and <Suppression>.")  # fmt: skip
GEARA = unit("GD05-056", "Rezin's Geara Doga", link_trait="Cyber-Newtype", color=Color.PURPLE, ap=3, hp=4)
CARDS: dict[N, CardModel] = catalog(MARIDA, BIG, SMALL, BESSERUNG, PURPLE, GEARA)


def squad(*members: tuple[N, int]) -> Squad:
    return Squad(cards=tuple(SquadCard(card_number=n, decks=d) for n, d in members), decks_with_any=1, share_with_any=0.1, kinds=(SynergyKind.FUNCTIONAL_EFFECT,))


def test_the_deck_colors_are_the_two_most_common() -> None:
    assert main_colors([MARIDA.number, BIG.number, SMALL.number, BESSERUNG.number, GEARA.number], CARDS) == {Color.RED, Color.BLUE}  # red x3, then blue and purple tie: first seen


def test_a_core_card_is_never_covered_by_a_peer() -> None:
    required = [MARIDA.number, BIG.number]
    found = slot_alternatives(required, frozenset(), [squad((BIG.number, 100), (PURPLE.number, 90))], CARDS)
    assert found[BIG.number].counted == () and found[BIG.number].similar == (PURPLE.number,)  # a suggestion, not a substitute


def test_an_option_card_counts_a_peer_played_often_enough_in_a_color_the_deck_plays() -> None:
    option = frozenset({BIG.number})
    red_deck = [MARIDA.number, BIG.number, SMALL.number]  # plays red only
    purple_deck = [MARIDA.number, BIG.number, GEARA.number]  # plays red and purple
    other_color = slot_alternatives(red_deck, option, [squad((BIG.number, 100), (PURPLE.number, 100))], CARDS)
    assert other_color[BIG.number].counted == () and other_color[BIG.number].similar == (PURPLE.number,)  # purple is not a color a red deck plays
    in_color = slot_alternatives(purple_deck, option, [squad((BIG.number, 100), (PURPLE.number, 100))], CARDS)
    assert in_color[BIG.number].counted == (PURPLE.number,)  # same job, a color the deck plays, played as often
    rare = slot_alternatives(purple_deck, option, [squad((BIG.number, 100), (PURPLE.number, 10))], CARDS)
    assert rare[BIG.number].counted == () and ALT_MIN_SHARE == 0.5  # played far less often than the card itself


def test_candidates_find_the_cheap_unplayed_stand_in_with_the_decks_pilots() -> None:
    required = [MARIDA.number, BIG.number]
    prices = {BESSERUNG.number: 16, PURPLE.number: 149, SMALL.number: 11, BIG.number: 4429}
    found = candidates(BIG.number, required, CARDS, prices, limit=5)
    by = {c.card: c for c in found}
    assert BESSERUNG.number in by and PURPLE.number in by and SMALL.number not in by  # the vanilla 3/4 is not almost as good as a 5/4 with an ability
    assert by[BESSERUNG.number].in_deck_colors is False and by[BESSERUNG.number].color is Color.BLUE  # needs blue
    assert candidates(BIG.number, required, {}, prices) == ()


def test_owned_alternatives_are_the_stand_ins_i_already_have_and_a_card_the_deck_runs_is_not_one() -> None:
    required = [MARIDA.number, BIG.number]
    prices = {BESSERUNG.number: 16, PURPLE.number: 149, BIG.number: 4429}
    mine = owned_alternatives(BIG.number, required, CARDS, {BESSERUNG.number: 2, SMALL.number: 4})
    assert [(c.card, c.owned) for c in mine] == [(BESSERUNG.number, 2)]  # Besserung: a stand-in I own. The vanilla Kshatriya is not almost as good as the 5/4.
    assert mine[0].in_deck_colors is False  # blue: flagged, since a red deck does not play it
    listed = candidates(BIG.number, required, CARDS, prices, owned={BESSERUNG.number: 2})
    assert [(c.card, c.owned) for c in listed if c.card == BESSERUNG.number] == [(BESSERUNG.number, 2)]  # the cheapest list says what I own of each
    assert owned_alternatives(BIG.number, [MARIDA.number, BIG.number, BESSERUNG.number], CARDS, {BESSERUNG.number: 2}) == ()  # already in the deck: not an alternative
    assert owned_alternatives(BIG.number, required, CARDS, {}) == ()
