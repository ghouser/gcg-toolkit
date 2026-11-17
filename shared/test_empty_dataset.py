"""AC-5: on a fresh clone with an empty dataset, the commands that read it say "no data" for the missing source instead of crashing.
(The root conftest points GCG_DATA_DIR at an empty folder for every test.)"""
from __future__ import annotations

import re
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
    (cards_cli.main, ["reparse-tcgplayer"], "card catalog"),
    (meta_cli.main, ["popularity"], "card catalog"),
    (meta_cli.main, ["duplicates"], "in-person events"),
    (meta_cli.main, ["top-cards", "--meta", "major"], "card catalog"),
    (meta_cli.main, ["top-cards", "--meta", "msa"], "card catalog"),
    (packages_cli.main, ["packages"], "card catalog"),
    (packages_cli.main, ["card", "GD01-044"], "card catalog"),
    (packages_cli.main, ["pairs", "GD01-044"], "card catalog"),
    (packages_cli.main, ["build"], "card catalog"),
    (packages_cli.main, ["build", "--source", "online"], "example decks"),
    (packages_cli.main, ["archetypes"], "card catalog"),
    (packages_cli.main, ["synergy"], "card catalog"),
    (packages_cli.main, ["package-synergy"], "card catalog"),
    (packages_cli.main, ["free"], "card catalog"),
    (packages_cli.main, ["squads"], "card catalog"),
    (packages_cli.main, ["package", "barbatos"], "card catalog"),
    (packages_cli.main, ["compare"], "card catalog"),
    (packages_cli.main, ["drift"], "card catalog"),
    (packages_cli.main, ["report"], "card catalog"),
    (collection_cli.main, ["check"], "card catalog"),
    (collection_cli.main, ["coverage"], "card catalog"),
    (collection_cli.main, ["decks"], "card catalog"),
    (collection_cli.main, ["buy", "suletta"], "card catalog"),
    (collection_cli.main, ["deck", "redletta"], "card catalog"),
    (collection_cli.main, ["value"], "card catalog"),
    (collection_cli.main, ["template", "ST01"], "card catalog"),
    (collection_cli.main, ["import", "--file", __file__], "card catalog"),  # any existing file: the catalog is needed first
    (collection_cli.main, ["card", "GD01-001"], "card catalog"),
    (collection_cli.main, ["styles"], "card catalog"),
    (collection_cli.main, ["suggest", "barbatos"], "card catalog"),
    (collection_cli.main, ["archetypes"], "card catalog"),
    (collection_cli.main, ["nickname", "--list"], "card catalog"),
]

# Commands that still work without the dataset: they list what they can and say which source has no data.
DEGRADED: list[tuple[Main, list[str], str]] = [
    (meta_cli.main, ["eras"], "in-person events"),
    (cards_cli.main, ["restrictions"], "card catalog"),
]

# Subcommands that are not reads of the dataset: they fetch over the network, rebuild from saved responses, or read only tracked files.
NOT_DATASET_READS: dict[Main, set[str]] = {
    cards_cli.main: {"sync", "refetch", "sync-tcgplayer", "sync-restrictions", "reparse", "sets"},
    meta_cli.main: {"sync", "refetch", "reparse"},
    packages_cli.main: set(),
    collection_cli.main: set(),
}


@pytest.mark.parametrize(("main", "argv", "source"), COMMANDS, ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a, _ in COMMANDS])
def test_a_command_on_an_empty_dataset_reports_no_data(main: Main, argv: list[str], source: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert f"no data: {source}" in capsys.readouterr().err


@pytest.mark.parametrize(("main", "argv", "source"), DEGRADED, ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a, _ in DEGRADED])
def test_a_command_that_works_without_the_dataset_says_which_source_has_no_data(
    main: Main, argv: list[str], source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 0
    assert f"no data: {source}" in capsys.readouterr().err


@pytest.mark.parametrize("main", list(NOT_DATASET_READS), ids=lambda m: m.__module__.split(".")[1])
def test_every_subcommand_is_checked_or_is_not_a_dataset_read(main: Main, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    match = re.search(r"\{([a-z,-]+)\}", capsys.readouterr().out)
    assert match is not None
    checked = {a[0] for m, a, _ in COMMANDS + DEGRADED if m is main}
    assert set(match.group(1).split(",")) == checked | NOT_DATASET_READS[main]
