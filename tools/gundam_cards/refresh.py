"""Refresh the card catalog from Bandai's official English card site: fetch and check everything, then write.

    .venv/bin/python -m tools.gundam_cards.cli refresh             # fetch, check, then write the dataset (network)
    .venv/bin/python -m tools.gundam_cards.cli refresh --dry-run   # what a real run would add; fetches no detail pages, writes nothing

Three phases. Fetch: Bandai's package list, every package's listing (always fresh) and the detail pages not cached yet (a cached
page is never requested again), stopping at the first failure. Plan: the shape check, provisional packages, the rebuild from the
cached pages (a printing keeps its stored packages and gains this run's), misses, and the anomaly guard. Write: only after a
complete, accepted, non-dry run, so a refused run, or one that fails or is interrupted before writing, leaves the dataset as it
was. Each file is written atomically, cards.json first; an interruption among the writes may leave the derived files behind
until the next run.
The tracked sets.json is only read.
See .claude/feature-design/refresh-cards.md.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from shared.basetypes import CardNumber, PackageId, PrintingId
from shared.fetch import FetchError, TextFetcher
from tools.gundam_cards.build import Issue, ParseError, SourcePage, build_catalog, parse_color, parse_kind, parse_rarity
from tools.gundam_cards.models import CardModel, CardSet
from tools.gundam_cards.parse_detail import DetailPageError, parse_detail_html
from tools.gundam_cards.printings import DETAIL_URL, LIST_URL, detail_page_key, list_page_key, parse_card_list_raw
from tools.gundam_cards.sets import build_sets, fetch_package_list
from tools.gundam_cards.store import (
    OUT_DIR,
    load_catalog,
    load_provisional_sets,
    load_source_pages,
    load_tracked_sets,
    merge_catalog,
    release_dates,
    save_catalog,
    write_provisional_sets,
)

ANOMALY_SHARE = 0.02  # refuse a run that would drop or change more than this share of existing cards (docs/tuning.md)


@dataclass(frozen=True)
class Rejected:
    subject: str
    reason: str


@dataclass(frozen=True)
class RefreshReport:
    dry_run: bool
    complete: bool  # every listing (and, in a real run, every new detail page) was fetched and readable
    failure: str | None = None  # why the run is incomplete
    provisional: tuple[CardSet, ...] = ()  # packages this run records as provisional
    packages_with_new: tuple[tuple[str, bool], ...] = ()  # (package label, provisional?) for packages listing new printings
    new_cards: tuple[CardNumber, ...] = ()
    new_printings: tuple[PrintingId, ...] = ()
    missed: tuple[CardNumber, ...] = ()  # existing cards absent from this run's listings (a first or a second miss)
    marked: tuple[CardNumber, ...] = ()  # of those, the ones on their second miss: marked no longer listed
    changed: tuple[CardNumber, ...] = ()  # existing cards whose data (beyond printings) differs
    existing: int = 0  # stored cards not marked no longer listed
    guard_trips: bool = False  # the anomaly guard would refuse this run
    refused: bool = False  # ... and no override was given
    rejected: tuple[Rejected, ...] = ()
    issues: tuple[Issue, ...] = ()
    written: bool = False


def shape_problems(page: SourcePage) -> list[str]:
    """Why a detail page fails the shape check: card number shape, and TYPE, COLOR and rarity in the known vocabularies."""
    raw, subject, problems = page.raw, str(page.printing_id), []
    try:
        if CardNumber(raw.card_no) != page.printing_id.card_number:
            problems.append(f"page shows card number {raw.card_no!r}, not {page.printing_id.card_number}")
    except ValueError:
        problems.append(f"card number {raw.card_no!r} is not a valid card number")
    checks: list[tuple[str, Callable[[str, str], object]]] = [("TYPE", parse_kind), ("rarity", parse_rarity)]
    if "COLOR" in raw.fields:
        checks.append(("COLOR", parse_color))
    for label, check in checks:
        try:
            check(raw.rarity if label == "rarity" else raw.fields.get(label, ""), subject)
        except ParseError as e:
            problems.append(e.detail)
    return problems


def _shape_checked(pages: Sequence[SourcePage]) -> tuple[list[SourcePage], list[Rejected]]:
    """Pages that pass the shape check. A rejected base printing leaves its whole card out (a stored card keeps its data)."""
    bad = {p.printing_id: problems for p in pages if (problems := shape_problems(p))}
    base_bad = {i.card_number for i in bad if i.variant is None}
    kept = [p for p in pages if p.printing_id not in bad and p.printing_id.card_number not in base_bad]
    rejected = [
        Rejected(str(i), "; ".join(problems) + ("; the base printing: whole card left out" if i.variant is None else ""))
        for i, problems in bad.items()
    ]
    return kept, rejected


def _comparable(card: CardModel) -> object:
    """What the anomaly guard compares: everything but the printings, the text-version list and the fetch time, plus the current
    wording. Gaining a printing or a package is not a change."""
    return (card.model_dump(exclude={"printings", "text_versions", "fetched_at"}), card.text)


def refresh_catalog(
    fetcher: TextFetcher,
    raw_dir: Path,
    *,
    tracked_dir: Path = OUT_DIR,
    out_dir: Path | None = None,
    dry_run: bool = False,
    allow_anomaly: bool = False,
    now: datetime | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> RefreshReport:
    """Run one refresh (see the module docstring). `raw_dir` is the page cache the fetcher writes; `tracked_dir` holds sets.json
    (read only); `out_dir` is the catalog's dataset folder (default `data_out_dir()`)."""
    now = now or datetime.now(tz=UTC)
    rejected: list[Rejected] = []

    def incomplete(failure: str) -> RefreshReport:
        return RefreshReport(dry_run=dry_run, complete=False, failure=failure, rejected=tuple(rejected))

    # ---- fetch: the package list and every listing
    try:
        packages, products = fetch_package_list(fetcher)
    except FetchError as e:
        return incomplete(f"package list: {e}")
    if not packages:
        return incomplete("package list: Bandai's card page shows no packages (unreadable)")
    listings: dict[PackageId, tuple[PrintingId, ...]] = {}
    for package in packages:
        where = f"listing of {package.label} ({package.id})"
        try:
            html = fetcher.get_text(LIST_URL.format(package.id), cache_key=list_page_key(package.id), force=True).text
        except FetchError as e:
            return incomplete(f"{where}: {e}")
        raw_ids = parse_card_list_raw(html)
        if not raw_ids:
            return incomplete(f"{where}: lists no printings (unreadable)")
        ids: list[PrintingId] = []
        for raw_id in raw_ids:
            try:
                ids.append(PrintingId(raw_id))
            except ValueError:
                rejected.append(Rejected(where, f"{raw_id!r} is not a valid printing id"))
        listings[package.id] = tuple(ids)
    listed = tuple(dict.fromkeys(i for ids in listings.values() for i in ids))
    progress(f"{len(listed)} printings listed across {len(packages)} packages")

    stored = load_catalog(out_dir)
    stored_cards = {c.number: c for c in stored.data} if stored else {}
    stored_printings = {p.id for c in stored_cards.values() for p in c.printings}
    new_printings = tuple(i for i in listed if i not in stored_printings)
    new_cards = tuple(dict.fromkeys(i.card_number for i in new_printings if i.card_number not in stored_cards))

    # ---- fetch: detail pages not cached yet (real run only)
    if not dry_run:
        missing = [i for i in listed if not (raw_dir / detail_page_key(i)).is_file()]
        for n, printing_id in enumerate(missing, start=1):
            try:
                text = fetcher.get_text(DETAIL_URL.format(printing_id), cache_key=detail_page_key(printing_id)).text
            except FetchError as e:
                return incomplete(f"detail page {printing_id}: {e}")
            try:
                parse_detail_html(text)
            except DetailPageError as e:
                (raw_dir / detail_page_key(printing_id)).unlink(missing_ok=True)  # not a card page: ask again next run
                return incomplete(f"detail page {printing_id}: unreadable ({e})")
            if n % 25 == 0 or n == len(missing):
                progress(f"fetched {n}/{len(missing)} new detail pages")

    # ---- plan: packages
    tracked = load_tracked_sets(tracked_dir)
    tracked_codes = {s.code for s in tracked}
    tracked_ids = {s.bandai_package_id for s in tracked}
    sets_build = build_sets(packages, products)
    stored_provisional = {s.code: s for s in load_provisional_sets(out_dir)}
    from_bandai = {s.code: s for s in sets_build.sets if s.bandai_package_id is not None and s.code not in tracked_codes}
    provisional = tuple({**stored_provisional, **from_bandai}.values())
    recorded = tuple(s for code, s in sorted(from_bandai.items()) if code not in stored_provisional)
    new_set = set(new_printings)
    packages_with_new = tuple(
        (p.label, p.id not in tracked_ids) for p in packages if any(i in new_set for i in listings[p.id])
    )

    # ---- plan: cards (rebuilt from the cached pages). A printing's packages are its stored ones plus those listing it in this run:
    # a refresh never takes a package away from a printing, even one that no listing names any more (owner decision 2026-11-20).
    packages_of: dict[PrintingId, list[PackageId]] = defaultdict(list)
    for stored_card in stored_cards.values():
        for printing in stored_card.printings:
            packages_of[printing.id].extend(printing.package_ids)
    for package_id, package_ids in listings.items():
        for printing_id in package_ids:
            if package_id not in packages_of[printing_id]:
                packages_of[printing_id].append(package_id)
    loaded = load_source_pages(raw_dir, {k: tuple(v) for k, v in packages_of.items()})
    pages, page_rejects = _shape_checked(loaded.pages)
    rejected += page_rejects
    dates = release_dates(tracked + tuple(s for s in provisional if s.code not in tracked_codes))
    result = build_catalog(pages, dates)
    listed_numbers = frozenset(i.card_number for i in listed)
    merged = merge_catalog(stored, result.cards, now, listed_numbers)

    # ---- plan: misses (read from the merged records, so the report says what is written) and the anomaly guard
    active = [r for r in (stored.records if stored else ()) if not r.no_longer_listed]
    merged_records = {r.number: r for r in merged.records}
    missed = tuple(r.number for r in active if merged_records[r.number].missed_once)
    marked = tuple(r.number for r in active if merged_records[r.number].no_longer_listed)
    rebuilt = {c.number: c for c in merged.data}
    changed = tuple(r.number for r in active if _comparable(rebuilt[r.number]) != _comparable(stored_cards[r.number]))
    affected = len(set(missed) | set(changed))
    guard_trips = bool(active) and affected / len(active) > ANOMALY_SHARE
    report = RefreshReport(
        dry_run=dry_run,
        complete=True,
        provisional=recorded,
        packages_with_new=packages_with_new,
        new_cards=new_cards,
        new_printings=new_printings,
        missed=missed,
        marked=marked,
        changed=changed,
        existing=len(active),
        guard_trips=guard_trips,
        refused=guard_trips and not allow_anomaly,
        rejected=tuple(rejected),
        issues=(*sets_build.issues, *loaded.issues, *result.issues),
    )
    if dry_run or report.refused:
        return report

    # ---- write
    save_catalog(merged, out_dir)
    write_provisional_sets(provisional, now, out_dir)
    return replace(report, written=True)


