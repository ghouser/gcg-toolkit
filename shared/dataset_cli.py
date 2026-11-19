"""The local dataset: how old each source is.

    .venv/bin/python -m shared.dataset_cli status                 # "data as of" for each of the five sources ("no data" when empty)

The dataset folder is $GCG_DATA_DIR, or ~/.gcg/data when it is unset (see shared/dataset.py).
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from shared.dataset import Kind, data_dir
from tools.gundam_cards.store import catalog_as_of, prices_as_of
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help='"data as of" for each source').set_defaults(func=cmd_status)
    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
