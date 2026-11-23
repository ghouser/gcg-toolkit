"""base-token-kind: a token-series Base with no color is a `base_token`; every deck kind still needs a color; the dry run predicts
what the real run drops.

The refresh runs with the fake Bandai of the refresh tests in the per-test temp dataset. Expected values come from the spec: T-037 is
TYPE Base, no color, 5 HP, and nothing else shown.
"""
from __future__ import annotations

import email.message
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path

import pytest

from shared.basetypes import PackageId, SetCode, Trait
from shared.dataset import data_dir, tool_data_root
from shared.fetch import Fetcher
from shared.test_tool_data_dir import _Body, bandai_pages
from tools.gundam_cards import cli
from tools.gundam_cards.models import BaseCard, BaseTokenCard, CardKind, CardModel, CardSet, Color, SetKind, Zone
from tools.gundam_cards.printings import DETAIL_URL
from tools.gundam_cards.refresh import RefreshReport, format_report, refresh_catalog
from tools.gundam_cards.store import load_catalog, pages_folder
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai, all_dataset_bytes, detail, write_tracked_sets

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


# ---- AC-3 --------------------------------------------------------------------------------------------------------------------
DROPPED = ("GD99-001", "GD99-004", "T-041", "T-044")  # a colorless Unit and non-token Base, a colorless T- Unit, an unknown color
ADDED = ("T-037", "T-040")  # the base token and a colored T- Base


def predicted_cards(site: FakeBandai) -> None:
    new_cards(site, {
        "GD99-001": colorless("GD99-001", "UNIT"), "GD99-004": colorless("GD99-004", "BASE"), "T-041": colorless("T-041", "UNIT"),
        "T-044": detail("T-044", kind="Base", color="Orange"), "T-037": t037(), "T-040": detail("T-040", kind="Base", color="Blue"),
    })  # fmt: skip


def test_the_dry_run_names_each_card_the_real_run_drops_with_its_reason_and_no_card_it_adds(site: FakeBandai, tracked: Path) -> None:
    assert run(site, tracked, T1).written
    predicted_cards(site)
    dry = run(site, tracked, T2, dry_run=True)
    real = run(site, tracked, T2)

    assert real.written and set(DROPPED).isdisjoint(stored()) and set(ADDED) <= stored().keys()
    expected = {
        "GD99-001": [f"  [parse_failure] GD99-001: {COLOR_REQUIRED}"],
        "GD99-004": [f"  [parse_failure] GD99-004: {COLOR_REQUIRED}"],
        "T-041": [f"  [parse_failure] T-041: {COLOR_REQUIRED}"],
        "T-044": ["rejected T-044: unknown color 'Orange'; the base printing: whole card left out"],
        "T-037": [], "T-040": [],
    }  # fmt: skip
    for report in (dry, real):
        assert {n: named(report, n) for n in expected} == expected
    assert dry.issues == real.issues and dry.rejected == real.rejected


def test_the_dry_run_fetches_the_new_pages_and_leaves_every_dataset_file_and_the_page_cache_as_they_were(
    site: FakeBandai, tracked: Path
) -> None:
    assert run(site, tracked, T1).written
    predicted_cards(site)
    before, tracked_before = all_dataset_bytes(), (tracked / "sets.json").read_bytes()
    site.calls.clear()
    report = run(site, tracked, T2, dry_run=True)

    assert report.complete and not report.written
    assert sorted(site.detail_calls()) == sorted(DETAIL_URL.format(i) for i in (*DROPPED, *ADDED))
    assert all_dataset_bytes() == before and (tracked / "sets.json").read_bytes() == tracked_before


def test_a_dry_run_on_an_empty_dataset_creates_no_file(site: FakeBandai, tracked: Path) -> None:
    predicted_cards(site)
    report = run(site, tracked, T1, dry_run=True)
    assert report.complete and named(report, "GD99-004") == [f"  [parse_failure] GD99-004: {COLOR_REQUIRED}"]
    assert all_dataset_bytes() == {}


@pytest.mark.parametrize("trouble", ["unreadable", "fails"])
def test_a_new_page_the_dry_run_cannot_read_makes_it_incomplete_and_stores_nothing(
    site: FakeBandai, tracked: Path, trouble: str
) -> None:
    assert run(site, tracked, T1).written
    new_cards(site, {"T-037": "<html><body>not a card page</body></html>" if trouble == "unreadable" else t037()})
    if trouble == "fails":
        site.fail.add(DETAIL_URL.format("T-037"))
    before = all_dataset_bytes()
    report = run(site, tracked, T2, dry_run=True)

    assert not report.complete and report.failure is not None and report.failure.startswith("detail page T-037: ")
    assert all_dataset_bytes() == before


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The web, faked at `urlopen` (url -> page, else 404); the refresh command's fetcher is the real one, minus the wait."""
    pages: dict[str, str] = {}

    def urlopen(request: urllib.request.Request, timeout: float) -> _Body:
        if request.full_url not in pages:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", email.message.Message(), None)
        return _Body(pages[request.full_url])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cli, "Fetcher", partial(Fetcher, sleep=lambda _: None))
    return pages


def every_file(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_dry_run_command_with_the_real_fetcher_stores_nothing(
    site: FakeBandai, network: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    network.update(bandai_pages(site))
    assert cli.main(["refresh"]) == 0  # GD01-001 stored, its page cached
    site.packages[PackageId(NEW)] = ("New Pack [GD99]", ["T-037", "GD99-004"])
    site.details.update({"T-037": t037(), "GD99-004": colorless("GD99-004", "BASE")})
    network.update(bandai_pages(site))
    before, tool_before = every_file(data_dir()), every_file(tool_data_root())
    capsys.readouterr()

    assert cli.main(["refresh", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"  [parse_failure] GD99-004: {COLOR_REQUIRED}" in out and "T-037:" not in out and "dry run: nothing written" in out
    assert every_file(data_dir()) == before and every_file(tool_data_root()) == tool_before
