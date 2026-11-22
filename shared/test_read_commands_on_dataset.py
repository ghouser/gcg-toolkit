"""AC-4: with the data in the dataset, the existing read commands produce unchanged output.

A small fixture dataset is built in a temp `GCG_DATA_DIR`, then representative read commands of each tool run against it. EXPECTED is the
output of the same commands from the code before this change (on `main`), run against the same data in the repository's `shared/data/`
(where main kept it), passed through `normalized()`. Do not regenerate it with this branch's code: that would only check the code
against itself. The fixture holds every dataset source, example decks included, so each is read back from `GCG_DATA_DIR`.

The tracked analysis outputs (packages, appearance rates) and the collection are not part of the dataset; here they are absent
(rates) or the small fixture collection file, exactly as in the run on main; `build` saves into a temp folder.

AC-1 (shared-data-contracts), at the end: the commands of these tools listed there, read or write, do not write the catalog export.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import dataset_cli
from shared.basetypes import CardNumber, ProductId
from tools.gundam_cards import cli as cards_cli
from tools.gundam_cards.models import Card, CardRecord, CardsFile, CardPrice, PriceFile, SourceTitlesFile, TraitsFile
from tools.gundam_cards.store import catalog_export_path
from tools.gundam_collection import cli as collection_cli
from tools.gundam_collection import store as collection_store
from tools.gundam_meta import cli as meta_cli
from tools.gundam_meta import duelfrontier
from tools.gundam_meta.models import (
    Deck,
    DeckCard,
    DeckId,
    DecksSnapshotFile,
    Event,
    EventFile,
    EventId,
    EventType,
    ExampleArchetype,
    ExampleDecksSnapshot,
    ExampleList,
    OnlineRankedCard,
    OnlineRankingSnapshot,
    SnapshotFile,
    Source,
)
from tools.gundam_meta.redo import RedoReport
from tools.gundam_meta.store import pretty, snapshot_key
from tools.gundam_packages import cli as packages_cli
from tools.gundam_packages import store as packages_store
from tools.gundam_packages.tests.helpers import pilot, unit

Main = Callable[[Sequence[str] | None], int]

CATALOG_AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PULLED = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
RANKED = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
DECKS_AT = datetime(2026, 10, 11, 7, 30, tzinfo=UTC)


def _cards() -> tuple[Card, ...]:
    return (unit("GD01-001", "Gundam", link="Amuro Ray", cost=3), pilot("GD01-002", "Amuro Ray"), unit("GD01-003", "Zaku II"))


def _prices() -> PriceFile:
    rows = (CardPrice(card_number=CardNumber("GD01-001"), price_cents=125, product_id=ProductId(7), fetched_at=PULLED),
            CardPrice(card_number=CardNumber("GD01-003"), price_cents=10, product_id=ProductId(9), fetched_at=PULLED))  # fmt: skip
    return PriceFile(generated_at=PULLED, source_updated_at=PULLED, data=rows)


def _event(source: Source, event_id: str, day: int, decks: tuple[Deck, ...]) -> Event:
    return Event(
        source=source, id=EventId(event_id), name=f"Regional {event_id}", start_date=date(2026, 10, day), end_date=None, country="US",
        city=None, players=16, rounds=4, event_type=EventType.REGIONAL, type_raw="regional", format_label=None, decks=decks,
        fetched_at=datetime(2026, 10, day + 1, 9, 0, tzinfo=UTC), warnings=(),
    )  # fmt: skip


def _deck(n: int, *cards: tuple[str, int]) -> Deck:
    main = tuple(DeckCard(card_number=CardNumber(c), qty=q) for c, q in cards)
    return Deck(id=DeckId(f"d{n}"), player_name=f"p{n}", placement=n, name=None, available=True, main=main, side=(), unresolved=())


def dataset_tree(root: Path) -> Path:
    """A small dataset in its layout (`gundam_cards/`, `gundam_meta/`): the catalog first recorded at its refresh, one price snapshot,
    two events, one online ranking and one example-deck snapshot."""
    cards, meta = root / "gundam_cards", root / "gundam_meta"
    for folder in (cards / "prices", meta / "online_rankings", meta / "example_decks"):
        folder.mkdir(parents=True)
    records = tuple(CardRecord(number=c.number, first_recorded=CATALOG_AT, no_longer_listed=False) for c in _cards())
    catalog = CardsFile(generated_at=CATALOG_AT, data=_cards(), records=records)
    (cards / "cards.json").write_text(pretty(catalog.model_dump_json()), encoding="utf-8")
    (cards / "traits.json").write_text(TraitsFile(generated_at=CATALOG_AT, data=()).model_dump_json(), encoding="utf-8")
    (cards / "source_titles.json").write_text(SourceTitlesFile(generated_at=CATALOG_AT, data=()).model_dump_json(), encoding="utf-8")
    (cards / "prices" / f"{snapshot_key(PULLED)}.json").write_text(_prices().model_dump_json(indent=1), encoding="utf-8")
    events = (
        _event(Source.EGM, "e1", 3, (_deck(1, ("GD01-001", 4), ("GD01-002", 4)), _deck(2, ("GD01-003", 4), ("GD01-001", 2)))),
        _event(Source.DUELFRONTIER, "f1", 5, (_deck(1, ("GD01-003", 4)),)),
    )
    for e in events:
        path = meta / "events" / e.source.value / f"{e.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pretty(EventFile(data=e).model_dump_json()), encoding="utf-8")
    ranking = OnlineRankingSnapshot(
        generated_at=RANKED, window_start=RANKED - timedelta(days=14), window_end=RANKED, window_days=14, eligible_player_games=200,
        cards_observed=2, stale=False, fetched_at=RANKED,
        cards=(OnlineRankedCard(card_number=CardNumber("GD01-003"), rank=1, games_observed=90, appearance_rate_pct=45.0),
               OnlineRankedCard(card_number=CardNumber("GD01-001"), rank=2, games_observed=20, appearance_rate_pct=10.0)),
    )  # fmt: skip
    (meta / "online_rankings" / f"{snapshot_key(RANKED)}.json").write_text(pretty(SnapshotFile(data=ranking).model_dump_json()), encoding="utf-8")
    (meta / "example_decks" / f"{snapshot_key(DECKS_AT)}.json").write_text(pretty(DecksSnapshotFile(data=example_decks()).model_dump_json()),
                                                                     encoding="utf-8")  # fmt: skip
    return root


def example_decks() -> ExampleDecksSnapshot:
    def lst(n: int, share: float, *cards: tuple[str, int]) -> ExampleList:
        return ExampleList(url=f"https://example.test/list/{n}", cards=tuple(DeckCard(card_number=CardNumber(c), qty=q) for c, q in cards), share=share)

    archetypes = (
        ExampleArchetype(slug="gundam", name="Gundam", games=60, sides_analyzed=10,
                         lists=(lst(1, 0.75, ("GD01-001", 4), ("GD01-002", 4)), lst(2, 0.25, ("GD01-001", 4), ("GD01-003", 2)))),
        ExampleArchetype(slug="zaku", name="Zaku", games=40, sides_analyzed=None, lists=(lst(3, 1.0, ("GD01-003", 4)),)),  # no weights
    )  # fmt: skip
    return ExampleDecksSnapshot(fetched_at=DECKS_AT, window_days=14, season="s1", archetypes=archetypes, slugs_without_archetype=(),
                                unresolved_lists=())  # fmt: skip


def normalized(out: str) -> str:
    """Output with what differs between runs on purpose taken out: the ranking header names its source, and `build` prints the paths it
    wrote (a temp folder here)."""
    out = re.sub(r"^== \S+ online ranking", "== online ranking", out, flags=re.M)
    return re.sub(r" -> \S+, \S+$", " -> <packages>, <rates>", out, flags=re.M)


def write_collection_file(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The small fixture collection, as the UI's file, found through GCG_COLLECTION_FILE."""
    path = folder / "collection.json"
    path.write_text('{"schema_version": 1, "updated_at": "2026-10-01T00:00:00Z", "counts": {"GD01-001": 2, "GD01-002": 1, "GD01-003": 3}}\n', encoding="utf-8")
    monkeypatch.setenv("GCG_COLLECTION_FILE", str(path))


