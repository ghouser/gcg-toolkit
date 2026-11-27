"""toolkit-hardening AC-2 (backstop): while the test suite runs, a write that resolves inside `~/.gcg` (the real dataset, images or
catalog export) is refused with a clear error and writes nothing, even when no location was redirected.

The real `~/.gcg` is never touched here: HOME points at a temp folder, so `~/.gcg` resolves inside it, and the locations are left at
their defaults, as a test that forgot to redirect them would leave them."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared import dataset
from shared.dataset import ENV_VAR, REPO_ROOT, RealDataWrite, data_dir
from shared.fetch import Fetcher
from shared.test_fetch import serve
from tools.gundam_cards import store as cards_store
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.store import CATALOG_FILE_VAR, catalog_export_path
from tools.gundam_meta import store as meta_store
from tools.gundam_meta.tests.test_store_history import event
from tools.gundam_packages.tests.helpers import unit


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in home folder, with the dataset and the catalog export left at their defaults (under `~/.gcg`)."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.delenv(ENV_VAR)
    monkeypatch.delenv(CATALOG_FILE_VAR)
    assert (
        Path.home() == fake
        and data_dir() == fake / ".gcg" / "data"
        and catalog_export_path() == fake / ".gcg" / "catalog.json"
    )
    return fake


def files_under(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file()]


@pytest.mark.parametrize("where", ["data/gundam_cards/cards.json", "catalog.json", "images/GD01-001.webp", "."])
def test_the_shared_writer_refuses_the_real_gcg_folder(home: Path, where: str) -> None:
    with pytest.raises(RealDataWrite, match=r"refused to write .*the test suite is running.*nothing was written"):
        dataset.write_atomic(home / ".gcg" / where, "{}")
    assert files_under(home) == []


def test_a_store_write_left_at_the_default_dataset_is_refused(home: Path) -> None:
    with pytest.raises(RealDataWrite):
        cards_store.write_catalog(CatalogResult(cards=(unit("GD01-001", "One"),), issues=(), trait_vocabulary=frozenset()),
                                  datetime(2026, 11, 1, tzinfo=UTC))  # fmt: skip
    with pytest.raises(RealDataWrite):
        meta_store.write_event(event("a", datetime(2026, 11, 1, tzinfo=UTC)))
    assert files_under(home) == []


def test_the_fetcher_cache_refuses_the_real_gcg_folder(home: Path) -> None:
    fetcher = Fetcher(home / ".gcg" / "images", min_interval_s=0.0)
    with serve() as server, pytest.raises(RealDataWrite):
        fetcher.get_text(f"{server}/ok", cache_key="GD01-001.txt")
    assert files_under(home) == []


def test_a_write_outside_gcg_still_works(home: Path) -> None:
    dataset.write_atomic(home / "elsewhere" / "file.json", "{}")
    assert (home / "elsewhere" / "file.json").read_text(encoding="utf-8") == "{}"


def test_the_refusal_holds_in_a_real_data_run(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_TEST_REAL_DATA", "1")
    with pytest.raises(RealDataWrite):
        cards_store.write_catalog(CatalogResult(cards=(unit("GD01-001", "One"),), issues=(), trait_vocabulary=frozenset()),
                                  datetime(2026, 11, 1, tzinfo=UTC))  # fmt: skip
    assert files_under(home) == []


WRITE_OUTSIDE_TESTS = """
import sys
from datetime import UTC, datetime
from shared.dataset import write_atomic
from tools.gundam_cards import store
from tools.gundam_cards.build import CatalogResult
from tools.gundam_packages.tests.helpers import unit
assert "pytest" not in sys.modules
store.write_catalog(CatalogResult(cards=(unit("GD01-001", "One"),), issues=(), trait_vocabulary=frozenset()), datetime(2026, 11, 1, tzinfo=UTC))
write_atomic(store.catalog_export_path(), "{}")
"""


def test_outside_a_test_run_the_same_writes_go_through(home: Path) -> None:
    """A separate Python without pytest, its home at the temp folder and the locations at their defaults, writes into `~/.gcg`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GCG_") and k != "PYTEST_CURRENT_TEST"} | {
        "HOME": str(home)
    }
    done = subprocess.run(
        [sys.executable, "-c", WRITE_OUTSIDE_TESTS], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert (home / ".gcg" / "data" / "gundam_cards" / "cards.json").is_file()
    assert (home / ".gcg" / "catalog.json").read_text(encoding="utf-8") == "{}"
