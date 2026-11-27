"""packages-store-data-folders AC-1, the collection tool: with GCG_DATA_DIR and GCG_TOOL_DATA_DIR pointed at a temp folder after the
collection tool has been imported (this module imports it at load; the folders are set per test), `nickname` (set, remove, list) and
the buy export read and write only under the temp folder, and the repository's own collection folder is neither read nor changed.

Not read: nicknames set in one temp folder are not listed once the setting points at another, so the nicknames are read from wherever
the setting points when the command runs. Not changed: after every command the repository's collection folder has the same files with
the same bytes and modification times. The commands run for real (`main` with arguments) over the packages fixture dataset, with the
packages built in the temp folder."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from shared.dataset import ENV_VAR, TOOL_DATA_VAR
from shared.test_read_commands_on_dataset import packages_dataset_tree, write_collection_file
from tools.gundam_collection import cli as collection_cli
from tools.gundam_packages import cli as packages_cli

REPO = Path(__file__).resolve().parents[3]
REAL = REPO / "shared" / "data" / "gundam_collection"
COLLECTION = Path("shared") / "data" / "gundam_collection"


def real_folder() -> dict[str, tuple[bytes, int]]:
    """Every file in the repository's collection folder with its bytes and modification time."""
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(REAL.iterdir()) if p.is_file()}


def tool_data(folder: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`folder` as the tool data folder, with the tracked set list the eras need and the packages built in it."""
    (folder / "shared" / "data" / "gundam_cards").mkdir(parents=True)
    shutil.copyfile(
        REPO / "shared" / "data" / "gundam_cards" / "sets.json",
        folder / "shared" / "data" / "gundam_cards" / "sets.json",
    )
    monkeypatch.setenv(TOOL_DATA_VAR, str(folder))
    assert packages_cli.main(["build"]) == 0
    assert packages_cli.main(["build", "--source", "online"]) == 0
    return folder


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The fixture dataset in the temp dataset folder, the fixture collection file, and the temp tool data folder (no collection folder yet)."""
    monkeypatch.setenv(ENV_VAR, str(packages_dataset_tree(tmp_path / "dataset")))
    write_collection_file(tmp_path, monkeypatch)
    folder = tool_data(tmp_path / "tool-data", monkeypatch)
    assert not (folder / COLLECTION).exists()
    return folder


def nicknames(folder: Path) -> dict[str, str]:
    data: dict[str, str] = json.loads((folder / COLLECTION / "deck_names.json").read_text(encoding="utf-8"))["data"]
    return data


def test_nickname_set_list_and_remove_use_only_the_temp_folder(temp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = real_folder()

    assert collection_cli.main(["nickname", "amuro", "mine"]) == 0
    assert list(nicknames(temp).values()) == ["mine"]
    assert real_folder() == before

    capsys.readouterr()
    assert collection_cli.main(["nickname", "--list"]) == 0
    listed = capsys.readouterr().out
    assert "deck nicknames (1)" in listed and "mine" in listed
    assert real_folder() == before

    assert collection_cli.main(["nickname", "mine", "--remove"]) == 0
    assert nicknames(temp) == {}
    assert real_folder() == before


def test_nicknames_are_read_from_where_the_setting_points_when_the_command_runs(
    temp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = real_folder()
    assert collection_cli.main(["nickname", "amuro", "mine"]) == 0

    tool_data(tmp_path / "other-tool-data", monkeypatch)
    capsys.readouterr()
    assert collection_cli.main(["nickname", "--list"]) == 0
    assert "deck nicknames (0)" in capsys.readouterr().out  # the first folder's nickname is not read

    monkeypatch.setenv(TOOL_DATA_VAR, str(temp))
    assert collection_cli.main(["nickname", "--list"]) == 0
    assert "deck nicknames (1)" in capsys.readouterr().out
    assert real_folder() == before


def test_the_buy_export_is_written_only_in_the_temp_folder(temp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = real_folder()
    assert collection_cli.main(["buy", "amuro", "--min-rate", "0", "--export"]) == 0
    exported = temp / COLLECTION / "buy_amuro.txt"
    assert exported.is_file()
    assert str(exported) in capsys.readouterr().out
    assert real_folder() == before
