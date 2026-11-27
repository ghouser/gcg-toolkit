"""refresh-prices: tcgcsv products matched to printings by set, card number and art tier, checked, and added as one per-printing snapshot.

The tcgcsv site is faked at the fetcher; the catalog, the sets and the dataset are small fixtures in the root conftest's temp folders. Expected
values are worked out by hand from the dump below; nothing touches the network, the real dataset or `~/.gcg`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from shared.basetypes import CardNumber, PackageId, PrintingId, ProductId, SetCode
from shared.dataset import NoData
from shared.fetch import FetchError, Response
from tools.gundam_cards import cli
from tools.gundam_cards.export import build_export
from tools.gundam_cards.models import CardPrice, CardSet, PriceFile, PrintingPrice, PrintingPriceFile, SetKind
from tools.gundam_cards.price_refresh import (
    MATCH_DROP_SHARE,
    REQUEST_DELAY_S,
    Matched,
    format_report,
    match_products,
    plan_report,
    refresh_prices,
)
from tools.gundam_cards.tests.price_files import write_prices
from tools.gundam_cards.store import (
    data_out_dir,
    load_cards_with_prices,
    load_catalog_or_fail,
    load_prices,
    load_printing_price_history,
    load_printing_prices,
    raw_folder,
    tracked_folder,
    write_printing_prices,
)
from tools.gundam_cards.tcgcsv import BASE_URL, RawDump, parse_dump, stamp_of
from tools.gundam_cards.tests.test_catalog_refresh import all_dataset_bytes, write_tracked_sets
from tools.gundam_cards.tests.test_export import CATALOG_AT, printing, store
from tools.gundam_packages.tests.helpers import unit

T1 = datetime(2026, 11, 4, 21, tzinfo=UTC)  # the first pull
UPDATED = datetime(2026, 11, 4, 20, tzinfo=UTC)  # tcgcsv's own time for the first dump
UPDATED2 = datetime(2026, 11, 6, 20, tzinfo=UTC)


# ---- the catalog and the tcgcsv dump ------------------------------------------------------------------------------------------------
def card(number: str, name: str, printings: tuple[tuple[str, str, int, bool], ...]) -> Any:
    """A unit card whose printings are `(id, set code, alt art level, link art)`."""
    return unit(number, name).model_copy(
        update={"printings": tuple(printing(i, s, alt=a, link=k) for i, s, a, k in printings)}
    )


GUNDAM = card("GD01-001", "Gundam", (("GD01-001", "GD01", 0, False), ("GD01-001_p1", "GD01", 1, False),
                                     ("GD01-001_p2", "SC01", 0, False), ("GD01-001_p3", "BETA", 0, False)))  # fmt: skip
ZAKU = card(
    "GD01-002", "Zaku", (("GD01-002", "GD01", 0, False), ("GD01-002_p1", "GD01", 1, True))
)  # a link art, matched as an alt art
DOM = card(
    "GD01-003",
    "Dom",
    (("GD01-003", "GD01", 0, False), ("GD01-003_p1", "GD01", 1, False), ("GD01-003_p2", "GD01", 1, False)),
)
GELGOOG = card(
    "GD01-004",
    "Gelgoog",
    (("GD01-004", "GD01", 0, False), ("GD01-004_p1", "GD01", 1, False), ("GD01-004_p2", "GD01", 2, False)),
)
AMURO = card("ST01-010", "Amuro Ray", (("ST01-010", "ST01", 0, False),))
CATALOG = (GUNDAM, ZAKU, DOM, GELGOOG, AMURO)


def sets() -> tuple[CardSet, ...]:
    return tuple(
        CardSet(
            code=SetCode(code),
            name=code,
            kind=SetKind.BOOSTER,
            bandai_package_id=PackageId(f"6160{i}"),
            release_date=date(2025, 7, 25),
            product_category_raw=None,
            product_url=None,
        )
        for i, code in enumerate(("GD01", "SC01", "ST01"))
    )


def results(rows: list[dict[str, object]]) -> str:
    return json.dumps({"totalItems": len(rows), "success": True, "errors": [], "results": rows})


def product(pid: int, name: str, number: str | None, rarity: str | None, group: int) -> dict[str, object]:
    fields = [{"name": "Number", "value": number}] if number else []
    fields += [{"name": "Rarity", "value": rarity}] if rarity else []
    return {"productId": pid, "name": name, "groupId": group, "extendedData": fields}


def row(pid: int, market: float | None, kind: str = "Normal") -> dict[str, object]:
    return {"productId": pid, "marketPrice": market, "lowPrice": market, "subTypeName": kind}


GROUPS = [
    {"groupId": 1, "name": "Newtype Rising", "abbreviation": "GD01"},
    {"groupId": 2, "name": "Deck Build Box", "abbreviation": "SC01"},
    {"groupId": 3, "name": "Newtype Rising Edition Beta", "abbreviation": "GD01_b"},
    {"groupId": 4, "name": "Gundam Promotional Cards", "abbreviation": "GCG-PR"},
    {"groupId": 5, "name": "Mystery Pack", "abbreviation": "ZZ99"},
    {"groupId": 6, "name": "Heroic Beginnings", "abbreviation": "ST01"},
]
PRODUCTS = {
    1: [
        product(10, "N10 Gundam", "GD01-001", "Rare", 1),
        product(11, "N11 Gundam alt", "GD01-001", "Rare+", 1),
        product(12, "N12 Zaku", "GD01-002", "Rare", 1),
        product(13, "N13 Zaku link", "GD01-002", "Rare+", 1),
        product(14, "N14 Dom", "GD01-003", "Rare", 1),
        product(15, "N15 Dom alt", "GD01-003", "Rare+", 1),  # two printings: ambiguous
        product(60, "N60 Not ours", "GD01-099", "Rare", 1),
        product(61, "N61 Mythic", "GD01-001", "Mythic", 1),
        product(62, "N62 Foil etched", "GD01-002", "Rare", 1),
        product(63, "N63 No price", "GD01-003", "Rare", 1),
        product(18, "N18 Gelgoog", "GD01-004", "Rare", 1),
        product(19, "N19 Gelgoog +", "GD01-004", "Rare+", 1),
        product(21, "N21 Gelgoog ++", "GD01-004", "Rare++", 1),
        product(23, "N23 Gundam ++", "GD01-001", "Rare++", 1),  # no ++ printing of GD01-001
        product(70, "N70 Booster Pack", None, None, 1),
    ],
    2: [
        product(20, "N20 Gundam SC01", "GD01-001", "Rare", 2),
        product(22, "N22 Zaku in SC01", "GD01-002", "Rare", 2),
    ],  # no SC01 printing of Zaku
    3: [product(30, "N30 Gundam Beta", "GD01-001", "Rare", 3)],
    4: [product(40, "N40 Gundam promo", "GD01-001", "Promo", 4)],
    5: [product(50, "N50 Gundam mystery", "GD01-001", "Rare", 5)],
    6: [
        product(16, "N16 Amuro", "ST01-010", "Rare", 6),
        product(17, "N17 Amuro again", "ST01-010", "Rare", 6),
    ],  # two products, one printing
}
PRICES = {
    1: [row(10, 1.50), row(11, 5.00), row(12, 2.00), row(13, 9.00), row(14, 0.50), row(15, 3.00), row(60, 1.0), row(61, 1.0),
        row(62, 1.0, "Foil Etched"), row(70, 4.0), row(18, 1.0), row(19, 2.0), row(21, 4.0), row(23, 6.0)],
    2: [row(20, 1.20), row(22, 1.1)], 3: [row(30, 0.80)], 4: [row(40, 0.10)], 5: [row(50, 0.20)], 6: [row(16, 0.40), row(17, 0.45)],
}  # fmt: skip
EXPECTED = {  # printing -> (cents, product id, alt art level): matched exactly once, both ways
    "GD01-001": (150, 10, 0),
    "GD01-001_p1": (500, 11, 1),
    "GD01-001_p2": (120, 20, 0),
    "GD01-001_p3": (80, 30, 0),
    "GD01-002": (200, 12, 0),
    "GD01-002_p1": (900, 13, 1),
    "GD01-003": (50, 14, 0),
    "GD01-004": (100, 18, 0),
    "GD01-004_p1": (200, 19, 1),
    "GD01-004_p2": (400, 21, 2),  # each tier matches only its own printing
}


def make_dump(
    updated: datetime = UPDATED,
    *,
    products: dict[int, list[dict[str, object]]] | None = None,
    prices: dict[int, list[dict[str, object]]] | None = None,
) -> RawDump:
    products, prices = products or PRODUCTS, prices or PRICES
    return RawDump(updated, results(list(GROUPS)), {g: results(products.get(g, [])) for g in range(1, 7)},
                   {g: results(prices.get(g, [])) for g in range(1, 7)})  # fmt: skip


class FakeTcgcsv:
    """tcgcsv at the fetcher: serves the current dump, records every request made, and writes the raw cache like the real fetcher."""

    def __init__(self, dump: RawDump | None = None) -> None:
        self.dump = dump or make_dump()
        self.calls: list[str] = []
        self.fail: set[str] = set()
        self.interrupt: set[str] = set()
        self.garbled: set[str] = set()
        self.bad_updated = False

    @property
    def network_requests(self) -> int:
        return len(self.calls)

    def answer(self, url: str) -> str:
        path = url.removeprefix(BASE_URL)
        if path == "/last-updated.txt":
            if self.bad_updated:
                return "yesterday"
            return self.dump.source_updated_at.strftime("%Y-%m-%dT%H:%M:%S+0000")
        if path.endswith("/groups"):
            return self.dump.groups
        group, kind = path.split("/")[-2:]
        return (self.dump.products if kind == "products" else self.dump.prices)[int(group)]

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        cached = raw_folder() / "tcgcsv" / cache_key if cache_key is not None else None
        if (
            cached is not None and cached.is_file() and not force
        ):  # like the real fetcher: a cached page is not requested again
            return Response(url, cached.read_text(encoding="utf-8"), T1, from_cache=True)
        self.calls.append(url)
        if url in self.interrupt:
            raise KeyboardInterrupt
        if url in self.fail:
            raise FetchError(url, "HTTP 500", 500)
        text = "<html>not json" if url in self.garbled else self.answer(url)
        if cache_key is not None:
            target = raw_folder() / "tcgcsv" / cache_key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return Response(url, text, T1, from_cache=False)


def url(group: int, kind: str) -> str:
    return f"{BASE_URL}/tcgplayer/86/{group}/{kind}"


@pytest.fixture(autouse=True)
def dataset() -> None:
    """The catalog and the reviewed sets of the temp dataset."""
    store(CATALOG, unlisted=())
    write_tracked_sets(sets(), CATALOG_AT, tracked_folder())
    (tracked_folder() / "restrictions.json").write_text('{"owner": "by hand"}\n', encoding="utf-8")


def tracked_bytes() -> dict[str, bytes]:
    """The tracked folder's files (sets.json, restrictions.json): no refresh-prices run may change them."""
    return {p.name: p.read_bytes() for p in sorted(tracked_folder().iterdir())}


