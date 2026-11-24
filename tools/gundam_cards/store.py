"""Reading the raw page cache and writing the catalog files.

- The set list and the restrictions file are tracked in the repository (`tracked_folder()`); the tcgcsv dumps and the restrictions
  page are cached in `raw_folder()`. Both are under `tool_data_root()` (see `shared/dataset.py`), resolved on every call.
- Bandai's card pages (landing, product, list and detail pages) are cached in the dataset (`pages_folder()`), so every checkout pointed
  at the same dataset shares one cache.
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
from shared.dataset import (
    Kind,
    NoData,
    add_snapshot,
    data_dir,
    newest_snapshot,
    refuse_real_data_write,
    snapshot_key,
    snapshot_paths,
    tool_data_root,
)
from tools.gundam_cards.build import CatalogResult, Issue, IssueKind, SourcePage
from tools.gundam_cards.export import CatalogExport, export_json
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


def raw_folder() -> Path:
    """This tool's raw cache in the checkout (git-ignored): tcgcsv dumps and the restrictions page."""
    return tool_data_root() / "tools" / "gundam_cards" / "data" / "raw"


def pages_folder() -> Path:
    """The cache of Bandai's card pages, in the dataset: `$GCG_DATA_DIR/gundam_cards/pages/`."""
    return data_out_dir() / "pages"


def tracked_folder() -> Path:
    """This tool's tracked files: sets.json (changed only by hand) and restrictions.json."""
    return tool_data_root() / "shared" / "data" / "gundam_cards"


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


def load_source_pages(raw_dir: Path | None = None, packages_of: dict[PrintingId, tuple[PackageId, ...]] | None = None) -> LoadedPages:
    """Parse every cached detail page. Pages that can't be parsed become issues. Each printing's packages come from `packages_of`,
    or from the cached list pages when it is not given."""
    raw_dir = raw_dir or pages_folder()
    if packages_of is None:
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


def load_tracked_sets(out_dir: Path | None = None) -> tuple[CardSet, ...]:
    """The reviewed, tracked sets.json, or () when there is none. Changed only by hand: no code writes it."""
    path = (out_dir or tracked_folder()) / "sets.json"
    if not path.is_file():
        return ()
    return SetsFile.model_validate_json(path.read_text(encoding="utf-8")).data


def load_provisional_sets(out_dir: Path | None = None) -> tuple[CardSet, ...]:
    """Sets a rebuild found on Bandai that sets.json does not have (dataset `provisional_sets.json`), or ()."""
    path = (out_dir or data_out_dir()) / "provisional_sets.json"
    return SetsFile.model_validate_json(path.read_text(encoding="utf-8")).data if path.is_file() else ()


def write_provisional_sets(sets: tuple[CardSet, ...], generated_at: datetime, out_dir: Path | None = None) -> bool:
    """Store the provisional packages (sorted by code). Writes nothing (False) when they are the ones stored already."""
    ordered = tuple(sorted(sets, key=lambda s: str(s.code)))
    if ordered == load_provisional_sets(out_dir):
        return False
    write_atomic((out_dir or data_out_dir()) / "provisional_sets.json", _pretty(SetsFile(generated_at=generated_at, data=ordered).model_dump_json()))
    return True


def load_sets(out_dir: Path | None = None, data_out: Path | None = None) -> tuple[CardSet, ...]:
    """Every known set: the tracked sets.json plus the dataset's provisional packages; for a code in both, the sets.json entry wins."""
    tracked = load_tracked_sets(out_dir)
    codes = {s.code for s in tracked}
    return tracked + tuple(s for s in load_provisional_sets(data_out) if s.code not in codes)


def release_dates(sets: tuple[CardSet, ...]) -> dict[SetCode, date]:
    """Set code -> release date, for sets that have one."""
    return {s.code: s.release_date for s in sets if s.release_date is not None}


def package_set_codes(sets: tuple[CardSet, ...]) -> dict[PackageId, SetCode]:
    """Bandai package id -> set code, for sets that have a package id (the build's fallback for a printing whose text names no set)."""
    return {s.bandai_package_id: s.code for s in sets if s.bandai_package_id is not None}


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


