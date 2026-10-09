"""Gundam meta CLI: what's being played online (MobileSuitArena ranking) and at tournaments (DuelFrontier, EGM).

    .venv/bin/python -m tools.gundam_meta.cli sync                      # fetch new data from all sources, rebuild popularity.json
    .venv/bin/python -m tools.gundam_meta.cli sync --only egm           # or duelfrontier
    .venv/bin/python -m tools.gundam_meta.cli top-cards --meta major    # most played at major events, current era, all sources combined
    .venv/bin/python -m tools.gundam_meta.cli top-cards --meta major --source egm   # or duelfrontier, or one source's own view
    .venv/bin/python -m tools.gundam_meta.cli duplicates                # events both sources report (counted once), with the evidence
    .venv/bin/python -m tools.gundam_meta.cli top-cards --meta local --era gd05
    .venv/bin/python -m tools.gundam_meta.cli top-cards --meta msa --bucket core_meta
    .venv/bin/python -m tools.gundam_meta.cli eras                      # eras with start dates and how much data each has
    .venv/bin/python -m tools.gundam_meta.cli popularity                # rebuild popularity.json from stored data (no network)
    .venv/bin/python -m tools.gundam_meta.cli reparse                   # rebuild stored events/snapshots from saved raw responses (no network)
    .venv/bin/python -m tools.gundam_meta.cli refetch --source duelfrontier --event regional-milwaukee-2026   # re-pull; or --all
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from collections.abc import Sequence
from datetime import UTC, date, datetime

from shared.basetypes import CardNumber
from shared.fetch import Fetcher
from tools.gundam_cards.models import CardKind, CardsFile
from tools.gundam_cards.store import OUT_DIR as CARDS_DIR
from tools.gundam_cards.store import load_sets, release_dates
from tools.gundam_meta import duelfrontier, egm
from tools.gundam_meta.common import is_complete
from tools.gundam_meta.dedupe import combined_events, find_duplicate_groups
from tools.gundam_meta.egm import egm_raw_path
from tools.gundam_meta.eras import EraError, current_era, find_era, load_era_defs, resolve_eras
from tools.gundam_meta.models import Era, EraId, EventId, MsaBucket, Source, Tier, TournamentStats
from tools.gundam_meta.redo import RedoReport, refetch_duelfrontier, refetch_egm, reparse_all
from tools.gundam_meta.stats import build_popularity, compute_stats, events_in_window, msa_stats
from tools.gundam_meta.store import (
    OUT_DIR,
    RAW_DIR,
    known_snapshot_times,
    load_events,
    load_snapshots,
    snapshot_key,
    stored_event_ids,
    write_atomic,
    write_decks_snapshot,
    write_event,
    write_popularity,
    write_snapshot,
)

USER_AGENT = "gcg-toolkit-meta/0.1 (personal hobby tooling; polite rate-limited fetcher)"


def _today() -> date:
    return datetime.now(tz=UTC).date()


class Catalog:
    """Card names and kinds from the card catalog, which must have been synced."""

    def __init__(self) -> None:
        path = CARDS_DIR / "cards.json"
        if not path.is_file():
            raise SystemExit(f"{path} not found; run `python -m tools.gundam_cards.cli sync` first")
        cards = CardsFile.model_validate_json(path.read_text(encoding="utf-8")).data
        self.kinds: dict[CardNumber, CardKind] = {c.number: c.kind for c in cards}
        self.names: dict[CardNumber, str] = {c.number: c.name for c in cards}

    def name(self, number: CardNumber) -> str:
        return self.names.get(number, "(not in catalog)")


def _eras() -> tuple[Era, ...]:
    sets = load_sets()
    if not sets:
        raise SystemExit("no sets.json; run `python -m tools.gundam_cards.cli sync --only sets` first")
    return resolve_eras(load_era_defs(), release_dates(sets))


# ---- sync -----------------------------------------------------------------------------------------------------
def _sync_duelfrontier() -> bool:
    fetcher = Fetcher(RAW_DIR, user_agent=USER_AGENT)
    listed = duelfrontier.list_events(fetcher)
    result = duelfrontier.sync_events(
        fetcher, RAW_DIR, listed, stored_event_ids(Source.DUELFRONTIER), _today(), progress=lambda m: print(f"  {m}", flush=True)
    )
    stored = sum(write_event(e) for e in result.events)
    print(
        f"duelfrontier: {result.listed} events listed, {result.already_stored} already stored, {stored} stored now, "
        f"{result.not_complete_yet} not complete yet, {result.waiting_for_results} waiting for results, "
        f"{len(result.failures)} failed; {fetcher.network_requests} request(s)"
    )
    for slug, detail in result.failures:
        print(f"  FAILED {slug}: {detail}")
    return not result.failures


def _sync_egm() -> bool:
    fetcher = Fetcher(None, user_agent=USER_AGENT)
    raw, parsed = egm.fetch_tournaments(fetcher)
    write_atomic(egm_raw_path(RAW_DIR, parsed.fetched_at), raw)  # named by the same instant stamped on its events
    stored_ids = stored_event_ids(Source.EGM)
    today = _today()
    new = [e for e in parsed.events if e.id not in stored_ids and is_complete(e.start_date, today)]
    stored = sum(write_event(e) for e in new)
    held = sum(1 for e in new for d in e.decks if d.unresolved)
    print(
        f"egm: {len(parsed.events)} events listed ({len(parsed.skipped)} aggregate rows skipped), {len(stored_ids)} already stored, "
        f"{stored} stored now, {sum(1 for e in parsed.events if e.id not in stored_ids) - len(new)} not complete yet"
    )
    if held:
        print(f"  note: {held} new deck(s) have list slots we can't interpret (e.g. 'A:3|B:3'); they are stored but not counted")
    return True


def cmd_sync(args: argparse.Namespace) -> int:
    ok = True
    if args.only in (None, "egm"):
        ok &= _sync_egm()
    if args.only in (None, "duelfrontier"):
        ok &= _sync_duelfrontier()
    cmd_popularity(args)
    return 0 if ok else 1


def cmd_popularity(_: argparse.Namespace) -> int:
    catalog = Catalog()
    build = build_popularity(load_events(), load_snapshots(), catalog.kinds, _eras(), _today(), datetime.now(tz=UTC))
    path = write_popularity(build.popularity)
    print(f"popularity: {len(build.popularity.tournaments)} tournament window(s), msa={'yes' if build.popularity.msa else 'no'} -> {path}")
    if build.unknown_cards:
        print(f"  warning: {len(build.unknown_cards)} card number(s) in decks are not in the card catalog (excluded): "
              f"{', '.join(sorted(map(str, build.unknown_cards))[:12])}")
    return 0


# ---- reading ---------------------------------------------------------------------------------------------------
def _percent(x: float) -> str:
    return f"{100 * x:5.2f}%"


def _print_tournament_stats(stats: TournamentStats, catalog: Catalog, limit: int, label: str) -> None:
    span = f"{stats.start} to {stats.end or 'today'}"
    who = "all sources combined, de-duplicated" if stats.source is None else stats.source.value
    print(f"\n== {who}, {stats.tier.value} events, {label} ({span}) ==")
    print(f"   {stats.events} events, {stats.decks} decks counted ({stats.decks_not_counted} private/unreadable), {stats.total_copies} card copies")
    print(f"   {'#':>3} {'share':>7} {'copies':>6} {'decks':>5}  {'card':9} name")
    for rank, card in enumerate(stats.cards[:limit], start=1):
        print(f"   {rank:>3} {_percent(card.share)} {card.copies:>6} {card.decks:>5}  {card.card_number:9} {catalog.name(card.card_number)}")


def cmd_top_cards(args: argparse.Namespace) -> int:
    catalog = Catalog()
    if args.meta == "msa":
        snapshots = load_snapshots()
        if not snapshots:
            print("no online ranking snapshots stored", file=sys.stderr)
            return 2
        msa = msa_stats(max(snapshots, key=lambda s: s.generated_at))
        cards = [c for c in msa.cards if args.bucket is None or c.bucket.value == args.bucket]
        print(f"== MobileSuitArena online ranking, {msa.window_start:%Y-%m-%d} to {msa.window_end:%Y-%m-%d}, {msa.games} games ==")
        print(f"   {'#':>3} {'in games':>9}  {'bucket':17} {'card':9} name")
        for card in cards[: args.limit]:
            print(f"   {card.rank:>3} {card.appearance_rate_pct:>8.1f}%  {card.bucket.value:17} {card.card_number:9} {catalog.name(card.card_number)}")
        print(f"   ({len(cards)} cards in this selection)", file=sys.stderr)
        return 0

    tier = Tier(args.meta)
    events = load_events()
    if args.since:
        era_id: EraId | None = None
        start, end, label = date.fromisoformat(args.since), (date.fromisoformat(args.until) if args.until else None), "date range"
    else:
        eras = _eras()
        try:
            era = current_era(eras, _today()) if args.era == "current" else find_era(eras, EraId(args.era))
        except EraError as e:
            print(e, file=sys.stderr)
            return 2
        if era is None:
            print("no era has started yet", file=sys.stderr)
            return 2
        era_id, start, end, label = era.id, era.start, era.end, f"era {era.definition.label}"
    sources: list[Source | None] = [None] if args.source in (None, "combined") else [Source(args.source)]
    for source in sources:
        pool = combined_events(events) if source is None else events
        result = compute_stats(pool, catalog.kinds, source=source, tier=tier, era=era_id, start=start, end=end)
        if args.json:
            print(result.stats.model_dump_json())
        else:
            _print_tournament_stats(result.stats, catalog, args.limit, label)
        if result.unknown_cards:
            print(f"   warning: {len(result.unknown_cards)} card(s) not in the catalog were excluded", file=sys.stderr)
    return 0


def _print_redo(report: RedoReport) -> int:
    print(f"{len(report.changed)} changed, {len(report.unchanged)} unchanged, {len(report.failures)} failed")
    for label in report.changed[:40]:
        print(f"  changed: {label}")
    for label, detail in report.failures:
        print(f"  FAILED {label}: {detail}")
    return 1 if report.failures else 0


def cmd_reparse(args: argparse.Namespace) -> int:
    code = _print_redo(reparse_all(RAW_DIR, OUT_DIR))
    cmd_popularity(args)
    return code


def cmd_refetch(args: argparse.Namespace) -> int:
    source = Source(args.source)
    if not args.event and not args.all:
        print("give --event ID (repeatable) or --all", file=sys.stderr)
        return 2
    stored = [e.id for e in load_events(OUT_DIR, source)]
    ids = stored if args.all else [EventId(e) for e in args.event]
    if source is Source.DUELFRONTIER:
        report = refetch_duelfrontier(Fetcher(RAW_DIR, user_agent=USER_AGENT), RAW_DIR, OUT_DIR, ids, progress=print)
    else:
        report = refetch_egm(Fetcher(None, user_agent=USER_AGENT), RAW_DIR, OUT_DIR, None if args.all else frozenset(ids))
    code = _print_redo(report)
    if report.changed:
        cmd_popularity(args)
    return code


def cmd_duplicates(_: argparse.Namespace) -> int:
    groups = find_duplicate_groups(load_events())
    for g in groups:
        other = g.others[0]
        print(f"{g.canonical.start_date}  kept {g.canonical.source.value}: {g.canonical.name}\n"
              f"            also {other.source.value} ({other.start_date}): {other.name}\n"
              f"            {g.evidence}" + (f"; filled in {len(g.borrowed)} deck(s)" if g.borrowed else ""))
    print(f"{len(groups)} event(s) reported by both sources", file=sys.stderr)
    return 0


def cmd_eras(_: argparse.Namespace) -> int:
    eras = _eras()
    events = load_events()
    today = _today()
    current = current_era(eras, today)
    print(f"{'era':8} {'label':8} {'start':11} {'end':11} {'status':9} {'events (df / egm)':20}")
    for era in eras:
        status = "current" if current == era else ("upcoming" if era.start > today else "past")
        counts = {s: sum(1 for e in events if e.source is s and era.contains(e.start_date) and e.tier is not Tier.OTHER) for s in Source}
        print(f"{era.id:8} {era.definition.label:8} {era.start!s:11} {str(era.end or '-'):11} {status:9} "
              f"{counts[Source.DUELFRONTIER]} / {counts[Source.EGM]}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="fetch new data (network), then rebuild popularity.json")
    sync.add_argument("--only", choices=["duelfrontier", "egm"], help="one source (default: all)")
    sync.set_defaults(func=cmd_sync)
    sub.add_parser("popularity", help="rebuild popularity.json from stored data (no network)").set_defaults(func=cmd_popularity)
    sub.add_parser("eras", help="list eras and how many events each has").set_defaults(func=cmd_eras)
    sub.add_parser("reparse", help="rebuild stored events/snapshots from the saved raw responses (no network)").set_defaults(func=cmd_reparse)
    refetch = sub.add_parser("refetch", help="re-pull stored events from a source and replace them if they changed (network)")
    refetch.add_argument("--source", required=True, choices=[s.value for s in Source])
    refetch.add_argument("--event", action="append", default=[], help="event id (repeatable)")
    refetch.add_argument("--all", action="store_true", help="every stored event of that source")
    refetch.set_defaults(func=cmd_refetch)
    sub.add_parser("duplicates", help="events both sources report, with the matching evidence (no network)").set_defaults(func=cmd_duplicates)
    top = sub.add_parser("top-cards", help="most played cards (no network)")
    top.add_argument("--meta", required=True, choices=["msa", "major", "local"], help="msa = MobileSuitArena online; major/local = tournaments")
    top.add_argument("--source", choices=["combined", *[s.value for s in Source]], help="default: combined (events both sources report counted once)")
    top.add_argument("--era", default="current", help="era id (e.g. gd05_5) or 'current' (default)")
    top.add_argument("--since", help="YYYY-MM-DD: use a date range instead of an era")
    top.add_argument("--until", help="YYYY-MM-DD (exclusive); with --since")
    top.add_argument("--bucket", choices=[b.value for b in MsaBucket], help="msa only: just this bucket")
    top.add_argument("--limit", type=int, default=25)
    top.add_argument("--json", action="store_true", help="tournament stats as JSON")
    top.set_defaults(func=cmd_top_cards)
    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