COMMANDS: list[tuple[str, Main, list[str]]] = [
    ("cards", cards_cli.main, ["show", "GD01-002"]),
    ("cards", cards_cli.main, ["search", "--kind", "unit"]),
    ("cards", cards_cli.main, ["price", "GD01-001"]),
    ("meta", meta_cli.main, ["top-cards", "--meta", "msa"]),
    ("meta", meta_cli.main, ["top-cards", "--meta", "major", "--since", "2026-10-01"]),
    ("packages", packages_cli.main, ["pairs", "GD01-001"]),
    ("packages", packages_cli.main, ["build", "--source", "online"]),
    ("collection", collection_cli.main, ["value"]),
]

EXPECTED: dict[str, tuple[int, str]] = {
    'cards show GD01-002': (0, (
        '{\n'
        '  "number": "GD01-002",\n'
        '  "name": "Amuro Ray",\n'
        '  "text_versions": [\n'
        '    {\n'
        '      "text": "",\n'
        '      "printing_ids": [\n'
        '        "GD01-002"\n'
        '      ],\n'
        '      "block": "1",\n'
        '      "as_of": null,\n'
        '      "substantive": false\n'
        '    }\n'
        '  ],\n'
        '  "keywords": [],\n'
        '  "referenced_traits": [],\n'
        '  "printings": [\n'
        '    {\n'
        '      "id": "GD01-002",\n'
        '      "variant": null,\n'
        '      "rarity": "C",\n'
        '      "alt_art_level": 0,\n'
        '      "link_art": false,\n'
        '      "block": "1",\n'
        '      "source_title": null,\n'
        '      "where_to_get": "x",\n'
        '      "set_code": null,\n'
        '      "package_ids": [],\n'
        '      "image_url": null\n'
        '    }\n'
        '  ],\n'
        '  "faq": [],\n'
        '  "unknown_tags": [],\n'
        '  "fetched_at": "2026-01-01T00:00:00Z",\n'
        '  "kind": "pilot",\n'
        '  "color": "blue",\n'
        '  "level": 3,\n'
        '  "cost": 1,\n'
        '  "ap_bonus": 1,\n'
        '  "hp_bonus": 1,\n'
        '  "traits": []\n'
        '}\n'
    )),
    'cards search --kind unit': (0, (
        'GD01-001  unit        Gundam                             blue    Lv3 C3    \n'
        'GD01-003  unit        Zaku II                            blue    Lv3 C2    \n'
    )),
    'cards price GD01-001': (0, (
        'GD01-001 Gundam: $1.25  (TCGPlayer market price, product 7, pulled 2026-10-09 21:00 UTC)\n'
    )),
    'meta top-cards --meta msa': (0, (
        '== online ranking, 2026-09-26 to 2026-10-10, 200 games ==\n'
        '     #  in games  bucket            card      name\n'
        '     1     45.0%  core_meta         GD01-003  Zaku II\n'
        '     2     10.0%  core_meta         GD01-001  Gundam\n'
    )),
    'meta top-cards --meta major --since 2026-10-01': (0, (
        '\n'
        '== all sources combined, de-duplicated, major events, date range (2026-10-01 to today) ==\n'
        '   2 events, 3 decks counted (0 private/unreadable), 18 card copies\n'
        '     #   share copies decks  card      name\n'
        '     1 44.44%      8     2  GD01-003  Zaku II\n'
        '     2 33.33%      6     2  GD01-001  Gundam\n'
        '     3 22.22%      4     1  GD01-002  Amuro Ray\n'
    )),
    'packages pairs GD01-001': (0, (
        "== pilots that make GD01-001 Gundam Link (kind='pilot_name' fragment='Amuro Ray') ==\n"
        '   rate = how often decks that run GD01-001 also run it (no rates built); price = TCGPlayer market\n'
        '\n'
        '   GD01-002  Amuro Ray                          blue    pilot      not seen with it  unpriced\n'
    )),
    'packages build --source online': (0, (
        'online (example decks, 2026-10-11, 14 days): 2 weighted lists as 10000 online decks (each deck is 0.01% of the field) -> <packages>, <rates>\n'
        '0 packages, 0 synergistic package pairs, 0 synergy ties, 3 free-floating cards, 1 archetypes (0 cards too rare to classify)\n'
    )),
    'collection value': (0, (
        '== my collection: 3 cards, 6 copies, worth $2.80 at TCGPlayer market prices (pulled 2026-10-09 21:00 UTC) ==\n'
        '   with the bulk ignored (cards of $0.50 or more, the ones worth selling): $2.50 from 1 cards, 2 copies\n'
        '   bulk (under $0.50 a card): $0.30 from 1 cards, 3 copies; the total above includes it\n'
        "   each printing is valued at its own market price when one is stored, else at the card's (the cheapest regular printing's), so an alt art with no price of its own is valued as the base card\n"
        '\n'
        '== $10 or more: 0 cards, 0 copies, worth $0.00 ==\n'
        '   none\n'
        '\n'
        '== $5 to under $10: 0 cards, 0 copies, worth $0.00 ==\n'
        '   none\n'
        '\n'
        '== $1 to under $5: 1 card, 2 copies, worth $2.50 ==\n'
        '   card                                                 copies      each      worth\n'
        '   Gundam (GD01-001)                                         2     $1.25      $2.50\n'
        '\n'
        '== $0.50 to under $1: 0 cards, 0 copies, worth $0.00 ==\n'
        '   none\n'
        '\n'
        '== under $0.50: 1 card, 3 copies, worth $0.30 (not listed; use --bulk to list) ==\n'
        '\n'
        '   1 owned cards have no price (resources, EX cards or tokens: not sold as singles): GD01-002 Amuro Ray\n'
    )),
}  # fmt: skip


