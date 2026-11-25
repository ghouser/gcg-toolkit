"""Reading and writing the deck nicknames. The collection itself and the text list are found through `collection_file.py`.

The deck nicknames and the buy export are kept in `shared/data/gundam_collection/` under `tool_data_root()` (the repository unless
`$GCG_TOOL_DATA_DIR` stands in, see `shared/dataset.py`), resolved on every call.
"""
from __future__ import annotations

import json
from pathlib import Path

from shared.dataset import tool_data_root, write_atomic
from tools.gundam_collection.models import DeckNamesFile


def tracked_folder() -> Path:
    """The tracked collection folder under `tool_data_root()`."""
    return tool_data_root() / "shared" / "data" / "gundam_collection"


def load_deck_names(path: Path | None = None) -> dict[str, str]:
    """Deck id -> nickname (from `deck_names.json` in the tracked folder unless `path` is given). Empty when there is no file."""
    path = path or tracked_folder() / "deck_names.json"
    return DeckNamesFile.model_validate_json(path.read_text(encoding="utf-8")).data if path.is_file() else {}


def save_deck_names(names: dict[str, str], path: Path | None = None) -> Path:
    path = path or tracked_folder() / "deck_names.json"
    write_atomic(path, json.dumps(json.loads(DeckNamesFile(data=dict(sorted(names.items()))).model_dump_json()), ensure_ascii=False, indent=1) + "\n")
    return path
