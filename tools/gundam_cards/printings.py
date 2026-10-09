"""Printings: each package's card list page gives printing ids; each id has a detail page to fetch once.

- List pages are always refetched (new cards appear in packages).
- Detail pages are fetched only if not already cached; a cached page is never re-pinged (use `refetch` for that).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from shared.basetypes import CardNumber, PackageId, PrintingId
from shared.fetch import FetchError, TextFetcher
from tools.gundam_cards.sets import CARDS_URL, LANDING_KEY, PackageEntry, parse_package_filter, split_title

DETAIL_URL = CARDS_URL + "detail.php?detailSearch={}"
LIST_URL = CARDS_URL + "index.php?package={}"


def list_page_key(package_id: PackageId) -> str:
    return f"lists/{package_id}.html"


def detail_page_key(printing_id: PrintingId) -> str:
    return f"detail/{printing_id}.html"


class _CardListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: dict[str, None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        src = dict(attrs).get("data-src") or ""
        prefix = "detail.php?detailSearch="
        if src.startswith(prefix):
            self.ids.setdefault(src[len(prefix) :], None)


def parse_card_list(html: str) -> tuple[PrintingId, ...]:
    """Printing ids on one package's list page, in page order, deduplicated."""
    parser = _CardListParser()
    parser.feed(html)
    return tuple(PrintingId(i) for i in parser.ids)


@dataclass(frozen=True)
class SyncReport:
    packages: int
    listed: int  # distinct printing ids across all packages
    already_cached: int
    fetched: int
    failures: tuple[tuple[PrintingId, str], ...]


def read_package_lists(raw_dir: Path, packages: Sequence[PackageEntry]) -> dict[PackageId, tuple[PrintingId, ...]]:
    """Printing ids per package from the cached list pages (no network); packages without a cached page are omitted."""
    result: dict[PackageId, tuple[PrintingId, ...]] = {}
    for package in packages:
        path = raw_dir / list_page_key(package.id)
        if path.is_file():
            result[package.id] = parse_card_list(path.read_text(encoding="utf-8"))
    return result


def read_packages(raw_dir: Path) -> tuple[PackageEntry, ...]:
    """The package filter from the cached card page; () if it hasn't been fetched yet."""
    landing = raw_dir / LANDING_KEY
    return parse_package_filter(landing.read_text(encoding="utf-8")) if landing.is_file() else ()


def sync_printings(
    fetcher: TextFetcher,
    raw_dir: Path,
    packages: Sequence[PackageEntry],
    progress: Callable[[str], None] = lambda _: None,
) -> SyncReport:
    """Refetch every package list page, then fetch each listed printing page that isn't cached yet."""
    listed: dict[PrintingId, None] = {}
    for package in packages:
        response = fetcher.get_text(LIST_URL.format(package.id), cache_key=list_page_key(package.id), force=True)
        for printing_id in parse_card_list(response.text):
            listed.setdefault(printing_id, None)
    progress(f"{len(listed)} printings listed across {len(packages)} packages")

    missing = [i for i in listed if not (raw_dir / detail_page_key(i)).is_file()]
    failures: list[tuple[PrintingId, str]] = []
    fetched = 0
    for n, printing_id in enumerate(missing, start=1):
        try:
            fetcher.get_text(DETAIL_URL.format(printing_id), cache_key=detail_page_key(printing_id))
            fetched += 1
        except FetchError as e:
            failures.append((printing_id, str(e)))
        if n % 25 == 0 or n == len(missing):
            progress(f"fetched {n}/{len(missing)} missing printing pages ({len(failures)} failed)")
    return SyncReport(len(packages), len(listed), len(listed) - len(missing), fetched, tuple(failures))


# ---- refetch (the "redo" path: re-pull pages we already have) --------------------------------------------
@dataclass(frozen=True)
class RefetchReport:
    changed: tuple[PrintingId, ...]  # content differs from the cached copy (or there was no copy)
    unchanged: tuple[PrintingId, ...]
    failures: tuple[tuple[PrintingId, str], ...]


def select_printings(
    raw_dir: Path,
    packages: Sequence[PackageEntry],
    *,
    card: CardNumber | None = None,
    package: str | None = None,
) -> tuple[PrintingId, ...]:
    """Printing ids for a refetch from the cached list pages: one card's printings, or one package's.

    `package` is a Bandai package id (`616105`) or a set code (`GD05`). With neither, every listed printing.
    """
    lists = read_package_lists(raw_dir, packages)
    chosen = list(packages)
    if package is not None:
        chosen = [p for p in packages if p.id == package or split_title(p.label)[1] == package]
        if not chosen:
            raise ValueError(f"no such package: {package!r}")
    ids: dict[PrintingId, None] = {}
    for entry in chosen:
        for printing_id in lists.get(entry.id, ()):
            if card is None or printing_id.card_number == card:
                ids.setdefault(printing_id, None)
    return tuple(ids)


def refetch_printings(
    fetcher: TextFetcher,
    raw_dir: Path,
    ids: Sequence[PrintingId],
    progress: Callable[[str], None] = lambda _: None,
) -> RefetchReport:
    """Re-pull each page from Bandai, replacing the cached copy, and report which ones really changed."""
    changed: list[PrintingId] = []
    unchanged: list[PrintingId] = []
    failures: list[tuple[PrintingId, str]] = []
    for n, printing_id in enumerate(ids, start=1):
        path = raw_dir / detail_page_key(printing_id)
        before = path.read_text(encoding="utf-8") if path.is_file() else None
        try:
            after = fetcher.get_text(DETAIL_URL.format(printing_id), cache_key=detail_page_key(printing_id), force=True).text
        except FetchError as e:
            failures.append((printing_id, str(e)))
            continue
        (unchanged if before == after else changed).append(printing_id)
        if n % 25 == 0 or n == len(ids):
            progress(f"refetched {n}/{len(ids)} ({len(changed)} changed, {len(failures)} failed)")
    return RefetchReport(tuple(changed), tuple(unchanged), tuple(failures))
