"""The catalog export (`gundam_cards export`), run end to end on a small catalog in the temp dataset. The root conftest points
GCG_CATALOG_FILE at a temp file for every test. Expected values are worked out by hand from the cards below."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from shared.basetypes import CardNumber, PackageId, PrintingId, ProductId, SetCode
from tools.gundam_cards import cli
from tools.gundam_cards.export import CatalogExport
from tools.gundam_cards.models import (
    BaseTokenCard,
    CardPrice,
    CardRecord,
    CardSet,
    CardKind,
    CardsFile,
    Color,
    ExBaseCard,
    ExResourceCard,
    PriceFile,
    Printing,
    Rarity,
    ResourceCard,
    Restrictions,
    SetKind,
    TextVersion,
    UnitTokenCard,
)
from tools.gundam_cards.printings import RefetchReport, SyncReport
from tools.gundam_cards.sets import SetsBuild
from tools.gundam_cards.store import (
    CATALOG_FILE_VAR,
    LoadedPages,
    catalog_export_path,
    save_catalog,
    write_prices,
    write_provisional_sets,
)
from tools.gundam_cards.tcgcsv import RawDump, stamp_of
from tools.gundam_packages.tests.helpers import base, command, pilot, unit

REPO_DOCS = Path(__file__).resolve().parents[3] / "docs"
CATALOG_AT = datetime(2026, 11, 1, tzinfo=UTC)


def printing(pid: str, set_code: str | None, *, rarity: Rarity = Rarity.R, alt: int = 0, link: bool = False,
             image: str | None = None) -> Printing:  # fmt: skip
    printing_id = PrintingId(pid)
    return Printing(id=printing_id, variant=printing_id.variant, rarity=rarity, alt_art_level=alt, link_art=link, block=None,
                    source_title=None, where_to_get="x", set_code=SetCode(set_code) if set_code else None, package_ids=(),
                    image_url=image)  # fmt: skip


GUNDAM = unit("GD01-001", "Gundam", level=4, cost=3).model_copy(update={"printings": (
    printing("GD01-001", "GD01", image="https://img/GD01-001.webp"),
    printing("GD01-001_p1", "GD01", alt=1, image="https://img/GD01-001_p1.webp"),
    printing("GD01-001_p2", "GD01", alt=1, link=True),
    printing("GD01-001_p3", "ST01"),
)})  # fmt: skip
AMURO = pilot("ST01-010", "Amuro Ray").model_copy(update={"printings": (printing("ST01-010", "ST01"), printing("ST01-010_p1", "ST01"))})
RESOURCE = ResourceCard(
    number=CardNumber("R-001"), name="Resource",
    text_versions=(TextVersion(text="", printing_ids=(PrintingId("R-001_p4"),), block=None, as_of=None, substantive=False),),
    keywords=frozenset(), referenced_traits=frozenset(), printings=(printing("R-001_p4", None, rarity=Rarity.C, alt=1),),
    faq=(), unknown_tags=(), fetched_at=CATALOG_AT,
)  # fmt: skip
CARDS = (RESOURCE, GUNDAM, AMURO)  # stored order: by number

GD01 = CardSet(code=SetCode("GD01"), name="Newtype Rising", kind=SetKind.BOOSTER, bandai_package_id=PackageId("616001"),
               release_date=date(2025, 7, 25), product_category_raw=None, product_url=None)  # fmt: skip
ST01 = CardSet(code=SetCode("ST01"), name="Heroic Beginnings", kind=SetKind.STARTER, bandai_package_id=None, release_date=None,
               product_category_raw=None, product_url=None)  # fmt: skip


def bandai(code: str, name: str) -> CardSet:
    return CardSet(code=SetCode(code), name=name, kind=SetKind.BOOSTER, bandai_package_id=PackageId("616901"),
                   release_date=date(2027, 1, 1), product_category_raw=None, product_url=None)  # fmt: skip


def price(number: str, set_code: str, cents: int, at: datetime) -> CardPrice:
    return CardPrice(card_number=CardNumber(number), price_cents=cents, product_id=ProductId(1), set_code=set_code, fetched_at=at)


def store(cards: tuple[Any, ...] = CARDS, *, unlisted: tuple[str, ...] = ("ST01-010",)) -> None:
    records = tuple(CardRecord(number=c.number, first_recorded=CATALOG_AT, no_longer_listed=str(c.number) in unlisted) for c in cards)
    save_catalog(CardsFile(generated_at=CATALOG_AT, data=cards, records=records))


@pytest.fixture
def tracked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reviewed sets.json, as a small fixture (the repository's own file is never read here)."""
    monkeypatch.setattr(cli, "load_tracked_sets", lambda *a, **k: (GD01, ST01))


