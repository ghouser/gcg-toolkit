"""Where meta data lives, and reading/writing it.

- Events are immutable once written: `write_event` refuses to overwrite unless told this is a deliberate redo.
- Online ranking snapshots are named by their `generated_at`; example-deck snapshots by their `fetched_at`. A snapshot is added once and
  never rewritten; storing the same data again adds nothing.
- Events, online ranking and example-deck snapshots live in the local dataset (`data_out_dir()`, see `shared/dataset.py`).
- Raw responses are cached under the tool's own `data/raw/`; the derived `popularity.json` is tracked in `shared/data/gundam_meta/`.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from shared.dataset import add_snapshot, data_dir, entry_on_day, newest_snapshot, snapshot_paths
from shared.dataset import snapshot_key as snapshot_key
from tools.gundam_meta.models import (
    DecksSnapshotFile,
    Event,
    EventFile,
    EventId,
    ExampleDecksSnapshot,
    OnlineRankingSnapshot,
    PopularityFile,
    SnapshotFile,
    Source,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "tools" / "gundam_meta" / "data" / "raw"
OUT_DIR = REPO_ROOT / "shared" / "data" / "gundam_meta"  # tracked: popularity.json


def data_out_dir() -> Path:
    """This tool's folder in the local dataset: events/, online_rankings/, example_decks/."""
    return data_dir() / "gundam_meta"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def pretty(compact_json: str) -> str:
    return json.dumps(json.loads(compact_json), ensure_ascii=False, indent=1) + "\n"


def _safe_name(name: str) -> str:
    if "/" in name or "\\" in name or name in ("", ".", "..") or name.startswith("."):
        raise ValueError(f"not usable as a file name: {name!r}")
    return name


# ---- events ----------------------------------------------------------------------------------------------
def event_path(source: Source, event_id: EventId, out_dir: Path | None = None) -> Path:
    return (out_dir or data_out_dir()) / "events" / source.value / f"{_safe_name(str(event_id))}.json"


def write_event(event: Event, out_dir: Path | None = None, *, replace: bool = False) -> bool:
    """Store an event. Returns False (writing nothing) if it is already stored and `replace` is not set."""
    path = event_path(event.source, event.id, out_dir)
    if path.exists() and not replace:
        return False
    write_atomic(path, pretty(EventFile(data=event).model_dump_json()))
    return True


def load_events(out_dir: Path | None = None, source: Source | None = None) -> tuple[Event, ...]:
    """Every stored event (optionally of one source), ordered by start date then source then id."""
    out_dir = out_dir or data_out_dir()
    events: list[Event] = []
    for src in [source] if source else list(Source):
        for path in sorted((out_dir / "events" / src.value).glob("*.json")):
            events.append(EventFile.model_validate_json(path.read_text(encoding="utf-8")).data)
    return tuple(sorted(events, key=lambda e: (e.start_date, e.source.value, str(e.id))))


def stored_event_ids(source: Source, out_dir: Path | None = None) -> frozenset[EventId]:
    return frozenset(EventId(p.stem) for p in ((out_dir or data_out_dir()) / "events" / source.value).glob("*.json"))


def events_as_of(out_dir: Path | None = None) -> date | None:
    """The newest collection date (`fetched_at`) of any stored event, or None (no data)."""
    events = load_events(out_dir)
    return max(e.fetched_at for e in events).date() if events else None


# ---- Online ranking snapshots -------------------------------------------------------------------------------------
def snapshot_path(generated_at: datetime, out_dir: Path | None = None) -> Path:
    return (out_dir or data_out_dir()) / "online_rankings" / f"{snapshot_key(generated_at)}.json"


def write_snapshot(snapshot: OnlineRankingSnapshot, out_dir: Path | None = None, *, replace: bool = False) -> bool:
    """Add a dated ranking snapshot. False (writing nothing) when that UTC day is stored already or the newest snapshot holds the same
    ranking. `replace` is the deliberate redo of one stored snapshot from its raw response."""
    path = snapshot_path(snapshot.generated_at, out_dir)
    text = pretty(SnapshotFile(data=snapshot).model_dump_json())
    if replace:
        write_atomic(path, text)
        return True
    same = snapshot.model_copy(update={"fetched_at": None})
    return add_snapshot(path.parent, path.stem, text,
                        lambda old: SnapshotFile.model_validate_json(old).data.model_copy(update={"fetched_at": None}) == same) is not None


def load_snapshots(out_dir: Path | None = None) -> tuple[OnlineRankingSnapshot, ...]:
    """All stored snapshots, oldest first."""
    paths = snapshot_paths((out_dir or data_out_dir()) / "online_rankings")
    return tuple(SnapshotFile.model_validate_json(p.read_text(encoding="utf-8")).data for p in paths)


def known_snapshot_times(out_dir: Path | None = None) -> frozenset[datetime]:
    return frozenset(s.generated_at for s in load_snapshots(out_dir))


def rankings_as_of(out_dir: Path | None = None) -> date | None:
    """The date of the newest online ranking snapshot, or None (no data)."""
    path = newest_snapshot((out_dir or data_out_dir()) / "online_rankings")
    return SnapshotFile.model_validate_json(path.read_text(encoding="utf-8")).data.generated_at.date() if path else None


# ---- Example decks (weighted lists) -----------------------------------------------------------------------
def decks_snapshot_path(fetched_at: datetime, out_dir: Path | None = None) -> Path:
    return (out_dir or data_out_dir()) / "example_decks" / f"{snapshot_key(fetched_at)}.json"


def write_decks_snapshot(snapshot: ExampleDecksSnapshot, out_dir: Path | None = None) -> Path:
    """Add a dated example-deck snapshot, unless that UTC day is stored already or the newest snapshot holds the same lists (an existing
    entry is never rewritten). Returns the entry that holds it: the new one, the one of that day, or the identical newest one."""
    path = decks_snapshot_path(snapshot.fetched_at, out_dir)
    same = snapshot.model_copy(update={"fetched_at": None})
    added = add_snapshot(path.parent, path.stem, pretty(DecksSnapshotFile(data=snapshot).model_dump_json()),
                         lambda old: DecksSnapshotFile.model_validate_json(old).data.model_copy(update={"fetched_at": None}) == same)
    newest = newest_snapshot(path.parent)
    return added or entry_on_day(path.parent, path.stem) or (path if newest is None else newest)


def load_decks_snapshot(out_dir: Path | None = None) -> ExampleDecksSnapshot | None:
    """The newest stored snapshot of the weighted example deck lists, or None."""
    path = newest_snapshot((out_dir or data_out_dir()) / "example_decks")
    return DecksSnapshotFile.model_validate_json(path.read_text(encoding="utf-8")).data if path else None


def decks_as_of(out_dir: Path | None = None) -> date | None:
    """The date of the newest example-deck snapshot, or None (no data)."""
    snapshot = load_decks_snapshot(out_dir)
    return snapshot.fetched_at.date() if snapshot else None


# ---- derived ---------------------------------------------------------------------------------------------------
def write_popularity(popularity: PopularityFile, out_dir: Path = OUT_DIR) -> Path:
    path = out_dir / "popularity.json"
    write_atomic(path, pretty(popularity.model_dump_json()))
    return path
