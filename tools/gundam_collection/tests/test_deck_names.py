"""Deck ids, readable unique names, nicknames and lookup."""
from __future__ import annotations

from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color
from tools.gundam_collection.decks import Deck, anchor_of, deck_id, find_decks, label_decks, normalize_id
from tools.gundam_collection.store import load_deck_names, save_deck_names
from tools.gundam_packages.models import DataSource, PackageId
from tools.gundam_packages.tests.helpers import catalog, unit

N = CardNumber


def deck(*packages: tuple[str, str], rate: float = 0.05) -> Deck:
    """A deck of (package name, anchor card number) pairs."""
    refs = tuple((name, DataSource.TOURNAMENT, PackageId(f"pkg:{anchor}")) for name, anchor in packages)
    anchors = tuple(a for _, a in packages)
    name = " + ".join(n for n, _ in packages)
    return Deck(name=name, package_refs=refs, rates={DataSource.TOURNAMENT: rate}, low_sample=False, requirements=(), anchors=anchors, id=deck_id(anchors), plain_name=name)


CARDS: dict[CardNumber, CardModel] = catalog(
    unit("GD01-026", "Char's Zaku Ⅱ", color=Color.GREEN), unit("ST11-001", "Char's Z'Gok", color=Color.BLUE), unit("ST11-002", "Acguy", color=Color.BLUE),
    unit("GD02-054", "Gundam Barbatos 1st Form", color=Color.PURPLE),
)  # fmt: skip


def test_an_id_is_the_sorted_anchor_cards_and_is_the_same_whichever_source_named_the_package() -> None:
    assert deck_id(["ST11-001", "GD02-054"]) == "GD02-054+ST11-001"
    assert anchor_of(PackageId("pkg:GD02-054")) == "GD02-054" and anchor_of("online:pkg:ST11-001") == "ST11-001"


def test_any_punctuation_and_case_is_ignored_in_an_id() -> None:
    assert normalize_id("gd02-054 + st11-001") == normalize_id("GD02-054+ST11-001") == "GD02054ST11001"


def test_the_same_package_name_for_different_packages_gets_a_color_and_a_unique_name_stays_plain() -> None:
    a = deck(("Mikazuki Barbatos", "GD02-054"), ("Char Aznable", "GD01-026"))
    b = deck(("Mikazuki Barbatos", "GD02-054"), ("Char Aznable", "ST11-001"))
    named = label_decks([a, b], CARDS, {})
    assert [d.name for d in named] == ["Mikazuki Barbatos + Char Aznable (G)", "Mikazuki Barbatos + Char Aznable (B)"]  # only the colliding name is tagged
    assert named[0].plain_name == "Mikazuki Barbatos + Char Aznable" and named[0].id == "GD01-026+GD02-054"
    assert named[0].package_labels == ("Mikazuki Barbatos", "Char Aznable (G)") and named[1].package_labels == ("Mikazuki Barbatos", "Char Aznable (B)")


def test_two_decks_that_still_share_a_name_get_the_card_each_is_anchored_on() -> None:
    a = deck(("Char Aznable", "ST11-001"), ("Haman", "GD02-054"))
    b = deck(("Char Aznable", "ST11-002"), ("Haman", "GD02-054"))  # both blue Char packages: a color cannot tell them apart
    named = label_decks([a, b], CARDS, {})
    assert [d.name for d in named] == ["Char Aznable (B) + Haman (Char's Z'Gok)", "Char Aznable (B) + Haman (Acguy)"]


def test_a_nickname_replaces_the_name_and_keeps_the_generated_one() -> None:
    a = deck(("Suletta Aerial", "ST13-006"), ("Academy", "GD04-024"))
    named = label_decks([a], CARDS, {a.id: "redletta"})
    assert named[0].name == "redletta" and named[0].nickname == "redletta" and named[0].plain_name == "Suletta Aerial + Academy"


def test_lookup_goes_id_then_nickname_then_name_then_words_then_digits() -> None:
    a = label_decks([deck(("Suletta Aerial", "ST13-006"), ("Academy", "GD04-024")), deck(("Kira Strike Freedom", "GD05-002"))], CARDS, {"GD04-024+ST13-006": "redletta"})
    assert [d.nickname for d in find_decks(a, "GD04-024+ST13-006")] == ["redletta"]  # an id
    assert [d.nickname for d in find_decks(a, "gd04024 st13006")] == ["redletta"]  # any punctuation and case
    assert [d.nickname for d in find_decks(a, "ST13006GD04024")] == ["redletta"]  # any order
    assert [d.nickname for d in find_decks(a, "REDLETTA")] == ["redletta"]  # a nickname, any case
    assert [d.plain_name for d in find_decks(a, "kira strike")] == ["Kira Strike Freedom"]  # the words of a name
    assert [d.plain_name for d in find_decks(a, "GD05-002")] == ["Kira Strike Freedom"]  # one of its card numbers
    assert [d.nickname for d in find_decks(a, "0402413006")] == ["redletta"]  # digits only, when it matches
    assert find_decks(a, "nothing like it") == [] and find_decks(a, "   ") == []


def test_ambiguous_texts_return_every_match_and_digits_only_works_when_unique() -> None:
    a = deck(("Mikazuki Barbatos", "GD02-054"), ("Char Aznable", "GD01-026"))
    b = deck(("Mikazuki Barbatos", "GD02-054"), ("Char Aznable", "ST11-001"))
    named = label_decks([a, b], CARDS, {})
    assert len(find_decks(named, "Mikazuki Barbatos")) == 2  # the caller lists them, never guesses
    assert [d.id for d in find_decks(named, "0102602054")] == ["GD01-026+GD02-054"]  # digits only, unique


def test_nicknames_round_trip_through_the_file(tmp_path: Path) -> None:
    path = tmp_path / "deck_names.json"
    assert load_deck_names(path) == {}
    save_deck_names({"GD04-024+ST13-006": "redletta", "GD01-026+GD02-054": "barbatos zaku"}, path)
    assert load_deck_names(path) == {"GD01-026+GD02-054": "barbatos zaku", "GD04-024+ST13-006": "redletta"}
