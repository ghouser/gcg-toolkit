"""safe-refresh: one Bandai page cache in the dataset, every field-level change counted and named, orphan pages reported.

The refresh logic runs with the fake Bandai of the refresh tests; the commands run through `cli.main` with only the network faked, so the
real `Fetcher` writes the cache wherever the command points it. Expected values are worked out by hand from the pages each test writes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, PackageId, PrintingId, SetCode
from shared.dataset import ENV_VAR, TOOL_DATA_VAR
from shared.test_tool_data_dir import bandai_pages
from tools.gundam_cards import cli
from tools.gundam_cards.models import CardModel, CardSet, SetKind
from tools.gundam_cards.printings import DETAIL_URL, detail_page_key
from tools.gundam_cards.refresh import ChangedCard, RefreshReport, format_report, refresh_catalog
from tools.gundam_cards.sets import CARDS_URL, LANDING_KEY, PRODUCTS_URL, products_page_key
from tools.gundam_cards.store import data_out_dir, load_catalog, load_provisional_sets, pages_folder
from tools.gundam_cards.tests.bandai_web import Web, install_web
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai, dataset_bytes, detail, write_tracked_sets

T1 = datetime(2026, 11, 1, tzinfo=UTC)
T2 = datetime(2026, 11, 2, tzinfo=UTC)
GD01 = "616101"
GD09 = "616109"
NINE = ["GD01-001", "GD01-001_p1", *[f"GD01-{n:03}" for n in range(2, 10)]]  # 9 GD01 cards; GD01-001 has an alt art


def page(printing_id: str, *, name: str = "", source_title: str = "-", text: str = "-", faq: str = "") -> str:
    """A detail page the real parser reads, with a source title, card text and an FAQ entry when given."""
    html = detail(printing_id, name=name)
    html = html.replace(
        'Source Title</dt><dd class="dataTxt">-<', f'Source Title</dt><dd class="dataTxt">{source_title}<'
    )
    html = html.replace('<div class="dataTxt isRegular">-</div>', f'<div class="dataTxt isRegular">{text}</div>')
    if faq:
        html = html.replace(
            "</body>",
            f'<h3 class="qaColNum">Q1</h3><p class="qaColDate"><span>July 04, 2025</span> Updated</p>'
            f'<dl><dt class="qaColQuestion">May I?</dt><dd class="qaColAnswer">{faq}</dd></dl></body>',
        )
    return html


def cache(printing_id: str, html: str) -> None:
    path = pages_folder() / detail_page_key(PrintingId(printing_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


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
def site() -> FakeBandai:
    """Ten cards once refreshed: GD01-001 (with GD01-001_p1) to GD01-009, and GD09-001."""
    return FakeBandai(
        pages_folder(),
        {GD01: ("Newtype Rising [GD01]", list(NINE)), GD09: ("Future Pack [GD09]", ["GD09-001"])},
        products=[("Newtype Rising [GD01]", "July 25,2025"), ("Future Pack [GD09]", "March 5,2027")],
    )


def run(
    site: FakeBandai, tracked: Path, when: datetime, *, dry_run: bool = False, allow_anomaly: bool = False
) -> RefreshReport:
    return refresh_catalog(
        site, site.raw_dir, tracked_dir=tracked, now=when, dry_run=dry_run, allow_anomaly=allow_anomaly
    )


def ten_cards(site: FakeBandai, tracked: Path) -> None:
    assert run(site, tracked, T1).written and len(cards()) == 10


def cards() -> dict[str, CardModel]:
    stored = load_catalog()
    assert stored is not None
    return {str(c.number): c for c in stored.data}


# ---- AC-1: one cache, in the dataset ------------------------------------------------------------------------------------------------
@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Web:
    return install_web(monkeypatch)


FUTURE = FakeBandai(
    Path(), {"616190": ("Future Pack [GD90]", ["GD90-001"])}, products=[("Future Pack [GD90]", "March 5,2027")]
)
OLD = FakeBandai(Path(), {"616191": ("Old Pack [GD91]", ["GD91-001"])}, products=[("Old Pack [GD91]", "May 1,2025")])


def write_package_list(folder: Path, site: FakeBandai) -> None:
    """The cached landing page and first product page (what the sets rebuild reads), as `site` draws them."""
    for key, url in ((LANDING_KEY, CARDS_URL), (products_page_key(1), f"{PRODUCTS_URL}?page=1")):
        (folder / key).parent.mkdir(parents=True, exist_ok=True)
        (folder / key).write_text(site.page(url), encoding="utf-8")


def checkout_with_an_old_cache(folder: Path) -> dict[str, bytes]:
    """A checkout whose own raw folder holds an older Bandai cache (a detail page, and a package list naming GD91, not GD90);
    returns its files' bytes, to compare after a run."""
    raw = folder / "tools" / "gundam_cards" / "data" / "raw"
    (raw / "detail").mkdir(parents=True)
    (raw / detail_page_key(PrintingId("GD01-001"))).write_text(
        detail("GD01-001", name="Old Checkout Name"), encoding="utf-8"
    )
    write_package_list(raw, OLD)
    return {str(p): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def files_of(folder: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_two_checkouts_share_the_datasets_page_cache_and_ignore_their_own(
    web: Web, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout_b = tmp_path / "checkout-b"
    old_b = checkout_with_an_old_cache(checkout_b)
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "dataset"))

    monkeypatch.setenv(TOOL_DATA_VAR, str(checkout_b))
    assert cli.main(["refresh"]) == 0
    assert sorted(web.detail_requests()) == [
        DETAIL_URL.format("GD01-001"),
        DETAIL_URL.format("GD01-002"),
    ]  # B's old page not read
    assert cards()["GD01-001"].name == "Card GD01-001"  # Bandai's page, not the checkout's old one
    assert files_of(checkout_b) == old_b  # and the checkout's cache is not changed
    assert sorted(p.name for p in (tmp_path / "dataset" / "gundam_cards" / "pages" / "detail").iterdir()) == [
        "GD01-001.html",
        "GD01-002.html",
    ]

    web.requested.clear()
    monkeypatch.setenv(TOOL_DATA_VAR, str(tmp_path / "checkout-a"))
    assert cli.main(["refresh"]) == 0
    assert web.detail_requests() == []  # the pages B's run cached are not requested again from checkout A
    assert not (tmp_path / "checkout-a").exists()

    web.requested.clear()
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "other-dataset"))
    assert cli.main(["refresh"]) == 0
    assert len(web.detail_requests()) == 2  # another dataset has its own, empty, cache
    assert (tmp_path / "other-dataset" / "gundam_cards" / "pages" / detail_page_key(PrintingId("GD01-002"))).is_file()