def merge_catalog(
    stored: CardsFile | None, cards: tuple[Card, ...], generated_at: datetime, listed: frozenset[CardNumber] | None = None
) -> CardsFile:
    """Append-only: every stored card stays. A card in `cards` takes its new data and keeps its first-recorded date; a stored card
    missing from `cards` keeps its last data; a new card is first recorded now. Sorted by number.

    `listed` is the card numbers a complete refresh saw on Bandai's listings; only then are misses counted. A stored card not listed
    is missed and keeps its stored data as it is (its rebuild knows none of its packages): a first miss sets `missed_once`, a miss
    on a card already missed once marks it no longer listed. A listed card clears both. Without `listed` (a rebuild from saved
    pages) every stored card keeps its marks."""
    old_cards = {c.number: c for c in stored.data} if stored else {}
    old_records = {r.number: r for r in stored.records} if stored else {}
    missed = {n for n in old_cards if listed is not None and n not in listed}
    merged = {**old_cards, **{c.number: c for c in cards if c.number not in missed}}
    numbers = sorted(merged, key=str)

    def record(n: CardNumber) -> CardRecord:
        old = old_records.get(n)
        first = old.first_recorded if old else generated_at
        if listed is None:
            return CardRecord(number=n, first_recorded=first, no_longer_listed=old.no_longer_listed if old else False,
                              missed_once=old.missed_once if old else False)
        if n in listed or old is None:
            return CardRecord(number=n, first_recorded=first, no_longer_listed=False, missed_once=False)
        return CardRecord(number=n, first_recorded=first, no_longer_listed=old.no_longer_listed or old.missed_once, missed_once=True)

    return CardsFile(generated_at=generated_at, data=tuple(merged[n] for n in numbers), records=tuple(record(n) for n in numbers))


def write_catalog(result: CatalogResult, generated_at: datetime, out_dir: Path | None = None) -> None:
    """Merge the build into the stored catalog (see `merge_catalog`; no listings, so no card is marked), then write it."""
    save_catalog(merge_catalog(load_catalog(out_dir), result.cards, generated_at), out_dir)


def save_catalog(cards: CardsFile, out_dir: Path | None = None) -> None:
    """Write cards.json, traits.json and source_titles.json (deterministic: sorted, indented). The vocabularies cover the whole
    catalog; cards.json is written first."""
    out_dir = out_dir or data_out_dir()
    generated_at = cards.generated_at
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


def load_price_history(out_dir: Path | None = None) -> tuple[PriceFile, ...]:
    """Every stored price snapshot, oldest first (empty when there are none)."""
    return tuple(PriceFile.model_validate_json(p.read_text(encoding="utf-8")) for p in snapshot_paths((out_dir or data_out_dir()) / "prices"))


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


def raw_dump_stamps(raw_dir: Path | None = None) -> tuple[str, ...]:
    """The saved tcgcsv dumps (`20261008T200609Z`), oldest first."""
    return tuple(sorted(p.name for p in ((raw_dir or raw_folder()) / "tcgcsv").glob("*Z") if (p / "groups.json").is_file()))


def read_raw_dump(stamp: str, raw_dir: Path | None = None) -> RawDump:
    """A saved dump read back from disk (no network). Raises `NoData` naming the dump when it is not stored, or only partly stored
    (a group's products or prices file is missing)."""
    folder = (raw_dir or raw_folder()) / "tcgcsv" / stamp
    if not (folder / "groups.json").is_file():
        raise NoData(Kind.PRICES, f"saved price dump {stamp} is not in {folder.parent}")
    groups_text = (folder / "groups.json").read_text(encoding="utf-8")
    group_ids = [g["groupId"] for g in json.loads(groups_text)["results"]]
    for name in (f"{g}_{part}.json" for g in group_ids for part in ("products", "prices")):
        if not (folder / name).is_file():
            raise NoData(Kind.PRICES, f"saved price dump {stamp} is incomplete: {name} is missing from {folder}")
    return RawDump(
        source_updated_at=datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
        groups=groups_text,
        products={g: (folder / f"{g}_products.json").read_text(encoding="utf-8") for g in group_ids},
        prices={g: (folder / f"{g}_prices.json").read_text(encoding="utf-8") for g in group_ids},
    )


# ---- the catalog export (for the UI) ---------------------------------------------------------------------------------
CATALOG_FILE_VAR = "GCG_CATALOG_FILE"


def catalog_export_path() -> Path:
    """Where the catalog export goes: `$GCG_CATALOG_FILE`, else `~/.gcg/catalog.json` (resolved on every call)."""
    value = os.environ.get(CATALOG_FILE_VAR)
    return Path(value).expanduser() if value else Path.home() / ".gcg" / "catalog.json"


def write_catalog_export(export: CatalogExport, path: Path) -> None:
    """Write the export atomically: a failure part-way leaves an earlier export as it was."""
    write_atomic(path, export_json(export))


def _pretty(compact_json: str) -> str:
    return json.dumps(json.loads(compact_json), ensure_ascii=False, indent=1) + "\n"


def write_restrictions(file: RestrictionsFile, out_dir: Path | None = None) -> Path:
    path = (out_dir or tracked_folder()) / "restrictions.json"
    write_atomic(path, json.dumps(json.loads(file.model_dump_json()), ensure_ascii=False, indent=1) + "\n")
    return path


def load_restrictions(out_dir: Path | None = None) -> RestrictionsFile | None:
    path = (out_dir or tracked_folder()) / "restrictions.json"
    return RestrictionsFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None
