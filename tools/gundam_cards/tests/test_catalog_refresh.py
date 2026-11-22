"""refresh-cards: the catalog refresh from Bandai, with a fake Bandai (no network) and small synthetic pages."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from shared.basetypes import CardNumber, PackageId, PrintingId, SetCode
from shared.dataset import REPO_ROOT, TOOL_DATA_VAR
from shared.fetch import DEFAULT_USER_AGENT, FetchError, Fetcher, Response
from shared.test_fetch import _Handler, serve
from tools.gundam_cards import cli
from tools.gundam_cards.models import CardModel, CardSet, CardsFile, SetKind, SetsFile
from tools.gundam_cards.printings import DETAIL_URL, LIST_URL, detail_page_key
from tools.gundam_cards.refresh import ANOMALY_SHARE, RefreshReport, format_report, refresh_catalog
from tools.gundam_cards.sets import CARDS_URL, PRODUCTS_URL
from tools.gundam_cards.store import (
    catalog_export_path,
    data_out_dir,
    load_catalog,
    load_provisional_sets,
    load_sets,
    raw_folder,
    write_provisional_sets,
)

T1 = datetime(2026, 11, 1, tzinfo=UTC)
T2 = datetime(2026, 11, 2, tzinfo=UTC)
T3 = datetime(2026, 11, 3, tzinfo=UTC)
T4 = datetime(2026, 11, 4, tzinfo=UTC)

GD01 = "616101"  # in the tracked sets.json
GD09 = "616109"  # not tracked: becomes provisional
RP02 = "616902"


def detail(
    printing_id: str,
    name: str = "",
    *,
    kind: str = "UNIT",
    color: str = "Blue",
    rarity: str = "C",
    card_no: str | None = None,
    where: str = "Newtype Rising [GD01]",
) -> str:
    """A minimal Bandai detail page that the real parser reads."""
    number = printing_id.split("_p")[0]
    fields = {"Lv.": "2", "COST": "1", "COLOR": color, "TYPE": kind, "Zone": "Space", "Trait": "(Earth Federation)", "Link": "-",
              "AP": "1", "HP": "2", "Source Title": "-", "Where to get it": where}
    rows = "".join(f'<dt class="dataTit">{k}</dt><dd class="dataTxt">{v}</dd>' for k, v in fields.items())
    return (f'<html><body><div class="cardNo">{card_no or number}</div><div class="rarity">{rarity}</div>'
            f'<div class="blockIcon">1</div><h1 class="cardName">{name or "Card " + number}</h1><dl>{rows}</dl>'
            f'<div class="dataTxt isRegular">-</div></body></html>')


@dataclass
class FakeBandai:
    """Bandai's card site in memory. Writes the page cache like the real fetcher; records every request in order."""

    raw_dir: Path
    packages: dict[str, tuple[str, list[str]]]  # package id -> (label, listed printing ids)
    details: dict[str, str] = field(default_factory=dict)  # printing id -> detail page
    products: list[tuple[str, str]] = field(default_factory=list)  # (title, release date text)
    fail: set[str] = field(default_factory=set)  # urls that fail
    interrupt: set[str] = field(default_factory=set)  # urls during which the owner presses Ctrl-C
    calls: list[str] = field(default_factory=list)

    def page(self, url: str) -> str:
        if url == CARDS_URL:
            return "".join(f'<a data-val="{pid}">{label}</a>' for pid, (label, _) in self.packages.items())
        if url == f"{PRODUCTS_URL}?page=1":
            return "".join(
                f'<div class="productsDetail"><a class="productsDetailInner" href="https://example.test/p"><span class="cardCategory">'
                f'BOOSTER PACK</span><div class="cardTit">{title}</div><dl><dt class="cardInfoTit">Release Date</dt>'
                f'<dd class="cardInfoTxt">{released}</dd></dl></a></div>'
                for title, released in self.products
            )
        for pid, (_, ids) in self.packages.items():
            if url == LIST_URL.format(pid):
                return "".join(f'<a data-src="detail.php?detailSearch={i}">x</a>' for i in ids)
        printing_id = url.rsplit("=", 1)[1]
        if url == DETAIL_URL.format(printing_id):
            return self.details.get(printing_id) or detail(printing_id)
        raise FetchError(url, "HTTP 404", 404)

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        self.calls.append(url)
        if url in self.interrupt:
            raise KeyboardInterrupt
        if url in self.fail:
            raise FetchError(url, "HTTP 500", 500)
        text = self.page(url)
        if cache_key is not None:
            path = self.raw_dir / cache_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return Response(url, text, datetime.now(tz=UTC), from_cache=False)

    def detail_calls(self) -> list[str]:
        return [c for c in self.calls if c.startswith(DETAIL_URL.split("{}")[0])]


