"""base-token-kind: a token-series Base with no color is a `base_token`; every deck kind still needs a color; the dry run predicts
what the real run drops.

The refresh runs with the fake Bandai of the refresh tests in the per-test temp dataset. Expected values come from the spec: T-037 is
TYPE Base, no color, 5 HP, and nothing else shown.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.basetypes import PackageId, SetCode, Trait
from tools.gundam_cards.models import BaseCard, BaseTokenCard, CardKind, CardModel, CardSet, Color, SetKind, Zone
from tools.gundam_cards.refresh import RefreshReport, format_report, refresh_catalog
from tools.gundam_cards.store import load_catalog, pages_folder
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai, detail, write_tracked_sets

T1 = datetime(2026, 11, 1, tzinfo=UTC)
T2 = datetime(2026, 11, 2, tzinfo=UTC)
GD01 = "616101"
NEW = "616199"  # the package the new cards come in
COLOR_REQUIRED = "COLOR is required here but the page shows none"
# T-037 as Bandai shows it: TYPE Base, no color, 5 HP, nothing else.
T037 = {"COLOR": "-", "Lv.": "-", "COST": "-", "AP": "-", "HP": "5", "Zone": "-", "Trait": "-"}


def t037(printing_id: str = "T-037") -> str:
    return detail(printing_id, kind="Base", shown=T037)


def colorless(printing_id: str, kind: str) -> str:
    return detail(printing_id, kind=kind, color="-")


@pytest.fixture
def tracked(tmp_path: Path) -> Path:
    gd01 = CardSet(code=SetCode("GD01"), name="Newtype Rising", kind=SetKind.BOOSTER, bandai_package_id=PackageId(GD01),
                   release_date=date(2025, 7, 25), product_category_raw="BOOSTER PACK", product_url=None)  # fmt: skip
    write_tracked_sets((gd01,), T1, tmp_path / "tracked")
    return tmp_path / "tracked"


@pytest.fixture
def site() -> FakeBandai:
    """One stored card once refreshed (GD01-001); each test lists its new cards in the NEW package."""
    return FakeBandai(pages_folder(), {GD01: ("Newtype Rising [GD01]", ["GD01-001"])}, products=[("Newtype Rising [GD01]", "July 25,2025")])


def run(site: FakeBandai, tracked: Path, when: datetime, *, dry_run: bool = False) -> RefreshReport:
    return refresh_catalog(site, site.raw_dir, tracked_dir=tracked, now=when, dry_run=dry_run)


def new_cards(site: FakeBandai, pages: dict[str, str]) -> None:
    site.packages[PackageId(NEW)] = ("New Pack [GD99]", list(pages))
    site.details.update(pages)


def stored() -> dict[str, CardModel]:
    catalog = load_catalog()
    assert catalog is not None
    return {str(c.number): c for c in catalog.data}


def named(report: RefreshReport, number: str) -> list[str]:
    """Every issue and rejection line of the report that names this card."""
    return [line for line in format_report(report) if line.startswith((f"  [parse_failure] {number}", f"rejected {number}"))]


# ---- AC-1 --------------------------------------------------------------------------------------------------------------------
def test_a_token_series_base_with_no_color_is_added_as_a_base_token(site: FakeBandai, tracked: Path) -> None:
    new_cards(site, {"T-037": t037()})
    report = run(site, tracked, T1)

    assert report.written and named(report, "T-037") == []
    assert not [i for i in report.issues if i.subject == "T-037"] and not report.rejected
    token = stored()["T-037"]
    assert isinstance(token, BaseTokenCard) and token.kind is CardKind.BASE_TOKEN
    assert (token.hp, token.level, token.cost, token.zones, token.traits) == (5, None, None, frozenset(), ())
    assert "color" not in token.model_dump() and not token.kind.is_deck_card


def test_a_base_token_keeps_whichever_fields_its_page_shows_and_needs_none(site: FakeBandai, tracked: Path) -> None:
    new_cards(site, {
        "T-038": detail("T-038", kind="Base", color="-", shown={"Lv.": "2", "COST": "1", "HP": "3"}),  # Zone Space, the trait
        "T-039": detail("T-039", kind="Base", shown={"COLOR": "-", "Lv.": "-", "COST": "-", "HP": None}),  # no HP label at all
    })  # fmt: skip
    report = run(site, tracked, T1)

    assert report.written and named(report, "T-038") == named(report, "T-039") == []
    shows_all, shows_little = stored()["T-038"], stored()["T-039"]
    assert isinstance(shows_all, BaseTokenCard) and isinstance(shows_little, BaseTokenCard)
    assert (shows_all.level, shows_all.cost, shows_all.hp) == (2, 1, 3)
    assert shows_all.zones == {Zone.SPACE} and shows_all.traits == (Trait("Earth Federation"),)
    assert (shows_little.level, shows_little.cost, shows_little.hp) == (None, None, None)


def test_a_token_series_base_page_without_a_color_label_is_a_base_token(site: FakeBandai, tracked: Path) -> None:
    new_cards(site, {"T-037": detail("T-037", kind="Base", shown={**T037, "COLOR": None})})
    assert run(site, tracked, T1).written
    assert isinstance(stored()["T-037"], BaseTokenCard)


def test_a_token_series_base_that_shows_a_color_is_a_base(site: FakeBandai, tracked: Path) -> None:
    new_cards(site, {"T-040": detail("T-040", kind="Base", color="Blue")})
    report = run(site, tracked, T1)

    assert report.written and named(report, "T-040") == []
    base = stored()["T-040"]
    assert isinstance(base, BaseCard) and base.kind is CardKind.BASE and base.color is Color.BLUE


# ---- AC-2 --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("number", "kind"), [
    ("GD99-001", "UNIT"), ("GD99-002", "PILOT"), ("GD99-003", "COMMAND"), ("GD99-004", "BASE"),
    ("T-041", "UNIT"), ("T-042", "PILOT"), ("T-043", "COMMAND"),
])  # fmt: skip
def test_a_deck_kind_with_no_color_is_left_out_as_today(site: FakeBandai, tracked: Path, number: str, kind: str) -> None:
    new_cards(site, {number: colorless(number, kind)})
    report = run(site, tracked, T1)

    assert report.written and number not in stored()
    assert named(report, number) == [f"  [parse_failure] {number}: {COLOR_REQUIRED}"]


def test_a_non_token_base_with_no_color_label_is_left_out_as_today(site: FakeBandai, tracked: Path) -> None:
    new_cards(site, {"GD99-004": detail("GD99-004", kind="BASE", shown={"COLOR": None})})
    report = run(site, tracked, T1)
    assert "GD99-004" not in stored()
    assert named(report, "GD99-004") == ["  [parse_failure] GD99-004: page has no 'COLOR' field"]


@pytest.mark.parametrize("number", ["T-044", "GD99-005"])
def test_a_base_with_an_unknown_color_is_rejected_as_today(site: FakeBandai, tracked: Path, number: str) -> None:
    new_cards(site, {number: detail(number, kind="Base", color="Orange", shown={"Lv.": "-", "COST": "-"})})
    report = run(site, tracked, T1)
    assert number not in stored()
    assert named(report, number) == [f"rejected {number}: unknown color 'Orange'; the base printing: whole card left out"]