def test_refetch_and_reparse_do_not_read_a_checkouts_old_cache(
    web: Web, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = tmp_path / "checkout"
    old = checkout_with_an_old_cache(checkout)
    monkeypatch.setenv(TOOL_DATA_VAR, str(checkout))

    assert (
        cli.main(["refetch", "--card", "GD01-001"]) == 2
    )  # the dataset has no package list; the checkout's is not used
    assert "no cached package list" in capsys.readouterr().err
    assert cli.main(["reparse"]) == 2  # no listings in the dataset to tell cards from orphans: nothing built
    assert "no cached package listings" in capsys.readouterr().err  # the checkout's old detail page is not built
    assert files_of(checkout) == old and web.requested == []


def provisional_codes() -> list[str]:
    return [str(s.code) for s in load_provisional_sets()]


def test_reparse_rebuilds_the_sets_from_the_datasets_package_list_not_the_checkouts(
    web: Web, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = tmp_path / "checkout"
    old = checkout_with_an_old_cache(checkout)
    monkeypatch.setenv(TOOL_DATA_VAR, str(checkout))
    write_package_list(pages_folder(), FUTURE)

    cli.main(["reparse"])
    assert "1 sets on Bandai's list, 1 provisional" in capsys.readouterr().out
    assert provisional_codes() == ["GD90"]  # from the dataset's pages; the checkout's GD91 is not read
    assert files_of(checkout) == old and web.requested == []


def test_sync_rebuilds_the_sets_from_the_pages_it_cached_in_the_dataset(
    web: Web, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    old = checkout_with_an_old_cache(checkout)
    monkeypatch.setenv(TOOL_DATA_VAR, str(checkout))
    web.pages.update(bandai_pages(FUTURE))
    web.pages[DETAIL_URL.format("GD90-001")] = detail("GD90-001", where="Future Pack [GD90]")

    cli.main(["sync"])
    assert (pages_folder() / LANDING_KEY).read_text(encoding="utf-8") == FUTURE.page(CARDS_URL)
    assert provisional_codes() == ["GD90"]  # the reparse inside sync read the dataset's pages, not the checkout's GD91
    assert "GD90-001" in cards()
    assert files_of(checkout) == old


# ---- AC-2 and AC-3: every field-level change counted and named ----------------------------------------------------------------------
CHANGES = {  # what is written to the cache after the first refresh -> the changed card and its fields (worked out by hand)
    "name": ({"GD01-002": page("GD01-002", name="Renamed")}, ChangedCard(CardNumber("GD01-002"), ("name",))),
    "faq": ({"GD01-003": page("GD01-003", faq="Yes.")}, ChangedCard(CardNumber("GD01-003"), ("faq",))),
    "text": ({"GD01-004": page("GD01-004", text="Draw 1.")}, ChangedCard(CardNumber("GD01-004"), ("text", "GD01-004 text"))),
    "printing source title": ({"GD01-001_p1": page("GD01-001_p1", source_title="Mobile Suit Gundam")},
                              ChangedCard(CardNumber("GD01-001"), ("GD01-001_p1 source_title",))),
}  # fmt: skip


@pytest.mark.parametrize("family", list(CHANGES))
def test_each_kind_of_field_change_is_counted_and_named(site: FakeBandai, tracked: Path, family: str) -> None:
    ten_cards(site, tracked)
    pages, expected = CHANGES[family]
    for printing_id, html in pages.items():
        cache(printing_id, html)
    for report in (run(site, tracked, T2, dry_run=True), run(site, tracked, T2)):
        assert report.changed == (expected,)
        assert report.refused  # 1 of 10 is over the 2% limit
        lines = format_report(report)
        assert "anomaly guard: 0 dropped, 1 changed of 10 existing cards (limit 2%): would refuse" in lines
        assert f"  changed {expected.number}: {', '.join(expected.fields)}" in lines


def test_a_stored_printing_missing_from_the_rebuild_is_a_change(site: FakeBandai, tracked: Path) -> None:
    ten_cards(site, tracked)
    site.packages[GD01] = (
        "Newtype Rising [GD01]",
        [i for i in NINE if i != "GD01-001_p1"],
    )  # no listing names it any more
    (pages_folder() / detail_page_key(PrintingId("GD01-001_p1"))).unlink()  # and a fresh cache has no page for it
    report = run(site, tracked, T2)
    assert report.changed == (ChangedCard(CardNumber("GD01-001"), ("GD01-001_p1 missing",)),) and report.refused
    assert [str(p.id) for p in cards()["GD01-001"].printings] == ["GD01-001", "GD01-001_p1"]  # refused: nothing written


@pytest.mark.parametrize("growth", ["a new printing", "a new package", "a page fetched again", "nothing"])
def test_gaining_a_printing_or_a_package_is_not_a_change(site: FakeBandai, tracked: Path, growth: str) -> None:
    ten_cards(site, tracked)
    if growth == "a new printing":
        site.packages[GD01] = ("Newtype Rising [GD01]", [*NINE, "GD01-002_p1"])
    elif growth == "a new package":
        site.packages[PackageId("616901")] = ("Reprint Pack [RP01]", ["GD01-003"])
    elif growth == "a page fetched again":
        cache("GD01-005", detail("GD01-005"))  # same page, new fetch time
    report = run(site, tracked, T2)
    assert report.changed == () and report.written
    assert not any(line.startswith("  changed ") for line in format_report(report))
    if growth == "a new printing":
        assert [str(p.id) for p in cards()["GD01-002"].printings] == ["GD01-002", "GD01-002_p1"]
    if growth == "a new package":
        assert cards()["GD01-003"].printings[0].package_ids == (GD01, "616901")


FIFTY = ["GD01-001", "GD01-001_p1", *[f"GD01-{n:03}" for n in range(2, 50)]]  # 49 GD01 cards; with GD09-001, 50


def fifty_cards(site: FakeBandai, tracked: Path) -> None:
    site.packages[GD01] = ("Newtype Rising [GD01]", list(FIFTY))
    assert run(site, tracked, T1).written and len(cards()) == 50


def test_the_guard_counts_n_changed_cards_and_allow_anomaly_still_writes(site: FakeBandai, tracked: Path) -> None:
    fifty_cards(site, tracked)
    cache("GD01-002", page("GD01-002", name="Renamed"))
    cache("GD01-003", page("GD01-003", faq="Yes."))
    cache("GD01-001_p1", page("GD01-001_p1", source_title="Mobile Suit Gundam"))
    before = dataset_bytes()

    dry = run(site, tracked, T2, dry_run=True)
    real = run(site, tracked, T2)
    assert dry.changed == real.changed and [str(c.number) for c in real.changed] == ["GD01-001", "GD01-002", "GD01-003"]
    assert guard_lines(dry) == guard_lines(real)  # the same guard line and changed lines
    assert "anomaly guard: 0 dropped, 3 changed of 50 existing cards (limit 2%): would refuse" in format_report(real)
    assert real.refused and dataset_bytes() == before  # neither run wrote anything

    forced = run(site, tracked, T2, allow_anomaly=True)
    assert forced.written and cards()["GD01-001"].printings[1].source_title == "Mobile Suit Gundam"


def guard_lines(report: RefreshReport) -> list[str]:
    return [line for line in format_report(report) if line.startswith(("anomaly guard", "  changed "))]


# ---- AC-4: orphan pages -------------------------------------------------------------------------------------------------------------
def test_an_orphan_page_is_reported_and_not_added(site: FakeBandai, tracked: Path) -> None:
    ten_cards(site, tracked)
    cache("GD99-001", detail("GD99-001"))
    cache("GD99-001_p1", detail("GD99-001_p1"))
    cache("GD01-002_p3", detail("GD01-002_p3"))  # a listed card's unlisted printing: not an orphan
    expected = "2 orphan page(s), in no listing and not in the catalog, not added: GD99-001 GD99-001_p1"

    dry = run(site, tracked, T2, dry_run=True)
    real = run(site, tracked, T2)
    for report in (dry, real):
        assert report.orphans == ("GD99-001", "GD99-001_p1") and expected in format_report(report)
    assert real.written and not real.guard_trips  # orphans alone never refuse a run
    assert "GD99-001" not in cards() and len(cards()) == 10


def test_a_stored_card_missing_from_the_listings_is_missed_not_an_orphan(site: FakeBandai, tracked: Path) -> None:
    ten_cards(site, tracked)
    site.packages[GD01] = ("Newtype Rising [GD01]", [i for i in NINE if i != "GD01-009"])
    report = run(site, tracked, T2, allow_anomaly=True)
    assert report.missed == ("GD01-009",) and report.orphans == ()
    assert not any("orphan" in line for line in format_report(report))  # with none, no orphan line
    assert "GD01-009" in cards()


def test_the_refresh_command_prints_changed_cards_and_orphans(
    site: FakeBandai, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "refresh_fetcher", lambda: site)
    assert cli.main(["refresh"]) == 0
    assert site.raw_dir == pages_folder() == data_out_dir() / "pages"
    cache("GD01-002", page("GD01-002", name="Renamed"))
    cache("GD99-001", detail("GD99-001"))
    capsys.readouterr()

    assert cli.main(["refresh", "--dry-run"]) == 1  # 1 changed of 10: refused
    out = capsys.readouterr().out
    assert "  changed GD01-002: name" in out
    assert "1 orphan page(s), in no listing and not in the catalog, not added: GD99-001" in out


# The limit is 2% of 50 existing cards: 1 affected card (2%) passes, 2 (4%) refuse.
def test_one_dropped_and_one_changed_are_added_together_and_refused(site: FakeBandai, tracked: Path) -> None:
    fifty_cards(site, tracked)
    site.packages[GD01] = ("Newtype Rising [GD01]", [i for i in FIFTY if i != "GD01-049"])  # 1 dropped: 2% alone
    cache("GD01-002", page("GD01-002", name="Renamed"))  # 1 changed: 2% alone
    before = dataset_bytes()
    report = run(site, tracked, T2)
    assert report.missed == ("GD01-049",) and report.changed == (ChangedCard(CardNumber("GD01-002"), ("name",)),)
    assert "anomaly guard: 1 dropped, 1 changed of 50 existing cards (limit 2%): would refuse" in format_report(report)
    assert report.refused and dataset_bytes() == before  # together 4%: over the limit


def test_changed_cards_at_the_limit_pass_and_a_card_with_several_changed_fields_counts_once(
    site: FakeBandai, tracked: Path
) -> None:
    fifty_cards(site, tracked)
    cache("GD01-002", page("GD01-002", name="Renamed", faq="Yes."))  # one card, two fields: 1 changed card, 2%
    report = run(site, tracked, T2)
    lines = format_report(report)
    assert "anomaly guard: 0 dropped, 1 changed of 50 existing cards (limit 2%): ok" in lines
    assert "  changed GD01-002: faq, name" in lines and "written" in lines  # named in a real, passing run
    assert report.written and not report.guard_trips
    assert cards()["GD01-002"].name == "Renamed" and len(cards()["GD01-002"].faq) == 1