def write_tracked_sets(sets: tuple[CardSet, ...], generated_at: datetime, folder: Path) -> None:
    """A reviewed sets.json, as the owner keeps it by hand (no toolkit code writes it)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sets.json").write_text(SetsFile(generated_at=generated_at, data=sets).model_dump_json(), encoding="utf-8")


@pytest.fixture
def tracked(tmp_path: Path) -> Path:
    """A tracked folder with the reviewed sets.json: GD01 only."""
    folder = tmp_path / "tracked"
    gd01 = CardSet(code=SetCode("GD01"), name="Newtype Rising (reviewed)", kind=SetKind.BOOSTER, bandai_package_id=PackageId(GD01),
                   release_date=date(2025, 7, 25), product_category_raw="BOOSTER PACK", product_url=None)
    write_tracked_sets((gd01,), T1, folder)
    return folder


@pytest.fixture
def site(tmp_path: Path) -> FakeBandai:
    return FakeBandai(
        raw_folder(),
        {GD01: ("Newtype Rising [GD01]", ["GD01-001", "GD01-002"]), GD09: ("Future Pack [GD09]", ["GD09-001"])},
        details={"GD09-001": detail("GD09-001", where="Future Pack [GD09]")},
        products=[("Newtype Rising [GD01]", "July 25,2025"), ("Future Pack [GD09]", "March 5,2027")],
    )


def run(site: FakeBandai, tracked: Path, when: datetime, *, dry_run: bool = False, allow_anomaly: bool = False) -> RefreshReport:
    return refresh_catalog(site, site.raw_dir, tracked_dir=tracked, now=when, dry_run=dry_run, allow_anomaly=allow_anomaly)


def catalog() -> CardsFile:
    stored = load_catalog()
    assert stored is not None
    return stored


def numbers() -> list[str]:
    return [str(c.number) for c in catalog().data]


def card(number: str) -> CardModel:
    return next(c for c in catalog().data if c.number == CardNumber(number))


def flags() -> dict[str, tuple[bool, bool]]:
    return {str(r.number): (r.missed_once, r.no_longer_listed) for r in catalog().records}


def dataset_bytes() -> dict[str, bytes]:
    root = data_out_dir().parent
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ---- AC-1 --------------------------------------------------------------------------------------------------------------------
def test_first_refresh_builds_the_catalog_from_bandai_and_records_an_unknown_package_as_provisional(
    site: FakeBandai, tracked: Path
) -> None:
    tracked_before = (tracked / "sets.json").read_bytes()
    report = run(site, tracked, T1)

    assert report.complete and report.written and not report.rejected
    assert numbers() == ["GD01-001", "GD01-002", "GD09-001"]  # crawled with no hand-entered data
    [gd09] = load_provisional_sets()
    assert (gd09.code, gd09.name, gd09.bandai_package_id, gd09.release_date) == ("GD09", "Future Pack", GD09, date(2027, 3, 5))
    assert [s.code for s in report.provisional] == ["GD09"]
    assert (tracked / "sets.json").read_bytes() == tracked_before  # the golden list is never edited
    assert {s.code: s.name for s in load_sets(tracked)} == {"GD01": "Newtype Rising (reviewed)", "GD09": "Future Pack"}
    assert card("GD09-001").printings[0].package_ids == (GD09,)


def test_a_package_bandai_gives_no_release_date_for_is_still_recorded_and_crawled(site: FakeBandai, tracked: Path) -> None:
    site.packages[RP02] = ("Reprint Box [RP02]", ["RP02-001"])  # no product page: Bandai gives no release date
    site.details["RP02-001"] = detail("RP02-001", where="Reprint Box [RP02]")
    report = run(site, tracked, T1)

    assert report.written and [s.code for s in report.provisional] == ["GD09", "RP02"]
    rp02 = next(s for s in load_provisional_sets() if s.code == "RP02")
    assert (rp02.name, rp02.bandai_package_id, rp02.release_date) == ("Reprint Box", RP02, None)
    assert card("RP02-001").printings[0].package_ids == (RP02,)
    assert "provisional RP02 Reprint Box (released unknown)" in "\n".join(format_report(report))


def test_readers_of_sets_prefer_the_tracked_entry_when_a_code_is_in_both(tracked: Path) -> None:
    clash = CardSet(code=SetCode("GD01"), name="Bandai's name", kind=SetKind.BOOSTER, bandai_package_id=PackageId(GD01),
                    release_date=date(2025, 8, 1), product_category_raw=None, product_url=None)
    write_provisional_sets((clash,), T1)
    [gd01] = load_sets(tracked)
    assert gd01.name == "Newtype Rising (reviewed)" and gd01.release_date == date(2025, 7, 25)


def test_a_second_refresh_adds_new_cards_and_printings_and_removes_nothing(site: FakeBandai, tracked: Path) -> None:
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-001_p1", "GD01-002", "GD01-003"])
    report = run(site, tracked, T2)

    assert report.written and report.new_cards == ("GD01-003",) and report.new_printings == ("GD01-001_p1", "GD01-003")
    assert numbers() == ["GD01-001", "GD01-002", "GD01-003", "GD09-001"]  # nothing removed or duplicated
    first = {str(r.number): r.first_recorded for r in catalog().records}
    assert first == {"GD01-001": T1, "GD01-002": T1, "GD01-003": T2, "GD09-001": T1}
    assert [str(p.id) for p in card("GD01-001").printings] == ["GD01-001", "GD01-001_p1"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_refresh_reading_the_real_tracked_folder_changes_no_tracked_file(site: FakeBandai, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOOL_DATA_VAR)  # the repository's own tracked folder; the pages stay in the temp folder
    repo = REPO_ROOT
    status = ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"]
    if subprocess.run(["git", "-C", str(repo), "rev-parse"], capture_output=True, check=False).returncode != 0:
        pytest.skip("not inside a git checkout")
    before = subprocess.run(status, capture_output=True, text=True, check=True).stdout
    site.packages[PackageId("999999")] = ("Not Yet Promoted [GD99]", ["GD99-001"])
    assert refresh_catalog(site, site.raw_dir, now=T1).written  # tracked_dir defaults to the repository's own folder
    assert subprocess.run(status, capture_output=True, text=True, check=True).stdout == before


# ---- AC-2 --------------------------------------------------------------------------------------------------------------------
def test_a_reprint_package_adds_printings_to_existing_cards_and_creates_none(site: FakeBandai, tracked: Path) -> None:
    run(site, tracked, T1)
    before = card("GD01-001")
    site.packages[RP02] = ("Reprint Box [RP02]", ["GD01-001_p2", "GD01-002_p2"])
    site.details["GD01-001_p2"] = detail("GD01-001_p2", name="A different name on the reprint", where="Reprint Box [RP02]")
    site.details["GD01-002_p2"] = detail("GD01-002_p2", where="Reprint Box [RP02]")
    report = run(site, tracked, T2)

    assert report.written and report.new_cards == () and len(report.new_printings) == 2
    assert [s.code for s in report.provisional] == ["RP02"]  # the run records the package, though it adds no card
    assert {str(s.code): s.bandai_package_id for s in load_sets(tracked)}["RP02"] == RP02
    assert numbers() == ["GD01-001", "GD01-002", "GD09-001"]
    after = card("GD01-001")
    assert (after.number, after.name) == (before.number, before.name)
    base, reprint = after.printings
    assert (base.id, base.set_code, base.package_ids) == ("GD01-001", "GD01", (GD01,))  # its original set
    assert (reprint.id, reprint.set_code, reprint.package_ids) == ("GD01-001_p2", "RP02", (RP02,))  # the printing records the package
    assert [str(p.id) for p in card("GD01-002").printings] == ["GD01-002", "GD01-002_p2"]


def test_a_package_listing_existing_printing_ids_adds_itself_to_those_printings(site: FakeBandai, tracked: Path) -> None:
    run(site, tracked, T1)
    site.packages[RP02] = ("Reprint Box [RP02]", ["GD01-001"])
    report = run(site, tracked, T2)
    assert report.written and report.new_printings == () and report.new_cards == ()
    assert "RP02" in {s.code for s in load_sets(tracked)}  # recorded, though it lists only printings we have
    [printing] = card("GD01-001").printings  # no duplicate printing
    assert printing.package_ids == (GD01, RP02)


def test_a_printing_that_leaves_one_package_listing_keeps_that_package(site: FakeBandai, tracked: Path) -> None:
    run(site, tracked, T1)
    site.packages[RP02] = ("Reprint Box [RP02]", ["GD01-001"])
    run(site, tracked, T2)
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-002"])  # GD01's listing drops GD01-001; RP02 still lists it
    report = run(site, tracked, T3)
    assert report.written and report.missed == () and report.changed == ()
    [printing] = card("GD01-001").printings
    assert printing.package_ids == (GD01, RP02)  # a refresh never takes a package away (owner decision 2026-11-20)


def test_a_printing_no_listing_names_keeps_its_packages_while_its_card_is_listed(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-001_p1", "GD01-002"])
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-002"])  # GD01-001_p1 on no listing; GD01-001 still is
    dry = run(site, tracked, T2, dry_run=True)
    report = run(site, tracked, T2)
    assert report.written and report.missed == () and report.changed == () and not report.guard_trips
    assert (dry.missed, dry.changed, dry.guard_trips) == (report.missed, report.changed, report.guard_trips)
    assert [(str(p.id), p.package_ids) for p in card("GD01-001").printings] == [("GD01-001", (GD01,)), ("GD01-001_p1", (GD01,))]


def test_a_mixed_package_creates_cards_only_for_new_numbers_and_a_rerun_changes_nothing(site: FakeBandai, tracked: Path) -> None:
    run(site, tracked, T1)
    site.packages[RP02] = ("Reprint Box [RP02]", ["GD01-002_p3", "RP02-001"])
    site.details["GD01-002_p3"] = detail("GD01-002_p3", where="Reprint Box [RP02]")
    site.details["RP02-001"] = detail("RP02-001", where="Reprint Box [RP02]")
    report = run(site, tracked, T2)
    assert report.new_cards == ("RP02-001",) and report.new_printings == ("GD01-002_p3", "RP02-001")
    assert numbers() == ["GD01-001", "GD01-002", "GD09-001", "RP02-001"]
    assert [str(p.id) for p in card("GD01-002").printings] == ["GD01-002", "GD01-002_p3"]

    first, provisional = catalog(), (data_out_dir() / "provisional_sets.json").read_bytes()
    again = run(site, tracked, T3)
    assert again.written and again.new_cards == again.missed == again.changed == () and again.new_printings == ()
    second = catalog()
    assert (second.data, second.records) == (first.data, first.records)  # only the refresh time moves
    assert (data_out_dir() / "provisional_sets.json").read_bytes() == provisional


# ---- AC-3 --------------------------------------------------------------------------------------------------------------------
def test_a_card_is_marked_only_after_two_consecutive_complete_misses(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 51)])
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 50)])  # GD01-050 gone: 1 of 51

    first_miss = run(site, tracked, T2)
    assert first_miss.written and first_miss.missed == ("GD01-050",) and first_miss.marked == ()
    assert flags()["GD01-050"] == (True, False)  # recorded, nothing visible
    assert "GD01-050" in numbers()

    second_miss = run(site, tracked, T3)
    assert second_miss.marked == ("GD01-050",) and flags()["GD01-050"] == (True, True)
    assert "GD01-050" in numbers()  # never removed

    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 51)])
    run(site, tracked, T4)
    assert flags()["GD01-050"] == (False, False)  # listed again


def test_a_missed_card_keeps_its_stored_data_including_its_packages(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 51)])
    run(site, tracked, T1)
    stored = card("GD01-050")
    assert stored.printings[0].package_ids == (GD01,)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 50)])  # GD01-050 gone
    # its cached page now reads differently, so a rebuild of it would differ from what is stored
    (site.raw_dir / detail_page_key(PrintingId("GD01-050"))).write_text(detail("GD01-050", name="Renamed"), encoding="utf-8")

    first_miss = run(site, tracked, T2)
    assert first_miss.missed == ("GD01-050",) and flags()["GD01-050"] == (True, False)
    assert card("GD01-050") == stored  # one complete miss changes nothing visible: its stored data is kept
    second_miss = run(site, tracked, T3)
    assert second_miss.marked == ("GD01-050",) and flags()["GD01-050"] == (True, True)
    assert card("GD01-050") == stored  # marked no longer listed, its data (and package history) kept


def test_a_card_that_reappears_after_one_miss_has_its_miss_cleared(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 51)])
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 50)])
    run(site, tracked, T2)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 51)])
    run(site, tracked, T3)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 50)])
    run(site, tracked, T4)
    assert flags()["GD01-050"] == (True, False)  # a miss after a listing is a first miss again, not a second


def test_an_incomplete_run_counts_no_miss(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 51)])
    run(site, tracked, T1)
    run(site, tracked, T2)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 50)])
    site.fail.add(LIST_URL.format(GD09))
    before = dataset_bytes()
    report = run(site, tracked, T3)
    assert not report.complete and not report.written and report.missed == ()
    assert dataset_bytes() == before
    assert flags()["GD01-050"] == (False, False)


# ---- AC-4 --------------------------------------------------------------------------------------------------------------------
def test_shape_check_rejects_bad_cards_and_printings_and_keeps_the_rest(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "gd01-9", "GD01-003", "GD01-004", "GD01-005", "GD01-006",
                                                     "GD01-007", "GD01-007_p1"])
    site.details.update({
        "GD01-003": detail("GD01-003", kind="SPELL"),
        "GD01-004": detail("GD01-004", color="Orange"),
        "GD01-005": detail("GD01-005", rarity="SSR"),
        "GD01-006": detail("GD01-006", card_no="GD-01-006"),
        "GD01-007_p1": detail("GD01-007_p1", rarity="Q +"),
    })
    report = run(site, tracked, T1)

    assert report.written
    reasons = {r.subject: r.reason for r in report.rejected}
    assert "'gd01-9' is not a valid printing id" in reasons["listing of Newtype Rising [GD01] (616101)"]
    assert "unknown card TYPE 'SPELL'" in reasons["GD01-003"]
    assert "unknown color 'Orange'" in reasons["GD01-004"]
    assert "unrecognized rarity 'SSR'" in reasons["GD01-005"]
    assert "not a valid card number" in reasons["GD01-006"]
    assert "unrecognized rarity 'Q +'" in reasons["GD01-007_p1"]
    assert numbers() == ["GD01-001", "GD01-007", "GD09-001"]  # the valid rest is stored; nothing rejected is
    assert [str(p.id) for p in card("GD01-007").printings] == ["GD01-007"]
    assert any(line.startswith("rejected GD01-003: unknown card TYPE") for line in format_report(report))


def test_a_rejected_page_never_replaces_a_stored_card(site: FakeBandai, tracked: Path) -> None:
    run(site, tracked, T1)
    before = card("GD01-002")
    (site.raw_dir / detail_page_key(PrintingId("GD01-002"))).write_text(detail("GD01-002", kind="SPELL"), encoding="utf-8")
    report = run(site, tracked, T2)
    assert [r.subject for r in report.rejected] == ["GD01-002"] and "whole card left out" in report.rejected[0].reason
    assert card("GD01-002") == before


def _ten_cards(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 10)])
    run(site, tracked, T1)  # 9 + GD09-001 = 10 existing cards


def test_the_anomaly_guard_refuses_a_run_that_drops_too_many_cards(site: FakeBandai, tracked: Path) -> None:
    _ten_cards(site, tracked)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 8)])  # 2 of 10 gone: 20%
    before = dataset_bytes()
    report = run(site, tracked, T2)
    assert report.refused and not report.written and (len(report.missed), report.existing) == (2, 10)
    assert dataset_bytes() == before
    assert "anomaly guard: 2 dropped, 0 changed of 10 existing cards (limit 2%): would refuse" in format_report(report)

    forced = run(site, tracked, T2, allow_anomaly=True)
    assert forced.written and forced.guard_trips and not forced.refused
    assert flags()["GD01-009"] == (True, False)


def test_the_anomaly_guard_counts_changed_cards(site: FakeBandai, tracked: Path) -> None:
    _ten_cards(site, tracked)
    for number in ("GD01-001", "GD01-002"):
        (site.raw_dir / detail_page_key(PrintingId(number))).write_text(detail(number, name="Renamed"), encoding="utf-8")
    before = dataset_bytes()
    report = run(site, tracked, T2)
    assert report.refused and report.changed == ("GD01-001", "GD01-002") and report.missed == ()
    assert dataset_bytes() == before


def test_the_refresh_command_refuses_with_a_nonzero_exit_and_allow_anomaly_overrides(
    site: FakeBandai, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "refresh_fetcher", lambda: site)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 10)])
    assert cli.main(["refresh"]) == 0
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 8)])  # 2 of 10 gone
    capsys.readouterr()
    before = dataset_bytes()

    assert cli.main(["refresh"]) == 1  # refused
    assert "refused by the anomaly guard, nothing written" in capsys.readouterr().out
    assert dataset_bytes() == before

    assert cli.main(["refresh", "--allow-anomaly"]) == 0  # the owner's override reaches the refresh
    assert "would refuse (overridden)" in capsys.readouterr().out
    assert dataset_bytes() != before and flags()["GD01-009"] == (True, False)


@pytest.mark.parametrize(("existing", "written"), [(50, True), (49, False)])
def test_the_anomaly_guard_boundary_is_two_percent(site: FakeBandai, tracked: Path, existing: int, written: bool) -> None:
    assert ANOMALY_SHARE == 0.02
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, existing)])
    run(site, tracked, T1)  # existing - 1 + GD09-001 = existing cards
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, existing - 1)])  # 1 gone
    report = run(site, tracked, T2)
    assert (report.existing, len(report.missed)) == (existing, 1)
    assert report.written is written and report.guard_trips is not written  # exactly 2% passes; just over refuses


@pytest.mark.parametrize(
    "breakage",
    ["package list fails", "package list unreadable", "listing fails", "listing unreadable", "detail fails", "detail unreadable",
     "interrupted at the package list", "interrupted at a listing", "interrupted"],
)
def test_a_failed_or_interrupted_run_writes_nothing(site: FakeBandai, tracked: Path, breakage: str) -> None:
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-002", "GD01-003"])  # something new to write
    new_page = DETAIL_URL.format("GD01-003")
    match breakage:
        case "package list fails":
            site.fail.add(CARDS_URL)
        case "package list unreadable":
            site.packages.clear()  # the card page is fetched but shows no packages
        case "interrupted at the package list":
            site.interrupt.add(CARDS_URL)
        case "interrupted at a listing":
            site.interrupt.add(LIST_URL.format(GD09))
        case "listing fails":
            site.fail.add(LIST_URL.format(GD09))
        case "listing unreadable":
            site.packages[GD09] = ("Future Pack [GD09]", [])
        case "detail fails":
            site.fail.add(new_page)
        case "detail unreadable":
            site.details["GD01-003"] = "<html>Service temporarily unavailable</html>"
        case "interrupted":
            site.interrupt.add(new_page)
    before = dataset_bytes()
    if breakage.startswith("interrupted"):  # any interruption before the write phase writes nothing
        with pytest.raises(KeyboardInterrupt):
            run(site, tracked, T2)
    else:
        report = run(site, tracked, T2)
        assert not report.complete and not report.written and report.failure
        assert format_report(report)[0].startswith("refresh incomplete, nothing written")
        if breakage == "package list unreadable":
            assert report.failure.startswith("package list:") and "unreadable" in report.failure
    assert dataset_bytes() == before
    if breakage == "detail unreadable":
        assert not (site.raw_dir / detail_page_key(PrintingId("GD01-003"))).exists()  # asked again next run


@pytest.mark.parametrize("when", ["before the rename", "mid-write"])
@pytest.mark.parametrize("nth", [1, 2, 3, 4])
def test_an_interruption_during_the_write_phase_never_leaves_a_file_partly_written(
    site: FakeBandai, tracked: Path, monkeypatch: pytest.MonkeyPatch, nth: int, when: str
) -> None:
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-002", "GD01-003"])  # something new to write
    site.packages[PackageId("616110")] = ("Next Pack [GD10]", ["GD10-001"])  # a new provisional package: a 4th write
    before = dataset_bytes()
    writes = {"n": 0}
    real_replace, real_fdopen = os.replace, os.fdopen

    def replace(src: str, dst: Path) -> None:  # the rename that publishes a written file
        writes["n"] += 1
        if when == "before the rename" and writes["n"] == nth:
            raise KeyboardInterrupt
        real_replace(src, dst)

    class HalfWriter:
        def __init__(self, f: Any) -> None:
            self.f = f

        def __enter__(self) -> HalfWriter:
            return self

        def __exit__(self, *exc: object) -> None:
            self.f.close()

        def write(self, text: str) -> None:
            self.f.write(text[: len(text) // 2])
            raise KeyboardInterrupt

    def fdopen(fd: int, *args: Any, **kwargs: Any) -> Any:
        f = real_fdopen(fd, *args, **kwargs)
        if when == "mid-write" and writes["n"] == nth - 1:
            return HalfWriter(f)
        return f

    with monkeypatch.context() as patched, pytest.raises(KeyboardInterrupt):
        patched.setattr(os, "replace", replace)
        patched.setattr(os, "fdopen", fdopen)
        run(site, tracked, T2)

    after = dataset_bytes()
    assert not [name for name in after if ".tmp-" in name]  # no stray temporary file
    for name, content in after.items():
        assert content == before.get(name) or json.loads(content)  # each file is the old one or a whole new one
    assert (after["gundam_cards/cards.json"] != before["gundam_cards/cards.json"]) is (nth > 1)  # cards.json is written first
    provisional = "gundam_cards/provisional_sets.json"
    assert after[provisional] == before[provisional]  # written last: an interruption at any write leaves the old one
    assert "GD10" not in {s.code for s in load_provisional_sets()}

    assert run(site, tracked, T3).written  # the next run repairs any derived file left behind
    assert "GD10" in {s.code for s in load_provisional_sets()}  # ... and records the package left out
    stamps = {json.loads(after_bytes)["generated_at"] for name, after_bytes in dataset_bytes().items()
              if name in ("gundam_cards/cards.json", "gundam_cards/traits.json", "gundam_cards/source_titles.json")}
    assert len(stamps) == 1


def test_a_failed_first_run_creates_no_dataset(site: FakeBandai, tracked: Path) -> None:
    site.fail.add(DETAIL_URL.format("GD01-002"))
    assert not run(site, tracked, T1).written
    assert dataset_bytes() == {}


# ---- AC-5 --------------------------------------------------------------------------------------------------------------------
def test_a_run_with_nothing_new_requests_only_the_package_list_and_listings(site: FakeBandai, tracked: Path) -> None:
    run(site, tracked, T1)
    assert sorted(site.detail_calls()) == [DETAIL_URL.format(i) for i in ("GD01-001", "GD01-002", "GD09-001")]  # each once
    site.calls.clear()
    run(site, tracked, T2)
    assert site.calls == [CARDS_URL, f"{PRODUCTS_URL}?page=1", LIST_URL.format(GD01), LIST_URL.format(GD09)]


def test_the_refresh_uses_the_polite_fetcher() -> None:
    fetcher = cli.refresh_fetcher()
    assert isinstance(fetcher, Fetcher)
    assert fetcher._min_interval_s >= 0.5 and fetcher._user_agent == DEFAULT_USER_AGENT  # spacing itself: shared/test_fetch.py
    assert fetcher._cache_dir == raw_folder()


def _changes_for_a_dry_run(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 50)])
    run(site, tracked, T1)  # 49 + GD09-001 = 50 existing cards
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-001_p1", *[f"GD01-{n:03}" for n in range(3, 50)]])
    site.packages[PackageId("616110")] = ("Next Pack [GD10]", ["GD10-001"])
    site.products.append(("Next Pack [GD10]", "June 4,2027"))


def test_a_dry_run_reports_what_a_real_run_would_do_and_changes_nothing(site: FakeBandai, tracked: Path) -> None:
    _changes_for_a_dry_run(site, tracked)
    before, tracked_before = dataset_bytes(), (tracked / "sets.json").read_bytes()
    site.calls.clear()
    report = run(site, tracked, T2, dry_run=True)

    assert site.detail_calls() == [] and not report.written
    assert dataset_bytes() == before and (tracked / "sets.json").read_bytes() == tracked_before
    assert [s.code for s in report.provisional] == ["GD10"]
    assert report.packages_with_new == (("Newtype Rising [GD01]", False), ("Next Pack [GD10]", True))
    assert report.new_cards == ("GD10-001",) and report.new_printings == ("GD01-001_p1", "GD10-001")
    assert report.missed == ("GD01-002",) and not report.guard_trips
    lines = "\n".join(format_report(report))
    for expected in ("provisional GD10 Next Pack (released 2027-06-04)", "Next Pack [GD10] (provisional)",
                     "Newtype Rising [GD01] (known)", "1 new card number(s): GD10-001", "2 new printing(s): GD01-001_p1 GD10-001",
                     "1 card(s) missed: GD01-002", "anomaly guard: 1 dropped, 0 changed of 50 existing cards (limit 2%): ok",
                     "dry run: nothing written"):
        assert expected in lines

    real = run(site, tracked, T2)  # the real run does what the dry run said
    assert (real.new_cards, real.new_printings, real.missed) == (report.new_cards, report.new_printings, report.missed)


def test_a_tracked_set_without_a_package_id_is_reported_known_and_an_untracked_one_provisional(
    site: FakeBandai, tmp_path: Path
) -> None:
    folder = tmp_path / "tracked_gd06"
    gd01 = CardSet(code=SetCode("GD01"), name="Newtype Rising", kind=SetKind.BOOSTER, bandai_package_id=PackageId(GD01),
                   release_date=date(2025, 7, 25), product_category_raw="BOOSTER PACK", product_url=None)
    gd06 = CardSet(code=SetCode("GD06"), name="Stardust Trails", kind=SetKind.BOOSTER, bandai_package_id=None,
                   release_date=date(2026, 9, 1), product_category_raw="BOOSTER PACK", product_url=None)
    write_tracked_sets((gd01, gd06), T1, folder)
    run(site, folder, T1)
    site.packages[PackageId("616106")] = ("Stardust Trails [GD06]", ["GD06-001"])
    site.packages[PackageId("616110")] = ("Next Pack [GD10]", ["GD10-001"])
    expected = (("Stardust Trails [GD06]", False), ("Next Pack [GD10]", True))

    for report in (run(site, folder, T2, dry_run=True), run(site, folder, T2)):
        assert report.packages_with_new == expected
        assert [s.code for s in report.provisional] == ["GD10"]
        lines = "\n".join(format_report(report))
        assert "Stardust Trails [GD06] (known)" in lines and "Next Pack [GD10] (provisional)" in lines


def test_a_dry_run_reports_that_the_anomaly_guard_would_refuse(site: FakeBandai, tracked: Path) -> None:
    _ten_cards(site, tracked)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 8)])  # 2 of 10 gone
    before = dataset_bytes()
    report = run(site, tracked, T2, dry_run=True)
    assert report.guard_trips and not report.written and dataset_bytes() == before
    assert "anomaly guard: 2 dropped, 0 changed of 10 existing cards (limit 2%): would refuse" in format_report(report)


def test_the_refresh_fetcher_sends_the_toolkit_user_agent() -> None:
    with serve() as server:
        cli.refresh_fetcher().get_text(f"{server}/ok")  # no cache key: nothing written to the page cache
    assert _Handler.agents == [DEFAULT_USER_AGENT]


def test_the_refresh_command_dry_run(site: FakeBandai, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "refresh_fetcher", lambda: site)
    assert cli.main(["refresh", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "3 new card number(s): GD01-001 GD01-002 GD09-001" in out and "dry run: nothing written" in out
    assert site.detail_calls() == [] and dataset_bytes() == {}

    assert cli.main(["refresh"]) == 0
    assert numbers() == ["GD01-001", "GD01-002", "GD09-001"]
    assert not catalog_export_path().exists()  # only `export` writes the catalog export
    site.fail.add(CARDS_URL)
    assert cli.main(["refresh"]) == 1
