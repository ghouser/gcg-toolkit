"""AC-4: with data from the old in-repository layout migrated into the dataset, the existing read commands produce unchanged output.

A small fixture in the old layout (`shared/data/...`) is migrated into a temp dataset, then representative read commands of each tool run
against it. EXPECTED is the output of the same commands from the code before this change (on `main`), run against the same fixture in
the old layout: a copy of main's `tools/` and `shared/` code with `legacy_tree()` written as its `shared/data`, its output passed through
`normalized()`. Regenerate it the same way if the fixture changes. The fixture holds every dataset source, example decks included, so
each is read back from `GCG_DATA_DIR`.

The tracked analysis outputs (packages, appearance rates) and the hand-typed collection are not part of the dataset; here they are absent
(rates) or the small fixture collection, exactly as in the run on main; `build` saves into a temp folder.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, ProductId
from shared.dataset_cli import migrate_legacy
from tools.gundam_cards import cli as cards_cli
from tools.gundam_cards.models import CardPrice, PriceFile, SourceTitlesFile, TraitsFile
from tools.gundam_collection import cli as collection_cli
from tools.gundam_collection.models import Art, CollectionFile, OwnedCard, OwnedPrinting
from tools.gundam_meta import cli as meta_cli
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
from tools.gundam_meta.store import pretty, snapshot_key
from tools.gundam_packages import cli as packages_cli
from tools.gundam_packages import store as packages_store
from tools.gundam_packages.tests.helpers import pilot, unit

Main = Callable[[Sequence[str] | None], int]

CATALOG_AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PULLED = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
RANKED = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
DECKS_AT = datetime(2026, 10, 11, 7, 30, tzinfo=UTC)


def _cards() -> list[dict[str, object]]:
    cards = (unit("GD01-001", "Gundam", link="Amuro Ray", cost=3), pilot("GD01-002", "Amuro Ray"), unit("GD01-003", "Zaku II"))
    return [json.loads(c.model_dump_json()) for c in cards]


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


def legacy_tree(root: Path) -> Path:
    """A small repository in the old layout: the source data under shared/data/, and a collection."""
    cards, meta, coll = (root / "shared" / "data" / name for name in ("gundam_cards", "gundam_meta", "gundam_collection"))
    for folder in (cards, meta / "online_rankings", meta / "example_decks", coll):
        folder.mkdir(parents=True)
    old_catalog = {"schema_version": 1, "generated_at": "2026-10-08T12:00:00Z", "data": _cards()}
    (cards / "cards.json").write_text(json.dumps(old_catalog, indent=1) + "\n", encoding="utf-8")
    (cards / "traits.json").write_text(TraitsFile(generated_at=CATALOG_AT, data=()).model_dump_json(), encoding="utf-8")
    (cards / "source_titles.json").write_text(SourceTitlesFile(generated_at=CATALOG_AT, data=()).model_dump_json(), encoding="utf-8")
    (cards / "prices.json").write_text(_prices().model_dump_json(indent=1), encoding="utf-8")
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
    (coll / "collection.json").write_text(pretty(collection().model_dump_json()), encoding="utf-8")
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


def collection() -> CollectionFile:
    owned = ((CardNumber("GD01-001"), 2), (CardNumber("GD01-002"), 1), (CardNumber("GD01-003"), 3))
    return CollectionFile(generated_at=CATALOG_AT, source_file="my_tcg_collection",
                          data=tuple(OwnedCard(card_number=n, copies=c, printings=(OwnedPrinting(art=Art.BASE, copies=c),)) for n, c in owned))  # fmt: skip


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
        "   each card is valued at the cheapest regular printing's market price, so an alt art or a pricier printing is valued as the base card\n"
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
def migrated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ds = tmp_path / "ds"
    report = migrate_legacy(legacy_tree(tmp_path / "repo"), ds)
    assert report.conflicts == ()
    monkeypatch.setenv("GCG_DATA_DIR", str(ds))
    # What is not in the dataset is pinned to what the run on main saw: no saved price dumps, no rates built, the fixture collection.
    monkeypatch.setattr(cards_cli, "raw_dump_stamps", lambda *a, **k: ())
    monkeypatch.setattr(packages_cli, "load_rates", lambda *a, **k: None)
    monkeypatch.setattr(collection_cli, "_refresh_collection", lambda cards: None)
    monkeypatch.setattr(collection_cli, "load_collection", lambda *a, **k: collection())
    # `build` saves its packages and rates; here into a temp folder instead of the repository.
    out = tmp_path / "packages_out"
    monkeypatch.setattr(packages_cli, "write_packages", lambda file: packages_store.write_packages(file, out))
    monkeypatch.setattr(packages_cli, "write_rates", lambda file: packages_store.write_rates(file, out))
    return ds


@pytest.mark.parametrize(("tool", "main", "argv"), COMMANDS, ids=[f"{t} {' '.join(a)}" for t, _, a in COMMANDS])
def test_a_read_command_on_the_migrated_dataset_gives_the_same_output_as_before(
    migrated: Path, tool: str, main: Main, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(argv)
    assert (code, normalized(capsys.readouterr().out)) == EXPECTED[f"{tool} {' '.join(argv)}"]
