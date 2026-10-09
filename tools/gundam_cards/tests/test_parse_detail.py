"""Parsing one Bandai detail page into the raw boundary structure."""
from __future__ import annotations

from collections.abc import Callable

import pytest

from tools.gundam_cards.parse_detail import DetailPageError, RawDetail, clean_block, clean_inline, parse_detail_html


def test_unit_page_fields(raw: Callable[[str], RawDetail]) -> None:
    unit = raw("ST01-001")
    assert (unit.card_no, unit.rarity, unit.block, unit.name) == ("ST01-001", "LR", "1", "Gundam")
    assert unit.fields["TYPE"] == "UNIT"
    assert unit.fields["Trait"] == "(Earth Federation) (White Base Team)"
    assert unit.fields["Link"] == "[Amuro Ray]"
    assert unit.fields["Where to get it"] == "Heroic Beginnings [ST01]"
    assert unit.text.splitlines()[0].startswith("<Repair 2>")
    assert "【During Pair】During your turn, all your Units get AP+1." in unit.text
    assert unit.image_src is not None and unit.image_src.endswith("ST01-001.webp?261001")


def test_faq_is_parsed(raw: Callable[[str], RawDetail]) -> None:
    (faq,) = raw("ST01-001").faq
    assert (faq.id, faq.updated) == ("Q113", "July 04, 2025")
    assert faq.question.startswith("Does this Unit also get AP+1")
    assert faq.answer == "Yes, it does."


def test_zero_width_space_is_removed_from_names(raw: Callable[[str], RawDetail]) -> None:
    assert raw("GD05-111").name == "Airframe Seizure"


def test_alt_art_rarity_keeps_its_plus(raw: Callable[[str], RawDetail]) -> None:
    assert raw("ST11-005_p1").rarity == "C +"


def test_missing_structure_raises() -> None:
    with pytest.raises(DetailPageError):
        parse_detail_html("<html><body><p>nothing here</p></body></html>")


def test_cleaners() -> None:
    assert clean_inline("  a​ b \n\t c\xa0d ") == "a b c d"
    assert clean_block("one  line\r\n\r\n  two​ \n\n\nthree") == "one line\ntwo\nthree"
