"""reparse-orphans: `reparse` (and the `sync` and `refetch` that end in one) leaves orphan pages out of the catalog and reports them.

An orphan is a cached detail page whose card is in no cached package listing and not in the catalog. Expected values are worked out by
hand from the pages each test writes; the fake Bandai and the page helpers are those of the refresh tests.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from shared.basetypes import PackageId, PrintingId, SetCode
from tools.gundam_cards import cli
from tools.gundam_cards.models import CardSet, SetKind
from tools.gundam_cards.printings import detail_page_key
from tools.gundam_cards.refresh import orphan_line
from tools.gundam_cards.sets import LANDING_KEY
from tools.gundam_cards.store import data_out_dir, load_catalog, pages_folder
from tools.gundam_cards.tests.bandai_web import Web, install_web
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai, detail, write_tracked_sets
from tools.gundam_cards.tests.test_safe_refresh import GD01, T1, cache, page, run

LISTED = ["GD01-001", "GD01-002", "GD01-003"]
CATALOG_FILES = ("cards.json", "traits.json", "source_titles.json")


@pytest.fixture
def tracked(tmp_path: Path) -> Path:
    gd01 = CardSet(
        code=SetCode("GD01"),
        name="Newtype Rising",
        kind=SetKind.BOOSTER,
        bandai_package_id=PackageId(GD01),
        release_date=date(2025, 7, 25),
        product_category_raw="BOOSTER PACK",
        product_url=None,
    )
    write_tracked_sets((gd01,), T1, tmp_path / "tracked")
    return tmp_path / "tracked"


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Web:
    return install_web(monkeypatch)


@pytest.fixture
def site() -> FakeBandai:
    return FakeBandai(
        pages_folder(),
        {GD01: ("Newtype Rising [GD01]", list(LISTED))},
        products=[("Newtype Rising [GD01]", "July 25,2025")],
    )


def stored_numbers() -> list[str]:
    stored = load_catalog()
    assert stored is not None
    return sorted(str(c.number) for c in stored.data)


def catalog_bytes() -> dict[str, bytes]:
    return {n: (data_out_dir() / n).read_bytes() for n in CATALOG_FILES if (data_out_dir() / n).is_file()}


def reparse(capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    code = cli.main(["reparse"])
    out = capsys.readouterr()
    return code, out.out, out.err


ORPHANS = "2 orphan page(s), in no listing and not in the catalog, not added: GD99-001 GD99-001_p1"


def cache_orphans() -> None:
    cache("GD99-001", detail("GD99-001"))
    cache("GD99-001_p1", detail("GD99-001_p1"))


# ---- AC-1 and AC-2: orphans are left out and named -----------------------------------------------------------------------------------
def test_reparse_leaves_an_orphan_out_of_an_existing_catalog_and_names_it(
    site: FakeBandai, tracked: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site, tracked, T1).written and stored_numbers() == LISTED
    cache_orphans()
    code, out, _ = reparse(capsys)
    assert code == 0  # an orphan alone does not change the exit status
    assert stored_numbers() == LISTED  # the card count is unchanged by it
    assert ORPHANS in out and "3 pages -> 3 cards" in out  # the same line the refresh prints
    assert out.count("orphan page(s)") == 1  # one report: the line appears once, not once per phase
    assert orphan_line([PrintingId("GD99-001"), PrintingId("GD99-001_p1")]) == ORPHANS


def test_reparse_builds_a_first_catalog_without_the_orphan(
    site: FakeBandai, tracked: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site, tracked, T1).written
    (data_out_dir() / "cards.json").unlink()  # no catalog yet: only the cached pages are left
    cache_orphans()
    code, out, _ = reparse(capsys)
    assert code == 0 and ORPHANS in out
    assert stored_numbers() == LISTED


def test_reparse_still_builds_listed_cards_and_stored_cards_no_listing_names(
    site: FakeBandai, tracked: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site, tracked, T1).written
    listing = pages_folder() / "lists" / f"{GD01}.html"
    listing.write_text(
        listing.read_text(encoding="utf-8").replace('<a data-src="detail.php?detailSearch=GD01-003">x</a>', ""),
        encoding="utf-8",
    )
    cache("GD01-002", page("GD01-002", name="Renamed"))  # a listed card is rebuilt as before
    code, out, _ = reparse(capsys)  # GD01-003 is stored but now unlisted: not an orphan
    assert code == 0 and "orphan" not in out and "3 pages -> 3 cards" in out
    assert stored_numbers() == LISTED
    stored = load_catalog()
    assert stored is not None and {str(c.number): c.name for c in stored.data}["GD01-002"] == "Renamed"


def test_an_unlisted_printing_page_of_a_listed_card_is_built_not_an_orphan(
    site: FakeBandai, tracked: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site, tracked, T1).written
    cache(
        "GD01-002_p1", detail("GD01-002_p1")
    )  # no listing names this printing id, but its card number GD01-002 is listed
    code, out, _ = reparse(capsys)
    assert code == 0 and "orphan" not in out and "4 pages -> 3 cards" in out
    stored = load_catalog()
    assert stored is not None
    card = next(c for c in stored.data if str(c.number) == "GD01-002")
    assert sorted(str(p.id) for p in card.printings) == ["GD01-002", "GD01-002_p1"]


def test_no_orphan_line_when_there_is_no_orphan(
    site: FakeBandai, tracked: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site, tracked, T1).written
    _, out, _ = reparse(capsys)
    assert "orphan" not in out


# ---- AC-1: no cached listing -------------------------------------------------------------------------------------------------------
def test_with_no_cached_listing_reparse_says_so_and_leaves_the_catalog_as_it_was(
    site: FakeBandai, tracked: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site, tracked, T1).written
    (pages_folder() / LANDING_KEY).unlink()  # no package list cached any more
    cache_orphans()
    before = catalog_bytes()
    code, out, err = reparse(capsys)
    assert code == 2 and "no cached package listings" in err and "cannot tell orphan pages from real cards" in err
    assert "pages ->" not in out and "orphan page" not in out  # it does not call every page an orphan
    assert catalog_bytes() == before and stored_numbers() == LISTED  # and does not build an empty catalog


def test_with_the_landing_page_cached_but_no_list_page_reparse_says_so_and_leaves_the_catalog_as_it_was(
    site: FakeBandai, tracked: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site, tracked, T1).written
    (
        pages_folder() / "lists" / f"{GD01}.html"
    ).unlink()  # the package list is known, but no package's listing is cached
    assert (pages_folder() / LANDING_KEY).is_file()
    cache_orphans()
    before = catalog_bytes()
    code, out, err = reparse(capsys)
    assert code == 2 and "no cached package listings" in err
    assert "pages ->" not in out and "orphan page" not in out
    assert catalog_bytes() == before and stored_numbers() == LISTED


def test_with_no_cached_listing_and_no_catalog_reparse_creates_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    for number in ("GD01-001", "GD01-002"):
        cache(number, detail(number))
    code, _, err = reparse(capsys)
    assert code == 2 and "no cached package listings" in err
    assert catalog_bytes() == {} and load_catalog() is None


# ---- AC-2: the commands that end in a reparse behave the same ----------------------------------------------------------------------
def test_sync_and_refetch_leave_the_orphan_out_and_name_it_too(web: Web, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["refresh"]) == 0
    cache("GD99-001", detail("GD99-001"))
    capsys.readouterr()

    assert cli.main(["sync"]) == 0
    out = capsys.readouterr().out
    assert "1 orphan page(s), in no listing and not in the catalog, not added: GD99-001" in out
    assert out.count("orphan page(s)") == 1  # one report, not one from sync and one from its reparse
    assert stored_numbers() == ["GD01-001", "GD01-002"]

    cache("GD01-001", page("GD01-001", name="Stale"))  # so the refetch finds a change and reparses
    assert cli.main(["refetch", "--card", "GD01-001"]) == 0
    out = capsys.readouterr().out
    assert "1 orphan page(s), in no listing and not in the catalog, not added: GD99-001" in out
    assert out.count("orphan page(s)") == 1
    assert stored_numbers() == ["GD01-001", "GD01-002"]
    assert (
        pages_folder() / detail_page_key(PrintingId("GD99-001"))
    ).is_file()  # only reported: its page is not deleted