def run(site: FakeTcgcsv, when: datetime = T1, **options: Any) -> Any:
    return refresh_prices(site, raw_folder(), now=when, **options)


def stored() -> dict[str, tuple[int, int, int]]:
    file = load_printing_prices()
    assert file is not None
    return {str(r.printing_id): (r.price_cents, int(r.product_id), r.alt_art_level) for r in file.data}


def snapshot_files() -> list[Path]:
    return sorted((data_out_dir() / "printing_prices").glob("*.json"))


# ---- AC-1: matching -----------------------------------------------------------------------------------------------------------------
def matched(dump: RawDump | None = None) -> Matched:
    products, _ = parse_dump(dump or make_dump())
    return match_products(products, load_catalog_or_fail().data, {s.code for s in sets()}, T1)


def test_a_product_matches_the_printing_of_its_set_card_number_and_art_tier() -> None:
    result = matched()
    assert {str(r.printing_id): (r.price_cents, int(r.product_id), r.alt_art_level) for r in result.rows} == EXPECTED
    by_id = {str(r.printing_id): r for r in result.rows}
    assert (
        by_id["GD01-001_p3"].set_code == "GD01_b" and by_id["GD01-001_p2"].set_code == "SC01"
    )  # Beta and SC01 reprints price on their own
    assert by_id["GD01-002_p1"].price_cents == 900  # a link art matched as an alt art
    assert [str(r.printing_id) for r in result.rows] == sorted(by_id)  # sorted by printing id
    assert all(r.fetched_at == T1 for r in result.rows) and result.sealed == 1


