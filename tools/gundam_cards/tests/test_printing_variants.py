"""How a card's alt arts, promos and Beta printings differ, and what the builder does about it.

Every case here is a real one found in Bandai's data (fixtures are saved pages).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date

import pytest

from shared.basetypes import PrintingId, SetCode, Trait
from tools.gundam_cards.build import (
    BuildResult,
    IssueKind,
    ParseError,
    SourcePage,
    build_card,
    comparison_core,
    parse_rarity,
    strip_reminders,
)
from tools.gundam_cards.models import Block, CardKind, Rarity, TraitLink, UnitCard

Page = Callable[[str], SourcePage]
DATES = {
    SetCode("GD01"): date(2025, 7, 25),
    SetCode("ST01"): date(2025, 7, 11),
    SetCode("GD05"): date(2026, 7, 24),
    SetCode("SC01"): date(2026, 7, 24),
}
TRAITS = frozenset(Trait(t) for t in ("Londo Bell", "Neo Zeon", "Cyber-Newtype", "Earth Federation", "White Base Team", "Zeon", "ZAFT"))


def build(page: Page, *ids: str) -> BuildResult:
    return build_card([page(i) for i in ids], TRAITS, DATES)


def kinds(result: BuildResult) -> list[IssueKind]:
    return [i.kind for i in result.issues]



# ---- rarity: two alt-art tiers and the GD05 "LK" rarities ------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("C", (Rarity.C, 0, False)),
        ("C +", (Rarity.C, 1, False)),
        ("LR", (Rarity.LR, 0, False)),  # the L in LR is not the link-art prefix
        ("LR ++", (Rarity.LR, 2, False)),
        ("C ++", (Rarity.C, 2, False)),
        ("P +", (Rarity.P, 1, False)),
        ("LKR +", (Rarity.R, 1, True)),  # "LK" = Link art: the linked pilot is in the art
        ("LKC +", (Rarity.C, 1, True)),
        ("LKU +", (Rarity.U, 1, True)),
    ],
)
def test_rarity_alt_art_level_and_link_art(value: str, expected: tuple[Rarity, int, bool]) -> None:
    assert parse_rarity(value, "t") == expected


def test_unknown_rarity_and_three_plusses_still_fail() -> None:
    for bad in ("XYZ", "LR +++", "+"):
        with pytest.raises(ParseError):
            parse_rarity(bad, "t")


def test_alt_art_levels_on_real_printings(page: Page) -> None:
    card = build(page, "GD01-067", "GD01-067_p2").card
    assert [(p.rarity, p.alt_art_level, p.alt_art) for p in card.printings] == [(Rarity.LR, 0, False), (Rarity.LR, 2, True)]


def test_link_art_is_an_alt_art_of_the_underlying_rarity(page: Page) -> None:
    lk = build(page, "GD05-003", "GD05-003_p1").card
    base, link = lk.printings
    assert (base.rarity, base.link_art, base.alt_art) == (Rarity.R, False, False)
    assert (link.rarity, link.alt_art_level, link.link_art, link.alt_art) == (Rarity.R, 1, True, True)


# ---- alt arts differ from the base in source title, but that's not a mismatch -----------------------------
def test_source_title_is_per_printing_and_not_reported(page: Page) -> None:
    result = build(page, "GD05-111", "GD05-111_p1")
    base, alt = result.card.printings
    assert base.source_title != alt.source_title and alt.source_title is not None
    assert result.card.source_title == base.source_title  # the reference printing's
    assert result.issues == ()


def test_cosmetic_differences_are_not_mismatches(page: Page) -> None:
    assert build(page, "GD03-027", "GD03-027_p1").issues == ()  # Z’Gok vs Z'Gok
    assert build(page, "ST02-012", "ST02-012_p1").issues == ()  # HP "+1" vs "1"
    assert build(page, "T-029", "T-029_p1").issues == ()  # "UNIT・TOKEN" vs "UNIT TOKEN"


def test_real_attribute_differences_are_reported_and_the_base_wins(page: Page) -> None:
    result = build(page, "GD01-051", "GD01-051_p1")
    assert kinds(result) == [IssueKind.PRINTING_ATTRIBUTE_MISMATCH]
    assert "Link" in result.issues[0].detail and "Enhanced Human" in result.issues[0].detail
    card = result.card
    assert isinstance(card, UnitCard) and card.link is not None
    assert card.link.any_of == (TraitLink(trait=Trait("Cyber-Newtype")),)  # the base printing's link, not the alt art's


# ---- card numbers Bandai only lists as alt arts -----------------------------------------------------------
def test_card_with_only_alt_arts_uses_the_lowest_as_reference(page: Page) -> None:
    result = build(page, "R-001_p5", "R-001_p4")  # passed out of order on purpose
    assert result.issues[0].kind is IssueKind.NO_BASE_PRINTING and "R-001_p4" in result.issues[0].detail
    # Bandai's Beta data is unreliable: these two printings of a Resource even disagree on AP/HP.
    assert [i.kind for i in result.issues[1:]] == [IssueKind.PRINTING_ATTRIBUTE_MISMATCH] and "AP" in result.issues[1].detail
    card = result.card
    assert card.kind is CardKind.RESOURCE
    assert [str(p.id) for p in card.printings] == ["R-001_p4", "R-001_p5"]
    assert card.printings[0].block is Block.BETA


# ---- one bad alt art must not drop the card -----------------------------------------------------------------
def test_unparseable_alt_art_is_left_out_and_reported(page: Page) -> None:
    alt = page("GD05-003_p1")
    broken = replace(alt, raw=replace(alt.raw, rarity="ZZZ +"))
    result = build_card([page("GD05-003"), broken], TRAITS, DATES)
    assert [str(p.id) for p in result.card.printings] == ["GD05-003"]
    assert kinds(result) == [IssueKind.PARSE_FAILURE] and "left out" in result.issues[0].detail


def test_unparseable_reference_printing_fails_the_card(page: Page) -> None:
    base = page("GD05-003")
    with pytest.raises(ParseError):
        build_card([replace(base, raw=replace(base.raw, rarity="ZZZ"))], TRAITS, DATES)


# ---- wording: reminder text, "no text", and genuinely different wording ---------------------------------------
def test_removing_a_reminder_line_leaves_no_blank_line_behind() -> None:
    text = "【During Pair】This Unit gains <Breach 3>.\n(Reminder: deal damage.)\n【Deploy】Draw 1."
    stripped, removed = strip_reminders(text, TRAITS)
    assert stripped == "【During Pair】This Unit gains <Breach 3>.\n【Deploy】Draw 1."
    assert removed == len("(Reminder: deal damage.)")


def test_reminder_only_differences_are_not_substantive_and_keep_the_reminder(page: Page) -> None:
    # GD05-020 vs its alt art: same block and set, the alt art just lacks the reminder paragraph.
    result = build(page, "GD05-020", "GD05-020_p1")
    card = result.card
    assert result.issues == ()
    assert "(During your turn, when this Unit destroys" in card.text
    assert [v.substantive for v in card.text_versions] == [False, False]
    assert [str(v.printing_ids[0]) for v in card.text_versions] == ["GD05-020", "GD05-020_p1"]


def test_dash_means_no_text(page: Page) -> None:
    # RP-068: the base has reminder text, the alt art shows "-" (no text). Not a wording change.
    result = build(page, "RP-068", "RP-068_p1")
    assert result.issues == ()
    assert result.card.text == "(Rest a Resource when paying a cost.)"
    assert [v.text for v in result.card.text_versions] == ["(Rest a Resource when paying a cost.)", ""]
    assert [v.substantive for v in result.card.text_versions] == [False, False]


def test_wording_changes_across_rules_blocks_pick_the_newest_block(page: Page) -> None:
    # GD01-005 was reworded when the rules changed: Beta/launch printings vs the block-2 reprint (SC01).
    result = build(page, "GD01-005", "GD01-005_p2", "GD01-005_p3", "GD01-005_p4")
    card = result.card
    assert card.text.startswith("【During Link】【Destroyed】Return this Unit's paired Pilot")  # the block-2 wording
    assert {str(i) for i in card.text_versions[0].printing_ids} == {"GD01-005", "GD01-005_p4"}
    assert card.text_versions[0].block is Block.TWO and card.text_versions[0].as_of == date(2026, 7, 24)
    assert any(v.block is Block.BETA for v in card.text_versions[1:])
    assert IssueKind.KEYWORDS_CHANGED in kinds(result)  # During Pair -> During Link: reported, not hidden
    assert IssueKind.AMBIGUOUS_RECENCY not in kinds(result)


def test_alt_arts_do_not_make_a_wording_look_newer(page: Page) -> None:
    # ST01-015: the base says "no Units in play"; a Bonus Pack alt art and the Edition Beta card say "0 Units in play".
    # Decided rule: an alt art doesn't establish recency, so that wording's age comes from the Beta printing (older).
    result = build(page, "ST01-015", "ST01-015_p1", "ST01-015_p2")
    assert result.issues == ()
    card = result.card
    assert "if you have no Units in play" in card.text
    assert [str(i) for i in card.text_versions[1].printing_ids] == ["ST01-015_p1", "ST01-015_p2"]
    assert card.text_versions[1].substantive is True


def _alt_art_only_wording(page: Page, text: str) -> SourcePage:
    """GD05-003's alt art (an alt art of a same-block, same-set card) with different, substantive text."""
    alt = page("GD05-003_p1")
    return replace(alt, raw=replace(alt.raw, text=text))


