"""The local dataset: how old each source is, and the one-time move of data from the old in-repository layout.

    .venv/bin/python -m shared.dataset_cli status                 # "data as of" for each of the five sources ("no data" when empty)
    .venv/bin/python -m shared.dataset_cli migrate --from .       # copy data from <root>/shared/data/ into the dataset (refuses to overwrite)

The dataset folder is $GCG_DATA_DIR, or ~/.gcg/data when it is unset (see shared/dataset.py).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from shared.dataset import Kind, data_dir, snapshot_key, write_atomic
from tools.gundam_cards.models import CardsFile, PriceFile, SourceTitlesFile, TraitsFile
from tools.gundam_cards.store import catalog_as_of, prices_as_of
from tools.gundam_meta.models import DecksSnapshotFile, EventFile, SnapshotFile
from tools.gundam_meta.store import decks_as_of, events_as_of, rankings_as_of


# ---- data as of -----------------------------------------------------------------------------------------------------
def as_of_report(root: Path | None = None) -> list[tuple[Kind, date | None]]:
    """Each source's "data as of" date, or None when it has no data."""
    root = root or data_dir()
    cards, meta = root / "gundam_cards", root / "gundam_meta"
    return [
        (Kind.CATALOG, catalog_as_of(cards)),
        (Kind.PRICES, prices_as_of(cards)),
        (Kind.ONLINE_RANKING, rankings_as_of(meta)),
        (Kind.EXAMPLE_DECKS, decks_as_of(meta)),
        (Kind.EVENTS, events_as_of(meta)),
    ]


_WHAT = {
    Kind.CATALOG: "last refreshed",
    Kind.PRICES: "newest snapshot",
    Kind.ONLINE_RANKING: "newest snapshot",
    Kind.EXAMPLE_DECKS: "newest snapshot",
    Kind.EVENTS: "newest collection date",
}


def cmd_status(_: argparse.Namespace) -> int:
    print(f"data as of (dataset {data_dir()}):")
    for kind, when in as_of_report():
        print(f"  {kind.value:17} " + (f"{when}  ({_WHAT[kind]})" if when else "no data"))
    return 0


# ---- migration from the old layout ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Move:
    source: Path
    target: Path
    convert: Callable[[str], str] | None  # None: copied byte for byte


@dataclass(frozen=True)
class MigrationReport:
    copied: dict[Kind, int]
    conflicts: tuple[Path, ...]  # targets that already exist: nothing was written


def _pretty(compact_json: str) -> str:
    return json.dumps(json.loads(compact_json), ensure_ascii=False, indent=1) + "\n"


def _catalog_v2(text: str) -> str:
    """A schema-1 cards.json as schema 2: same cards, each first recorded at the file's `generated_at`."""
    raw = json.loads(text)
    if raw.get("schema_version") != 1:
        raise ValueError(f"expected a schema 1 cards.json, got schema {raw.get('schema_version')!r}")
    records = [{"number": c["number"], "first_recorded": raw["generated_at"], "no_longer_listed": False} for c in raw["data"]]
    file = CardsFile.model_validate_json(json.dumps({**raw, "schema_version": 2, "records": records}))
    return _pretty(file.model_dump_json())


def plan_migration(legacy_root: Path, root: Path) -> tuple[dict[Kind, list[Move]], list[tuple[Path, type[BaseModel]]]]:
    """What moves where, and the model each moved file must parse as (checked before anything is written)."""
    old_cards, old_meta = legacy_root / "shared" / "data" / "gundam_cards", legacy_root / "shared" / "data" / "gundam_meta"
    cards, meta = root / "gundam_cards", root / "gundam_meta"
    moves: dict[Kind, list[Move]] = {k: [] for k in Kind}
    checks: list[tuple[Path, type[BaseModel]]] = []
    if (old_cards / "cards.json").is_file():
        moves[Kind.CATALOG].append(Move(old_cards / "cards.json", cards / "cards.json", _catalog_v2))
        vocabularies: tuple[tuple[str, type[BaseModel]], ...] = (("traits.json", TraitsFile), ("source_titles.json", SourceTitlesFile))
        for name, model in vocabularies:
            if (old_cards / name).is_file():
                moves[Kind.CATALOG].append(Move(old_cards / name, cards / name, None))
                checks.append((old_cards / name, model))
    if (old_cards / "prices.json").is_file():
        prices = PriceFile.model_validate_json((old_cards / "prices.json").read_text(encoding="utf-8"))
        moves[Kind.PRICES].append(Move(old_cards / "prices.json", cards / "prices" / f"{snapshot_key(prices.generated_at)}.json", None))
    snapshots: tuple[tuple[Kind, str, type[BaseModel]], ...] = (
        (Kind.ONLINE_RANKING, "online_rankings", SnapshotFile),
        (Kind.EXAMPLE_DECKS, "example_decks", DecksSnapshotFile),
        (Kind.EVENTS, "events", EventFile),
    )
    for kind, folder, file_model in snapshots:
        for path in sorted((old_meta / folder).rglob("*.json")):
            moves[kind].append(Move(path, meta / path.relative_to(old_meta), None))
            checks.append((path, file_model))
    return moves, checks


def migrate_legacy(legacy_root: Path, root: Path | None = None) -> MigrationReport:
    """Copy the data of the old in-repository layout into the dataset. Writes nothing when any target already exists, or when a
    file does not parse. Never deletes or changes the source files. No prices are backfilled from saved raw dumps."""
    root = root or data_dir()
    moves, checks = plan_migration(legacy_root, root)
    for path, model in checks:
        model.model_validate_json(path.read_text(encoding="utf-8"))
    every = [m for ms in moves.values() for m in ms]
    conflicts = tuple(m.target for m in every if m.target.exists())
    if conflicts:
        return MigrationReport({k: 0 for k in Kind}, conflicts)
    converted = {m.target: m.convert(m.source.read_text(encoding="utf-8")) for m in every if m.convert}  # fail before writing
    for m in every:
        if m.convert:
            write_atomic(m.target, converted[m.target])
        else:
            m.target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(m.source, m.target)
    return MigrationReport({k: len(ms) for k, ms in moves.items()}, ())


def cmd_migrate(args: argparse.Namespace) -> int:
    report = migrate_legacy(Path(args.source))
    if report.conflicts:
        print(f"the dataset {data_dir()} already has {len(report.conflicts)} of these files; nothing was written:", file=sys.stderr)
        for path in report.conflicts[:20]:
            print(f"  {path}", file=sys.stderr)
        return 2
    print(f"copied into {data_dir()}: " + ", ".join(f"{n} {k.value} file(s)" for k, n in report.copied.items()))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help='"data as of" for each source').set_defaults(func=cmd_status)
    migrate = sub.add_parser("migrate", help="copy data from the old in-repository layout (<root>/shared/data/) into the dataset")
    migrate.add_argument("--from", dest="source", required=True, help="the repository root that holds the old files")
    migrate.set_defaults(func=cmd_migrate)
    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