@pytest.fixture
def dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ds = dataset_tree(tmp_path / "ds")
    monkeypatch.setenv("GCG_DATA_DIR", str(ds))
    # What is not in the dataset is pinned to what the run on main saw: no saved price dumps, no rates built, the fixture collection.
    monkeypatch.setattr(cards_cli, "raw_dump_stamps", lambda *a, **k: ())
    monkeypatch.setattr(packages_cli, "load_rates", lambda *a, **k: None)
    folder = tmp_path / "collection"
    folder.mkdir()
    write_collection_file(folder, monkeypatch)
    # `build` saves its packages and rates; here into a temp folder instead of the repository.
    out = tmp_path / "packages_out"
    monkeypatch.setattr(packages_cli, "write_packages", lambda file: packages_store.write_packages(file, out))
    monkeypatch.setattr(packages_cli, "write_rates", lambda file: packages_store.write_rates(file, out))
    return ds


@pytest.mark.parametrize(("tool", "main", "argv"), COMMANDS, ids=[f"{t} {' '.join(a)}" for t, _, a in COMMANDS])
def test_a_read_command_on_the_dataset_gives_the_same_output_as_before(
    dataset: Path, tool: str, main: Main, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(argv)
    assert (code, normalized(capsys.readouterr().out)) == EXPECTED[f"{tool} {' '.join(argv)}"]


# ---- AC-1: no command but `gundam_cards export` writes the catalog export -----------------------------------------------------------
# The other tools' commands, read and write, run on the fixture dataset and leaves $GCG_CATALOG_FILE absent (the gundam_cards
# commands are covered in tools/gundam_cards/tests/test_export.py). Nothing touches the network, the raw response caches or the tracked
# files: fetches are replaced by fakes and every write outside the dataset goes to a temp folder. The command bodies run for real.
COLLECTION_LINES = "GD01-001 2\nGD01-002 1\nGD01-003 3\n"


class Offline:
    """Stands in for the network fetcher; the steps that would use it are replaced in the sandbox."""

    network_requests = 0

    def __init__(self, *_: object, **__: object) -> None:
        pass


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The fixture dataset, plus one gd05 event so a tournament build has an era to read; the packages and collection folders redirected
    to temp folders (the raw and popularity folders are in the root conftest's temp tool data folder); the tournament and online packages built (by the commands under test)."""
    ds = dataset_tree(tmp_path / "ds")
    monkeypatch.setenv("GCG_DATA_DIR", str(ds))
    gd05 = _event(Source.EGM, "e0", 3, (_deck(1, ("GD01-001", 4), ("GD01-002", 4)),)).model_copy(update={"start_date": date(2026, 8, 3)})
    path = ds / "gundam_meta" / "events" / gd05.source.value / f"{gd05.id}.json"
    path.write_text(pretty(EventFile(data=gd05).model_dump_json()), encoding="utf-8")
    monkeypatch.setattr(cards_cli, "raw_dump_stamps", lambda *a, **k: ())
    # A newer example-deck snapshot in which Gundam and its pilot are always played together, so the online build finds a package
    # (and the deck and package commands below have one to name).
    together = ExampleList(url="https://example.test/list/9", share=1.0,
                           cards=(DeckCard(card_number=CardNumber("GD01-001"), qty=4), DeckCard(card_number=CardNumber("GD01-002"), qty=4)))
    archetypes = (ExampleArchetype(slug="gundam", name="Gundam", games=60, sides_analyzed=10, lists=(together,)),
                  example_decks().archetypes[1].model_copy(update={"sides_analyzed": 10}))
    newer = example_decks().model_copy(update={"fetched_at": DECKS_AT + timedelta(days=1), "archetypes": archetypes})
    (ds / "gundam_meta" / "example_decks" / f"{snapshot_key(newer.fetched_at)}.json").write_text(
        pretty(DecksSnapshotFile(data=newer).model_dump_json()), encoding="utf-8")

    packages, coll = tmp_path / "packages", tmp_path / "collection"
    for folder in (packages, coll):
        folder.mkdir()
    for name in ("write_packages", "write_rates", "write_drift"):
        monkeypatch.setattr(packages_cli, name, partial(getattr(packages_store, name), out_dir=packages))
    for cli in (packages_cli, collection_cli):
        monkeypatch.setattr(cli, "load_packages", partial(packages_store.load_packages, packages))
        monkeypatch.setattr(cli, "load_rates", partial(packages_store.load_rates, packages))
    monkeypatch.setattr(packages_cli, "OUT_DIR", packages)

    (coll / "my_tcg_collection").write_text(COLLECTION_LINES, encoding="utf-8")
    monkeypatch.setattr(collection_cli, "OUT_DIR", coll)
    monkeypatch.setattr(collection_cli, "COLLECTION_PATH", coll / "my_tcg_collection")
    write_collection_file(coll, monkeypatch)
    monkeypatch.setattr(collection_cli, "load_deck_names", partial(collection_store.load_deck_names, coll / "deck_names.json"))
    monkeypatch.setattr(collection_cli, "save_deck_names", partial(collection_store.save_deck_names, path=coll / "deck_names.json"))

    monkeypatch.setattr(meta_cli, "Fetcher", Offline)
    monkeypatch.setattr(meta_cli, "egm", SimpleNamespace(fetch_tournaments=lambda _: ("[]", SimpleNamespace(fetched_at=PULLED, events=[], skipped=[]))))
    synced = duelfrontier.SyncResult(events=(), listed=0, already_stored=0, not_complete_yet=0, waiting_for_results=0, failures=())
    monkeypatch.setattr(meta_cli, "duelfrontier", SimpleNamespace(list_events=lambda _: (), sync_events=lambda *_, **__: synced))
    refetched = RedoReport(changed=("egm:e1",), unchanged=(), failures=())
    monkeypatch.setattr(meta_cli, "refetch_egm", lambda *_: refetched)
    monkeypatch.setattr(meta_cli, "refetch_duelfrontier", lambda *_, **__: refetched)

    assert packages_cli.main(["build"]) == 0
    assert packages_cli.main(["build", "--source", "online"]) == 0
    return tmp_path


OTHER_COMMANDS: list[tuple[Main, list[str], int]] = [
    (dataset_cli.main, ["status"], 0),
    (meta_cli.main, ["sync"], 0),
    (meta_cli.main, ["popularity"], 0),
    (meta_cli.main, ["eras"], 0),
    (meta_cli.main, ["reparse"], 1),  # runs to the end: the temp raw folder has no saved response for the fixture events, so it reports them failed
    (meta_cli.main, ["refetch", "--source", "egm", "--all"], 0),
    (meta_cli.main, ["refetch", "--source", "duelfrontier", "--all"], 0),
    (meta_cli.main, ["duplicates"], 0),
    (meta_cli.main, ["top-cards", "--meta", "major"], 0),
    (meta_cli.main, ["top-cards", "--meta", "msa"], 0),
    (packages_cli.main, ["build"], 0),
    (packages_cli.main, ["build", "--source", "online"], 0),
    (packages_cli.main, ["packages"], 0),
    (packages_cli.main, ["archetypes"], 0),
    (packages_cli.main, ["synergy"], 0),
    (packages_cli.main, ["package-synergy"], 0),
    (packages_cli.main, ["free"], 0),
    (packages_cli.main, ["squads"], 0),
    (packages_cli.main, ["package", "amuro", "--source", "online"], 0),
    (packages_cli.main, ["compare"], 0),
    (packages_cli.main, ["card", "GD01-001"], 0),
    (packages_cli.main, ["pairs", "GD01-001"], 0),
    (packages_cli.main, ["drift"], 0),
    (packages_cli.main, ["report"], 0),
    (collection_cli.main, ["check"], 0),
    (collection_cli.main, ["template", "GD01"], 0),
    (collection_cli.main, ["import"], 0),
    (collection_cli.main, ["coverage"], 0),
    (collection_cli.main, ["card", "GD01-001"], 0),
    (collection_cli.main, ["decks", "--all"], 0),
    (collection_cli.main, ["styles", "--min-rate", "0"], 0),
    (collection_cli.main, ["suggest", "amuro"], 0),
    (collection_cli.main, ["archetypes", "--min-share", "0"], 0),
    (collection_cli.main, ["buy", "amuro", "--min-rate", "0", "--export"], 0),
    (collection_cli.main, ["nickname", "amuro", "mine"], 0),
    (collection_cli.main, ["deck", "amuro"], 0),
    (collection_cli.main, ["value"], 0),
]


TOOL: dict[Main, str] = {dataset_cli.main: "dataset", meta_cli.main: "meta", packages_cli.main: "packages", collection_cli.main: "collection"}


@pytest.mark.parametrize(("main", "argv", "code"), OTHER_COMMANDS, ids=[f"{TOOL[m]} {' '.join(a)}" for m, a, _ in OTHER_COMMANDS])
def test_no_command_of_the_other_tools_writes_the_catalog_export(sandbox: Path, main: Main, argv: list[str], code: int) -> None:
    assert main(argv) == code
    assert not catalog_export_path().exists()

