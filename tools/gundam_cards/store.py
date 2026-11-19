"""Reading the raw page cache and writing the catalog files.

- The set list and the restrictions file are tracked in the repository (`OUT_DIR`).
- The catalog, its vocabularies and the price snapshots live in the local dataset (`data_out_dir()`, see `shared/dataset.py`).
  The catalog only grows; price snapshots are added, never rewritten.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from shared.basetypes import CardNumber, PackageId, PrintingId, SetCode, SourceTitle, Trait
from shared.dataset import Kind, NoData, add_snapshot, data_dir, newest_snapshot, snapshot_key
from tools.gundam_cards.build import CatalogResult, Issue, IssueKind, SourcePage
from tools.gundam_cards.models import (
    Card,
    CardPrice,
    CardRecord,
    CardSet,
    CardsFile,
    PriceFile,
    RestrictionsFile,
    PricedCard,
    SetsFile,
    SourceTitlesFile,
    SourceTitleStat,
    TraitsFile,
    TraitStat,
    traits_of,
)
from tools.gundam_cards.parse_detail import DetailPageError, parse_detail_html
from tools.gundam_cards.printings import read_package_lists, read_packages
from tools.gundam_cards.tcgcsv import RawDump

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "tools" / "gundam_cards" / "data" / "raw"
OUT_DIR = REPO_ROOT / "shared" / "data" / "gundam_cards"  # tracked: sets.json, restrictions.json


def data_out_dir() -> Path:
    """This tool's folder in the local dataset: cards.json, traits.json, source_titles.json, prices/."""
    return data_dir() / "gundam_cards"


@dataclass(frozen=True)
class LoadedPages:
    pages: tuple[SourcePage, ...]
    issues: tuple[Issue, ...]


def packages_by_printing(raw_dir: Path) -> dict[PrintingId, tuple[PackageId, ...]]:
    """Which package list pages each printing appears on, from the cached list pages (no network)."""
    inverted: dict[PrintingId, list[PackageId]] = defaultdict(list)
    for package_id, ids in read_package_lists(raw_dir, read_packages(raw_dir)).items():
        for printing_id in ids:
            inverted[printing_id].append(package_id)
    return {k: tuple(v) for k, v in inverted.items()}


def load_source_pages(raw_dir: Path = RAW_DIR) -> LoadedPages:
    """Parse every cached detail page. Pages that can't be parsed become issues."""
    packages_of = packages_by_printing(raw_dir)
    pages: list[SourcePage] = []
    issues: list[Issue] = []
    for path in sorted((raw_dir / "detail").glob("*.html")):
        try:
            printing_id = PrintingId(path.stem)
            raw = parse_detail_html(path.read_text(encoding="utf-8"))
        except (ValueError, DetailPageError) as e:
            issues.append(Issue(IssueKind.PARSE_FAILURE, path.name, str(e)))
            continue
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        pages.append(SourcePage(printing_id, raw, fetched_at, packages_of.get(printing_id, ())))
    return LoadedPages(tuple(pages), tuple(issues))


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


def write_sets(sets: tuple[CardSet, ...], generated_at: datetime, out_dir: Path = OUT_DIR) -> None:
    write_atomic(out_dir / "sets.json", _pretty(SetsFile(generated_at=generated_at, data=sets).model_dump_json()))


def load_sets(out_dir: Path = OUT_DIR) -> tuple[CardSet, ...]:
    """The saved sets, or () when sets.json doesn't exist yet."""
    path = out_dir / "sets.json"
    if not path.is_file():
        return ()
    return SetsFile.model_validate_json(path.read_text(encoding="utf-8")).data


def release_dates(sets: tuple[CardSet, ...]) -> dict[SetCode, date]:
    """Set code -> release date, for sets that have one."""
    return {s.code: s.release_date for s in sets if s.release_date is not None}


def load_catalog(out_dir: Path | None = None) -> CardsFile | None:
    """The stored catalog, or None when the dataset has none."""
    path = (out_dir or data_out_dir()) / "cards.json"
    return CardsFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_catalog_or_fail(out_dir: Path | None = None) -> CardsFile:
    """The stored catalog; raises `NoData` when there is none."""
    catalog = load_catalog(out_dir)
    if catalog is None:
        raise NoData(Kind.CATALOG)
    return catalog


def merge_catalog(stored: CardsFile | None, cards: tuple[Card, ...], generated_at: datetime) -> CardsFile:
    """Append-only: every stored card stays. A card in `cards` takes its new data and keeps its first-recorded date; a stored card
    missing from `cards` keeps its last data and is marked no longer listed; a new card is first recorded now. Sorted by number."""
    old_cards = {c.number: c for c in stored.data} if stored else {}
    old_records = {r.number: r for r in stored.records} if stored else {}
    listed = {c.number: c for c in cards}
    merged = {**old_cards, **listed}
    numbers = sorted(merged, key=str)
    records = tuple(
        CardRecord(
            number=n,
            first_recorded=old_records[n].first_recorded if n in old_records else generated_at,
            no_longer_listed=n not in listed,
        )
        for n in numbers
    )
    return CardsFile(generated_at=generated_at, data=tuple(merged[n] for n in numbers), records=records)


