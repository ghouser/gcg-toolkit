"""AC-5: on a fresh clone with an empty dataset, the commands that read it say "no data" for the missing source instead of crashing.
(The root conftest points GCG_DATA_DIR at an empty folder for every test.)"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.test_read_commands_on_dataset import collection
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.store import write_catalog
from tools.gundam_meta.models import EraId
from tools.gundam_meta.store import write_event
from tools.gundam_meta.tests.test_store_history import event
from tools.gundam_packages.discover import DEFAULT_PARAMS
from tools.gundam_packages.models import PackagesFile, Window
from tools.gundam_packages.tests.helpers import pilot, unit

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
    (cards_cli.main, ["export"], "card catalog"),
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
    cards_cli.main: {"refresh", "sync", "refetch", "sync-tcgplayer", "sync-restrictions", "reparse", "sets"},
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


# ---- a catalog but no other source: each command names the other source it is missing ------------------------------------
# Every read command, by the sources it reads besides the catalog. Those that read only the catalog (and tracked files) are listed
# apart; the empty-dataset tests above already cover them.
OTHER_SOURCE: list[tuple[Main, list[str], str, int]] = [
    (cards_cli.main, ["price", "GD01-001"], "prices", 1),
    (cards_cli.main, ["export"], "prices", 0),
    (meta_cli.main, ["popularity"], "in-person events", 2),
    (meta_cli.main, ["duplicates"], "in-person events", 2),
    (meta_cli.main, ["top-cards", "--meta", "major"], "in-person events", 2),
    (meta_cli.main, ["top-cards", "--meta", "local"], "in-person events", 2),
    (meta_cli.main, ["top-cards", "--meta", "msa"], "online ranking", 2),
    (meta_cli.main, ["eras"], "in-person events", 0),
    (packages_cli.main, ["build"], "in-person events", 2),
    (packages_cli.main, ["build", "--source", "online"], "example decks", 2),
    (packages_cli.main, ["drift"], "in-person events", 2),
    (packages_cli.main, ["report"], "in-person events", 2),
    (packages_cli.main, ["pairs", "GD01-001"], "prices", 0),
    (collection_cli.main, ["coverage"], "prices", 2),
    (collection_cli.main, ["card", "GD01-001"], "prices", 0),
    (collection_cli.main, ["value"], "prices", 0),
    (collection_cli.main, ["decks"], "prices", 2),
    (collection_cli.main, ["buy", "suletta"], "prices", 2),
    (collection_cli.main, ["deck", "redletta"], "prices", 2),
    (collection_cli.main, ["styles"], "prices", 2),
    (collection_cli.main, ["suggest", "barbatos"], "prices", 2),
    (collection_cli.main, ["archetypes"], "prices", 2),
    (collection_cli.main, ["nickname", "--list"], "prices", 2),
]
CATALOG_ONLY: dict[Main, set[str]] = {
    cards_cli.main: {"search", "changes", "show", "restrictions", "reparse-tcgplayer"},
    meta_cli.main: set(),
    packages_cli.main: {"packages", "archetypes", "synergy", "package-synergy", "free", "squads", "package", "compare", "card"},
    collection_cli.main: {"check", "template", "import"},
}
CATALOG_AT = datetime(2026, 10, 1, tzinfo=UTC)


def _base_packages() -> PackagesFile:
    """A saved tournament build for the base era of `drift` and `report`, so they go on to read the events."""
    window = Window(era=EraId("gd05"), start=date(2026, 1, 1), end=None, tiers=(), events=0, decks=0, decks_not_counted=0)
    return PackagesFile(generated_at=CATALOG_AT, window=window, params=DEFAULT_PARAMS, packages=(), synergy_cards=(), free_floating=(),
                        archetypes=(), squads=(), package_synergies=(), rare_cards=0)  # fmt: skip


@pytest.fixture
def catalog_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(CatalogResult(cards=(unit("GD01-001", "Gundam", link="Amuro Ray"), pilot("GD01-002", "Amuro Ray")), issues=(),
                                trait_vocabulary=frozenset()), CATALOG_AT)  # fmt: skip
    # Inputs outside the dataset are small fixtures, never the repository's own files; nothing is written into the repository.
    monkeypatch.setattr(collection_cli, "_refresh_collection", lambda cards: None)
    monkeypatch.setattr(collection_cli, "load_collection", lambda *a, **k: collection())
    for cli in (collection_cli, packages_cli):
        monkeypatch.setattr(cli, "load_rates", lambda *a, **k: None)
    monkeypatch.setattr(collection_cli, "load_packages", lambda *a, **k: None)
    monkeypatch.setattr(packages_cli, "load_packages", lambda *a, **k: _base_packages())
    monkeypatch.setattr(meta_cli, "write_popularity", lambda file: tmp_path / "popularity.json")


@pytest.mark.parametrize(("main", "argv", "source", "code"), OTHER_SOURCE,
                         ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a, _, _ in OTHER_SOURCE])  # fmt: skip
def test_with_only_the_catalog_a_command_names_the_other_source_it_is_missing(
    catalog_only: None, main: Main, argv: list[str], source: str, code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == code
    captured = capsys.readouterr()
    assert f"no data: {source}" in captured.err + captured.out
    assert "no data: card catalog" not in captured.err + captured.out


def test_popularity_without_a_ranking_says_so_and_builds_from_events(catalog_only: None, capsys: pytest.CaptureFixture[str]) -> None:
    write_event(event("a", datetime(2026, 10, 2, tzinfo=UTC)))
    assert meta_cli.main(["popularity"]) == 0
    assert "no data: online ranking" in capsys.readouterr().err


@pytest.mark.parametrize("main", list(CATALOG_ONLY), ids=lambda m: m.__module__.split(".")[1])
def test_every_read_command_is_classified_by_the_sources_it_reads(main: Main) -> None:
    reads = {a[0] for m, a, _ in COMMANDS + DEGRADED if m is main}
    others = {a[0] for m, a, _, _ in OTHER_SOURCE if m is main}
    assert reads == others | CATALOG_ONLY[main] and not others & CATALOG_ONLY[main]
