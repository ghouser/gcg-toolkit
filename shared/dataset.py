"""The local dataset: where the raw inputs and their dated history live, outside git.

The folder is `$GCG_DATA_DIR`, or `~/.gcg/data` when it is unset; it is resolved on every call, never at import.
History rules shared by the stores: a dated snapshot is added once and never rewritten (see `add_snapshot`).
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ENV_VAR = "GCG_DATA_DIR"


def data_dir() -> Path:
    """The dataset folder: `$GCG_DATA_DIR`, else `~/.gcg/data`."""
    value = os.environ.get(ENV_VAR)
    return Path(value).expanduser() if value else Path.home() / ".gcg" / "data"


class Kind(StrEnum):
    """The five sources the dataset keeps."""

    CATALOG = "card catalog"
    PRICES = "prices"
    ONLINE_RANKING = "online ranking"
    EXAMPLE_DECKS = "example decks"
    EVENTS = "in-person events"


class NoData(Exception):
    """A source the command needs has nothing in the dataset. CLIs print it and exit 2 instead of crashing."""

    def __init__(self, kind: Kind) -> None:
        self.kind = kind
        super().__init__(f"no data: {kind.value} (dataset {data_dir()}; refresh it, or set {ENV_VAR})")


def snapshot_key(when: datetime) -> str:
    """`2026-10-06T223217Z`: sortable and filename-safe."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")


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


def snapshot_paths(folder: Path) -> tuple[Path, ...]:
    """The stored snapshots in a folder, oldest first (keys sort by time)."""
    return tuple(sorted(folder.glob("*.json")))


def newest_snapshot(folder: Path) -> Path | None:
    paths = snapshot_paths(folder)
    return paths[-1] if paths else None


def add_snapshot(folder: Path, key: str, text: str, same_as: Callable[[str], bool]) -> Path | None:
    """Store `<key>.json` as a new dated entry. Nothing is written (None) when an entry with that key exists already, or when
    `same_as(text of the newest entry)` says it holds the same data. Existing entries are never rewritten."""
    path = folder / f"{key}.json"
    if path.exists():
        return None
    newest = newest_snapshot(folder)
    if newest is not None and same_as(newest.read_text(encoding="utf-8")):
        return None
    write_atomic(path, text)
    return path
