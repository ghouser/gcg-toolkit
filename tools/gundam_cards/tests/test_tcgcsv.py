"""TCGPlayer prices from tcgcsv: identifying products, choosing a price per card, fetching and storing (no network)."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, ProductId, Trait
from shared.fetch import Response
from tools.gundam_cards.build import SourcePage, build_card
from tools.gundam_cards.models import CardPrice, CardsFile, PriceFile, Rarity
from tools.gundam_cards.store import load_cards_with_prices, load_prices, raw_dump_stamps, read_raw_dump, write_prices
from tools.gundam_cards.tcgcsv import (
    IssueKind,
    RawDump,
    TcgcsvError,
    choose_prices,
    fetch_dump,
    parse_dump,
    parse_rarity,
    parse_updated,
    stamp_of,
    why_unpriced,
)

N = CardNumber
UPDATED = datetime(2026, 10, 8, 20, 6, 9, tzinfo=UTC)
PULLED = datetime(2026, 10, 8, 21, 0, 0, tzinfo=UTC)


def results(rows: list[dict[str, object]]) -> str:
    return json.dumps({"totalItems": len(rows), "success": True, "errors": [], "results": rows})


def card(pid: int, name: str, number: str | None, rarity: str | None, group: int) -> dict[str, object]:
    fields = [{"name": "Number", "value": number}] if number else []
    fields += [{"name": "Rarity", "value": rarity}] if rarity else []
    return {"productId": pid, "name": name, "groupId": group, "extendedData": fields}


def price(pid: int, market: float | None, kind: str = "Normal") -> dict[str, object]:
    return {"productId": pid, "marketPrice": market, "lowPrice": market, "subTypeName": kind}


def dump() -> RawDump:
    groups = results([
        {"groupId": 1, "name": "Freedom Ascension", "abbreviation": "GD05"},
        {"groupId": 2, "name": "Deck Build Box Freedom Ascension", "abbreviation": "SC01"},
        {"groupId": 3, "name": "Gundam Promotional Cards", "abbreviation": "GCG-PR"},
    ])  # fmt: skip
    products = {
        1: results([
            card(10, "V2 Gundam", "GD05-001", "Legend Rare", 1), card(11, "V2 Gundam (LR+)", "GD05-001", "LR+", 1),
            card(12, "Booster Pack", None, None, 1), card(13, "Bad number", "GD05-1", "Common", 1),
            card(14, "Odd rarity", "GD05-002", "Mythic", 1), card(15, "No price", "GD05-003", "Rare", 1),
            card(16, "Not ours", "GD05-099", "Rare", 1), card(17, "Two rows", "GD05-004", "Uncommon", 1),
            card(18, "Null price", "GD05-005", "Common", 1),
        ]),  # fmt: skip
        2: results([card(20, "V2 Gundam", "GD05-001", "Legend Rare", 2)]),
        3: results([card(30, "V2 Gundam promo", "GD05-001", "P", 3)]),
    }
    prices = {
        1: results([price(10, 1.50), price(11, 5.00, "Holofoil"), price(12, 4.00), price(14, 0.50), price(16, 1.0),
                    price(17, 0.40), price(17, 0.30, "Holofoil"), price(18, None)]),
        2: results([price(20, 1.20)]),
        3: results([price(30, 0.10)]),
    }  # fmt: skip
    return RawDump(UPDATED, groups, products, prices)


CATALOG = [N(f"GD05-00{i}") for i in range(1, 7)]  # GD05-006 has no product at all


def test_rarity_names_and_codes_resolve_and_a_plus_marks_an_alt_art() -> None:
    assert parse_rarity("Legend Rare") == (Rarity.LR, 0) and parse_rarity("LR+") == (Rarity.LR, 1) and parse_rarity("LR++") == (Rarity.LR, 2)
    assert parse_rarity("Common") == (Rarity.C, 0) and parse_rarity("C+") == (Rarity.C, 1) and parse_rarity("UC") == (Rarity.U, 0)
    assert parse_rarity("Promo") == (Rarity.P, 0)  # the promo groups write the whole word
    assert parse_rarity("Mythic") == (None, 0) and parse_rarity("Mythic+") == (None, 1)


def test_identification_reads_numbers_alt_arts_promos_and_prices() -> None:
    products, issues = parse_dump(dump())
    by_id = {int(p.product_id): p for p in products}
    assert [int(p.product_id) for p in products] == sorted(by_id)  # sorted, deterministic
    assert by_id[10].buyable and by_id[10].price_cents == 150 and by_id[10].rarity is Rarity.LR
    assert by_id[11].alt_art_level == 1 and not by_id[11].buyable  # an alt art is never bought
    assert by_id[12].card_number is None and not by_id[12].buyable  # a sealed product
    assert by_id[30].promo and not by_id[30].buyable  # a promo group
    assert by_id[17].price_cents == 30  # two price rows: the cheapest
    assert by_id[14].rarity is None and by_id[14].buyable  # an unknown rarity is reported, not dropped
    kinds = {i.kind for i in issues}
    assert kinds == {IssueKind.BAD_NUMBER, IssueKind.UNKNOWN_RARITY, IssueKind.NULL_PRICE, IssueKind.MULTIPLE_PRICE_ROWS, IssueKind.NO_PRICE_ROW}


def test_a_cards_price_is_the_cheapest_buyable_product_across_groups() -> None:
    products, _ = parse_dump(dump())
    prices, unpriced, issues = choose_prices(products, CATALOG, PULLED)
    got = {p.card_number: (p.price_cents, int(p.product_id)) for p in prices}
    assert got[N("GD05-001")] == (120, 20)  # the SC01 reprint beats the set's own printing; the alt art and promo never count
    assert got[N("GD05-002")] == (50, 14) and got[N("GD05-004")] == (30, 17)
    assert [p.card_number for p in prices] == sorted(p.card_number for p in prices)  # sorted by card number
    assert unpriced == (N("GD05-003"), N("GD05-005"), N("GD05-006"))
    assert [(i.kind, i.detail) for i in issues] == [(IssueKind.NUMBER_NOT_IN_CATALOG, "GD05-099")]
    assert all(p.fetched_at == PULLED for p in prices)


def test_the_reason_a_card_has_no_price_is_given_in_words() -> None:
    products, _ = parse_dump(dump())
    assert why_unpriced(N("GD05-006"), products) == "no TCGPlayer product with this card number"
    assert why_unpriced(N("GD05-003"), products) == "no price row for its products"
    only_alt = [p for p in products if p.card_number == N("GD05-001") and p.alt_art_level > 0]
    assert why_unpriced(N("GD05-001"), only_alt) == "only alt-art products (never bought)"


class FakeFetcher:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str | None, bool]] = []

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        self.calls.append((url, cache_key, force))
        return Response(url, self.answers[url], PULLED, from_cache=False)


def test_a_dump_is_fetched_group_by_group_and_cached_under_its_own_folder() -> None:
    d = dump()
    base = "https://tcgcsv.com/tcgplayer/86"
    answers = {f"{base}/groups": d.groups}
    for gid in d.products:
        answers[f"{base}/{gid}/products"] = d.products[gid]
        answers[f"{base}/{gid}/prices"] = d.prices[gid]
    fetcher = FakeFetcher(answers)
    got = fetch_dump(fetcher, UPDATED)
    assert len(fetcher.calls) == 1 + 2 * 3 and got.products == d.products and got.prices == d.prices
    assert all(key is not None and key.startswith("20261008T200609Z/") for _, key, _ in fetcher.calls)
    assert not any(force for _, _, force in fetcher.calls)
    forced = FakeFetcher(answers)
    fetch_dump(forced, UPDATED, force=True)
    assert all(force for _, _, force in forced.calls)


def test_updated_stamps_parse_and_a_changed_answer_fails_loudly() -> None:
    assert parse_updated("2026-10-08T20:06:09+0000\n") == UPDATED and stamp_of(UPDATED) == "20261008T200609Z"
    with pytest.raises(TcgcsvError):
        parse_updated("yesterday")
    bad = RawDump(UPDATED, json.dumps({"success": False, "results": []}), {}, {})
    with pytest.raises(TcgcsvError):
        parse_dump(bad)


def test_a_saved_dump_reads_back_the_same(tmp_path: Path) -> None:
    d = dump()
    folder = tmp_path / "tcgcsv" / stamp_of(UPDATED)
    folder.mkdir(parents=True)
    (folder / "groups.json").write_text(d.groups, encoding="utf-8")
    for gid in d.products:
        (folder / f"{gid}_products.json").write_text(d.products[gid], encoding="utf-8")
        (folder / f"{gid}_prices.json").write_text(d.prices[gid], encoding="utf-8")
    assert raw_dump_stamps(tmp_path) == ("20261008T200609Z",)
    assert read_raw_dump("20261008T200609Z", tmp_path) == d
    assert parse_dump(read_raw_dump("20261008T200609Z", tmp_path)) == parse_dump(d)


TRAITS = frozenset(Trait(t) for t in ("Earth Federation", "White Base Team", "G Generation", "Newtype", "Cyber-Newtype", "Teiwaz", "Tekkadan"))


def test_prices_round_trip_and_join_onto_cards_without_touching_them(tmp_path: Path, page: Callable[[str], SourcePage]) -> None:
    cards = tuple(build_card([page(i)], TRAITS, {}).card for i in ("ST01-001", "GD05-111", "ST01-010"))
    cards_file = CardsFile(generated_at=PULLED, data=cards)
    (tmp_path / "cards.json").write_text(cards_file.model_dump_json(), encoding="utf-8")
    before = (tmp_path / "cards.json").read_bytes()
    assert load_prices(tmp_path) is None and all(p.latest_tcg_price is None for p in load_cards_with_prices(tmp_path))  # no prices yet
    row = CardPrice(card_number=N("ST01-001"), price_cents=25, product_id=ProductId(7), fetched_at=PULLED)
    file = PriceFile(generated_at=PULLED, source_updated_at=UPDATED, data=(row,))
    write_prices(file, tmp_path)
    assert load_prices(tmp_path) == file
    joined = load_cards_with_prices(tmp_path)
    assert [str(p.card.number) for p in joined] == [str(c.number) for c in cards]  # every card exactly once, in order
    assert {str(p.card.number): p.latest_tcg_price for p in joined} == {"ST01-001": row, "GD05-111": None, "ST01-010": None}
    assert (tmp_path / "cards.json").read_bytes() == before  # a price sync never rewrites the card facts
