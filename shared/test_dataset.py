"""The dataset location and the shared snapshot rule (AC-2)."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, ProductId
from shared.dataset import REPO_ROOT, Kind, NoData, add_snapshot, data_dir, newest_snapshot, snapshot_key
from tools.gundam_cards import store as cards_store
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.models import CardPrice, PriceFile
from tools.gundam_meta import store as meta_store
from tools.gundam_meta.tests.test_store_history import T1, decks, event, ranking
from tools.gundam_packages.tests.helpers import unit


def test_the_dataset_is_gcg_data_dir_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_DATA_DIR", str(tmp_path / "elsewhere"))
    assert data_dir() == tmp_path / "elsewhere"


def test_the_dataset_defaults_to_dot_gcg_data_in_the_home_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCG_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert data_dir() == tmp_path / ".gcg" / "data"


def test_the_dataset_is_never_inside_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("GCG_DATA_DIR", raising=False)
    assert repo not in data_dir().resolve().parents


def _never_same(old: str) -> bool:
    return False


def test_a_snapshot_is_added_once_and_earlier_ones_are_untouched(tmp_path: Path) -> None:
    first = add_snapshot(tmp_path, "2026-10-01T000000Z", "one\n", _never_same)
    assert first is not None and first.read_text() == "one\n"
    assert add_snapshot(tmp_path, "2026-10-01T000000Z", "changed\n", _never_same) is None  # same date: not rewritten
    assert first.read_text() == "one\n"
    second = add_snapshot(tmp_path, "2026-10-02T000000Z", "two\n", _never_same)
    assert second is not None and newest_snapshot(tmp_path) == second and first.read_text() == "one\n"


def test_data_identical_to_the_newest_adds_nothing(tmp_path: Path) -> None:
    add_snapshot(tmp_path, "2026-10-01T000000Z", "same\n", lambda old: False)
    assert add_snapshot(tmp_path, "2026-10-02T000000Z", "same\n", lambda old: old == "same\n") is None
    assert [p.name for p in tmp_path.iterdir()] == ["2026-10-01T000000Z.json"]


def test_a_second_store_on_the_same_utc_day_adds_nothing_even_with_other_data(tmp_path: Path) -> None:
    morning = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
    first = add_snapshot(tmp_path, snapshot_key(morning), "one\n", _never_same)
    assert first is not None
    assert add_snapshot(tmp_path, snapshot_key(morning.replace(hour=23, minute=59)), "other\n", _never_same) is None
    late_west = datetime(2026, 10, 1, 19, 0, tzinfo=timezone(timedelta(hours=-5)))  # Oct 2, 00:00 in UTC: the next UTC day
    second = add_snapshot(tmp_path, snapshot_key(late_west), "two\n", _never_same)
    assert second is not None and second.name == "2026-10-02T000000Z.json"
    assert sorted(p.name for p in tmp_path.iterdir()) == [first.name, second.name] and first.read_text() == "one\n"


def test_no_data_names_the_source() -> None:
    assert str(NoData(Kind.PRICES)).startswith("no data: prices")


def test_no_data_with_what_is_missing_names_it_instead_of_the_dataset() -> None:
    error = NoData(Kind.PRICES, "saved price dump 20261008T200609Z is not in /x")
    assert error.kind is Kind.PRICES
    assert str(error) == "no data: prices (saved price dump 20261008T200609Z is not in /x)"
    assert f"dataset {data_dir()}" in str(NoData(Kind.PRICES))  # without it, the dataset hint stays


# ---- every writer, called without a folder, stores into the dataset and leaves the repository as it was ----------------
_SKIP = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _repository_files(root: Path, skip: set[Path]) -> dict[str, tuple[int, int]]:
    """Every file under the repository folder with its size and modification time (caches and fetched responses left out)."""
    found: dict[str, tuple[int, int]] = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP and Path(folder, d) not in skip]
        for name in files:
            st = Path(folder, name).stat()
            found[str(Path(folder, name).relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return found


def test_every_writer_defaults_to_the_dataset_and_leaves_the_repository_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = tmp_path / "ds"
    monkeypatch.setenv("GCG_DATA_DIR", str(ds))
    skip = {REPO_ROOT / "tools" / tool / "data" / "raw" for tool in ("gundam_cards", "gundam_meta")}
    before = _repository_files(REPO_ROOT, skip)

    pulled = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
    row = CardPrice(card_number=CardNumber("GD01-001"), price_cents=25, product_id=ProductId(7), fetched_at=pulled)
    price_path = cards_store.write_prices(PriceFile(generated_at=pulled, source_updated_at=pulled, data=(row,)))
    cards_store.write_catalog(CatalogResult(cards=(unit("GD01-001", "One"),), issues=(), trait_vocabulary=frozenset()), pulled)
    decks_path = meta_store.write_decks_snapshot(decks(T1))
    assert meta_store.write_snapshot(ranking(T1))
    assert meta_store.write_event(event("a", T1))

    assert price_path == ds / "gundam_cards" / "prices" / "2026-10-09T210000Z.json" and price_path.is_file()
    assert {p.name for p in (ds / "gundam_cards").glob("*.json")} == {"cards.json", "traits.json", "source_titles.json"}
    assert decks_path.parent == ds / "gundam_meta" / "example_decks" and decks_path.is_file()
    assert len(list((ds / "gundam_meta" / "online_rankings").glob("*.json"))) == 1
    assert (ds / "gundam_meta" / "events" / "egm" / "a.json").is_file()
    assert _repository_files(REPO_ROOT, skip) == before  # nothing written under the repository folder