def test_everything_not_matched_exactly_once_is_reported_with_the_reason_and_takes_no_part() -> None:
    result = matched()
    reasons = {u.name: u.reason for u in result.unmatched}
    assert reasons == {
        "N15 Dom alt": "2 printings in set GD01 with art tier 1, not exactly one",
        "N60 Not ours": "card number is not in the catalog",
        "N61 Mythic": "unrecognized rarity 'Mythic'",
        "N62 Foil etched": "unrecognized price kind 'Foil Etched'",
        "N63 No price": "no market price",
        "N40 Gundam promo": "promo group",
        "N50 Gundam mystery": "group maps to no set",
        "N22 Zaku in SC01": "0 printings in set SC01 with art tier 0, not exactly one",
        "N23 Gundam ++": "0 printings in set GD01 with art tier 2, not exactly one",
        "N16 Amuro": "2 products match printing ST01-010",
        "N17 Amuro again": "2 products match printing ST01-010",
    }
    assert {u.name: (u.group, u.number) for u in result.unmatched}["N50 Gundam mystery"] == (
        "ZZ99",
        "GD01-001",
    )  # name, group and Number
    assert not {"GD01-003_p1", "GD01-003_p2", "ST01-010"} & {
        str(r.printing_id) for r in result.rows
    }  # a printing with no product: no row


def test_a_group_maps_to_a_known_set_code_or_edition_beta_and_nothing_else() -> None:
    codes = {s.code for s in sets()}
    products, _ = parse_dump(make_dump())
    by_group = {
        p.group: p for p in products if int(p.product_id) in (10, 20, 30, 50)
    }  # GD01-001's plain Rare in four groups
    assert set(by_group) == {"GD01", "SC01", "GD01_b", "ZZ99"}
    got = {m.set_code for m in match_products(list(by_group.values()), CATALOG, codes, T1).rows}
    assert got == {"GD01", "SC01", "GD01_b"}  # ZZ99 maps to no set


# ---- AC-2: the snapshot -------------------------------------------------------------------------------------------------------------
def test_a_real_run_adds_one_dated_snapshot_with_a_row_per_matched_printing() -> None:
    report = run(FakeTcgcsv())
    assert report.written and report.stored and not report.refused and report.matched == 10
    assert stored() == EXPECTED
    [path] = snapshot_files()
    assert path.name == "2026-11-04T210000Z.json"
    file = load_printing_prices()
    assert (
        file is not None and file.generated_at == T1 and file.source_updated_at == UPDATED and file.schema_version == 1
    )
    assert all(r.fetched_at == T1 for r in file.data)  # the as-of date, and cents are integers
    assert [r.price_cents for r in file.data if str(r.printing_id) == "GD01-001"] == [150]


def test_the_same_prices_or_a_second_pull_on_the_same_day_add_nothing_and_say_so() -> None:
    run(FakeTcgcsv())
    [first] = snapshot_files()
    before = first.read_bytes()
    same_day = run(FakeTcgcsv(), T1 + timedelta(hours=2), force=True)  # forced inside 24 hours, the same UTC day
    assert same_day.written and not same_day.stored
    assert "no new snapshot (that UTC day is stored already, or the prices are unchanged)" in format_report(same_day)
    later = run(FakeTcgcsv(make_dump(UPDATED2)), T1 + timedelta(days=2))  # another day, the same prices
    assert later.written and not later.stored
    assert snapshot_files() == [first] and first.read_bytes() == before


def test_changed_prices_on_a_later_day_add_a_snapshot_and_leave_the_earlier_one_byte_identical() -> None:
    run(FakeTcgcsv())
    [first] = snapshot_files()
    before = first.read_bytes()
    cheaper = {**PRICES, 1: [row(10, 1.25), *PRICES[1][1:]]}
    run(FakeTcgcsv(make_dump(UPDATED2, prices=cheaper)), T1 + timedelta(days=2))
    assert len(snapshot_files()) == 2 and first.read_bytes() == before
    assert stored()["GD01-001"][0] == 125 and len(load_printing_price_history()) == 2


def test_a_second_pull_on_the_same_utc_day_with_different_prices_adds_nothing() -> None:
    run(FakeTcgcsv())
    [first] = snapshot_files()
    before = first.read_bytes()
    cheaper = {
        **PRICES,
        1: [row(10, 1.25), *PRICES[1][1:]],
    }  # a different dump, other prices, 21:00 and 23:00 on the same UTC day
    report = run(
        FakeTcgcsv(make_dump(UPDATED + timedelta(hours=1), prices=cheaper)), T1 + timedelta(hours=2), force=True
    )
    assert (
        report.written and not report.stored and report.changed == 1
    )  # the prices did change: only the same-day rule refuses it
    assert snapshot_files() == [first] and first.read_bytes() == before


def test_the_export_gives_each_printing_its_own_price_and_no_card_level_price() -> None:
    run(FakeTcgcsv())
    beta = CardSet(
        code=SetCode("BETA"),
        name="Edition Beta",
        kind=SetKind.OTHER,
        bandai_package_id=None,
        release_date=None,
        product_category_raw=None,
        product_url=None,
    )
    export = build_export(load_catalog_or_fail(), (*sets(), beta), (), (), load_printing_price_history(), T1)
    prices = {p.id: (p.price_cents, p.price_as_of) for c in export.cards for p in c.printings}
    assert prices[PrintingId("GD01-001")] == (150, date(2026, 11, 4)) and prices[PrintingId("GD01-001_p1")] == (
        500,
        date(2026, 11, 4),
    )
    assert prices[PrintingId("GD01-001_p2")] == (120, date(2026, 11, 4)) and prices[PrintingId("GD01-001_p3")] == (
        80,
        date(2026, 11, 4),
    )
    assert prices[PrintingId("GD01-003_p1")] == (None, None) and prices[PrintingId("ST01-010")] == (
        None,
        None,
    )  # no row, no price
    assert export.schema_version == 1 and all("price_cents" not in c.model_dump() for c in export.cards)


def beta() -> CardSet:
    return CardSet(
        code=SetCode("BETA"),
        name="Edition Beta",
        kind=SetKind.OTHER,
        bandai_package_id=None,
        release_date=None,
        product_category_raw=None,
        product_url=None,
    )