def format_report(report: RefreshReport) -> list[str]:
    """The run's summary, one line per fact, for the CLI."""
    mode = "dry run" if report.dry_run else "refresh"
    if not report.complete:
        lines = [f"{mode} incomplete, nothing written: {report.failure}"]
    else:
        lines = [
            f"{mode}: {len(report.provisional)} provisional package(s) recorded"
            + "".join(f"\n  provisional {s.code} {s.name} (released {s.release_date or 'unknown'})" for s in report.provisional),
            f"{len(report.packages_with_new)} package(s) with new printings"
            + "".join(f"\n  {label} ({'provisional' if prov else 'known'})" for label, prov in report.packages_with_new),
            f"{len(report.new_cards)} new card number(s): {' '.join(map(str, report.new_cards)) or '-'}",
            f"{len(report.new_printings)} new printing(s): {' '.join(map(str, report.new_printings)) or '-'}",
            f"{len(report.missed)} card(s) missed: {' '.join(map(str, report.missed)) or '-'}"
            + (f" (no longer listed after this run: {' '.join(map(str, report.marked))})" if report.marked else ""),
            f"anomaly guard: {len(report.missed)} dropped, {len(report.changed)} changed of {report.existing} existing cards "
            f"(limit {ANOMALY_SHARE:.0%}): "
            + ("would refuse" if report.guard_trips else "ok")
            + (" (overridden)" if report.guard_trips and not report.refused else ""),
        ]
        if report.refused:
            lines.append("refused by the anomaly guard, nothing written (rerun with --allow-anomaly to proceed)")
        elif report.dry_run:
            lines.append("dry run: nothing written")
        else:
            lines.append("written")
    lines += [f"rejected {r.subject}: {r.reason}" for r in report.rejected]
    lines += [f"  [{i.kind.value}] {i.subject}: {i.detail}" for i in report.issues]
    return lines
