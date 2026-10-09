"""Building typed cards from parsed pages, including the "newest wording wins" rules."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date

import pytest

from shared.basetypes import PilotName, SetCode, Trait
from tools.gundam_cards.build import (
    BuildResult,
    IssueKind,
    ParseError,
    SourcePage,
    build_card,
    parse_int,
    parse_link,
    parse_rarity,
)
from tools.gundam_cards.models import (
    BaseCard,
    Block,
    CardKind,
    CommandCard,
    Color,
    ExBaseCard,
    ExResourceCard,
    Keyword,
    PilotCard,
    PilotNameLink,
    Rarity,
    ResourceCard,
    TraitLink,
    UnitCard,
    UnitTokenCard,
    Zone,
    is_pilot,
)

Page = Callable[[str], SourcePage]
NO_DATES: dict[SetCode, date] = {}
TRAITS = frozenset(
    Trait(t)
    for t in ("Earth Federation", "White Base Team", "G Generation", "Newtype", "Cyber-Newtype", "Teiwaz", "Tekkadan", "Zeon")
)


def build(page: Page, *ids: str, dates: dict[SetCode, date] | None = None) -> BuildResult:
    return build_card([page(i) for i in ids], TRAITS, dates or NO_DATES)


def test_unit(page: Page) -> None:
    result = build(page, "ST01-001")
    card = result.card
    assert isinstance(card, UnitCard)
    assert (card.color, card.level, card.cost, card.ap, card.hp) == (Color.BLUE, 4, 3, 3, 4)
    assert card.zones == {Zone.SPACE, Zone.EARTH}
    assert card.traits == (Trait("Earth Federation"), Trait("White Base Team"))
    assert card.link is not None and card.link.any_of == (PilotNameLink(fragment=PilotName("Amuro Ray")),)
    assert card.keywords == {Keyword.REPAIR, Keyword.DURING_PAIR}
    assert (card.printings[0].rarity, card.printings[0].alt_art, card.printings[0].block) == (Rarity.LR, False, Block.ONE)
    assert card.printings[0].set_code == "ST01"
    assert [f.id for f in card.faq] == ["Q113"] and card.faq[0].updated == date(2025, 7, 4)
    assert result.issues == ()


def test_parallel_printing_with_same_text_adds_a_printing_not_a_version(page: Page) -> None:
    card = build(page, "ST01-001", "ST01-001_p5").card
    assert [str(p.id) for p in card.printings] == ["ST01-001", "ST01-001_p5"]
    assert card.printings[1].variant == 5 and card.printings[1].set_code is None
    assert len(card.text_versions) == 1
    assert [str(i) for i in card.text_versions[0].printing_ids] == ["ST01-001", "ST01-001_p5"]


def test_pilot(page: Page) -> None:
    card = build(page, "ST01-010").card
    assert isinstance(card, PilotCard)
    assert (card.ap_bonus, card.hp_bonus) == (2, 1)
    assert card.keywords == {Keyword.BURST, Keyword.WHEN_PAIRED}
    assert is_pilot(card)


def test_base(page: Page) -> None:
    card = build(page, "ST01-015").card
    assert isinstance(card, BaseCard) and card.hp == 5
    assert {Keyword.BURST, Keyword.DEPLOY, Keyword.ACTIVATE_MAIN, Keyword.ONCE_PER_TURN} <= card.keywords
    # Its text deploys tokens written "[Gundam]((White Base Team)･AP3･HP3)": a mention of that trait, not of its own others.
    assert card.referenced_traits == {Trait("White Base Team")}


def test_plain_command_is_not_a_pilot(page: Page) -> None:
    card = build(page, "GD05-111").card
    assert isinstance(card, CommandCard) and card.pilot is None
    assert card.keywords == {Keyword.MAIN}
    assert not is_pilot(card)


def test_command_with_pilot_effect(page: Page) -> None:
    card = build(page, "EB01-076").card
    assert isinstance(card, CommandCard) and card.pilot is not None
    assert (card.pilot.name, card.pilot.ap_bonus, card.pilot.hp_bonus) == ("Lowe Guele", 1, 1)
    assert card.traits  # the pilot effect's traits live on the command
    assert card.keywords == {Keyword.MAIN, Keyword.ACTION}  # 【Pilot】 is not a keyword
    assert is_pilot(card)


def test_command_with_traits_but_no_pilot_effect(page: Page) -> None:
    card = build(page, "GD05-110").card
    assert isinstance(card, CommandCard) and card.pilot is None


def test_non_deck_kinds(page: Page) -> None:
    assert isinstance(build(page, "T-001").card, UnitTokenCard)
    assert build(page, "T-025").card.kind is CardKind.UNIT_TOKEN  # the "UNIT・TOKEN" spelling
    assert isinstance(build(page, "R-002").card, ResourceCard)
    assert isinstance(build(page, "EXR-002").card, ExResourceCard)
    ex_base = build(page, "EXB-002").card
    assert isinstance(ex_base, ExBaseCard) and ex_base.hp == 3
    assert not ex_base.kind.is_deck_card and CardKind.UNIT.is_deck_card


def test_promo_and_beta_block(page: Page) -> None:
    resource = build(page, "RP-001").card
    assert resource.printings[0].rarity is Rarity.P
    assert build(page, "EXBP-001").card.printings[0].block is Block.BETA


def test_unit_with_no_ap(page: Page) -> None:
    card = build(page, "EB01-013").card
    assert isinstance(card, UnitCard) and card.ap is None


def test_fullwidth_digits_are_normalized(page: Page) -> None:
    card = build(page, "GD04-028").card
    assert isinstance(card, UnitCard)
    assert isinstance(card.level, int) and isinstance(card.cost, int) and isinstance(card.hp, int)


def test_development_keyword(page: Page) -> None:
    card = build(page, "EB01-008").card
    assert {Keyword.DEPLOY, Keyword.DEVELOPMENT} <= card.keywords


def test_pair_qualification_does_not_create_unknown_tags(page: Page) -> None:
    result = build(page, "EB01-022")
    assert Keyword.DURING_PAIR in result.card.keywords
    assert result.card.unknown_tags == ()


# ---- link conditions -----------------------------------------------------------------------------
def test_trait_alternatives_link(page: Page) -> None:
    card = build(page, "GD01-047").card
    assert isinstance(card, UnitCard) and card.link is not None
    assert card.link.any_of == (TraitLink(trait=Trait("Newtype")), TraitLink(trait=Trait("Cyber-Newtype")))


def test_pilot_name_alternatives_link(page: Page) -> None:
    card = build(page, "GD03-001").card
    assert isinstance(card, UnitCard) and card.link is not None
    assert [r.fragment for r in card.link.any_of if isinstance(r, PilotNameLink)] == ["Christina Mackenzie", "Amuro Ray"]


def test_pilot_name_with_parentheses(page: Page) -> None:
    card = build(page, "GD02-038").card
    assert isinstance(card, UnitCard) and card.link is not None
    assert PilotNameLink(fragment=PilotName("Amate Yuzuriha (Machu)")) in card.link.any_of


def test_bare_trait_alternative_is_a_trait(page: Page) -> None:
    # Decided rule: "(Teiwaz) / (Tekkadan) Trait" is the Teiwaz trait OR the Tekkadan trait.
    result = build(page, "GD03-067")
    card = result.card
    assert isinstance(card, UnitCard) and card.link is not None
    assert card.link.any_of == (TraitLink(trait=Trait("Teiwaz")), TraitLink(trait=Trait("Tekkadan")))
    assert result.issues == ()


def test_set_codes_in_where_to_get_accept_all_known_shapes(page: Page) -> None:
    p = page("ST01-001")
    for where, expected in [("Steel Requiem[GD03]", "GD03"), ("X -Wing- [PB01]", "PB01"), ("Y [PC02A]", "PC02A"), ("Z [EVX-01]", "EVX01"), ("Events", None)]:
        fields = dict(p.raw.fields, **{"Where to get it": where})
        card = build_card([replace(p, raw=replace(p.raw, fields=fields))], TRAITS, NO_DATES).card
        assert card.printings[0].set_code == expected


def test_link_satisfaction_follows_the_rules_example() -> None:
    # Rules 3-2-6-4: Pilot "Garrod Ran & Tiffa Adill" satisfies a link requirement of [Garrod Ran].
    link = parse_link("[Garrod Ran] / (Newtype) Trait", "t")
    assert link is not None
    assert link.satisfied_by(PilotName("Garrod Ran & Tiffa Adill"), frozenset())
    assert link.satisfied_by(PilotName("Someone Else"), frozenset({Trait("Newtype")}))
    assert not link.satisfied_by(PilotName("Someone Else"), frozenset({Trait("Zeon")}))
    assert parse_link("-", "t") is None


# ---- newest wording wins ---------------------------------------------------------------------------
def _with_text(p: SourcePage, text: str, block: str | None = None, where: str | None = None) -> SourcePage:
    fields = dict(p.raw.fields)
    if where is not None:
        fields["Where to get it"] = where
    raw = replace(p.raw, text=text, block=block or p.raw.block, fields=fields)
    return replace(p, raw=raw)


def test_newer_block_wins(page: Page) -> None:
    base = page("ST01-001")
    newer = _with_text(page("ST01-001_p5"), "【During Pair】During your turn, all your Units get AP+2.", block="2")
    card = build_card([base, newer], TRAITS, NO_DATES).card
    assert [str(v.printing_ids[0]) for v in card.text_versions] == ["ST01-001_p5", "ST01-001"]
    assert card.text.endswith("AP+2.")
    assert card.text_versions[0].block is Block.TWO
    assert card.text_versions[0].substantive is False  # the current version doesn't differ from itself
    assert card.text_versions[1].substantive is True  # the older wording really differs
    assert card.keywords == {Keyword.DURING_PAIR}  # keywords follow the current wording


def test_newer_set_wins_within_the_same_block(page: Page) -> None:
    base = page("ST01-001")  # where: Heroic Beginnings [ST01]
    newer = _with_text(page("ST01-001_p5"), "【During Pair】Changed wording.", where="Some Reprint [GD05]")
    dates = {SetCode("ST01"): date(2025, 7, 4), SetCode("GD05"): date(2026, 7, 24)}
    card = build_card([base, newer], TRAITS, dates).card
    assert card.text == "【During Pair】Changed wording."
    assert card.text_versions[0].as_of == date(2026, 7, 24)


def test_reminder_text_only_tie_keeps_the_version_with_reminder_text(page: Page) -> None:
    # GD05-037 vs its alt art: same block and set, wording differs only by reminder text.
    result = build(page, "GD05-037", "GD05-037_p1", dates={SetCode("GD05"): date(2026, 7, 24)})
    card = result.card
    assert "(During your turn, when this Unit destroys" in card.text  # the base printing has the reminder
    assert [str(i) for i in card.text_versions[0].printing_ids] == ["GD05-037"]
    assert len(card.text_versions) == 2 and card.text_versions[1].substantive is False
    assert result.issues == ()


def test_substantive_tie_is_reported_not_guessed(page: Page) -> None:
    # GD01-090 vs its promo alt art: same block, no way to tell the age, wording really differs.
    result = build(page, "GD01-090", "GD01-090_p2")
    card = result.card
    assert [i.kind for i in result.issues] == [IssueKind.AMBIGUOUS_RECENCY]
    assert [str(i) for i in card.text_versions[0].printing_ids] == ["GD01-090"]  # falls back to the base printing
    assert card.text_versions[1].substantive is True


# ---- failure modes ---------------------------------------------------------------------------------
def test_a_lone_alt_art_becomes_the_reference_printing(page: Page) -> None:
    result = build(page, "ST01-001_p5")
    assert [i.kind for i in result.issues] == [IssueKind.NO_BASE_PRINTING]
    assert str(result.card.printings[0].id) == "ST01-001_p5"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", 3), ("+2", 2), ("-3", -3), ("-", None), ("３", 3), (" 4 ", 4)],
)
def test_parse_int(value: str, expected: int | None) -> None:
    assert parse_int(value, "t", "x") == expected


def test_parse_int_rejects_garbage() -> None:
    with pytest.raises(ParseError):
        parse_int("three", "t", "x")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("C", (Rarity.C, 0, False)), ("C +", (Rarity.C, 1, False)), ("LR", (Rarity.LR, 0, False)), ("P", (Rarity.P, 0, False))],
)
def test_parse_rarity(value: str, expected: tuple[Rarity, int, bool]) -> None:
    assert parse_rarity(value, "t") == expected


def test_unknown_rarity_and_block_fail_loudly(page: Page) -> None:
    with pytest.raises(ParseError, match="rarity"):
        parse_rarity("SSR", "t")
    p = page("ST01-001")
    with pytest.raises(ParseError, match="block"):
        build_card([replace(p, raw=replace(p.raw, block="3"))], TRAITS, NO_DATES)


def test_unknown_card_type_fails_loudly(page: Page) -> None:
    p = page("ST01-001")
    fields = dict(p.raw.fields, TYPE="HOLOGRAM")
    with pytest.raises(ParseError, match="TYPE"):
        build_card([replace(p, raw=replace(p.raw, fields=fields))], TRAITS, NO_DATES)


def test_command_with_stats_but_no_pilot_effect_fails(page: Page) -> None:
    p = page("GD05-111")
    fields = dict(p.raw.fields, AP="+1", HP="+1")
    with pytest.raises(ParseError, match="Pilot"):
        build_card([replace(p, raw=replace(p.raw, fields=fields))], TRAITS, NO_DATES)