def test_the_export_uses_only_the_newest_per_printing_snapshot() -> None:
    run(FakeTcgcsv())
    without_the_alt = {1: [p for p in PRODUCTS[1] if p["productId"] != 11]}
    without_prices = {1: [r for r in PRICES[1] if r["productId"] != 11]}
    newest = make_dump(UPDATED2, products={**PRODUCTS, **without_the_alt}, prices={**PRICES, **without_prices})
    assert run(
        FakeTcgcsv(newest), T1 + timedelta(days=2), allow_anomaly=True
    ).stored  # one printing of ten gone: the guard would refuse
    history = load_printing_price_history()
    assert len(history) == 2 and "GD01-001_p1" in {str(r.printing_id) for r in history[0].data}
    export = build_export(load_catalog_or_fail(), (*sets(), beta()), (), (), history, T1)
    prices = {str(p.id): p.price_cents for c in export.cards for p in c.printings}
    assert prices["GD01-001_p1"] is None and prices["GD01-001"] == 150  # priced in the older snapshot only: no price


def test_once_a_per_printing_snapshot_exists_the_export_ignores_the_per_card_snapshot_and_its_stopgap() -> None:
    old_row = CardPrice(
        card_number=CardNumber("ST01-010"), price_cents=333, product_id=ProductId(9), set_code="ST01", fetched_at=T1
    )
    legacy = PriceFile(generated_at=T1 - timedelta(days=5), source_updated_at=UPDATED, data=(old_row,))
    write_prices(legacy)
    catalog, all_sets = load_catalog_or_fail(), (*sets(), beta())
    stopgap = build_export(
        catalog, all_sets, (), (legacy,), (), T1
    )  # without a per-printing snapshot the per-card price is given out
    assert {str(p.id): p.price_cents for c in stopgap.cards for p in c.printings}["ST01-010"] == 333
    run(FakeTcgcsv())  # ST01-010 has no row: two products claim it
    export = build_export(catalog, all_sets, (), (legacy,), load_printing_price_history(), T1)
    assert {str(p.id): p.price_cents for c in export.cards for p in c.printings}[
        "ST01-010"
    ] is None  # the per-card file is not read any more


def save_dump(dump: RawDump, marker: str | None = None) -> None:
    """A dump as the raw cache holds it, with the pull marker when one is given."""
    folder = raw_folder() / "tcgcsv" / stamp_of(dump.source_updated_at)
    folder.mkdir(parents=True)
    (folder / "groups.json").write_text(dump.groups, encoding="utf-8")
    for g in range(1, 7):
        (folder / f"{g}_products.json").write_text(dump.products[g], encoding="utf-8")
        (folder / f"{g}_prices.json").write_text(dump.prices[g], encoding="utf-8")
    if marker:
        (folder / "pulled-at.txt").write_text(marker + "\n", encoding="utf-8")


def test_reparse_tcgplayer_rebuilds_the_snapshots_oldest_first_with_no_network_and_adds_nothing_twice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    save_dump(make_dump(UPDATED2, prices={**PRICES, 1: [row(10, 1.25), *PRICES[1][1:]]}), "2026-11-06T21:00:00+00:00")
    save_dump(make_dump())
    monkeypatch.setattr(cli, "Fetcher", lambda *a, **k: pytest.fail("reparse-tcgplayer must not fetch"))
    assert cli.main(["reparse-tcgplayer"]) == 0
    assert "2 snapshot(s) added from 2 saved dump(s)" in capsys.readouterr().out
    first, second = load_printing_price_history()
    assert first.generated_at == UPDATED and second.generated_at == datetime(
        2026, 11, 6, 21, tzinfo=UTC
    )  # no marker: the dump's own time
    assert first.data[0].price_cents == 150 and second.data[0].price_cents == 125  # oldest first, each from its dump
    before = [p.read_bytes() for p in snapshot_files()]
    assert cli.main(["reparse-tcgplayer"]) == 0
    assert "0 snapshot(s) added" in capsys.readouterr().out and [p.read_bytes() for p in snapshot_files()] == before


# ---- AC-3: the per-card readers ------------------------------------------------------------------------------------------------------
def test_reparse_tcgplayer_says_so_and_exits_2_on_a_garbled_saved_dump(capsys: pytest.CaptureFixture[str]) -> None:
    save_dump(make_dump())
    (raw_folder() / "tcgcsv" / stamp_of(UPDATED) / "2_products.json").write_text("<html>not json", encoding="utf-8")
    assert cli.main(["reparse-tcgplayer"]) == 2
    assert "the saved dump is unreadable" in capsys.readouterr().err and not snapshot_files()


def test_the_per_card_price_is_the_cheapest_non_alt_art_printings_row_and_nothing_stores_it() -> None:
    run(FakeTcgcsv())
    derived = load_prices()
    assert derived is not None
    got = {str(p.card_number): (p.price_cents, int(p.product_id), p.set_code, p.name) for p in derived.data}
    assert (
        got
        == {  # GD01-001: the Beta printing's 80 beats 120 and 150, and the alt art never counts; GD01-002's link art never counts
            "GD01-001": (80, 30, "GD01_b", "N30 Gundam Beta"),
            "GD01-002": (200, 12, "GD01", "N12 Zaku"),
            "GD01-003": (50, 14, "GD01", "N14 Dom"),
            "GD01-004": (100, 18, "GD01", "N18 Gelgoog"),
        }
    )
    assert not (data_out_dir() / "prices").exists()  # the per-card price is derived on read, not stored a second time
    priced = {str(p.card.number): p.latest_tcg_price for p in load_cards_with_prices()}
    assert priced["ST01-010"] is None and priced["GD01-001"] is not None and priced["GD01-001"].price_cents == 80


def test_a_card_whose_only_priced_printings_are_alt_arts_has_no_price() -> None:
    only_alt = {1: [product(11, "N11 Gundam alt", "GD01-001", "Rare+", 1)]}
    run(FakeTcgcsv(make_dump(products=only_alt, prices={1: [row(11, 5.0)]})))
    assert stored() == {"GD01-001_p1": (500, 11, 1)}
    derived = load_prices()
    assert derived is not None and derived.data == ()


def test_the_price_command_prints_what_the_per_card_snapshot_gave(capsys: pytest.CaptureFixture[str]) -> None:
    run(FakeTcgcsv())
    assert cli.main(["price", "GD01-001"]) == 0
    assert (
        "GD01-001 Gundam: $0.80  (TCGPlayer market price, product 30, pulled 2026-11-04 21:00 UTC)"
        in capsys.readouterr().out
    )


