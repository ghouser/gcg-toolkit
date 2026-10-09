"""Reading Bandai's banned / restricted page, and the rules it gives (a small page with the real page's structure)."""
from __future__ import annotations

from datetime import date

import pytest

from shared.basetypes import CardNumber
from tools.gundam_cards.legality import NO_RULES, Rules
from tools.gundam_cards.models import BannedPair, LimitedCard, UnitCard
from tools.gundam_cards.restrictions import RestrictionsError, matches_vanilla, parse_restrictions, vanilla_cards
from tools.gundam_packages.tests.helpers import catalog, unit

N = CardNumber


def div(text: str) -> str:
    return f'<div class="text-area"><p style="text-align: center;">{text}</p></div>'


PAGE = (
    "<html><head><script>var x = 'GD99-999 Fake';</script></head><body>"
    + div("September 25, 2026")
    + '<a class="button" href="#Banned_Cards">Banned Cards</a><a class="button" href="#x">Banned pair</a>'  # the navigation buttons
    + "<h4>Banned Cards<a id='Banned_Cards'></a></h4>" + div("No copies of the card are permitted in the deck.") + div("GD01-020 Anksha")
    + "<h4>Restricted Cards〈2〉<a id='x'></a></h4>" + div("Only 2 copy of the card is permitted in the deck.") + div("ST02-016 Corsica Base")
    + "<h4>Banned pair<a id='y'></a></h4>" + div("Cards A and B cannot be used at the same time")
    + div("A") + div("ST01-010 Amuro Ray") + div("B") + div("ST05-010 Mikazuki Augus")
    + div("A") + div("GD01-008 Guntank") + div("B") + div("GD05-015 M1 Astray Shrike")
    + div("GD01-035 Zaku Ⅱ") + div("GD02-013 Hizack") + div("ST01-005 GM")
    + div('All combinations of cards that match the above description "a Unit card that is Lv.2 with cost 1, 2 AP, and 2 HP, and without effects" are included as banned pairs.')
    + "</body></html>"
)  # fmt: skip


def test_the_page_is_read_into_banned_restricted_pairs_and_the_vanilla_group() -> None:
    found, published = parse_restrictions(PAGE)
    assert published == date(2026, 9, 25)
    assert found.banned == (N("GD01-020"),) and found.limited == (LimitedCard(card=N("ST02-016"), copies=2),)
    assert found.banned_pairs == (BannedPair(a=N("ST01-010"), b=N("ST05-010")), BannedPair(a=N("GD01-008"), b=N("GD05-015")))
    assert found.vanilla_group == (N("GD01-035"), N("GD02-013"), N("ST01-005")) and "Lv.2 with cost 1" in found.vanilla_description  # script text is ignored


def test_a_page_with_none_of_the_sections_is_refused() -> None:
    with pytest.raises(RestrictionsError):
        parse_restrictions("<html><body>" + div("September 25, 2026") + div("Something else entirely") + "</body></html>")


def vanilla(number: str, name: str = "V", *, level: int = 2, cost: int = 1, ap: int = 2, hp: int = 2, text: str = "") -> UnitCard:
    return unit(number, name, level=level, cost=cost, ap=ap, hp=hp, text=text)


def test_the_vanilla_description_is_matched_against_the_cards_not_just_the_pages_list() -> None:
    cards = catalog(vanilla("GD01-035"), vanilla("GD05-099", "Future vanilla"), vanilla("GD01-036", level=3), vanilla("GD01-037", ap=3), vanilla("GD01-038", text="【Deploy】Draw 1."))
    assert vanilla_cards(dict(cards)) == {N("GD01-035"), N("GD05-099")}  # a new vanilla card is covered before the page lists it
    assert matches_vanilla(cards[N("GD01-035")]) and not matches_vanilla(cards[N("GD01-038")])


def rules() -> Rules:
    cards = catalog(vanilla("GD01-035"), vanilla("GD02-013"), vanilla("ST01-005"))
    found, _ = parse_restrictions(PAGE)
    return Rules.of(found, cards)


def test_copy_limits_banned_cards_and_restricted_cards() -> None:
    r = rules()
    assert (r.copy_limit(N("GD01-020")), r.copy_limit(N("ST02-016")), r.copy_limit(N("GD01-001"))) == (0, 2, 4)
    assert NO_RULES.copy_limit(N("GD01-020")) == 4  # with no list synced, nothing is restricted


def test_banned_pairs_and_the_vanilla_group_allow_one_card_but_up_to_four_copies() -> None:
    r = rules()
    assert r.conflicts(N("ST01-010"), [N("ST05-010")]) and r.conflicts(N("ST05-010"), [N("ST01-010")])  # either way round
    assert not r.conflicts(N("ST01-010"), [N("GD01-001")])
    assert r.conflicts(N("GD01-035"), [N("GD02-013")]) and not r.conflicts(N("GD01-035"), [N("GD01-035")])  # a different vanilla card is a pair; the same one is not
    assert r.violations({N("GD01-035"): 4}) == ()  # four copies of one vanilla card are fine


def test_violations_list_everything_illegal_in_a_deck() -> None:
    r = rules()
    counts = {N("GD01-020"): 1, N("ST02-016"): 3, N("ST01-010"): 4, N("ST05-010"): 4, N("GD01-035"): 2, N("ST01-005"): 2, N("GD01-001"): 4}
    text = " | ".join(r.violations(counts))
    assert "GD01-020 is banned" in text and "3 copies of ST02-016, restricted to 2" in text
    assert "ST01-010 and ST05-010 are a banned pair" in text and "GD01-035 and ST01-005 are both in the vanilla group" in text
    assert r.violations({N("GD01-001"): 4, N("ST02-016"): 2}) == ()
