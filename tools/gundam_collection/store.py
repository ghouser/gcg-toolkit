"""Where the collection lives and reading/writing it. The hand-typed file is the source of truth; `collection.json` is derived from it."""
from __future__ import annotations

import json
from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_collection.models import CollectionFile, DeckNamesFile
from tools.gundam_meta.store import write_atomic

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "shared" / "data" / "gundam_collection"
COLLECTION_PATH = OUT_DIR / "my_tcg_collection"  # the hand-typed list
DECK_NAMES_PATH = OUT_DIR / "deck_names.json"  # nicknames for decks, by deck id


def write_collection(file: CollectionFile, out_dir: Path = OUT_DIR) -> Path:
    path = out_dir / "collection.json"
    write_atomic(path, json.dumps(json.loads(file.model_dump_json()), ensure_ascii=False, indent=1) + "\n")
    return path


def load_collection(out_dir: Path = OUT_DIR) -> CollectionFile | None:
    path = out_dir / "collection.json"
    return CollectionFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def owned_copies(file: CollectionFile | None) -> dict[CardNumber, int]:
    """Card number -> copies owned (any printing). Empty when there is no collection yet."""
    return {c.card_number: c.copies for c in file.data} if file else {}


def load_deck_names(path: Path = DECK_NAMES_PATH) -> dict[str, str]:
    """Deck id -> nickname. Empty when there is no file."""
    return DeckNamesFile.model_validate_json(path.read_text(encoding="utf-8")).data if path.is_file() else {}


def save_deck_names(names: dict[str, str], path: Path = DECK_NAMES_PATH) -> Path:
    write_atomic(path, json.dumps(json.loads(DeckNamesFile(data=dict(sorted(names.items()))).model_dump_json()), ensure_ascii=False, indent=1) + "\n")
    return path