def test_the_readers_use_only_the_newest_per_printing_snapshot() -> None:
    run(FakeTcgcsv())
    gelgoog_gone = {
        1: [p for p in PRODUCTS[1] if p["productId"] != 14],
        3: PRODUCTS[3],
    }  # GD01-003's base product is gone
    prices = {
        1: [r for r in PRICES[1] if r["productId"] != 14],
        3: [row(30, 2.0)],
    }  # and the Beta printing of GD01-001 now costs $2.00
    newest = make_dump(UPDATED2, products={**PRODUCTS, **gelgoog_gone}, prices={**PRICES, **prices})
    assert run(FakeTcgcsv(newest), T1 + timedelta(days=2), allow_anomaly=True).stored
    derived = load_prices()
    assert derived is not None
    got = {str(p.card_number): (p.price_cents, int(p.product_id)) for p in derived.data}
    assert got["GD01-001"] == (120, 20)  # the newest snapshot's cheapest ($1.20 SC01), not the older $0.80 Beta row
    assert "GD01-003" not in got  # priced only in the older snapshot: no price
    priced = {str(c.card.number): c.latest_tcg_price for c in load_cards_with_prices()}
    assert priced["GD01-003"] is None and priced["GD01-001"] is not None and priced["GD01-001"].price_cents == 120


def test_reparse_tcgplayer_leaves_an_older_per_card_file_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_row = CardPrice(
        card_number=CardNumber("GD01-001"),
        price_cents=777,
        product_id=ProductId(9),
        set_code="GD01",
        fetched_at=T1 - timedelta(days=5),
    )
    path = write_prices(PriceFile(generated_at=T1 - timedelta(days=5), source_updated_at=UPDATED, data=(legacy_row,)))
    assert path is not None
    before = path.read_bytes()
    save_dump(make_dump())
    monkeypatch.setattr(cli, "Fetcher", lambda *a, **k: pytest.fail("reparse-tcgplayer must not fetch"))
    assert cli.main(["reparse-tcgplayer"]) == 0 and len(snapshot_files()) == 1
    assert path.read_bytes() == before and [p.name for p in path.parent.iterdir()] == [path.name]


def test_price_explain_tells_what_the_matching_did_with_each_product(capsys: pytest.CaptureFixture[str]) -> None:
    run(FakeTcgcsv())
    assert cli.main(["price", "GD01-001", "--explain"]) == 0
    out = capsys.readouterr().out
    assert (
        "matched to GD01-001 ($1.50)" in out and "matched to GD01-001_p3 ($0.80)" in out
    )  # the Beta and SC01 reprints are matched
    assert (
        "N50 Gundam mystery" in out
        and "group maps to no set" in out
        and "promo group" in out
        and "unrecognized rarity 'Mythic'" in out
    )
    assert cli.main(["price", "ST01-010", "--explain"]) == 1  # two products claim the one printing: neither is used
    out = capsys.readouterr().out
    assert "ST01-010 Amuro Ray: no price (no product matched a printing: 2 products match printing ST01-010)" in out
    assert out.count("2 products match printing ST01-010") == 3  # the summary and the two products


def test_a_card_whose_products_the_matching_rejected_is_not_explained_as_having_no_price_row(
    capsys: pytest.CaptureFixture[str],
) -> None:
    only_zaku_priced = make_dump(
        products={1: [PRODUCTS[1][2]], 4: PRODUCTS[4], 5: PRODUCTS[5]},
        prices={1: [row(12, 2.0)], 4: PRICES[4], 5: PRICES[5]},
    )
    run(
        FakeTcgcsv(only_zaku_priced)
    )  # a snapshot exists; GD01-001 has only a promo and an unmapped-group product, both with price rows
    assert cli.main(["price", "GD01-001", "--explain"]) == 1
    out = capsys.readouterr().out
    assert "GD01-001 Gundam: no price (no product matched a printing: group maps to no set; promo group)" in out
    assert "no price row" not in out and out.count("group maps to no set") == 2
    assert cli.main(["price", "GD01-002"]) == 0  # the priced card is as before


def test_price_says_a_card_priced_only_as_an_alt_art_has_no_price(capsys: pytest.CaptureFixture[str]) -> None:
    run(
        FakeTcgcsv(make_dump(products={1: [PRODUCTS[1][1]]}, prices={1: [row(11, 5.0)]}))
    )  # only N11, GD01-001's "+" alt art
    assert cli.main(["price", "GD01-001"]) == 1
    assert "GD01-001 Gundam: no price (only alt-art printings matched (never bought))" in capsys.readouterr().out


def test_price_says_when_no_product_has_the_card_number(capsys: pytest.CaptureFixture[str]) -> None:
    run(FakeTcgcsv(make_dump(products={1: [PRODUCTS[1][0]]}, prices={1: [row(10, 1.5)]})))  # nothing for ST01-010
    assert cli.main(["price", "ST01-010"]) == 1
    assert "ST01-010 Amuro Ray: no price (no TCGPlayer product with this card number)" in capsys.readouterr().out


def test_price_says_when_there_is_no_saved_dump_to_explain_it(capsys: pytest.CaptureFixture[str]) -> None:
    gelgoog = PrintingPrice(
        printing_id=PrintingId("GD01-004"),
        price_cents=100,
        product_id=ProductId(18),
        name="N18",
        set_code="GD01",
        alt_art_level=0,
        fetched_at=T1,
    )
    assert (
        write_printing_prices(PrintingPriceFile(generated_at=T1, source_updated_at=UPDATED, data=(gelgoog,)))
        is not None
    )  # no raw dump saved
    assert cli.main(["price", "GD01-001"]) == 1
    assert "GD01-001 Gundam: no price (no saved dump to explain it)" in capsys.readouterr().out


def test_until_a_per_printing_snapshot_exists_the_readers_keep_the_per_card_snapshot_and_it_is_never_changed() -> None:
    legacy_row = CardPrice(
        card_number=CardNumber("GD01-001"),
        price_cents=777,
        product_id=ProductId(9),
        set_code="GD01",
        fetched_at=T1 - timedelta(days=5),
    )
    path = write_prices(PriceFile(generated_at=T1 - timedelta(days=5), source_updated_at=UPDATED, data=(legacy_row,)))
    assert path is not None
    before = path.read_bytes()
    assert load_printing_prices() is None
    legacy = load_prices()
    assert legacy is not None and [(str(p.card_number), p.price_cents) for p in legacy.data] == [("GD01-001", 777)]
    run(FakeTcgcsv())
    derived = load_prices()
    assert (
        derived is not None and {str(p.card_number): p.price_cents for p in derived.data}["GD01-001"] == 80
    )  # from now on only the new ones
    assert path.read_bytes() == before and [p.name for p in path.parent.iterdir()] == [
        path.name
    ]  # the old file is untouched


