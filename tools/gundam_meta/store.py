"""Where meta data lives, and reading/writing it.

- Events are immutable once written: `write_event` refuses to overwrite unless told this is a deliberate redo.
- Online ranking snapshots are named by their `generated_at`.
- Raw responses are cached under the tool's own `data/raw/`; derived and shared files go to `shared/data/gundam_meta/`.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

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
OUT_DIR = REPO_ROOT / "shared" / "data" / "gundam_meta"


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
def event_path(source: Source, event_id: EventId, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / "events" / source.value / f"{_safe_name(str(event_id))}.json"


def write_event(event: Event, out_dir: Path = OUT_DIR, *, replace: bool = False) -> bool:
    """Store an event. Returns False (writing nothing) if it is already stored and `replace` is not set."""
    path = event_path(event.source, event.id, out_dir)
    if path.exists() and not replace:
        return False
    write_atomic(path, pretty(EventFile(data=event).model_dump_json()))
    return True


def load_events(out_dir: Path = OUT_DIR, source: Source | None = None) -> tuple[Event, ...]:
    """Every stored event (optionally of one source), ordered by start date then source then id."""
    events: list[Event] = []
    for src in [source] if source else list(Source):
        for path in sorted((out_dir / "events" / src.value).glob("*.json")):
            events.append(EventFile.model_validate_json(path.read_text(encoding="utf-8")).data)
    return tuple(sorted(events, key=lambda e: (e.start_date, e.source.value, str(e.id))))


def stored_event_ids(source: Source, out_dir: Path = OUT_DIR) -> frozenset[EventId]:
    return frozenset(EventId(p.stem) for p in (out_dir / "events" / source.value).glob("*.json"))


# ---- Online ranking snapshots -------------------------------------------------------------------------------------
def snapshot_key(generated_at: datetime) -> str:
    """`2026-10-06T223217Z`: sortable and filename-safe."""
    return generated_at.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")


def snapshot_path(generated_at: datetime, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / "online_rankings" / f"{snapshot_key(generated_at)}.json"


def write_snapshot(snapshot: OnlineRankingSnapshot, out_dir: Path = OUT_DIR, *, replace: bool = False) -> bool:
    path = snapshot_path(snapshot.generated_at, out_dir)
    if path.exists() and not replace:
        return False
    write_atomic(path, pretty(SnapshotFile(data=snapshot).model_dump_json()))
    return True


def load_snapshots(out_dir: Path = OUT_DIR) -> tuple[OnlineRankingSnapshot, ...]:
    """All stored snapshots, oldest first."""
    paths = sorted((out_dir / "online_rankings").glob("*.json"))
    return tuple(SnapshotFile.model_validate_json(p.read_text(encoding="utf-8")).data for p in paths)


def known_snapshot_times(out_dir: Path = OUT_DIR) -> frozenset[datetime]:
    return frozenset(s.generated_at for s in load_snapshots(out_dir))


# ---- Example decks (weighted lists) -----------------------------------------------------------------------
def decks_snapshot_path(fetched_at: datetime, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / "example_decks" / f"{snapshot_key(fetched_at)}.json"


def write_decks_snapshot(snapshot: ExampleDecksSnapshot, out_dir: Path = OUT_DIR) -> Path:
    path = decks_snapshot_path(snapshot.fetched_at, out_dir)
    write_atomic(path, pretty(DecksSnapshotFile(data=snapshot).model_dump_json()))
    return path


def load_decks_snapshot(out_dir: Path = OUT_DIR) -> ExampleDecksSnapshot | None:
    """The newest stored snapshot of the weighted example deck lists, or None."""
    paths = sorted((out_dir / "example_decks").glob("*.json"))
    return DecksSnapshotFile.model_validate_json(paths[-1].read_text(encoding="utf-8")).data if paths else None


# ---- derived ---------------------------------------------------------------------------------------------------
def write_popularity(popularity: PopularityFile, out_dir: Path = OUT_DIR) -> Path:
    path = out_dir / "popularity.json"
    write_atomic(path, pretty(popularity.model_dump_json()))
    return path
