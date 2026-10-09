"""The collection price analyzer: bands, boundaries, totals and what is left out."""
from __future__ import annotations

import pytest

from shared.basetypes import CardNumber
from tools.gundam_collection.models import Art, OwnedCard, OwnedPrinting
from tools.gundam_collection.value import DEFAULT_THRESHOLDS, analyze, band_index, labels

N = CardNumber


def owned(number: str, copies: int, alt: int = 0) -> OwnedCard:
    printings = [OwnedPrinting(art=Art.BASE, copies=copies - alt)] if copies - alt else []
    if alt:
        printings.append(OwnedPrinting(art=Art.ALT, copies=alt))
    return OwnedCard(card_number=N(number), copies=copies, printings=tuple(printings))


def test_the_default_bands_split_at_fifty_cents_one_five_and_ten_dollars_with_no_gap() -> None:
    assert DEFAULT_THRESHOLDS == (50, 100, 500, 1000)
    assert labels(DEFAULT_THRESHOLDS) == ("under $0.50", "$0.50 to under $1", "$1 to under $5", "$5 to under $10", "$10 or more")
    # every threshold opens the band above it: a card at exactly $0.50 is in "$0.50 to under $1"
    edges = {10: 0, 49: 0, 50: 1, 99: 1, 100: 2, 499: 2, 500: 3, 999: 3, 1000: 4, 5000: 4}
    assert {cents: band_index(cents, DEFAULT_THRESHOLDS) for cents in edges} == edges


def test_other_thresholds_follow_the_same_rule() -> None:
    assert labels((100, 500, 1000)) == ("under $1", "$1 to under $5", "$5 to under $10", "$10 or more")
    assert labels((50, 200, 500)) == ("under $0.50", "$0.50 to under $2", "$2 to under $5", "$5 or more")


def test_cards_are_banded_by_price_and_valued_by_copies() -> None:
    prices = {N("A-001"): 30, N("A-002"): 75, N("A-003"): 150, N("A-004"): 499, N("A-005"): 500, N("A-006"): 1000, N("A-007"): 2500}
    names = {n: f"Card {n}" for n in prices}
    report = analyze([owned(str(n), 2) for n in prices], prices, names)
    assert [(b.cards, b.copies, b.total_cents) for b in report.tiers] == [(1, 2, 60), (1, 2, 150), (2, 4, 1298), (1, 2, 1000), (2, 4, 7000)]
    assert report.total_cents == 60 + 150 + 1298 + 1000 + 7000
    assert report.bulk.label == "under $0.50" and [b.label for b in report.bands][0] == "$0.50 to under $1"
    top = report.bands[-1].lines  # $10 or more: most valuable first
    assert [(ln.card, ln.unit_cents, ln.total_cents) for ln in top] == [("A-007", 2500, 5000), ("A-006", 1000, 2000)]


def test_lines_sort_by_what_the_copies_are_worth_not_the_unit_price() -> None:
    prices = {N("A-001"): 300, N("A-002"): 200}
    report = analyze([owned("A-001", 1), owned("A-002", 4)], prices, {})
    assert [ln.card for ln in report.bands[1].lines] == ["A-002", "A-001"]  # 4 x $2.00 beats 1 x $3.00
    assert report.bands[1].lines[0].name == "A-002"  # no name known: the number stands in


def test_unpriced_cards_are_listed_apart_and_alt_arts_are_noted() -> None:
    report = analyze([owned("R-001", 3), owned("A-001", 2, alt=1)], {N("A-001"): 700}, {N("R-001"): "Resource", N("A-001"): "Twin"})
    assert report.unpriced == (("R-001", "Resource", 3),) and report.total_cents == 1400
    assert report.bands[2].lines[0].alt_art_copies == 1  # valued as the base card, and says so


def test_bad_thresholds_are_rejected_and_any_number_of_them_works() -> None:
    for bad in ((500, 100, 1000), (0, 500, 1000), (100, 100, 1000), ()):
        with pytest.raises(ValueError):
            analyze([], {}, {}, bad)
    custom = analyze([owned("A-001", 1)], {N("A-001"): 300}, {}, (200, 400, 800))
    assert [b.cards for b in custom.tiers] == [0, 1, 0, 0] and custom.tiers[1].label == "$2 to under $4"
    single = analyze([owned("A-001", 1)], {N("A-001"): 300}, {}, (250,))
    assert [b.label for b in single.tiers] == ["under $2.50", "$2.50 or more"] and [b.cards for b in single.tiers] == [0, 1]


def test_the_value_with_the_bulk_ignored_counts_only_cards_of_fifty_cents_or_more() -> None:
    from tools.gundam_collection.value import SELL_MIN_CENTS

    prices = {N("GD01-001"): 10, N("GD01-002"): 49, N("GD01-003"): 50, N("GD01-004"): 120, N("GD01-005"): 1500}
    report = analyze([owned("GD01-001", 10), owned("GD01-002", 3), owned("GD01-003", 2), owned("GD01-004", 1), owned("GD01-005", 1)], prices, {}, DEFAULT_THRESHOLDS)
    assert SELL_MIN_CENTS == 50
    assert report.total_cents == 100 + 147 + 100 + 120 + 1500  # the total includes the bulk
    assert report.sellable() == (100 + 120 + 1500, 3, 4)  # $0.50 exactly is worth selling; $0.49 is not
    assert report.bulk_below() == (100 + 147, 2, 13)
    assert report.sellable()[0] + report.bulk_below()[0] == report.total_cents  # nothing is counted twice or lost
