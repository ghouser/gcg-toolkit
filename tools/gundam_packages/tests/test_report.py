"""The markdown report on the synthetic world: sections, counts, and formatting."""
from __future__ import annotations

from datetime import UTC, datetime

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color
from tools.gundam_packages.report import combo_label, deck_combo, pts, render_report
from tools.gundam_packages.tests.helpers import catalog, unit
from tools.gundam_packages.tests.test_discover import A1, A2, A3, B1, world
from tools.gundam_packages.tests.test_drift import base_file, make_drift, new_decks


def cards_for(decks: list[frozenset[CardNumber]]) -> dict[CardNumber, CardModel]:
    numbers = sorted({n for d in decks for n in d})
    return catalog(*(unit(n, f"Card {n}", color=Color.BLUE if n < "GD02" else Color.RED) for n in numbers))


def test_changes_in_share_are_whole_points_and_never_negative_zero() -> None:
    assert pts(0.074) == "+7 pts" and pts(-0.094) == "-9 pts" and pts(-0.001) == "0 pts"


def test_a_deck_has_the_colors_with_enough_cards_and_ignores_a_splash() -> None:
    cards = cards_for([*world(), *new_decks()])
    assert deck_combo(frozenset({A1, A2, A3, B1}), cards) == (Color.BLUE,)  # one red card is a splash
    assert combo_label((Color.BLUE, Color.RED)) == "Blue / Red"


def test_the_report_has_both_parts_with_deck_counts() -> None:
    old, new = world(), new_decks()
    cards = cards_for([*old, *new])
    text = render_report(base_file(), old, make_drift(), new, cards, datetime(2026, 10, 7, tzinfo=UTC))
    assert "## 1. The meta by color combination" in text and "## 3. Meta adjustments" in text
    assert f"{len(old)} decks" in text and "**Low sample**" in text
    assert "| pkg:GD01-001 |" in text and "-0 pts" not in text
    assert "new package: " in text  # the two new cards that form an emerging package are labeled as such