def test_substantive_tie_between_alt_art_only_wording_and_main_set_wording_prefers_the_main_set(page: Page) -> None:
    base = page("GD05-003")
    alt = _alt_art_only_wording(page, "【Deploy】Draw 2.")  # same block and set as the base, so the ranks tie
    result = build_card([base, alt], TRAITS, DATES)
    assert IssueKind.AMBIGUOUS_RECENCY not in kinds(result)  # decided: prefer the non-alt-art wording, nothing to raise
    assert [str(v.printing_ids[0]) for v in result.card.text_versions] == ["GD05-003", "GD05-003_p1"]


def test_substantive_tie_between_two_non_alt_art_wordings_is_still_raised(page: Page) -> None:
    # Two main-set style printings (neither an alt art) with different wording and equal rank: no rule applies.
    base = page("GD05-003")
    other = _alt_art_only_wording(page, "【Deploy】Draw 2.")
    other = replace(other, printing_id=PrintingId("GD05-003_p9"), raw=replace(other.raw, rarity="R"))
    result = build_card([base, other], TRAITS, DATES)
    assert IssueKind.AMBIGUOUS_RECENCY in kinds(result)
    assert result.card.text == base.raw.text  # falls back to the base printing meanwhile


def test_cosmetic_wording_differences_are_not_substantive() -> None:
    a = "Return it to its owner's hand. If \"Awakened Potential\" is in your trash, this unit draws 1."
    b = "Return it to its owner' s hand. If \" Awakened Potential\" is in your trash, this Unit draws 1. (Reminder.)"
    assert comparison_core(a, TRAITS)[0] == comparison_core(b, TRAITS)[0]
    assert comparison_core(a, TRAITS)[0] != comparison_core("Return it to its owner's hand. Draw 2.", TRAITS)[0]
