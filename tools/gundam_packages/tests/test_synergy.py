from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_packages.models import SynergyKind
from tools.gundam_cards.models import CardModel
from tools.gundam_packages.synergy import SynergyGraph, build_graph, pilot_identity
from tools.gundam_packages.tests.helpers import command, pilot, unit

N = CardNumber


def kinds(graph: SynergyGraph, a: str, b: str) -> set[str]:
    return {e.kind.value for e in graph.edges_between(N(a), N(b))}


def test_a_units_named_link_ties_it_to_the_pilot() -> None:
    cards: list[CardModel] = [unit("U-001", "Gundam Barbatos Adapt", link="Mikazuki Augus"), pilot("P-001", "Mikazuki Augus"), pilot("P-002", "Someone Else")]
    graph = build_graph(cards)
    assert kinds(graph, "U-001", "P-001") == {"link_pilot"}
    assert graph.edges_between(N("U-001"), N("P-002")) == ()


def test_a_command_with_a_pilot_effect_counts_as_a_pilot() -> None:
    cards: list[CardModel] = [unit("U-001", "Gundam Maxter", link="Chibodee Crocket"), command("C-001", "Cyclone Punch", pilot_name="Chibodee Crocket"), command("C-002", "Plain Command")]
    graph = build_graph(cards)
    assert kinds(graph, "U-001", "C-001") == {"link_pilot"} and graph.edges_of(N("C-002")) == ()
    assert pilot_identity(cards[2]) is None and pilot_identity(cards[1]) is not None


def test_link_fragments_match_part_of_the_pilots_name() -> None:
    cards: list[CardModel] = [unit("U-001", "Gundam X", link="Garrod Ran"), pilot("P-001", "Garrod Ran & Tiffa Adill")]
    graph = build_graph(cards)
    assert kinds(graph, "U-001", "P-001") == {"link_pilot"}  # rules 3-2-6-4


def test_text_that_names_another_card_ties_them() -> None:
    cards: list[CardModel] = [command("C-001", "Darkness Finger", text='Then, if you have a Unit with "Master Gundam" in its card name in play, draw 1.'),
             unit("U-001", "Master Gundam"), unit("U-002", "Shining Gundam")]  # fmt: skip
    graph = build_graph(cards)
    assert kinds(graph, "C-001", "U-001") == {"name_reference"} and graph.edges_between(N("C-001"), N("U-002")) == ()
    assert graph.edges_between(N("C-001"), N("U-001"))[0].kind.relation.value == "combo"  # it names another card: must be played with it


def test_a_generic_name_fragment_is_ignored() -> None:
    many = [unit(f"U-{i:03d}", f"Gundam {i}") for i in range(30)]
    cards: list[CardModel] = [command("C-001", "Finder", text='Choose a Unit with "Gundam" in its card name.'), *many]
    assert build_graph(cards).edges_of(N("C-001")) == ()  # matches 30 cards: not a specific tie


def test_a_trait_ability_that_needs_other_cards_ties_them() -> None:
    # Barbatos Lupus: "Choose 3 (Tekkadan)/(Teiwaz) Unit cards from your trash": it can't count itself (it's in play), so it needs others.
    lupus = unit("GD03-050", "Gundam Barbatos Lupus", traits=("Tekkadan",), text="Choose 3 (Tekkadan)/(Teiwaz) Unit cards from your trash.", mentions=("Tekkadan", "Teiwaz"))
    graze = unit("ST05-004", "Graze Custom", traits=("Tekkadan",))
    hyakuren = unit("ST05-006", "Hyakuren", traits=("Teiwaz",))
    graph = build_graph([lupus, graze, hyakuren])
    assert kinds(graph, "GD03-050", "ST05-004") == {"trait_reference"} and kinds(graph, "GD03-050", "ST05-006") == {"trait_reference"}


def test_a_trait_check_the_card_satisfies_itself_is_not_a_package() -> None:
    # Kapool: "a friendly (Marine) Unit is in play" is satisfied by Kapool itself: it needs no other card, so Marine is not a package.
    kapool = unit("ST11-009", "Kapool", traits=("Marine",), text="【Destroyed】If it is your opponent's turn and a friendly (Marine) Unit is in play, draw 1.", mentions=("Marine",))
    other_marine = unit("ST11-010", "Other Marine", traits=("Marine",))
    assert build_graph([kapool, other_marine]).edges_of(N("ST11-009")) == ()


def test_the_word_another_makes_a_self_trait_check_need_other_cards() -> None:
    needs = unit("GD01-010", "Needs Another", traits=("Zeon",), text="If another friendly (Zeon) Unit is in play, draw 1.", mentions=("Zeon",))
    other = unit("GD01-011", "Other Zeon", traits=("Zeon",))
    assert kinds(build_graph([needs, other]), "GD01-010", "GD01-011") == {"trait_reference"}


def test_a_card_without_the_trait_always_needs_other_cards_and_traits_have_no_size_limit() -> None:
    broad = [unit(f"B-{i:03d}", f"Broad {i}", traits=("Zeon",)) for i in range(60)]  # a very common trait: no cap
    support = command("C-001", "Zeon Support", text="Choose 1 (Zeon) Unit.", mentions=("Zeon",))  # the Command isn't a Zeon card
    cards: list[CardModel] = [*broad, support]
    assert len(build_graph(cards).edges_of(N("C-001"))) == 60


def test_graph_helpers() -> None:
    cards: list[CardModel] = [unit("U-001", "A", link="P"), pilot("P-001", "P"), pilot("P-002", "P2")]
    graph = build_graph(cards)
    assert graph.neighbors(N("U-001")) == {N("P-001"), N("P-002")}
    assert len(graph.edges_among([N("U-001"), N("P-001")])) == 1 and graph.edges_among([N("P-001"), N("P-002")]) == ()
    assert len(graph.ties_to(N("U-001"), [N("P-002")])) == 1
    assert graph.edge_count == 2
