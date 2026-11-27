"""Stands in for the dataset of an owner who has older per-card price snapshots (`prices/`): no command writes that format any more."""

from __future__ import annotations

import json
from pathlib import Path

from shared.dataset import add_snapshot, snapshot_key
from tools.gundam_cards.models import PriceFile
from tools.gundam_cards.store import data_out_dir


def write_prices(file: PriceFile, out_dir: Path | None = None) -> Path | None:
    """Add a dated per-card snapshot (`prices/<generated_at>.json`) the way the toolkit did: None, writing nothing, when that UTC day is
    stored already or the newest snapshot has the same prices."""

    def content(f: PriceFile) -> object:
        return (f.source_updated_at, [row.model_dump(exclude={"fetched_at"}) for row in f.data])

    text = json.dumps(json.loads(file.model_dump_json()), ensure_ascii=False, indent=1) + "\n"
    return add_snapshot((out_dir or data_out_dir()) / "prices", snapshot_key(file.generated_at), text,
                        lambda old: content(PriceFile.model_validate_json(old)) == content(file))  # fmt: skip