def write_catalog(result: CatalogResult, generated_at: datetime, out_dir: Path | None = None) -> None:
    """Merge the build into the stored catalog (see `merge_catalog`), then write cards.json, traits.json and source_titles.json
    (deterministic: sorted, indented). The vocabularies cover the whole merged catalog."""
    out_dir = out_dir or data_out_dir()
    cards = merge_catalog(load_catalog(out_dir), result.cards, generated_at)
    write_atomic(out_dir / "cards.json", _pretty(cards.model_dump_json()))

    users: dict[Trait, set[CardNumber]] = defaultdict(set)
    for card in cards.data:
        for trait in traits_of(card):
            users[trait].add(card.number)
    stats = tuple(
        TraitStat(trait=trait, card_count=len(numbers), card_numbers=tuple(sorted(numbers)))
        for trait, numbers in sorted(users.items())
    )
    write_atomic(out_dir / "traits.json", _pretty(TraitsFile(generated_at=generated_at, data=stats).model_dump_json()))

    titles: dict[SourceTitle, int] = defaultdict(int)
    for card in cards.data:
        for title in {p.source_title for p in card.printings if p.source_title is not None}:
            titles[title] += 1
    title_stats = tuple(SourceTitleStat(source_title=t, card_count=n) for t, n in sorted(titles.items()))
    write_atomic(
        out_dir / "source_titles.json",
        _pretty(SourceTitlesFile(generated_at=generated_at, data=title_stats).model_dump_json()),
    )


# ---- prices (tcgcsv) -------------------------------------------------------------------------------------------------
def _price_content(file: PriceFile) -> object:
    """What a price snapshot says, without when it was stored (the pull time on the file and on each row)."""
    return (file.source_updated_at, [row.model_dump(exclude={"fetched_at"}) for row in file.data])


def write_prices(file: PriceFile, out_dir: Path | None = None) -> Path | None:
    """Add a dated price snapshot (`prices/<generated_at>.json`). None, writing nothing, when that UTC day is stored already or the
    newest snapshot has the same prices."""
    folder = (out_dir or data_out_dir()) / "prices"
    same = _price_content(file)
    return add_snapshot(
        folder, snapshot_key(file.generated_at), _pretty(file.model_dump_json()),
        lambda text: _price_content(PriceFile.model_validate_json(text)) == same,
    )


def load_prices(out_dir: Path | None = None) -> PriceFile | None:
    """The newest price snapshot, or None."""
    path = newest_snapshot((out_dir or data_out_dir()) / "prices")
    return PriceFile.model_validate_json(path.read_text(encoding="utf-8")) if path else None


def catalog_as_of(out_dir: Path | None = None) -> date | None:
    """When the catalog was last refreshed, or None (no data)."""
    catalog = load_catalog(out_dir)
    return catalog.generated_at.date() if catalog else None


def prices_as_of(out_dir: Path | None = None) -> date | None:
    """The date of the newest price snapshot, or None (no data)."""
    prices = load_prices(out_dir)
    return prices.generated_at.date() if prices else None


def load_cards_with_prices(out_dir: Path | None = None) -> tuple[PricedCard, ...]:
    """Every card in `cards.json` once, joined with its latest price (None when it has none). Built on read; nothing is stored.
    Raises `NoData` when there is no catalog."""
    cards = load_catalog_or_fail(out_dir).data
    prices = load_prices(out_dir)
    by_number: dict[CardNumber, CardPrice] = {p.card_number: p for p in prices.data} if prices else {}
    return tuple(PricedCard(card=c, latest_tcg_price=by_number.get(c.number)) for c in cards)


def raw_dump_stamps(raw_dir: Path = RAW_DIR) -> tuple[str, ...]:
    """The saved tcgcsv dumps (`20261008T200609Z`), oldest first."""
    return tuple(sorted(p.name for p in (raw_dir / "tcgcsv").glob("*Z") if (p / "groups.json").is_file()))


def read_raw_dump(stamp: str, raw_dir: Path = RAW_DIR) -> RawDump:
    """A saved dump read back from disk (no network)."""
    folder = raw_dir / "tcgcsv" / stamp
    groups_text = (folder / "groups.json").read_text(encoding="utf-8")
    group_ids = [g["groupId"] for g in json.loads(groups_text)["results"]]
    return RawDump(
        source_updated_at=datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
        groups=groups_text,
        products={g: (folder / f"{g}_products.json").read_text(encoding="utf-8") for g in group_ids},
        prices={g: (folder / f"{g}_prices.json").read_text(encoding="utf-8") for g in group_ids},
    )


def _pretty(compact_json: str) -> str:
    return json.dumps(json.loads(compact_json), ensure_ascii=False, indent=1) + "\n"


def write_restrictions(file: RestrictionsFile, out_dir: Path = OUT_DIR) -> Path:
    path = out_dir / "restrictions.json"
    write_atomic(path, json.dumps(json.loads(file.model_dump_json()), ensure_ascii=False, indent=1) + "\n")
    return path


def load_restrictions(out_dir: Path = OUT_DIR) -> RestrictionsFile | None:
    path = out_dir / "restrictions.json"
    return RestrictionsFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None