# ---- AC-4: nothing is written unless everything is ----------------------------------------------------------------------------------
def test_a_failed_or_unreadable_group_or_an_interruption_writes_nothing() -> None:
    before, tracked_before = all_dataset_bytes(), tracked_bytes()
    for how in ("fail", "garbled", "interrupt"):
        site = FakeTcgcsv()
        getattr(site, how).add(url(3, "prices"))  # the third group's prices: after two groups were fetched
        if how == "interrupt":
            with pytest.raises(KeyboardInterrupt):
                run(site)
        else:
            report = run(site)
            assert not report.complete and report.failure is not None and not report.written
            assert format_report(report)[0].startswith("incomplete, nothing written")
        assert all_dataset_bytes() == before and tracked_bytes() == tracked_before


@pytest.mark.parametrize(
    "how", ["garbled listing", "listing says failure", "bad last-updated", "failed listing", "interrupted listing"]
)
def test_a_listing_that_answers_but_is_invalid_or_fails_writes_nothing_and_changes_no_tracked_file(how: str) -> None:
    before, tracked_before = all_dataset_bytes(), tracked_bytes()
    site = FakeTcgcsv()
    groups = f"{BASE_URL}/tcgplayer/86/groups"
    if how == "garbled listing":
        site.garbled.add(groups)
    elif how == "listing says failure":
        site.dump = RawDump(UPDATED, json.dumps({"success": False, "errors": ["boom"], "results": []}), {}, {})
    elif how == "bad last-updated":
        site.bad_updated = True
    elif how == "failed listing":
        site.fail.add(groups)
    else:
        site.interrupt.add(groups)
    if how == "interrupted listing":
        with pytest.raises(KeyboardInterrupt):
            run(site)
    else:
        report = run(site)
        assert (
            not report.complete
            and not report.written
            and format_report(report)[0].startswith("incomplete, nothing written")
        )
    assert all_dataset_bytes() == before and tracked_bytes() == tracked_before and not snapshot_files()


def test_the_reported_request_count_is_the_requests_that_reached_the_network_not_cached_answers() -> None:
    broken = FakeTcgcsv()
    broken.fail.add(url(3, "prices"))
    run(broken)  # the listing, groups 1 and 2 and group 3's products are cached; group 3's prices failed
    resumed = FakeTcgcsv()
    report = run(resumed)
    assert (
        report.requests == len(resumed.calls) == 8
    )  # last-updated.txt, group 3's prices, and groups 4 to 6 (two files each)
    assert format_report(report)[0].startswith(
        "real run: tcgcsv dump of 2026-11-04 20:00 UTC, 8 request(s)"
    )  # not the 14 of a whole pull
    assert url(1, "products") not in resumed.calls  # a cached answer is not requested, so it is not counted


def test_a_run_from_the_saved_dump_inside_24_hours_reports_no_request() -> None:
    run(FakeTcgcsv(), T1)
    site = FakeTcgcsv(THIN)
    refused = run(site, T1 + timedelta(days=2))
    assert refused.refused and refused.requests == 14
    allowed = run(site, T1 + timedelta(days=2, hours=1), allow_anomaly=True)
    assert allowed.written and allowed.requests == 0 and "0 request(s)" in format_report(allowed)[0]
    dry = run(site, T1 + timedelta(days=2, hours=2), dry_run=True)
    assert dry.requests == 0 and "0 request(s)" in format_report(dry)[0]


def test_a_partly_saved_dump_is_resumed_and_a_garbled_saved_one_is_pulled_again() -> None:
    broken = FakeTcgcsv()
    broken.fail.add(url(3, "prices"))
    assert not run(broken).complete  # groups 1 and 2 and the third group's products are cached; the rest is not
    resumed = FakeTcgcsv()
    report = run(resumed)
    assert report.written and stored() == EXPECTED
    assert (
        url(1, "products") not in resumed.calls and url(3, "prices") in resumed.calls
    )  # only what was missing is requested again

    garbled = FakeTcgcsv(make_dump(UPDATED2))
    garbled.garbled.add(url(2, "products"))
    assert not run(garbled, T1 + timedelta(days=2)).complete  # the garbled answer is saved by the cache
    fixed = FakeTcgcsv(make_dump(UPDATED2))
    again = run(fixed, T1 + timedelta(days=2))
    assert (
        again.complete and url(2, "products") in fixed.calls
    )  # a saved dump that does not parse is pulled again, not used for ever


def _previous(count: int, groups: tuple[str, ...] = ("GD01",)) -> PrintingPriceFile:
    rows = tuple(PrintingPrice(printing_id=PrintingId(f"GD01-{n:03}"), price_cents=100, product_id=ProductId(n), name="x", set_code=groups[n % len(groups)],
                               alt_art_level=0, fetched_at=T1) for n in range(1, count + 1))  # fmt: skip
    return PrintingPriceFile(generated_at=T1 - timedelta(days=3), source_updated_at=UPDATED, data=rows)


def _now(previous: PrintingPriceFile, kept: int, groups: set[str]) -> Matched:
    return Matched(tuple(r for r in previous.data[:kept]), (), 0)


def test_the_guard_refuses_when_more_than_the_share_of_printings_is_no_longer_matched_and_not_at_the_limit() -> None:
    assert MATCH_DROP_SHARE == 0.05
    previous = _previous(20)
    at_limit = plan_report(
        (),
        _now(previous, 19, {"GD01"}),
        {"GD01"},
        previous,
        allow_anomaly=False,
        dry_run=False,
        source_updated_at=UPDATED,
    )
    assert at_limit.dropped == 1 and not at_limit.guard_trips and not at_limit.refused  # exactly 5%: written
    over = plan_report(
        (),
        _now(previous, 18, {"GD01"}),
        {"GD01"},
        previous,
        allow_anomaly=False,
        dry_run=False,
        source_updated_at=UPDATED,
    )
    assert over.dropped == 2 and over.guard_trips and over.refused  # 10%: refused
    assert "refused: 2 of 20 printings no longer matched (limit 5%)" in format_report(over)[-2]
    overridden = plan_report(
        (),
        _now(previous, 18, {"GD01"}),
        {"GD01"},
        previous,
        allow_anomaly=True,
        dry_run=False,
        source_updated_at=UPDATED,
    )
    assert overridden.guard_trips and not overridden.refused
    dry = plan_report(
        (),
        _now(previous, 18, {"GD01"}),
        {"GD01"},
        previous,
        allow_anomaly=False,
        dry_run=True,
        source_updated_at=UPDATED,
    )
    assert dry.guard_trips and not dry.refused and "guard: would refuse: 2 of 20" in format_report(dry)[-2]


