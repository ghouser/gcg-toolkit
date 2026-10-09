"""Printing ids from list pages, and the sync that fetches only what's missing."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, PackageId, PrintingId
from shared.fetch import FetchError, Response
from tools.gundam_cards.printings import (
    DETAIL_URL,
    LIST_URL,
    detail_page_key,
    list_page_key,
    parse_card_list,
    read_package_lists,
    read_packages,
    refetch_printings,
    select_printings,
    sync_printings,
)
from tools.gundam_cards.sets import LANDING_KEY, PackageEntry
from tools.gundam_cards.store import packages_by_printing

FIXTURES = Path(__file__).parent / "fixtures"
ST01 = PackageEntry(PackageId("616001"), "Heroic Beginnings [ST01]")
BASIC = PackageEntry(PackageId("616801"), "Basic Cards")


def _list_html(package: PackageEntry) -> str:
    return (FIXTURES / "lists" / f"{package.id}.html").read_text(encoding="utf-8")


class FakeFetcher:
    """Serves saved list pages and a stub detail page; writes to the cache like the real one; records calls."""

    def __init__(self, raw_dir: Path, fail: frozenset[str] = frozenset()) -> None:
        self.raw_dir = raw_dir
        self.fail = fail
        self.calls: list[tuple[str, bool]] = []  # (url, force)

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        self.calls.append((url, force))
        if url.startswith(LIST_URL.split("{}")[0]):
            package_id = url.rsplit("=", 1)[1]
            text = _list_html(next(p for p in (ST01, BASIC) if p.id == package_id))
        else:
            printing_id = url.rsplit("=", 1)[1]
            if printing_id in self.fail:
                raise FetchError(url, "HTTP 500", 500)
            text = f"<html>{printing_id}</html>"
        if cache_key is not None:
            path = self.raw_dir / cache_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return Response(url, text, datetime.now(tz=UTC), from_cache=False)


def test_parse_card_list() -> None:
    ids = parse_card_list(_list_html(ST01))
    assert len(ids) == len(set(ids)) == 35
    assert PrintingId("ST01-001") in ids and PrintingId("ST01-001_p1") in ids
    assert len(parse_card_list(_list_html(BASIC))) == 3
    assert parse_card_list("<html></html>") == ()


def test_sync_fetches_only_missing_pages_and_always_refreshes_lists(tmp_path: Path) -> None:
    cached = PrintingId("ST01-001")
    (tmp_path / detail_page_key(cached)).parent.mkdir(parents=True)
    (tmp_path / detail_page_key(cached)).write_text("already here", encoding="utf-8")
    fetcher = FakeFetcher(tmp_path)

    report = sync_printings(fetcher, tmp_path, [ST01, BASIC])

    assert (report.packages, report.listed, report.already_cached, report.fetched, report.failures) == (2, 38, 1, 37, ())
    list_calls = [c for c in fetcher.calls if c[0].startswith(LIST_URL.split("{}")[0])]
    assert list_calls == [(LIST_URL.format(ST01.id), True), (LIST_URL.format(BASIC.id), True)]  # lists are forced fresh
    detail_calls = [c for c in fetcher.calls if c not in list_calls]
    assert len(detail_calls) == 37 and all(force is False for _, force in detail_calls)
    assert (DETAIL_URL.format(cached), False) not in detail_calls  # a cached page is never re-pinged
    assert (tmp_path / detail_page_key(cached)).read_text(encoding="utf-8") == "already here"
    assert (tmp_path / detail_page_key(PrintingId("ST01-001_p1"))).is_file()


def test_second_sync_fetches_no_detail_pages(tmp_path: Path) -> None:
    sync_printings(FakeFetcher(tmp_path), tmp_path, [ST01, BASIC])
    again = FakeFetcher(tmp_path)
    report = sync_printings(again, tmp_path, [ST01, BASIC])
    assert (report.fetched, report.already_cached) == (0, 38)
    assert len(again.calls) == 2  # only the two list pages


def test_failures_are_reported_and_do_not_stop_the_sync(tmp_path: Path) -> None:
    fetcher = FakeFetcher(tmp_path, fail=frozenset({"ST01-002", "ST01-003"}))
    report = sync_printings(fetcher, tmp_path, [ST01])
    assert report.fetched == 33 and sorted(str(i) for i, _ in report.failures) == ["ST01-002", "ST01-003"]
    assert not (tmp_path / detail_page_key(PrintingId("ST01-002"))).exists()
    retry = sync_printings(FakeFetcher(tmp_path), tmp_path, [ST01])  # the next sync picks the failures up again
    assert retry.fetched == 2 and retry.failures == ()


def test_progress_messages(tmp_path: Path) -> None:
    messages: list[str] = []
    sync_printings(FakeFetcher(tmp_path), tmp_path, [BASIC], progress=messages.append)
    assert messages[0] == "3 printings listed across 1 packages"
    assert messages[-1].startswith("fetched 3/3")


def test_package_membership_from_cached_pages(tmp_path: Path) -> None:
    landing = (FIXTURES / "sets" / "landing.html").read_text(encoding="utf-8")
    (tmp_path / LANDING_KEY).parent.mkdir(parents=True)
    (tmp_path / LANDING_KEY).write_text(landing, encoding="utf-8")
    for package in (ST01, BASIC):
        (tmp_path / list_page_key(package.id)).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / list_page_key(package.id)).write_text(_list_html(package), encoding="utf-8")

    assert len(read_packages(tmp_path)) == 25
    lists = read_package_lists(tmp_path, read_packages(tmp_path))
    assert set(lists) == {ST01.id, BASIC.id}  # only packages with a cached list page
    membership = packages_by_printing(tmp_path)
    assert membership[PrintingId("ST01-001_p1")] == (ST01.id,)


def test_no_cache_means_no_packages(tmp_path: Path) -> None:
    assert read_packages(tmp_path) == ()
    assert packages_by_printing(tmp_path) == {}


# ---- refetch ---------------------------------------------------------------------------------------------
def _seed_cache(raw_dir: Path) -> None:
    """A cache like after a sync of ST01 + Basic: landing, list pages, and a stub detail page per printing."""
    (raw_dir / LANDING_KEY).parent.mkdir(parents=True, exist_ok=True)
    (raw_dir / LANDING_KEY).write_text((FIXTURES / "sets" / "landing.html").read_text(encoding="utf-8"), encoding="utf-8")
    for package in (ST01, BASIC):
        (raw_dir / list_page_key(package.id)).parent.mkdir(parents=True, exist_ok=True)
        (raw_dir / list_page_key(package.id)).write_text(_list_html(package), encoding="utf-8")
        for printing_id in parse_card_list(_list_html(package)):
            path = raw_dir / detail_page_key(printing_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"<html>{printing_id}</html>", encoding="utf-8")


def test_select_printings_by_card_package_and_everything(tmp_path: Path) -> None:
    _seed_cache(tmp_path)
    packages = read_packages(tmp_path)
    assert [str(i) for i in select_printings(tmp_path, packages, card=CardNumber("ST01-001"))] == ["ST01-001", "ST01-001_p1"]
    assert len(select_printings(tmp_path, packages, package="616001")) == 35  # by Bandai package id
    assert select_printings(tmp_path, packages, package="ST01") == select_printings(tmp_path, packages, package="616001")  # by set code
    assert len(select_printings(tmp_path, packages)) == 38  # everything that has a cached list page
    assert select_printings(tmp_path, packages, card=CardNumber("GD05-111")) == ()


def test_select_printings_rejects_an_unknown_package(tmp_path: Path) -> None:
    _seed_cache(tmp_path)
    with pytest.raises(ValueError, match="no such package"):
        select_printings(tmp_path, read_packages(tmp_path), package="XX99")


def test_refetch_reports_what_actually_changed(tmp_path: Path) -> None:
    _seed_cache(tmp_path)
    ids = [PrintingId("ST01-001"), PrintingId("ST01-002"), PrintingId("ST01-003")]
    (tmp_path / detail_page_key(ids[1])).write_text("<html>an older copy</html>", encoding="utf-8")  # Bandai now serves different content
    fetcher = FakeFetcher(tmp_path, fail=frozenset({"ST01-003"}))

    report = refetch_printings(fetcher, tmp_path, ids)

    assert report.changed == (ids[1],) and report.unchanged == (ids[0],) and [i for i, _ in report.failures] == [ids[2]]
    assert all(force is True for _, force in fetcher.calls)  # a refetch always bypasses the cache
    assert (tmp_path / detail_page_key(ids[1])).read_text(encoding="utf-8") == "<html>ST01-002</html>"  # replaced
    assert (tmp_path / detail_page_key(ids[2])).read_text(encoding="utf-8") == "<html>ST01-003</html>"  # a failure leaves the old copy


def test_refetching_a_page_with_no_cached_copy_counts_as_changed(tmp_path: Path) -> None:
    fetcher = FakeFetcher(tmp_path)
    assert refetch_printings(fetcher, tmp_path, [PrintingId("ST01-001")]).changed == (PrintingId("ST01-001"),)
