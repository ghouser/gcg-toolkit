"""The "redo" paths for when stored data might be wrong.

- `reparse_all`: rebuild every stored event/snapshot from the saved raw responses. No network. Use after a parser fix.
- `refetch_duelfrontier` / `refetch_egm`: pull from the source again and replace what is stored. Use when the stored data
  is suspect (the source corrected something). Both report what actually changed.
Events are otherwise immutable: a normal sync never touches one already stored.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.fetch import FetchError, TextFetcher
from tools.gundam_meta import duelfrontier, egm
from tools.gundam_meta.models import Event, EventId, OnlineRankingSnapshot, Source
from tools.gundam_meta.store import (
    OUT_DIR,
    load_events,
    load_snapshots,
    write_atomic,
    write_event,
    write_snapshot,
)


@dataclass(frozen=True)
class RedoReport:
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    failures: tuple[tuple[str, str], ...]

    def __add__(self, other: RedoReport) -> RedoReport:
        return RedoReport(self.changed + other.changed, self.unchanged + other.unchanged, self.failures + other.failures)


EMPTY = RedoReport((), (), ())


def same_content(a: Event, b: Event) -> bool:
    """Equal apart from when it was fetched."""
    return a.model_copy(update={"fetched_at": b.fetched_at}) == b


def _store(new: Event, old: Event | None, out_dir: Path) -> bool:
    """Replace the stored event if its content differs. Returns True if it changed (or is new)."""
    if old is not None and same_content(old, new):
        return False
    write_event(new, out_dir, replace=True)
    return True


def _label(event: Event) -> str:
    return f"{event.source.value}:{event.id}"


# ---- reparse: no network ---------------------------------------------------------------------------------------
def reparse_duelfrontier(raw_dir: Path, out_dir: Path = OUT_DIR) -> RedoReport:
    stored = {e.id: e for e in load_events(out_dir, Source.DUELFRONTIER)}
    report = EMPTY
    for path in sorted((raw_dir / "duelfrontier" / "events").glob("*.json")):
        slug = EventId(path.stem)
        try:
            event_text = path.read_text(encoding="utf-8")
            decks: dict[str, str | None] = {}
            for deck_slug in duelfrontier.player_deck_slugs(event_text):
                deck_path = raw_dir / duelfrontier.deck_key(deck_slug)
                if not deck_path.is_file():
                    raise FileNotFoundError(f"raw deck page missing: {deck_path.name}")
                decks[deck_slug] = deck_path.read_text(encoding="utf-8")
            old = stored.get(slug)
            fetched_at = old.fetched_at if old else datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            event = duelfrontier.parse_event(event_text, decks, fetched_at)
        except (ValueError, FileNotFoundError) as e:
            report += RedoReport((), (), ((f"duelfrontier:{slug}", str(e)[:300]),))
            continue
        label = f"duelfrontier:{slug}"
        report += RedoReport((label,), (), ()) if _store(event, stored.get(slug), out_dir) else RedoReport((), (label,), ())
    return report


def reparse_egm(raw_dir: Path, out_dir: Path = OUT_DIR) -> RedoReport:
    """Re-parse each stored EGM event from the raw response it was originally stored from (named by its fetched_at)."""
    report = EMPTY
    parsed_by_time: dict[datetime, dict[EventId, Event]] = {}
    for old in load_events(out_dir, Source.EGM):
        label = _label(old)
        if old.fetched_at not in parsed_by_time:
            path = egm.egm_raw_path(raw_dir, old.fetched_at)
            if not path.is_file():
                report += RedoReport((), (), ((label, f"raw response missing: {path.name}"),))
                continue
            parsed = egm.parse_tournaments(path.read_text(encoding="utf-8"), old.fetched_at)
            parsed_by_time[old.fetched_at] = {e.id: e for e in parsed.events}
        new = parsed_by_time[old.fetched_at].get(old.id)
        if new is None:
            report += RedoReport((), (), ((label, "event not in its raw response"),))
            continue
        report += RedoReport((label,), (), ()) if _store(new, old, out_dir) else RedoReport((), (label,), ())
    return report


def reparse_all(raw_dir: Path, out_dir: Path = OUT_DIR) -> RedoReport:
    return reparse_duelfrontier(raw_dir, out_dir) + reparse_egm(raw_dir, out_dir)


# ---- refetch: network --------------------------------------------------------------------------------------------
def refetch_duelfrontier(
    fetcher: TextFetcher,
    raw_dir: Path,
    out_dir: Path,
    slugs: Iterable[EventId],
    progress: Callable[[str], None] = lambda _: None,
) -> RedoReport:
    """Pull the event and all its decks again (bypassing the cache) and replace the stored event if anything changed."""
    stored = {e.id: e for e in load_events(out_dir, Source.DUELFRONTIER)}
    report = EMPTY
    todo = list(slugs)
    for n, slug in enumerate(todo, start=1):
        label = f"duelfrontier:{slug}"
        try:
            response = fetcher.get_text(
                f"{duelfrontier.API}/events/{slug}?Include=Players", cache_key=duelfrontier.event_key(slug), force=True
            )
            decks = {
                d: fetcher.get_text(f"{duelfrontier.API}/decks/{d}?Include=Cards", cache_key=duelfrontier.deck_key(d), force=True).text
                for d in duelfrontier.player_deck_slugs(response.text)
            }
            event = duelfrontier.parse_event(response.text, decks, response.fetched_at)
        except (FetchError, ValueError) as e:
            report += RedoReport((), (), ((label, str(e)[:300]),))
            continue
        report += RedoReport((label,), (), ()) if _store(event, stored.get(slug), out_dir) else RedoReport((), (label,), ())
        if n % 10 == 0 or n == len(todo):
            progress(f"refetched {n}/{len(todo)}")
    return report


def refetch_egm(
    fetcher: TextFetcher,
    raw_dir: Path,
    out_dir: Path,
    ids: frozenset[EventId] | None = None,
) -> RedoReport:
    """One request for everything; replace stored EGM events (all, or just `ids`) whose content changed."""
    raw, parsed = egm.fetch_tournaments(fetcher)
    write_atomic(egm.egm_raw_path(raw_dir, parsed.fetched_at), raw)
    stored = {e.id: e for e in load_events(out_dir, Source.EGM)}
    report = EMPTY
    for event in parsed.events:
        if event.id not in stored or (ids is not None and event.id not in ids):
            continue
        label = _label(event)
        report += RedoReport((label,), (), ()) if _store(event, stored[event.id], out_dir) else RedoReport((), (label,), ())
    for missing in sorted((ids or frozenset()) - {e.id for e in parsed.events}):
        report += RedoReport((), (), ((f"egm:{missing}", "not in EGM's current list"),))
    return report
