"""packages-store-data-folders AC-1: with GCG_DATA_DIR and GCG_TOOL_DATA_DIR pointed at a temp folder after the packages tool has been
imported (this module imports it at load; the folders are set per test), every packages command that reads or writes its stored files
reads and writes only under the temp folder, and the repository's own packages folder is neither read nor changed.

Not read: the repository's folder holds built packages and rates (tracked), so a command that read them would find some; with none in
the temp folder every reading command reports that nothing is built. Not changed: after every command the repository's folder has the
same files with the same bytes and modification times. The commands run for real (`main` with arguments) over the fixture dataset."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from shared.dataset import ENV_VAR, TOOL_DATA_VAR
from shared.test_read_commands_on_dataset import packages_dataset_tree
from tools.gundam_packages import cli as packages_cli

REPO = Path(__file__).resolve().parents[3]
REAL = REPO / "shared" / "data" / "gundam_packages"
BUILT = ("packages.json", "rates.json", "packages_online.json", "rates_online.json")

READS: list[list[str]] = [
    ["packages"],
    ["packages", "--source", "online"],
    ["archetypes"],
    ["synergy"],
    ["package-synergy"],
    ["free"],
    ["squads"],
    ["package", "amuro", "--source", "online"],
    ["card", "GD01-001"],
    ["compare"],
    ["drift"],
    ["report"],
]


def real_folder() -> dict[str, tuple[bytes, int]]:
    """Every file in the repository's packages folder with its bytes and modification time."""
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(REAL.iterdir()) if p.is_file()}


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The temp tool data folder (with the tracked set list the eras need); the fixture dataset in the temp dataset folder."""
    folder = tmp_path / "tool-data"
    (folder / "shared" / "data" / "gundam_cards").mkdir(parents=True)
    shutil.copyfile(
        REPO / "shared" / "data" / "gundam_cards" / "sets.json",
        folder / "shared" / "data" / "gundam_cards" / "sets.json",
    )
    monkeypatch.setenv(TOOL_DATA_VAR, str(folder))
    monkeypatch.setenv(ENV_VAR, str(packages_dataset_tree(tmp_path / "dataset")))
    return folder


def run(argv: list[str]) -> tuple[int | str | None, str]:
    """The command's exit code (or its SystemExit message) and what it printed."""
    try:
        return packages_cli.main(argv), ""
    except SystemExit as e:
        return e.code, str(e.code)


def test_the_repository_folder_holds_built_packages() -> None:
    """The precondition of the next test: a command reading the repository's folder would find packages and rates there."""
    assert all((REAL / name).is_file() for name in BUILT)


@pytest.mark.parametrize("argv", READS, ids=" ".join)
def test_with_nothing_built_in_the_temp_folder_a_reading_command_finds_nothing(
    temp: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    before = real_folder()
    code, message = run(argv)
    err = capsys.readouterr().err
    assert code != 0
    assert any(s in message + err for s in ("packages yet", "rates yet", "run `build", "first"))
    assert real_folder() == before


def test_pairs_without_rates_in_the_temp_folder_reports_none_built(
    temp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = real_folder()
    assert packages_cli.main(["pairs", "GD01-001"]) == 0
    assert "no rates built" in capsys.readouterr().out  # the repository's rates.json is not read
    assert real_folder() == before


def test_every_command_reads_and_writes_only_the_temp_folder(temp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = temp / "shared" / "data" / "gundam_packages"
    before = real_folder()

    assert packages_cli.main(["build"]) == 0
    assert packages_cli.main(["build", "--source", "online"]) == 0
    assert sorted(p.name for p in out_dir.iterdir()) == sorted(BUILT)
    assert real_folder() == before

    for argv in [*READS, ["pairs", "GD01-001"]]:
        assert packages_cli.main(argv) == 0, argv
        assert real_folder() == before, argv
    assert (out_dir / "drift.json").is_file()  # written by `drift`
    assert (out_dir / "gd05_meta_report.md").is_file()  # written by `report`
    assert "no rates built" not in capsys.readouterr().out  # `pairs` read the temp folder's rates
