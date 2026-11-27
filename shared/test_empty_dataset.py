"""AC-5: on a fresh clone with an empty dataset, the commands that read it say "no data" for the missing source instead of crashing.
(The root conftest points GCG_DATA_DIR at an empty folder for every test.)"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.dataset import Kind, NoData
from shared.test_read_commands_on_dataset import write_collection_file
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.store import write_catalog
from tools.gundam_meta.models import EraId, Source
from tools.gundam_meta.store import write_event
from tools.gundam_meta.tests.test_store_history import event
from tools.gundam_packages.discover import DEFAULT_PARAMS
from tools.gundam_packages.models import PackagesFile, RatesFile, Window
from tools.gundam_packages.store import write_packages, write_rates
from tools.gundam_packages.tests.helpers import pilot, unit

from shared import dataset_cli
from tools.gundam_cards import cli as cards_cli
from tools.gundam_cards import store as cards_store
from tools.gundam_collection import store as collection_store
from tools.gundam_meta import store as meta_store
from tools.gundam_packages import store as packages_store
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
    (
        collection_cli.main,
        ["check", "--file", __file__],
        "card catalog",
    ),  # any existing file: the catalog is needed first
    (collection_cli.main, ["coverage"], "card catalog"),
    (collection_cli.main, ["decks"], "card catalog"),
    (collection_cli.main, ["buy", "suletta"], "card catalog"),
    (collection_cli.main, ["deck", "redletta"], "card catalog"),
    (collection_cli.main, ["value"], "card catalog"),
    (collection_cli.main, ["template", "ST01"], "card catalog"),
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

# Commands that report on the dataset itself: on an empty one they succeed and say "no data" for every source.
SOURCE_REPORTS: list[tuple[Main, list[str]]] = [
    (dataset_cli.main, ["status"]),
]

# Subcommands that are not reads of the dataset: they fetch over the network, rebuild from saved responses, or read only tracked files.
NOT_DATASET_READS: dict[Main, set[str]] = {
    cards_cli.main: {
        "refresh",
        "refresh-prices",
        "sync",
        "refetch",
        "sync-tcgplayer",
        "sync-restrictions",
        "reparse",
        "sets",
    },
    meta_cli.main: {"sync", "refetch", "reparse"},
    packages_cli.main: set(),
    collection_cli.main: {"import"},  # prints a pointer to the UI
    dataset_cli.main: set(),
}


@pytest.fixture
def tracked_packages() -> None:
    """As on a fresh clone, the tracked packages and rates are there (small stand-ins, in the root conftest's temp tool data folder)."""
    base = _base_packages()
    write_packages(base)
    write_rates(
        RatesFile(generated_at=CATALOG_AT, window=base.window, total_decks=0, packages=(), archetypes=(), card_index={})
    )


@pytest.mark.parametrize(
    ("main", "argv", "source"), COMMANDS, ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a, _ in COMMANDS]
)
def test_a_command_on_an_empty_dataset_reports_no_data(
    tracked_packages: None, main: Main, argv: list[str], source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert f"no data: {source}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("main", "argv", "source"), DEGRADED, ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a, _ in DEGRADED]
)
def test_a_command_that_works_without_the_dataset_says_which_source_has_no_data(
    main: Main, argv: list[str], source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 0
    assert f"no data: {source}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("main", "argv"), SOURCE_REPORTS, ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a in SOURCE_REPORTS]
)
def test_a_source_report_on_an_empty_dataset_says_no_data_for_every_source(
    main: Main, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 0
    lines = capsys.readouterr().out.splitlines()
    for kind in Kind:
        assert [line.split() for line in lines if kind.value in line] == [[*kind.value.split(), "no", "data"]]


@pytest.mark.parametrize("main", list(NOT_DATASET_READS), ids=lambda m: m.__module__.split(".")[1])
def test_every_subcommand_is_checked_or_is_not_a_dataset_read(main: Main, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    match = re.search(r"\{([a-z,-]+)\}", capsys.readouterr().out)
    assert match is not None
    checked = {a[0] for m, a, _ in COMMANDS + DEGRADED if m is main} | {a[0] for m, a in SOURCE_REPORTS if m is main}
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
    packages_cli.main: {
        "packages",
        "archetypes",
        "synergy",
        "package-synergy",
        "free",
        "squads",
        "package",
        "compare",
        "card",
    },
    collection_cli.main: {"check", "template"},
}
CATALOG_AT = datetime(2026, 10, 1, tzinfo=UTC)


def _base_packages() -> PackagesFile:
    """A saved tournament build for the base era of `drift` and `report`, so they go on to read the events."""
    window = Window(
        era=EraId("gd05"), start=date(2026, 1, 1), end=None, tiers=(), events=0, decks=0, decks_not_counted=0
    )
    return PackagesFile(generated_at=CATALOG_AT, window=window, params=DEFAULT_PARAMS, packages=(), synergy_cards=(), free_floating=(),
                        archetypes=(), squads=(), package_synergies=(), rare_cards=0)  # fmt: skip


@pytest.fixture
def catalog_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(CatalogResult(cards=(unit("GD01-001", "Gundam", link="Amuro Ray"), pilot("GD01-002", "Amuro Ray")), issues=(),
                                trait_vocabulary=frozenset()), CATALOG_AT)  # fmt: skip
    # Inputs outside the dataset are small fixtures, never the repository's own files; nothing is written into the repository.
    folder = tmp_path / "collection"
    folder.mkdir()
    write_collection_file(folder, monkeypatch)
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


def test_popularity_without_a_ranking_says_so_and_builds_from_events(
    catalog_only: None, capsys: pytest.CaptureFixture[str]
) -> None:
    write_event(event("a", datetime(2026, 10, 2, tzinfo=UTC)))
    assert meta_cli.main(["popularity"]) == 0
    assert "no data: online ranking" in capsys.readouterr().err


@pytest.mark.parametrize("main", list(CATALOG_ONLY), ids=lambda m: m.__module__.split(".")[1])
def test_every_read_command_is_classified_by_the_sources_it_reads(main: Main) -> None:
    reads = {a[0] for m, a, _ in COMMANDS + DEGRADED if m is main}
    others = {a[0] for m, a, _, _ in OTHER_SOURCE if m is main}
    assert reads == others | CATALOG_ONLY[main] and not others & CATALOG_ONLY[main]


# ---- store readers on an empty dataset: each gives its documented empty answer or raises NoData naming the source -----------
# One row per public store reader (.claude/rules/store-readers.md). Each gets an empty folder; readers of the dataset and the raw
# caches ignore it and resolve the root conftest's empty folders, as a run would. Readers of tracked files (sets.json,
# restrictions.json, names.json, packages, rates, drift.json, deck_names.json) read the empty folder or a missing path in it,
# because the conftest copies the tracked inputs into its tool data folder.
Reader = Callable[[Path], object]
EMPTY_ANSWERS: list[tuple[str, Reader, object]] = [
    ("cards packages_by_printing", lambda empty: cards_store.packages_by_printing(cards_store.pages_folder()), {}),
    (
        "cards load_source_pages",
        lambda empty: cards_store.load_source_pages(),
        cards_store.LoadedPages(pages=(), issues=()),
    ),
    ("cards load_tracked_sets", lambda empty: cards_store.load_tracked_sets(empty), ()),
    ("cards load_provisional_sets", lambda empty: cards_store.load_provisional_sets(), ()),
    ("cards load_sets", lambda empty: cards_store.load_sets(empty), ()),
    ("cards load_catalog", lambda empty: cards_store.load_catalog(), None),
    ("cards load_price_history", lambda empty: cards_store.load_price_history(), ()),
    ("cards load_prices", lambda empty: cards_store.load_prices(), None),
    ("cards load_printing_price_history", lambda empty: cards_store.load_printing_price_history(), ()),
    ("cards load_printing_prices", lambda empty: cards_store.load_printing_prices(), None),
    ("cards catalog_as_of", lambda empty: cards_store.catalog_as_of(), None),
    ("cards prices_as_of", lambda empty: cards_store.prices_as_of(), None),
    ("cards raw_dump_stamps", lambda empty: cards_store.raw_dump_stamps(), ()),
    ("cards load_restrictions", lambda empty: cards_store.load_restrictions(empty), None),
    ("meta load_events", lambda empty: meta_store.load_events(), ()),
    ("meta stored_event_ids", lambda empty: meta_store.stored_event_ids(Source.EGM), frozenset()),
    ("meta events_as_of", lambda empty: meta_store.events_as_of(), None),
    ("meta load_snapshots", lambda empty: meta_store.load_snapshots(), ()),
    ("meta known_snapshot_times", lambda empty: meta_store.known_snapshot_times(), frozenset()),
    ("meta rankings_as_of", lambda empty: meta_store.rankings_as_of(), None),
    ("meta load_decks_snapshot", lambda empty: meta_store.load_decks_snapshot(), None),
    ("meta decks_as_of", lambda empty: meta_store.decks_as_of(), None),
    ("packages load_packages", lambda empty: packages_store.load_packages(empty), None),
    ("packages load_rates", lambda empty: packages_store.load_rates(empty), None),
    ("packages load_drift", lambda empty: packages_store.load_drift(empty), None),
    ("packages load_name_overrides", lambda empty: packages_store.load_name_overrides(empty / "names.json"), {}),
    ("collection load_deck_names", lambda empty: collection_store.load_deck_names(empty / "deck_names.json"), {}),
]
RAISES_NO_DATA: list[tuple[str, Reader, Kind]] = [
    ("cards load_catalog_or_fail", lambda empty: cards_store.load_catalog_or_fail(), Kind.CATALOG),
    ("cards load_cards_with_prices", lambda empty: cards_store.load_cards_with_prices(), Kind.CATALOG),
    ("cards read_raw_dump", lambda empty: cards_store.read_raw_dump("20261008T200609Z"), Kind.PRICES),
    ("meta load_events_or_fail", lambda empty: meta_store.load_events_or_fail(), Kind.EVENTS),
]


@pytest.mark.parametrize(
    ("reader", "expected"), [(r, e) for _, r, e in EMPTY_ANSWERS], ids=[n for n, _, _ in EMPTY_ANSWERS]
)
def test_a_store_reader_on_an_empty_dataset_gives_its_empty_answer(
    reader: Reader, expected: object, tmp_path: Path
) -> None:
    assert reader(tmp_path) == expected


@pytest.mark.parametrize(
    ("reader", "kind"), [(r, k) for _, r, k in RAISES_NO_DATA], ids=[n for n, _, _ in RAISES_NO_DATA]
)
def test_a_store_reader_on_an_empty_dataset_raises_no_data(reader: Reader, kind: Kind, tmp_path: Path) -> None:
    with pytest.raises(NoData) as raised:
        reader(tmp_path)
    assert raised.value.kind is kind
    assert str(raised.value).startswith(f"no data: {kind.value} (")


def test_reading_a_price_dump_that_is_not_stored_raises_no_data_naming_it(tmp_path: Path) -> None:
    stamp = "20261008T200609Z"
    with pytest.raises(NoData) as raised:
        cards_store.read_raw_dump(stamp)  # the empty raw cache: no tcgcsv folder at all
    assert raised.value.kind is Kind.PRICES and f"saved price dump {stamp}" in str(raised.value)
    (tmp_path / "tcgcsv" / stamp).mkdir(
        parents=True
    )  # a folder without groups.json is not a stored dump (as for raw_dump_stamps)
    with pytest.raises(NoData) as raised:
        cards_store.read_raw_dump(stamp, tmp_path)
    assert raised.value.kind is Kind.PRICES and f"saved price dump {stamp}" in str(raised.value)
