"""AC-3: "data as of" for each source."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, ProductId
from shared.dataset import Kind
from shared.dataset_cli import as_of_report, main
from tools.gundam_cards.models import CardPrice, PriceFile
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.tests.price_files import write_prices
from tools.gundam_cards.store import write_catalog
from tools.gundam_meta.models import Source
from tools.gundam_meta.store import load_events, write_decks_snapshot, write_event, write_snapshot
from tools.gundam_meta.tests.test_store_history import T1, T2, decks, event, ranking
from tools.gundam_packages.tests.helpers import unit

CATALOG_AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PULLED = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)


def _prices() -> PriceFile:
    row = CardPrice(card_number=CardNumber("GD01-001"), price_cents=25, product_id=ProductId(7), fetched_at=PULLED)
    return PriceFile(generated_at=PULLED, source_updated_at=PULLED, data=(row,))


def _dataset(root: Path) -> Path:
    """A small dataset with every source: a catalog, one price snapshot, two events, one ranking and one example-deck snapshot."""
    build = CatalogResult(cards=(unit("GD01-001", "GD01-001"), unit("GD01-002", "GD01-002")), issues=(), trait_vocabulary=frozenset())
    write_catalog(build, CATALOG_AT, root / "gundam_cards")
    write_prices(_prices(), root / "gundam_cards")
    meta = root / "gundam_meta"
    write_event(event("a", T1), meta)
    write_event(event("b", T2), meta)
    write_snapshot(ranking(T1), meta)
    write_decks_snapshot(decks(T1), meta)
    return root


# ---- AC-3 -----------------------------------------------------------------------------------------------------------
def test_an_empty_dataset_reports_no_data_for_every_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert as_of_report(tmp_path) == [(k, None) for k in Kind]
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert all(f"{k.value}" in out for k in Kind) and out.count("no data") == 5


def test_each_source_reports_its_newest_date(tmp_path: Path) -> None:
    _dataset(tmp_path / "ds")
    later = PULLED.replace(day=20)
    write_prices(_prices().model_copy(update={"generated_at": later, "source_updated_at": later}), tmp_path / "ds" / "gundam_cards")
    assert dict(as_of_report(tmp_path / "ds")) == {
        Kind.CATALOG: CATALOG_AT.date(),  # when it was last refreshed
        Kind.PRICES: later.date(),
        Kind.ONLINE_RANKING: T1.date(),
        Kind.EXAMPLE_DECKS: T1.date(),
        Kind.EVENTS: T2.date(),  # the newest collection date
    }


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
