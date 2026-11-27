"""The local dataset: where the raw inputs and their dated history live, outside git.

The folder is `$GCG_DATA_DIR`, or `~/.gcg/data` when it is unset; it is resolved on every call, never at import.
The cards and meta tools' raw page caches and the cards, meta, packages and collection tools' tracked files are found under `tool_data_root()` (`$GCG_TOOL_DATA_DIR`, else the
repository), resolved the same way.
History rules shared by the stores: a dated snapshot is added at most once per UTC day and never rewritten (see `add_snapshot`).
Backstop: while the test suite runs, every file writer refuses a path inside the real `~/.gcg` (see `refuse_real_data_write`).
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ENV_VAR = "GCG_DATA_DIR"
TOOL_DATA_VAR = "GCG_TOOL_DATA_DIR"
REPO_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """The dataset folder: `$GCG_DATA_DIR`, else `~/.gcg/data`."""
    value = os.environ.get(ENV_VAR)
    return Path(value).expanduser() if value else Path.home() / ".gcg" / "data"


def tool_data_root() -> Path:
    """The folder standing in for the repository root for the tools' data folders: the cards and meta raw page caches are
    `<root>/tools/<tool>/data/raw/` and the cards, meta, packages and collection tracked files `<root>/shared/data/<tool>/`. `$GCG_TOOL_DATA_DIR`, else the repository."""
    value = os.environ.get(TOOL_DATA_VAR)
    return Path(value).expanduser() if value else REPO_ROOT


class RealDataWrite(Exception):
    """A write into the real `~/.gcg` folder while the test suite runs. Raised before anything is written."""


def refuse_real_data_write(path: Path) -> None:
    """Raise `RealDataWrite` when the test suite is running (pytest is imported) and `path` resolves inside `~/.gcg`: the real dataset,
    images and catalog export. A backstop for a test, or an old checkout, that forgot to redirect a location or ran with real data;
    outside a test run it does nothing."""
    if "pytest" not in sys.modules:
        return
    real = (Path.home() / ".gcg").resolve()
    target = path.resolve()
    if target == real or real in target.parents:
        raise RealDataWrite(
            f"refused to write {path}: the test suite is running and this is inside the real {real} folder "
            "(tests write only to temp folders: GCG_DATA_DIR, GCG_CATALOG_FILE); nothing was written"
        )


class Kind(StrEnum):
    """The five sources the dataset keeps."""

    CATALOG = "card catalog"
    PRICES = "prices"
    ONLINE_RANKING = "online ranking"
    EXAMPLE_DECKS = "example decks"
    EVENTS = "in-person events"


class NoData(Exception):
    """A source the command needs has nothing in the dataset. CLIs print it and exit 2 instead of crashing. `missing` says what
    exactly is not stored, when it is not the dataset's copy of the source (a saved price dump)."""

    def __init__(self, kind: Kind, missing: str | None = None) -> None:
        self.kind = kind
        super().__init__(f"no data: {kind.value} ({missing or f'dataset {data_dir()}; refresh it, or set {ENV_VAR}'})")


def snapshot_key(when: datetime) -> str:
    """`2026-10-06T223217Z`: sortable and filename-safe."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")


def write_atomic(path: Path, text: str) -> None:
    refuse_real_data_write(path)
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


def entry_on_day(folder: Path, key: str) -> Path | None:
    """The stored entry dated on the same UTC calendar day as `key` (keys start with the UTC date), or None."""
    return next((p for p in snapshot_paths(folder) if p.stem[:10] == key[:10]), None)


def add_snapshot(folder: Path, key: str, text: str, same_as: Callable[[str], bool]) -> Path | None:
    """Store `<key>.json` as a new dated entry. Nothing is written (None) when an entry on the same UTC day exists already (even with
    different data), or when `same_as(text of the newest entry)` says it holds the same data. Existing entries are never rewritten."""
    path = folder / f"{key}.json"
    if entry_on_day(folder, key) is not None:
        return None
    newest = newest_snapshot(folder)
    if newest is not None and same_as(newest.read_text(encoding="utf-8")):
        return None
    write_atomic(path, text)
    return path
