"""promo-beta-set-codes: a printing whose "Where to get it" names no set in brackets takes its set from its package, through the
reviewed sets.json (AC-1, AC-2). Expected values are worked out by hand from the package map below."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date

from shared.basetypes import PackageId, SetCode, Trait
from tools.gundam_cards.build import SourcePage, build_card
from tools.gundam_cards.models import Printing

Page = Callable[[str], SourcePage]
TRAITS = frozenset({Trait("Earth Federation"), Trait("White Base Team")})
NO_DATES: dict[SetCode, date] = {}
GD01, GD02, SC01, PROMO, BETA, UNKNOWN = "616101", "616102", "616301", "616901", "616000", "616999"
PACKAGE_CODES = {PackageId(GD01): SetCode("GD01"), PackageId(GD02): SetCode("GD02"), PackageId(SC01): SetCode("SC01"),
                 PackageId(PROMO): SetCode("PROMO"), PackageId(BETA): SetCode("BETA")}  # fmt: skip


def printed(page: Page, where: str, *packages: str, codes: dict[PackageId, SetCode] = PACKAGE_CODES) -> Printing:
    """ST01-001's page with its "Where to get it" text and package ids replaced, built with the package map `codes`."""
    p = page("ST01-001")
    source = replace(p, raw=replace(p.raw, fields=dict(p.raw.fields, **{"Where to get it": where})),
                     package_ids=tuple(PackageId(i) for i in packages))  # fmt: skip
    result = build_card([source], TRAITS, NO_DATES, codes)
    assert result.issues == ()
    return result.card.printings[0]


# ---- AC-1 -------------------------------------------------------------------------------------------------------------------
def test_a_bracketed_code_in_the_text_wins_over_the_package(page: Page) -> None:
    assert printed(page, "Newtype Rising [GD01]", PROMO).set_code == "GD01"
    assert printed(page, "Some Reprint[GD02]", BETA).set_code == "GD02"


def test_a_printing_in_the_promo_package_with_no_bracketed_code_gets_promo(page: Page) -> None:
    assert printed(page, "Store tournament prize", PROMO).set_code == "PROMO"


def test_a_dash_printing_gets_the_set_its_package_maps_to(page: Page) -> None:
    assert printed(page, "-", GD02).set_code == "GD02"  # R-018, R-019, T-012 on the real data


def test_a_package_the_map_lacks_gives_no_set_code_and_the_card_still_builds(page: Page) -> None:
    assert printed(page, "Store tournament prize", UNKNOWN).set_code is None


def test_a_printing_with_no_package_and_no_bracketed_code_has_no_set_code(page: Page) -> None:
    assert printed(page, "Store tournament prize").set_code is None


def test_with_no_sets_json_no_package_is_known(page: Page) -> None:
    assert printed(page, "Store tournament prize", PROMO, codes={}).set_code is None


def test_with_several_packages_the_first_one_the_map_knows_wins(page: Page) -> None:
    assert printed(page, "-", UNKNOWN, GD02, PROMO).set_code == "GD02"
    assert printed(page, "-", PROMO, GD02).set_code == "PROMO"
    assert printed(page, "-", GD02, PROMO).set_code == "GD02"


def test_without_a_package_map_the_build_reads_only_the_bracket(page: Page) -> None:
    p = page("ST01-001")
    source = replace(p, raw=replace(p.raw, fields=dict(p.raw.fields, **{"Where to get it": "-"})), package_ids=(PackageId(GD02),))
    assert build_card([source], TRAITS, NO_DATES).card.printings[0].set_code is None


# ---- AC-2 -------------------------------------------------------------------------------------------------------------------
def test_an_edition_beta_printing_gets_beta_and_nothing_else_changes(page: Page) -> None:
    with_map = printed(page, "Edition Beta", BETA)
    without_map = printed(page, "Edition Beta", BETA, codes={})
    assert with_map.set_code == "BETA"
    assert with_map == without_map.model_copy(update={"set_code": SetCode("BETA")})