def test_the_guard_refuses_when_a_group_that_gave_the_last_snapshot_rows_is_missing() -> None:
    previous = _previous(20, ("GD01", "SC01"))
    report = plan_report(
        (),
        _now(previous, 20, {"GD01"}),
        {"GD01"},
        previous,
        allow_anomaly=False,
        dry_run=False,
        source_updated_at=UPDATED,
    )
    assert (
        report.dropped == 0 and report.missing_groups == ("SC01",) and report.refused
    )  # every printing matched, one group gone
    assert "groups missing from the pull: SC01" in "\n".join(format_report(report))
    assert not plan_report(
        (),
        _now(previous, 20, {"GD01"}),
        {"GD01", "SC01"},
        previous,
        allow_anomaly=False,
        dry_run=False,
        source_updated_at=UPDATED,
    ).guard_trips


THIN = make_dump(
    UPDATED2, products={1: PRODUCTS[1][:1]}, prices={1: PRICES[1][:1]}
)  # one printing matched of the last run's ten


def test_a_refused_run_writes_nothing_and_leaves_the_tracked_files_alone() -> None:
    run(FakeTcgcsv(), T1)
    [path] = snapshot_files()
    before, tracked_before, dataset = path.read_bytes(), tracked_bytes(), all_dataset_bytes()
    refused = run(FakeTcgcsv(THIN), T1 + timedelta(days=2))
    assert refused.refused and not refused.written and snapshot_files() == [path] and path.read_bytes() == before
    assert all_dataset_bytes() == dataset and tracked_bytes() == tracked_before


def test_after_a_refusal_allow_anomaly_without_force_writes_from_the_saved_dump_with_no_new_request() -> None:
    run(FakeTcgcsv(), T1)
    site = FakeTcgcsv(THIN)
    refused = run(site, T1 + timedelta(days=2))
    assert refused.refused
    assert (
        format_report(refused)[-1]
        == "refused by the guard, nothing written (rerun with --allow-anomaly to write it from the saved dump, with no new request)"
    )
    requests = len(site.calls)
    later = T1 + timedelta(days=2, hours=1)  # no clock jump: inside the 24 hours the refused pull started
    plain = run(site, later)
    assert (
        plain.skipped is not None
        and "--allow-anomaly writes it from the saved dump" in format_report(plain)[0]
        and len(snapshot_files()) == 1
    )
    allowed = run(site, later, allow_anomaly=True)  # no --force
    assert allowed.written and allowed.stored and not allowed.refused and len(site.calls) == requests  # no new request
    assert len(snapshot_files()) == 2 and set(stored()) == {"GD01-001"}


def test_the_command_after_a_refusal_writes_with_allow_anomaly_and_no_new_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    previous = matched().rows
    assert (
        write_printing_prices(
            PrintingPriceFile(
                generated_at=datetime.now(UTC) - timedelta(days=3), source_updated_at=UPDATED, data=previous
            )
        )
        is not None
    )
    site = FakeTcgcsv(THIN)
    monkeypatch.setattr(cli, "Fetcher", lambda *a, **k: site)
    assert cli.main(["refresh-prices"]) == 1 and "rerun with --allow-anomaly" in capsys.readouterr().out
    requests = len(site.calls)
    assert (
        cli.main(["refresh-prices"]) == 0 and "within 24 hours" in capsys.readouterr().out
    )  # the plain rerun still waits
    assert cli.main(["refresh-prices", "--allow-anomaly"]) == 0 and "snapshot written" in capsys.readouterr().out
    assert len(site.calls) == requests and set(stored()) == {"GD01-001"}


def test_a_large_price_move_never_refuses_and_the_biggest_moves_are_reported_in_both_runs() -> None:
    run(FakeTcgcsv())
    moved = {**PRICES, 1: [row(10, 15.0), row(11, 0.10), *PRICES[1][2:]]}  # GD01-001 x10, its alt art -490 cents
    site = FakeTcgcsv(make_dump(UPDATED2, prices=moved))
    dry = run(site, T1 + timedelta(days=2), dry_run=True)
    real = run(site, T1 + timedelta(days=2))
    for report in (dry, real):
        assert not report.guard_trips and report.changed == 2
        assert [(str(m.printing_id), m.old_cents, m.new_cents) for m in report.moves] == [
            ("GD01-001", 150, 1500),
            ("GD01-001_p1", 500, 10),
        ]
        assert "  move GD01-001: $1.50 -> $15.00" in format_report(report)
    assert real.written and not dry.written


# ---- AC-5: light on tcgcsv, with a dry run ------------------------------------------------------------------------------------------
def test_requests_go_to_tcgcsv_only_one_at_a_time_and_a_pull_is_about_one_request_per_group_half() -> None:
    site = FakeTcgcsv()
    run(site)
    assert site.calls[0] == f"{BASE_URL}/last-updated.txt" and len(site.calls) == 1 + 1 + 2 * 6
    assert all(u.startswith("https://tcgcsv.com/") for u in site.calls)


def test_the_command_fetches_with_the_toolkit_user_agent_no_closer_than_the_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: list[dict[str, Any]] = []
    site = FakeTcgcsv()

    def fetcher(folder: Path, **options: Any) -> FakeTcgcsv:
        made.append({"folder": folder, **options})
        return site

    monkeypatch.setattr(cli, "Fetcher", fetcher)
    assert REQUEST_DELAY_S >= 0.5
    assert cli.main(["refresh-prices", "--dry-run"]) == 0
    assert made == [
        {"folder": raw_folder() / "tcgcsv", "min_interval_s": REQUEST_DELAY_S}
    ]  # the default User-Agent: none given


def test_a_run_within_24_hours_of_the_last_pull_fetches_nothing_writes_nothing_and_says_so_unless_forced() -> None:
    run(FakeTcgcsv(), T1)
    [path] = snapshot_files()
    skipped_site = FakeTcgcsv(make_dump(UPDATED2))
    report = run(skipped_site, T1 + timedelta(hours=23))
    assert report.skipped is not None and "within 24 hours" in format_report(report)[0] and not report.written
    assert skipped_site.calls == [] and snapshot_files() == [path]
    after = run(skipped_site, T1 + timedelta(hours=25))
    assert after.skipped is None and after.written and skipped_site.calls  # past 24 hours it pulls
    forced_site = FakeTcgcsv()
    assert run(forced_site, T1 + timedelta(hours=25, minutes=30), force=True).written and forced_site.calls


