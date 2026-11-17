"""AC-5: on a fresh clone with an empty dataset, the commands that read it say "no data" for the missing source instead of crashing.
(The root conftest points GCG_DATA_DIR at an empty folder for every test.)"""
from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from tools.gundam_cards import cli as cards_cli
from tools.gundam_collection import cli as collection_cli
from tools.gundam_meta import cli as meta_cli
from tools.gundam_packages import cli as packages_cli

Main = Callable[[Sequence[str] | None], int]

COMMANDS: list[tuple[Main, list[str], str]] = [
    (cards_cli.main, ["search", "--name", "x"], "card catalog"),
    (cards_cli.main, ["changes"], "card catalog"),
    (cards_cli.main, ["show", "ST01-001"], "card catalog"),
    (cards_cli.main, ["price", "GD01-001"], "card catalog"),
    (meta_cli.main, ["popularity"], "card catalog"),
    (meta_cli.main, ["duplicates"], "in-person events"),
    (meta_cli.main, ["top-cards", "--meta", "major"], "card catalog"),
    (meta_cli.main, ["top-cards", "--meta", "msa"], "card catalog"),
    (packages_cli.main, ["packages"], "card catalog"),
    (packages_cli.main, ["card", "GD01-044"], "card catalog"),
    (packages_cli.main, ["pairs", "GD01-044"], "card catalog"),
    (packages_cli.main, ["build"], "card catalog"),
    (packages_cli.main, ["build", "--source", "online"], "example decks"),
    (collection_cli.main, ["check"], "card catalog"),
    (collection_cli.main, ["coverage"], "card catalog"),
    (collection_cli.main, ["decks"], "card catalog"),
    (collection_cli.main, ["buy", "suletta"], "card catalog"),
    (collection_cli.main, ["deck", "redletta"], "card catalog"),
    (collection_cli.main, ["value"], "card catalog"),
]


@pytest.mark.parametrize(("main", "argv", "source"), COMMANDS, ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a, _ in COMMANDS])
def test_a_command_on_an_empty_dataset_reports_no_data(main: Main, argv: list[str], source: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert f"no data: {source}" in capsys.readouterr().err


def test_eras_still_list_and_say_there_are_no_events(capsys: pytest.CaptureFixture[str]) -> None:
    assert meta_cli.main(["eras"]) == 0
    assert "no data: in-person events" in capsys.readouterr().err