def export() -> dict[str, Any]:
    assert cli.main(["export"]) == 0
    result: dict[str, Any] = json.loads(catalog_export_path().read_text(encoding="utf-8"))
    return result


def cards_by_number(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["number"]: c for c in data["cards"]}


def printings_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for c in data["cards"] for p in c["printings"]}


def values(node: object) -> list[object]:
    """Every value in a JSON tree, nested ones included."""
    if isinstance(node, dict):
        return [v for child in node.values() for v in [child, *values(child)]]
    if isinstance(node, list):
        return [v for child in node for v in [child, *values(child)]]
    return []


def keys(node: object) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for child in node.values() for k in keys(child)}
    if isinstance(node, list):
        return {k for child in node for k in keys(child)}
    return set()


# ---- AC-1 --------------------------------------------------------------------------------------------------------------------
def test_export_writes_every_card_with_its_printings_to_the_configured_file(tracked: None, tmp_path: Path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    target = tmp_path / "out" / "my-catalog.json"
    monkeypatch.setenv(CATALOG_FILE_VAR, str(target))
    store()
    assert cli.main(["export"]) == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert datetime.fromisoformat(data["generated_at"]).tzinfo is not None
    assert set(data["reference"]) == {"sets", "kinds", "colors", "rarities"}
    assert [c["number"] for c in data["cards"]] == ["R-001", "GD01-001", "ST01-010"]
    assert [(c["name"], c["kind"]) for c in data["cards"]] == [("Resource", "resource"), ("Gundam", "unit"), ("Amuro Ray", "pilot")]
    assert [[(p["id"], p["rarity"]) for p in c["printings"]] for c in data["cards"]] == [
        [("R-001_p4", "C")],
        [("GD01-001", "R"), ("GD01-001_p1", "R"), ("GD01-001_p2", "R"), ("GD01-001_p3", "R")],
        [("ST01-010", "R"), ("ST01-010_p1", "R")],
    ]


def test_a_card_no_longer_listed_is_exported_and_flagged_and_only_it_carries_the_flag(tracked: None) -> None:
    store()
    cards = cards_by_number(export())
    assert len(cards) == len(CARDS)
    assert cards["ST01-010"]["no_longer_listed"] is True
    assert "no_longer_listed" not in cards["GD01-001"] and "no_longer_listed" not in cards["R-001"]


def test_without_the_variable_the_export_goes_to_dot_gcg_catalog_json_in_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(CATALOG_FILE_VAR)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert catalog_export_path() == tmp_path / ".gcg" / "catalog.json"


def test_a_failed_write_leaves_the_earlier_export_intact_and_no_temp_file(tracked: None, monkeypatch: pytest.MonkeyPatch) -> None:
    store()
    export()
    path = catalog_export_path()
    before = path.read_bytes()

    def fail(*_: object) -> None:
        raise OSError("disk full")

    store(unlisted=())
    monkeypatch.setattr("tools.gundam_cards.store.os.replace", fail)
    with pytest.raises(OSError):
        cli.main(["export"])
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_a_second_export_replaces_the_first_with_the_new_content(tracked: None) -> None:
    store()
    assert cards_by_number(export())["ST01-010"]["no_longer_listed"] is True
    store(unlisted=())
    assert "no_longer_listed" not in cards_by_number(export())["ST01-010"]
    assert [p.name for p in catalog_export_path().parent.iterdir()] == [catalog_export_path().name]


TCGCSV_AT = datetime(2026, 11, 4, 20, tzinfo=UTC)


def tcgcsv_dump() -> RawDump:
    """One GD01 product for GD01-001, priced."""
    def results(rows: list[dict[str, object]]) -> str:
        return json.dumps({"totalItems": len(rows), "success": True, "errors": [], "results": rows})

    product = {"productId": 10, "name": "Gundam", "groupId": 1,
               "extendedData": [{"name": "Number", "value": "GD01-001"}, {"name": "Rarity", "value": "Rare"}]}  # fmt: skip
    return RawDump(TCGCSV_AT, results([{"groupId": 1, "name": "Newtype Rising", "abbreviation": "GD01"}]), {1: results([product])},
                   {1: results([{"productId": 10, "marketPrice": 1.5, "lowPrice": 1.5, "subTypeName": "Normal"}])})  # fmt: skip


class Offline:
    """Stands in for every network fetcher: each page is empty, and the steps that would read it are replaced below."""

    network_requests = 0

    def __init__(self, *_: object, **__: object) -> None:
        pass

    def get_text(self, *_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(text="")


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every other command runs to the end with no network, no raw page cache and no write to the tracked sets or restrictions files
    (those writes are replaced; the dataset writes go to the temp dataset)."""
    restrictions = Restrictions(banned=(), limited=(), banned_pairs=(), vanilla_description="vanilla", vanilla_group=())
    fakes: dict[str, object] = {
        "Fetcher": Offline,
        "sync_sets": lambda *_: SetsBuild((GD01, ST01)),
        "read_packages": lambda *_: ("one package",), "load_source_pages": lambda *_: LoadedPages((), ()),
        "sync_printings": lambda *_, **__: SyncReport(packages=1, listed=1, already_cached=1, fetched=0, failures=()),
        "select_printings": lambda *_, **__: (PrintingId("GD01-001"),),
        "refetch_printings": lambda *_, **__: RefetchReport(changed=(PrintingId("GD01-001"),), unchanged=(), failures=()),
        "parse_restrictions": lambda *_: (restrictions, date(2026, 11, 1)), "write_restrictions": lambda *_: tmp_path / "r.json",
        "fetch_updated": lambda *_: TCGCSV_AT, "fetch_dump": lambda *_, **__: tcgcsv_dump(),
        "raw_dump_stamps": lambda *_: (stamp_of(TCGCSV_AT),), "read_raw_dump": lambda *_: tcgcsv_dump(),
    }  # fmt: skip
    for name, fake in fakes.items():
        monkeypatch.setattr(cli, name, fake)


@pytest.mark.parametrize("argv", [
    ["sync"], ["reparse"], ["refetch", "--card", "GD01-001"], ["sync-tcgplayer"], ["reparse-tcgplayer"], ["sync-restrictions"],
    ["sets"], ["search"], ["show", "GD01-001"], ["changes"], ["price", "GD01-001"], ["restrictions"],
], ids=" ".join)  # fmt: skip
def test_no_other_command_writes_the_export(offline: None, argv: list[str]) -> None:
    store()
    write_prices(PriceFile(generated_at=CATALOG_AT, source_updated_at=CATALOG_AT, data=(price("GD01-001", "GD01", 150, CATALOG_AT),)))
    assert cli.main(argv) == 0
    assert not catalog_export_path().exists()


# ---- AC-2 --------------------------------------------------------------------------------------------------------------------
def test_the_export_holds_no_null_and_no_card_text_stats_or_price_on_the_card(tracked: None) -> None:
    store()
    write_prices(PriceFile(generated_at=CATALOG_AT, source_updated_at=CATALOG_AT, data=(price("GD01-001", "GD01", 150, CATALOG_AT),)))
    data = export()
    assert None not in values(data)
    excluded = {"text", "text_versions", "ap", "hp", "traits", "keywords", "referenced_traits", "faq", "zones", "link", "pilot"}
    assert not keys(data) & excluded
    assert all("price_cents" not in c and "price_as_of" not in c for c in data["cards"])


def test_color_level_and_cost_appear_only_on_deck_kinds(tracked: None) -> None:
    store()
    cards = cards_by_number(export())
    assert (cards["GD01-001"]["color"], cards["GD01-001"]["level"], cards["GD01-001"]["cost"]) == ("blue", 4, 3)
    assert (cards["ST01-010"]["color"], cards["ST01-010"]["level"], cards["ST01-010"]["cost"]) == ("blue", 3, 1)
    assert not {"color", "level", "cost"} & set(cards["R-001"])


def common(number: str) -> dict[str, Any]:
    """The fields every card kind has, with one base printing and no set code."""
    return {"number": CardNumber(number), "name": number, "keywords": frozenset(), "referenced_traits": frozenset(), "faq": (),
            "text_versions": (TextVersion(text="", printing_ids=(PrintingId(number),), block=None, as_of=None, substantive=False),),
            "printings": (printing(number, None),), "unknown_tags": (), "fetched_at": CATALOG_AT}  # fmt: skip


@pytest.mark.parametrize(("card", "stats"), [
    (unit("GD01-002", "Unit", color=Color.GREEN, level=5, cost=4), ("green", 5, 4)),
    (pilot("GD01-003", "Pilot", color=Color.RED), ("red", 3, 1)),
    (command("GD01-004", "Command", color=Color.WHITE, level=2, cost=3), ("white", 2, 3)),
    (base("GD01-005", "Base", color=Color.PURPLE, level=4, cost=2), ("purple", 4, 2)),
    (ExBaseCard(**common("EXB-001"), hp=2), None),
    (ResourceCard(**common("R-002")), None),
    (ExResourceCard(**common("EXR-001")), None),
    (UnitTokenCard(**common("T-001"), ap=1, hp=1, traits=()), None),
    (BaseTokenCard(**common("T-037"), level=None, cost=None, hp=5, zones=frozenset(), traits=()), None),
    (BaseTokenCard(**common("T-038"), level=2, cost=1, hp=3, zones=frozenset(), traits=()), None),  # shown, still not exported
], ids=[*(k.value for k in CardKind), "base_token showing level and cost"])  # fmt: skip
def test_every_kind_has_color_level_and_cost_exactly_when_it_goes_into_a_deck(tracked: None, card: Any,
                                                                               stats: tuple[str, int, int] | None) -> None:  # fmt: skip
    store((card,), unlisted=())
    exported = export()["cards"][0]
    if stats is None:
        assert not {"color", "level", "cost"} & set(exported)
    else:
        assert (exported["color"], exported["level"], exported["cost"]) == stats


def test_the_card_set_code_is_its_first_printings_and_absent_when_that_has_none(tracked: None) -> None:
    store()
    cards = cards_by_number(export())
    assert cards["GD01-001"]["set_code"] == "GD01"
    assert cards["ST01-010"]["set_code"] == "ST01"
    assert "set_code" not in cards["R-001"]


def test_each_printing_carries_only_what_applies_to_it(tracked: None) -> None:
    store()
    printings = printings_by_id(export())
    assert printings["GD01-001"] == {"id": "GD01-001", "rarity": "R", "set_code": "GD01", "image_url": "https://img/GD01-001.webp"}
    assert printings["GD01-001_p1"] == {"id": "GD01-001_p1", "rarity": "R", "set_code": "GD01", "variant": 1, "alt_art_level": 1,
                                        "link_art": False, "image_url": "https://img/GD01-001_p1.webp"}  # fmt: skip
    assert printings["GD01-001_p2"] == {"id": "GD01-001_p2", "rarity": "R", "set_code": "GD01", "variant": 2, "alt_art_level": 1,
                                        "link_art": True}  # fmt: skip
    assert printings["GD01-001_p3"] == {"id": "GD01-001_p3", "rarity": "R", "set_code": "ST01", "variant": 3, "alt_art_level": 0,
                                        "link_art": False}  # fmt: skip
    assert printings["R-001_p4"] == {"id": "R-001_p4", "rarity": "C", "variant": 4, "alt_art_level": 1, "link_art": False}


def test_a_printing_carries_its_latest_price_in_cents_with_its_as_of_date(tracked: None) -> None:
    store()
    day1, day2 = datetime(2026, 11, 2, 18, tzinfo=UTC), datetime(2026, 11, 3, 23, 30, tzinfo=UTC)
    write_prices(PriceFile(generated_at=day1, source_updated_at=day1, data=(
        price("GD01-001", "GD01", 150, day1), price("GD01-001", "ST01", 999, day1), price("ST01-010", "ST01", 40, day1),
    )))  # fmt: skip
    write_prices(PriceFile(generated_at=day2, source_updated_at=day2, data=(price("GD01-001", "GD01", 175, day2),)))
    printings = printings_by_id(export())
    # GD01: the newest snapshot wins. ST01: only the older snapshot has it, and its one non-alt ST01 printing is the reprint.
    assert (printings["GD01-001"]["price_cents"], printings["GD01-001"]["price_as_of"]) == (175, "2026-11-03")
    assert (printings["GD01-001_p3"]["price_cents"], printings["GD01-001_p3"]["price_as_of"]) == (999, "2026-11-02")
    # Alt arts are never the priced product; Amuro has two non-alt ST01 printings, so its price matches no single printing.
    unpriced = ["GD01-001_p1", "GD01-001_p2", "ST01-010", "ST01-010_p1", "R-001_p4"]
    assert all("price_cents" not in printings[p] and "price_as_of" not in printings[p] for p in unpriced)


def test_a_price_whose_set_matches_no_single_non_alt_printing_prices_none(tracked: None) -> None:
    zaku = unit("GD01-002", "Zaku").model_copy(update={"printings": (printing("GD01-002", "GD01"), printing("GD01-002_p1", "ST01", alt=1))})
    store((zaku, GUNDAM), unlisted=())
    write_prices(PriceFile(generated_at=CATALOG_AT, source_updated_at=CATALOG_AT, data=(
        price("GD01-001", "GD01_b", 300, CATALOG_AT),  # a set no printing has
        price("GD01-002", "ST01", 80, CATALOG_AT),  # only an alt art in that set
    )))  # fmt: skip
    assert not {"price_cents", "price_as_of"} & keys(export())


def test_without_prices_the_export_is_written_and_says_prices_are_missing(tracked: None, capsys: pytest.CaptureFixture[str]) -> None:
    store()
    data = export()
    assert "no data: prices" in capsys.readouterr().err
    assert not {"price_cents", "price_as_of"} & keys(data)


# ---- AC-3 --------------------------------------------------------------------------------------------------------------------
def test_the_reference_section_comes_from_the_sets_and_the_vocabularies(tracked: None) -> None:
    store()
    write_provisional_sets((bandai("PB03", "1st Anniversary Set"), bandai("GD01", "Bandai's GD01")), CATALOG_AT)
    reference = export()["reference"]
    assert reference["sets"] == [
        {"code": "GD01", "name": "Newtype Rising", "kind": "booster", "release_date": "2025-07-25"},
        {"code": "PB03", "name": "1st Anniversary Set", "kind": "booster", "release_date": "2027-01-01", "provisional": True},
        {"code": "ST01", "name": "Heroic Beginnings", "kind": "starter"},
    ]
    deck = {"unit", "pilot", "command", "base"}
    others = {"ex_base", "resource", "ex_resource", "unit_token", "base_token"}
    assert {k["kind"]: k["deck"] for k in reference["kinds"]} == {**dict.fromkeys(deck, True), **dict.fromkeys(others, False)}
    assert reference["colors"] == ["blue", "green", "white", "red", "purple"]
    assert reference["rarities"] == ["C", "U", "R", "LR", "P"]


def test_a_set_code_missing_from_the_reference_fails_naming_it_and_writes_nothing(tracked: None, capsys: pytest.CaptureFixture[str]) -> None:
    store()
    export()
    path = catalog_export_path()
    before = path.read_bytes()
    anniversary = GUNDAM.model_copy(update={"printings": (*GUNDAM.printings, printing("GD01-001_p4", "PB03", alt=1))})
    store((RESOURCE, anniversary, AMURO))
    assert cli.main(["export"]) == 1
    assert "PB03" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_a_printing_in_a_set_known_only_as_provisional_is_exported(tracked: None) -> None:
    anniversary = GUNDAM.model_copy(update={"printings": (*GUNDAM.printings, printing("GD01-001_p4", "PB03", alt=1))})
    store((anniversary,), unlisted=())
    write_provisional_sets((bandai("PB03", "1st Anniversary Set"),), CATALOG_AT)
    assert printings_by_id(export())["GD01-001_p4"]["set_code"] == "PB03"


def test_every_missing_set_code_is_named(tracked: None, capsys: pytest.CaptureFixture[str]) -> None:
    store((GUNDAM.model_copy(update={"printings": (printing("GD01-001", "EB01"), printing("GD01-001_p1", "PB03", alt=1))}),), unlisted=())
    assert cli.main(["export"]) == 1
    err = capsys.readouterr().err
    assert "EB01" in err and "PB03" in err
    assert not catalog_export_path().exists()


def test_a_failed_first_export_leaves_no_file(tracked: None) -> None:
    store((GUNDAM.model_copy(update={"printings": (printing("GD01-001", "EB01"),)}),), unlisted=())
    assert cli.main(["export"]) == 1
    assert not catalog_export_path().exists()


# ---- AC-4: the documented example ---------------------------------------------------------------------------------------------
def test_the_documented_example_export_is_a_valid_export_with_no_null() -> None:
    text = (REPO_DOCS / "catalog-export.example.json").read_text(encoding="utf-8")
    assert CatalogExport.model_validate_json(text).schema_version == 1
    assert None not in values(json.loads(text))