@pytest.mark.parametrize("damage", ["garbled", "deleted"])
@pytest.mark.parametrize("options", [{"allow_anomaly": True}, {"dry_run": True}])
def test_inside_24_hours_an_unreadable_saved_dump_is_never_downloaded_again_without_force(
    damage: str, options: dict[str, bool]
) -> None:
    run(FakeTcgcsv(), T1)  # a real pull: its marker is on the saved dump
    dump_folder = raw_folder() / "tcgcsv" / stamp_of(UPDATED)
    assert (dump_folder / "pulled-at.txt").is_file()
    damaged = dump_folder / "2_products.json"
    if damage == "garbled":
        damaged.write_text("<html>not json", encoding="utf-8")
    else:
        damaged.unlink()
    before, tracked_before = all_dataset_bytes(), tracked_bytes()
    site = FakeTcgcsv()
    report = run(site, T1 + timedelta(hours=1), **options)
    assert not report.complete and not report.written and site.calls == []  # no request at all
    assert (
        "unreadable or incomplete" in format_report(report)[0]
        and "rerun with --force to pull again" in format_report(report)[0]
    )
    assert all_dataset_bytes() == before and tracked_bytes() == tracked_before
    forced = run(site, T1 + timedelta(hours=1), force=True)  # --force is the way to pull again
    assert forced.complete and site.calls


def test_a_saved_dump_with_no_pull_marker_is_a_normal_first_pull_even_when_unreadable() -> None:
    save_dump(make_dump())  # saved by sync-tcgplayer or a dry run: no marker
    (raw_folder() / "tcgcsv" / stamp_of(UPDATED) / "2_products.json").write_text("<html>not json", encoding="utf-8")
    site = FakeTcgcsv()
    report = run(site, T1, allow_anomaly=True)
    assert (
        report.complete and report.written and stored() == EXPECTED and site.calls
    )  # pulled again, no 24-hour rule applies


def test_a_dry_run_inside_24_hours_plans_from_the_saved_dump_with_no_network_and_writes_nothing() -> None:
    run(FakeTcgcsv(), T1)
    before, tracked_before = all_dataset_bytes(), tracked_bytes()
    offline = FakeTcgcsv()
    report = run(offline, T1 + timedelta(hours=1), dry_run=True)
    assert offline.calls == [] and report.matched == 10 and report.dry_run and not report.written
    assert all_dataset_bytes() == before and tracked_bytes() == tracked_before


def test_a_dry_run_reports_matches_unmatched_changes_and_the_verdict_and_writes_no_dataset_file_then_a_real_run_still_works() -> (
    None
):
    before, tracked_before = all_dataset_bytes(), tracked_bytes()
    site = FakeTcgcsv()
    dry = run(site, dry_run=True)
    assert (
        all_dataset_bytes() == before and not snapshot_files()
    )  # the raw dump may be saved; the dataset is not touched
    assert tracked_bytes() == tracked_before  # and no tracked file is changed
    lines = format_report(dry)
    assert lines[0].startswith("dry run: tcgcsv dump of 2026-11-04 20:00 UTC, 14 request(s)")
    assert any(line.startswith("10 printing(s) matched, 11 product(s) unmatched or ambiguous") for line in lines)
    assert "  unmatched GD01 GD01-099 N60 Not ours: card number is not in the catalog" in lines
    assert lines[-2:] == ["guard: ok", "dry run: nothing written"]
    real = run(
        site, T1
    )  # the dry run left no pull marker: it did not use up the day, and the saved dump is not fetched again
    assert real.written and real.stored and len(site.calls) == 14 + 1  # one more last-updated check only
    assert stored() == EXPECTED


def test_with_no_catalog_the_run_fails_before_any_request() -> None:
    (data_out_dir() / "cards.json").unlink()
    site = FakeTcgcsv()
    with pytest.raises(NoData):
        run(site)
    assert site.calls == []


def test_sync_tcgplayer_only_saves_the_raw_dump_and_changes_nothing_in_the_dataset(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeTcgcsv()
    monkeypatch.setattr(cli, "Fetcher", lambda *a, **k: site)
    before = all_dataset_bytes()
    assert cli.main(["sync-tcgplayer"]) == 0
    assert (raw_folder() / "tcgcsv" / stamp_of(UPDATED) / "groups.json").is_file()
    assert all_dataset_bytes() == before
    capsys.readouterr()
    calls = len(site.calls)
    assert (
        cli.main(["sync-tcgplayer"]) == 0 and "up to date" in capsys.readouterr().out and len(site.calls) == calls + 1
    )  # one request: last-updated


def test_sync_tcgplayer_does_not_call_a_partly_saved_dump_up_to_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeTcgcsv()
    site.fail.add(url(3, "prices"))
    monkeypatch.setattr(cli, "Fetcher", lambda *a, **k: site)
    assert cli.main(["sync-tcgplayer"]) == 1  # an interrupted pull
    site.fail.clear()
    capsys.readouterr()
    assert cli.main(["sync-tcgplayer"]) == 0 and "up to date" not in capsys.readouterr().out
    assert (raw_folder() / "tcgcsv" / stamp_of(UPDATED) / "3_prices.json").is_file()


def test_refresh_prices_after_sync_tcgplayer_prices_from_the_saved_dump_with_one_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeTcgcsv()
    monkeypatch.setattr(cli, "Fetcher", lambda *a, **k: site)
    assert cli.main(["sync-tcgplayer"]) == 0
    assert (
        "`refresh-prices` prices from this saved dump, with no new download" in capsys.readouterr().out
    )  # what the message promises:
    saved = len(site.calls)
    assert (
        cli.main(["refresh-prices"]) == 0 and "snapshot written" in capsys.readouterr().out
    )  # no wait of 24 hours, no re-download
    assert len(site.calls) == saved + 1 and stored() == EXPECTED  # only last-updated.txt was asked


def test_the_refresh_prices_command_exits_1_when_refused_and_0_when_written(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeTcgcsv()
    monkeypatch.setattr(cli, "Fetcher", lambda *a, **k: site)
    assert cli.main(["refresh-prices"]) == 0 and "snapshot written" in capsys.readouterr().out
    assert stored() == EXPECTED
    site.dump = make_dump(UPDATED2, products={1: PRODUCTS[1][:1]}, prices={1: PRICES[1][:1]})
    assert cli.main(["refresh-prices", "--force"]) == 1 and "refused by the guard" in capsys.readouterr().out
    assert stored() == EXPECTED
