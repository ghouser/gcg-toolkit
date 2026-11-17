"""AC-3 ("data as of" for each source) and AC-4 (data in the old in-repository layout moves into the dataset with no loss)."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, ProductId
from shared.dataset import Kind, snapshot_key
from shared.dataset_cli import as_of_report, main, migrate_legacy, plan_migration
from tools.gundam_cards import store as cards_store
from tools.gundam_cards.models import CardPrice, PriceFile, SourceTitlesFile, TraitsFile
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.store import load_catalog, load_cards_with_prices, load_prices, write_catalog, write_prices
from tools.gundam_meta.models import Source
from tools.gundam_meta.store import load_decks_snapshot, load_events, load_snapshots, write_decks_snapshot, write_event, write_snapshot
from tools.gundam_meta.tests.test_store_history import T1, T2, decks, event, ranking
from tools.gundam_packages.tests.helpers import unit

CATALOG_AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PULLED = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)


def _prices() -> PriceFile:
    row = CardPrice(card_number=CardNumber("GD01-001"), price_cents=25, product_id=ProductId(7), fetched_at=PULLED)
    return PriceFile(generated_at=PULLED, source_updated_at=PULLED, data=(row,))


def _legacy(root: Path) -> Path:
    """A small repository in the old layout: everything under shared/data/."""
    cards, meta = root / "shared" / "data" / "gundam_cards", root / "shared" / "data" / "gundam_meta"
    cards.mkdir(parents=True)
    old_catalog = {"schema_version": 1, "generated_at": "2026-10-08T12:00:00Z",
                   "data": [json.loads(unit(n, n).model_dump_json()) for n in ("GD01-001", "GD01-002")]}  # fmt: skip
    (cards / "cards.json").write_text(json.dumps(old_catalog, indent=1) + "\n", encoding="utf-8")
    (cards / "traits.json").write_text(TraitsFile(generated_at=CATALOG_AT, data=()).model_dump_json(), encoding="utf-8")
    (cards / "source_titles.json").write_text(SourceTitlesFile(generated_at=CATALOG_AT, data=()).model_dump_json(), encoding="utf-8")
    (cards / "prices.json").write_text(_prices().model_dump_json(indent=1), encoding="utf-8")
    write_event(event("a", T1), meta)
    write_event(event("b", T2), meta)
    write_snapshot(ranking(T1), meta)
    write_decks_snapshot(decks(T1), meta)
    return root


def _bytes(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*.json"))}


# ---- AC-3 -----------------------------------------------------------------------------------------------------------
def test_an_empty_dataset_reports_no_data_for_every_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert as_of_report(tmp_path) == [(k, None) for k in Kind]
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert all(f"{k.value}" in out for k in Kind) and out.count("no data") == 5


def test_each_source_reports_its_newest_date(tmp_path: Path) -> None:
    migrate_legacy(_legacy(tmp_path / "repo"), tmp_path / "ds")
    later = PULLED.replace(day=20)
    write_prices(_prices().model_copy(update={"generated_at": later, "source_updated_at": later}), tmp_path / "ds" / "gundam_cards")
    assert dict(as_of_report(tmp_path / "ds")) == {
        Kind.CATALOG: CATALOG_AT.date(),  # when it was last refreshed
        Kind.PRICES: later.date(),
        Kind.ONLINE_RANKING: T1.date(),
        Kind.EXAMPLE_DECKS: T1.date(),
        Kind.EVENTS: T2.date(),  # the newest collection date
    }


# ---- AC-4 -----------------------------------------------------------------------------------------------------------
def test_migration_keeps_every_file_and_date(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "repo")
    old_meta = _bytes(legacy / "shared" / "data" / "gundam_meta")
    old_cards = legacy / "shared" / "data" / "gundam_cards"
    old_files = _bytes(old_cards)
    ds = tmp_path / "ds"

    report = migrate_legacy(legacy, ds)

    assert report.conflicts == ()
    assert report.copied == {Kind.CATALOG: 3, Kind.PRICES: 1, Kind.ONLINE_RANKING: 1, Kind.EXAMPLE_DECKS: 1, Kind.EVENTS: 2}
    assert _bytes(ds / "gundam_meta") == old_meta  # events and snapshots: byte for byte, dates kept
    for name in ("traits.json", "source_titles.json"):
        assert (ds / "gundam_cards" / name).read_bytes() == old_files[name]
    assert (ds / "gundam_cards" / "prices" / "2026-10-09T210000Z.json").read_bytes() == old_files["prices.json"]  # the first entry
    assert load_prices(ds / "gundam_cards") == _prices()
    catalog = load_catalog(ds / "gundam_cards")
    assert catalog is not None and catalog.generated_at == CATALOG_AT
    assert [str(c.number) for c in catalog.data] == ["GD01-001", "GD01-002"] and catalog.data[0] == unit("GD01-001", "GD01-001")
    assert {(str(r.number), r.first_recorded, r.no_longer_listed) for r in catalog.records} == {
        ("GD01-001", CATALOG_AT, False), ("GD01-002", CATALOG_AT, False)}  # fmt: skip
    assert [p.latest_tcg_price for p in load_cards_with_prices(ds / "gundam_cards")] == [_prices().data[0], None]
    assert len(load_events(ds / "gundam_meta")) == 2 and len(load_snapshots(ds / "gundam_meta")) == 1
    assert load_decks_snapshot(ds / "gundam_meta") == decks(T1)
    assert _bytes(old_cards) == old_files  # the source files are left as they were


def test_migration_refuses_to_overwrite_and_writes_nothing(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "repo")
    ds = tmp_path / "ds"
    migrate_legacy(legacy, ds)
    before = _bytes(ds)
    (legacy / "shared" / "data" / "gundam_cards" / "traits.json").write_text(
        TraitsFile(generated_at=T2, data=()).model_dump_json(), encoding="utf-8")  # fmt: skip
    again = migrate_legacy(legacy, ds)
    assert again.conflicts and sum(again.copied.values()) == 0
    assert _bytes(ds) == before


def test_migrate_command_uses_gcg_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _legacy(tmp_path / "repo")
    monkeypatch.setenv("GCG_DATA_DIR", str(tmp_path / "ds"))
    assert main(["migrate", "--from", str(legacy)]) == 0
    assert (tmp_path / "ds" / "gundam_cards" / "cards.json").is_file()
    assert main(["migrate", "--from", str(legacy)]) == 2


def test_migration_takes_only_the_current_prices_and_backfills_none(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "repo")
    older = _prices().model_copy(update={"generated_at": PULLED - timedelta(days=30), "source_updated_at": PULLED - timedelta(days=30)})
    decoys = (  # older price files elsewhere in the old repository: none of them may become a snapshot
        legacy / cards_store.RAW_DIR.relative_to(cards_store.REPO_ROOT) / "older" / "prices.json",  # the saved dumps' folder
        legacy / "shared" / "data" / "gundam_cards" / "prices" / f"{snapshot_key(older.generated_at)}.json",
        legacy / "shared" / "data" / "gundam_cards" / "prices_old.json",
    )
    for path in decoys:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(older.model_dump_json(indent=1), encoding="utf-8")
    ds = tmp_path / "ds"

    report = migrate_legacy(legacy, ds)

    assert report.copied[Kind.PRICES] == 1
    snapshots = sorted((ds / "gundam_cards" / "prices").iterdir())
    assert [p.read_bytes() for p in snapshots] == [(legacy / "shared" / "data" / "gundam_cards" / "prices.json").read_bytes()]
    assert load_prices(ds / "gundam_cards") == _prices()


def test_the_catalog_reports_its_latest_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("GCG_DATA_DIR", str(tmp_path))
    build = CatalogResult(cards=(unit("GD01-001", "One"),), issues=(), trait_vocabulary=frozenset())
    write_catalog(build, T1)
    write_catalog(CatalogResult(cards=(unit("GD01-002", "Two"),), issues=(), trait_vocabulary=frozenset()), T2)  # a second refresh
    assert dict(as_of_report())[Kind.CATALOG] == T2.date()  # not when the first card was recorded
    assert main(["status"]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if Kind.CATALOG.value in x)
    assert str(T2.date()) in line and str(T1.date()) not in line


def test_events_report_the_newest_collection_date_wherever_it_sorts(tmp_path: Path) -> None:
    newest = T2 + timedelta(days=3)
    stored = (  # in the order written; loading sorts by start date, then source, then id
        event("a-first", newest).model_copy(update={"start_date": date(2026, 9, 1)}),  # newest collection: first in sort and written first
        event("m-middle", T1).model_copy(update={"source": Source.DUELFRONTIER, "start_date": date(2026, 10, 5)}),
        event("z-last", T2).model_copy(update={"start_date": date(2026, 10, 20)}),  # last in sort and last written
    )
    for e in stored:
        write_event(e, tmp_path / "gundam_meta")
    assert load_events(tmp_path / "gundam_meta")[-1].id == "z-last"
    assert dict(as_of_report(tmp_path))[Kind.EVENTS] == newest.date()


def _first(folder: Path) -> Path:
    return sorted(folder.rglob("*.json"))[0]


BROKEN: list[tuple[str, Callable[[Path], Path], str, str]] = [  # what is broken, which file, what it holds, the error it gives
    ("an event", lambda old: _first(old / "gundam_meta" / "events"), "{not json", "EventFile"),
    ("a ranking snapshot", lambda old: _first(old / "gundam_meta" / "online_rankings"), "{not json", "SnapshotFile"),
    ("an example-deck snapshot", lambda old: _first(old / "gundam_meta" / "example_decks"), '{"schema_version": 1}', "DecksSnapshotFile"),
    ("the trait vocabulary", lambda old: old / "gundam_cards" / "traits.json", "[]", "TraitsFile"),
    ("the source-title vocabulary", lambda old: old / "gundam_cards" / "source_titles.json", "[]", "SourceTitlesFile"),
    ("the prices", lambda old: old / "gundam_cards" / "prices.json", "{not json", "PriceFile"),
    ("the catalog's JSON", lambda old: old / "gundam_cards" / "cards.json", "{not json", "Expecting property name"),
    ("a catalog not in schema 1", lambda old: old / "gundam_cards" / "cards.json",
     '{"schema_version": 2, "generated_at": "2026-10-08T12:00:00Z", "data": [], "records": []}', "expected a schema 1 cards.json, got schema 2"),
]  # fmt: skip


@pytest.mark.parametrize(("what", "which", "text", "error"), BROKEN, ids=[b[0] for b in BROKEN])
def test_a_legacy_file_that_does_not_parse_stops_the_migration_before_anything_is_written(
    tmp_path: Path, what: str, which: Callable[[Path], Path], text: str, error: str
) -> None:
    legacy = _legacy(tmp_path / "repo")
    which(legacy / "shared" / "data").write_text(text, encoding="utf-8")
    ds = tmp_path / "ds"
    with pytest.raises(ValueError, match=re.escape(error)):  # pydantic's ValidationError and json's JSONDecodeError are ValueErrors
        migrate_legacy(legacy, ds)
    assert not ds.exists() or not any(p.is_file() for p in ds.rglob("*"))  # the dataset stays empty


def _kind_of(path: Path, old: Path) -> str:
    """A file the migration copies, as a kind: its name under gundam_cards, its folder under gundam_meta."""
    rel = path.relative_to(old)
    return "/".join(rel.parts[:2])


def test_every_kind_of_file_the_migration_copies_has_a_broken_case(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "repo")
    old = legacy / "shared" / "data"
    moves, _ = plan_migration(legacy, tmp_path / "ds")
    copied = {_kind_of(m.source, old) for ms in moves.values() for m in ms}
    assert copied == {_kind_of(which(old), old) for _, which, _, _ in BROKEN}
