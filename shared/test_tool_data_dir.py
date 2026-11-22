"""toolkit-hardening AC-2: with GCG_TOOL_DATA_DIR pointed at a temp folder, the cards and meta commands read and write their raw caches
and tracked files only there; the repository's tracked sets.json, restrictions.json and popularity.json stay byte-identical and its raw
folders unchanged. Unset, the folders are the repository's own.

The commands run for real (`main` with arguments; real parsers and writers) over saved fixture pages copied into the temp folder."""
from __future__ import annotations

import os
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.basetypes import PackageId, SetCode
from shared.dataset import TOOL_DATA_VAR
from shared.test_read_commands_on_dataset import dataset_tree
from tools.gundam_cards import cli as cards_cli
from tools.gundam_cards import store as cards_store
from tools.gundam_cards.models import CardSet, CardsFile, SetKind, SetsFile
from tools.gundam_meta import cli as meta_cli
from tools.gundam_meta import store as meta_store

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tools" / "gundam_cards" / "tests" / "fixtures"
TRACKED = ("shared/data/gundam_cards/sets.json", "shared/data/gundam_cards/restrictions.json", "shared/data/gundam_meta/popularity.json")
REAL_RAW = (REPO / "tools" / "gundam_cards" / "data" / "raw", REPO / "tools" / "gundam_meta" / "data" / "raw")
PAGES = ("GD01-005", "GD01-005_p2", "ST01-001", "ST01-001_p5", "R-002")


def tracked_bytes() -> dict[str, bytes | None]:
    return {p: (REPO / p).read_bytes() if (REPO / p).is_file() else None for p in TRACKED}


def raw_listing() -> dict[str, tuple[int, int]]:
    """Every file in the real raw folders with its size and modification time (only listed, never opened)."""
    found: dict[str, tuple[int, int]] = {}
    for root in REAL_RAW:
        for folder, _, files in os.walk(root):
            for name in files:
                st = Path(folder, name).stat()
                found[str(Path(folder, name))] = (st.st_size, st.st_mtime_ns)
    return found


@pytest.fixture
def tool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "tool-data"
    monkeypatch.setenv(TOOL_DATA_VAR, str(folder))
    monkeypatch.setenv("GCG_DATA_DIR", str(tmp_path / "dataset"))
    return folder


def test_reparse_and_sets_use_only_the_temp_folder(tool_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    detail = tool_dir / "tools" / "gundam_cards" / "data" / "raw" / "detail"
    detail.mkdir(parents=True)
    for page in PAGES:
        shutil.copyfile(FIXTURES / f"{page}.html", detail / f"{page}.html")
    gd01 = CardSet(code=SetCode("GD01"), name="Temp Set", kind=SetKind.BOOSTER, bandai_package_id=PackageId("616101"),
                   release_date=date(2025, 7, 25), product_category_raw=None, product_url=None)  # fmt: skip
    sets_path = tool_dir / "shared" / "data" / "gundam_cards" / "sets.json"
    sets_path.parent.mkdir(parents=True)
    sets_path.write_text(SetsFile(generated_at=datetime(2026, 11, 1, tzinfo=UTC), data=(gd01,)).model_dump_json(), encoding="utf-8")
    tracked, raw = tracked_bytes(), raw_listing()

    assert cards_cli.main(["reparse"]) == 0
    catalog = CardsFile.model_validate_json((tmp_path / "dataset" / "gundam_cards" / "cards.json").read_text(encoding="utf-8"))
    assert sorted(str(c.number) for c in catalog.data) == ["GD01-005", "R-002", "ST01-001"]  # built from the temp folder's pages
    capsys.readouterr()
    assert cards_cli.main(["sets"]) == 0
    rows = capsys.readouterr().out.splitlines()[1:]
    assert [r.split()[0] for r in rows] == ["GD01"] and "Temp Set" in rows[0]  # the temp folder's sets.json, not the repository's

    assert tracked_bytes() == tracked
    assert raw_listing() == raw


def test_meta_popularity_writes_into_the_temp_folder(tool_dir: Path, tmp_path: Path) -> None:
    dataset_tree(tmp_path / "dataset")
    sets = REPO / "shared" / "data" / "gundam_cards" / "sets.json"
    (tool_dir / "shared" / "data" / "gundam_cards").mkdir(parents=True)
    shutil.copyfile(sets, tool_dir / "shared" / "data" / "gundam_cards" / "sets.json")  # the eras need release dates
    tracked, raw = tracked_bytes(), raw_listing()

    assert meta_cli.main(["popularity"]) == 0
    assert (tool_dir / "shared" / "data" / "gundam_meta" / "popularity.json").is_file()
    assert tracked_bytes() == tracked
    assert raw_listing() == raw


def test_unset_the_folders_are_the_repositorys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOOL_DATA_VAR)
    assert cards_store.raw_folder() == REPO / "tools" / "gundam_cards" / "data" / "raw"
    assert cards_store.tracked_folder() == REPO / "shared" / "data" / "gundam_cards"
    assert meta_store.raw_folder() == REPO / "tools" / "gundam_meta" / "data" / "raw"
    assert meta_store.tracked_folder() == REPO / "shared" / "data" / "gundam_meta"
