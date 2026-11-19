"""refresh-cards: the catalog refresh from Bandai, with a fake Bandai (no network) and small synthetic pages."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, PackageId, PrintingId, SetCode
from shared.fetch import DEFAULT_USER_AGENT, FetchError, Fetcher, Response
from tools.gundam_cards import cli
from tools.gundam_cards.models import CardModel, CardSet, CardsFile, SetKind
from tools.gundam_cards.printings import DETAIL_URL, LIST_URL, detail_page_key
from tools.gundam_cards.refresh import ANOMALY_SHARE, RefreshReport, format_report, refresh_catalog
from tools.gundam_cards.sets import CARDS_URL, PRODUCTS_URL
from tools.gundam_cards.store import (
    OUT_DIR,
    RAW_DIR,
    data_out_dir,
    load_catalog,
    load_provisional_sets,
    load_sets,
    write_provisional_sets,
    write_sets,
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


@pytest.fixture
def tracked(tmp_path: Path) -> Path:
    """A tracked folder with the reviewed sets.json: GD01 only."""
    folder = tmp_path / "tracked"
    gd01 = CardSet(code=SetCode("GD01"), name="Newtype Rising (reviewed)", kind=SetKind.BOOSTER, bandai_package_id=PackageId(GD01),
                   release_date=date(2025, 7, 25), product_category_raw="BOOSTER PACK", product_url=None)
    write_sets((gd01,), T1, folder)
    return folder


@pytest.fixture
def site(tmp_path: Path) -> FakeBandai:
    return FakeBandai(
        tmp_path / "raw",
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
def test_a_refresh_reading_the_real_tracked_folder_changes_no_tracked_file(site: FakeBandai) -> None:
    repo = OUT_DIR.parents[2]
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
    [printing] = card("GD01-001").printings  # no duplicate printing
    assert printing.package_ids == (GD01, RP02)


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
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 21)])
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 20)])  # GD01-020 gone

    first_miss = run(site, tracked, T2)
    assert first_miss.written and first_miss.missed == ("GD01-020",) and first_miss.marked == ()
    assert flags()["GD01-020"] == (True, False)  # recorded, nothing visible
    assert "GD01-020" in numbers()

    second_miss = run(site, tracked, T3)
    assert second_miss.marked == ("GD01-020",) and flags()["GD01-020"] == (True, True)
    assert "GD01-020" in numbers()  # never removed

    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 21)])
    run(site, tracked, T4)
    assert flags()["GD01-020"] == (False, False)  # listed again


def test_a_card_that_reappears_after_one_miss_has_its_miss_cleared(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 21)])
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 20)])
    run(site, tracked, T2)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 21)])
    run(site, tracked, T3)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 20)])
    run(site, tracked, T4)
    assert flags()["GD01-020"] == (True, False)  # a miss after a listing is a first miss again, not a second


def test_an_incomplete_run_counts_no_miss(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 21)])
    run(site, tracked, T1)
    run(site, tracked, T2)
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 20)])
    site.fail.add(LIST_URL.format(GD09))
    before = dataset_bytes()
    report = run(site, tracked, T3)
    assert not report.complete and not report.written and report.missed == ()
    assert dataset_bytes() == before
    assert flags()["GD01-020"] == (False, False)


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
    assert "anomaly guard: 2 dropped, 0 changed of 10 existing cards (limit 10%): would refuse" in format_report(report)

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


def test_the_anomaly_guard_lets_a_small_change_through(site: FakeBandai, tracked: Path) -> None:
    _ten_cards(site, tracked)
    assert ANOMALY_SHARE == 0.10
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 9)])  # 1 of 10: not more than 10%
    report = run(site, tracked, T2)
    assert report.written and not report.guard_trips


@pytest.mark.parametrize(
    "breakage",
    ["package list fails", "listing fails", "listing unreadable", "detail fails", "detail unreadable", "interrupted"],
)
def test_a_failed_or_interrupted_run_writes_nothing(site: FakeBandai, tracked: Path, breakage: str) -> None:
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-002", "GD01-003"])  # something new to write
    new_page = DETAIL_URL.format("GD01-003")
    match breakage:
        case "package list fails":
            site.fail.add(CARDS_URL)
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
    if breakage == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            run(site, tracked, T2)
    else:
        report = run(site, tracked, T2)
        assert not report.complete and not report.written and report.failure
        assert format_report(report)[0].startswith("refresh incomplete, nothing written")
    assert dataset_bytes() == before
    if breakage == "detail unreadable":
        assert not (site.raw_dir / detail_page_key(PrintingId("GD01-003"))).exists()  # asked again next run


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
    assert fetcher._cache_dir == RAW_DIR


def _changes_for_a_dry_run(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", [f"GD01-{n:03}" for n in range(1, 10)])
    run(site, tracked, T1)
    site.packages[GD01] = ("Newtype Rising [GD01]", ["GD01-001", "GD01-001_p1", *[f"GD01-{n:03}" for n in range(3, 10)]])
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
                     "1 card(s) missed: GD01-002", "anomaly guard: 1 dropped, 0 changed of 10 existing cards (limit 10%): ok",
                     "dry run: nothing written"):
        assert expected in lines

    real = run(site, tracked, T2)  # the real run does what the dry run said
    assert (real.new_cards, real.new_printings, real.missed) == (report.new_cards, report.new_printings, report.missed)


def test_the_refresh_command_dry_run(site: FakeBandai, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "refresh_fetcher", lambda: site)
    monkeypatch.setattr(cli, "RAW_DIR", site.raw_dir)
    assert cli.main(["refresh", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "3 new card number(s): GD01-001 GD01-002 GD09-001" in out and "dry run: nothing written" in out
    assert site.detail_calls() == [] and dataset_bytes() == {}

    assert cli.main(["refresh"]) == 0
    assert numbers() == ["GD01-001", "GD01-002", "GD09-001"]
    site.fail.add(CARDS_URL)
    assert cli.main(["refresh"]) == 1
