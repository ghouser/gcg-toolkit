"""Where the text list and the deck nicknames live, and reading and writing the nicknames. The collection itself is read only through `collection_file.py`."""
from __future__ import annotations

import json
from pathlib import Path

from tools.gundam_collection.models import DeckNamesFile
from tools.gundam_meta.store import write_atomic

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "shared" / "data" / "gundam_collection"
COLLECTION_PATH = OUT_DIR / "my_tcg_collection"  # the hand-typed list (read by `collection_file.py`; `check` and `template` still default to it)
DECK_NAMES_PATH = OUT_DIR / "deck_names.json"  # nicknames for decks, by deck id


def load_deck_names(path: Path = DECK_NAMES_PATH) -> dict[str, str]:
    """Deck id -> nickname. Empty when there is no file."""
    return DeckNamesFile.model_validate_json(path.read_text(encoding="utf-8")).data if path.is_file() else {}


def save_deck_names(names: dict[str, str], path: Path = DECK_NAMES_PATH) -> Path:
    write_atomic(path, json.dumps(json.loads(DeckNamesFile(data=dict(sorted(names.items()))).model_dump_json()), ensure_ascii=False, indent=1) + "\n")
    return path
