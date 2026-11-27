"""The one reader of collection data: the UI's collection file, or the old hand-typed text list when that file does not exist.

The collection file (`$GCG_COLLECTION_FILE`, else `~/.gcg/collection.json`) is written by the UI; the toolkit only reads it and
never writes it. Its schema is `docs/collection-file.md`. The text list (`my_tcg_collection`) is the read-only fallback until the
file exists; the two are never merged. Both are read into `Owned`: printing id -> count, with derived card and printing views.
Paths are resolved when a function runs (`.claude/rules/data-folders.md`).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Collection, Mapping
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from shared.basetypes import CardNumber, FrozenModel, PrintingId
from shared.dataset import tool_data_root
from tools.gundam_collection.models import Art
from tools.gundam_collection.parse import parse_lines

ENV_VAR = "GCG_COLLECTION_FILE"
SUPPORTED_VERSIONS = (1,)


def collection_file_path() -> Path:
    """The collection file: `$GCG_COLLECTION_FILE`, else `~/.gcg/collection.json`."""
    value = os.environ.get(ENV_VAR)
    return Path(value).expanduser() if value else Path.home() / ".gcg" / "collection.json"


def text_list_path() -> Path:
    """The legacy text list, in the tracked folder under `tool_data_root()` (the repository unless `$GCG_TOOL_DATA_DIR` stands in)."""
    return tool_data_root() / "shared" / "data" / "gundam_collection" / "my_tcg_collection"


class CollectionRefused(Exception):
    """The collection file is present but cannot be used. The message names the file and the problem."""


class Source(StrEnum):
    FILE = "collection file"
    TEXT_LIST = "text list"
    NONE = "nothing"  # neither exists yet


class Owned(FrozenModel):
    """What is owned: printing id -> count (1 or more), only ids the catalog knows; the unknown ids are kept apart."""

    printings: dict[PrintingId, int]
    unknown: tuple[PrintingId, ...] = ()
    source: Source = Source.NONE
    markers: int = 0  # text list only: marker lines (`+`, `++`, `LK`) counted as the base printing

    @property
    def cards(self) -> dict[CardNumber, int]:
        """Card number -> copies, any printing counting as the card."""
        totals: dict[CardNumber, int] = defaultdict(int)
        for printing, count in self.printings.items():
            totals[printing.card_number] += count
        return dict(totals)


def parse_collection_file(text: str) -> dict[PrintingId, int]:
    """Printing id -> count from the file's text. Raises `CollectionRefused` naming the first problem found."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CollectionRefused(f"not valid JSON ({e})") from e
    if not isinstance(data, dict):
        raise CollectionRefused("the top level is not a JSON object")
    version = data.get("schema_version")
    if isinstance(version, bool) or version not in SUPPORTED_VERSIONS:
        raise CollectionRefused(
            f"schema_version is {version!r}; this toolkit supports version {', '.join(map(str, SUPPORTED_VERSIONS))}"
        )
    stamp = data.get("updated_at")
    if not isinstance(stamp, str):
        raise CollectionRefused("updated_at is missing or not a time string")
    try:
        datetime.fromisoformat(stamp)
    except ValueError:
        raise CollectionRefused(f"updated_at is not an ISO 8601 time: {stamp!r}") from None
    counts = data.get("counts")
    if not isinstance(counts, dict):
        raise CollectionRefused("counts is missing or not an object")
    found: dict[PrintingId, int] = {}
    for key, count in counts.items():
        try:
            printing = PrintingId(key)
        except ValueError:
            raise CollectionRefused(f"{key!r} is not a printing id (like ST01-001 or ST01-001_p5)") from None
        if isinstance(count, bool) or not isinstance(count, int):
            raise CollectionRefused(f"{key}: the count must be an integer, not {json.dumps(count)}")
        if count < 1:
            raise CollectionRefused(f"{key}: the count must be 1 or more, not {count} (a card not owned is left out)")
        found[printing] = count
    return found


def parse_text_list(text: str) -> tuple[dict[PrintingId, int], int]:
    """Printing id -> count from the text list, and how many marker lines were counted. Every counted line is that card's base
    printing (a marker does not name a printing); lines that cannot be read, zero and `?` count as nothing, as `check` reports."""
    entries, _, _ = parse_lines(text.splitlines())
    found: dict[PrintingId, int] = defaultdict(int)
    for entry in entries:
        if entry.copies is not None:
            found[PrintingId(entry.card_number)] += entry.copies
    return dict(found), sum(1 for e in entries if e.copies is not None and e.art is not Art.BASE)


def read_owned(known_printings: Collection[PrintingId]) -> Owned:
    """What is owned, from the collection file when it exists (refusing it when invalid), else from the text list, else nothing.

    `known_printings` is every printing id of the catalog; the rest are reported in `unknown`. A text-list base id counts as
    known when the catalog has its card (the list names cards, not printings)."""
    path = collection_file_path()
    if path.exists():
        try:
            printings = parse_collection_file(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            raise CollectionRefused(f"{path}: cannot be read ({e})") from e
        except CollectionRefused as e:
            raise CollectionRefused(f"{path}: {e}") from e
        return _split(printings, set(known_printings), Source.FILE, 0)
    text_path = text_list_path()
    if text_path.is_file():
        printings, markers = parse_text_list(text_path.read_text(encoding="utf-8"))
        known_cards = {p.card_number for p in known_printings}
        return _split(printings, {p for p in printings if p.card_number in known_cards}, Source.TEXT_LIST, markers)
    return Owned(printings={})


def _split(printings: Mapping[PrintingId, int], known: set[PrintingId], source: Source, markers: int) -> Owned:
    return Owned(
        printings={p: n for p, n in sorted(printings.items()) if p in known},
        unknown=tuple(p for p in sorted(printings) if p not in known),
        source=source,
        markers=markers,
    )
