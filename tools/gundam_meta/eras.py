"""Eras: windows that start when new cards enter the game, defined by the sets that open them.

`eras.json` (hand-maintained) says which sets anchor each era; start dates come from the card catalog's
`sets.json` at read time, so nothing here goes stale. Eras don't overlap: an era ends where the next begins.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path

from shared.basetypes import SetCode
from tools.gundam_meta.models import Era, EraDef, EraId, ErasFile

ERAS_PATH = Path(__file__).parent / "eras.json"


class EraError(Exception):
    pass


def load_era_defs(path: Path = ERAS_PATH) -> tuple[EraDef, ...]:
    return ErasFile.model_validate_json(path.read_text(encoding="utf-8")).data


def resolve_eras(defs: Iterable[EraDef], release_dates: Mapping[SetCode, date]) -> tuple[Era, ...]:
    """Eras in start order. An era whose anchor sets have no release date yet is left out (it hasn't been announced)."""
    dated: list[tuple[date, EraDef]] = []
    for definition in defs:
        dates = [release_dates.get(code) for code in definition.anchor_sets]
        if any(d is None for d in dates):
            continue
        dated.append((max(d for d in dates if d is not None), definition))
    dated.sort(key=lambda pair: pair[0])
    starts = [d for d, _ in dated]
    if len(set(starts)) != len(starts):
        raise EraError(f"two eras start on the same day: {[(str(d), e.id) for d, e in dated]}")
    return tuple(
        Era(definition=definition, start=start, end=dated[i + 1][0] if i + 1 < len(dated) else None)
        for i, (start, definition) in enumerate(dated)
    )


def era_on(eras: Sequence[Era], day: date) -> Era | None:
    """The era containing `day`, or None for days before the first era."""
    return next((e for e in eras if e.contains(day)), None)


def current_era(eras: Sequence[Era], today: date) -> Era | None:
    """The latest era that has started by `today`."""
    return era_on(eras, today)


def find_era(eras: Sequence[Era], era_id: EraId) -> Era:
    for era in eras:
        if era.id == era_id:
            return era
    raise EraError(f"unknown or not-yet-announced era {era_id!r} (known: {[str(e.id) for e in eras]})")
