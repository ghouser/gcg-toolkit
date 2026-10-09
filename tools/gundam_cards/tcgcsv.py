"""TCGPlayer market prices for cards, from tcgcsv.com (a community export of TCGPlayer's catalog). See tools/gundam_cards/design.md.

tcgcsv updates once a day. Its rules, which this follows: a descriptive User-Agent, at least 100 ms between requests (the fetcher uses
500 ms), one pull per day (check `last-updated.txt` first and stop if nothing is new), well under 10,000 requests a day (a full pull is
about 58). TCGPlayer's own sites and APIs are never contacted.

Steps, kept apart so each can be tested and redone without the others:
  fetch_dump   the raw responses (network, cached per dump under the raw folder)
  parse_dump   raw text -> products (no network)
  choose_prices   products + the catalog's card numbers -> one price per card (no network)

Identifying a product needs its rarity: a trailing `+` or `++` on the rarity marks an alt art, which is never bought. A *buyable single*
is a product with a card number that is not an alt art and not in a promo group. A card's price is the cheapest buyable product's market price.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, TypeAdapter

from shared.basetypes import CardNumber, ProductId
from shared.fetch import TextFetcher
from tools.gundam_cards.models import CardPrice, Rarity

BASE_URL = "https://tcgcsv.com"
CATEGORY_ID = 86  # Gundam Card Game
PROMO_WORD = "promo"  # a group whose name has this is a promo group (its cards are not buyable singles)

_BASE_RARITY: Mapping[str, Rarity] = {
    "Common": Rarity.C, "Uncommon": Rarity.U, "Rare": Rarity.R, "Legend Rare": Rarity.LR,
    "C": Rarity.C, "U": Rarity.U, "UC": Rarity.U, "R": Rarity.R, "LR": Rarity.LR, "P": Rarity.P, "Promo": Rarity.P,
}  # fmt: skip


class TcgcsvError(Exception):
    """tcgcsv answered with something we can't read (a changed shape or an error)."""


class IssueKind(StrEnum):
    UNKNOWN_RARITY = "unknown_rarity"  # a rarity we have no mapping for (the product is treated as a normal printing, reported)
    BAD_NUMBER = "bad_number"  # a `Number` that is not shaped like a card number (the product is not matched)
    NUMBER_NOT_IN_CATALOG = "number_not_in_catalog"  # a card number the catalog does not have
    NULL_PRICE = "null_price"  # a price row with no market price (ignored)
    MULTIPLE_PRICE_ROWS = "multiple_price_rows"  # more than one price row for a product (the cheapest is used)
    NO_PRICE_ROW = "no_price_row"  # a card product with no price row


@dataclass(frozen=True)
class Issue:
    kind: IssueKind
    detail: str


# ---- wire formats --------------------------------------------------------------------------------------------------
class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)


class _Group(_Wire):
    groupId: int
    name: str
    abbreviation: str | None = None


class _Extended(_Wire):
    name: str
    value: str


class _Product(_Wire):
    productId: int
    name: str
    groupId: int
    extendedData: tuple[_Extended, ...] = ()


class _Price(_Wire):
    productId: int
    marketPrice: float | None = None
    subTypeName: str = ""


def _results(text: str) -> object:
    node = json.loads(text)
    if not isinstance(node, dict) or node.get("success") is not True or not isinstance(node.get("results"), list):
        raise TcgcsvError(f"unexpected tcgcsv answer: {text[:120]!r}")
    return node["results"]


def parse_updated(text: str) -> datetime:
    """`last-updated.txt`: `2026-10-08T20:06:09+0000`."""
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%dT%H:%M:%S%z").astimezone(UTC)
    except ValueError as e:
        raise TcgcsvError(f"unexpected last-updated value {text.strip()!r}") from e


def stamp_of(updated: datetime) -> str:
    """The folder name for a dump: `20261008T200609Z`."""
    return updated.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


# ---- fetching --------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RawDump:
    source_updated_at: datetime
    groups: str
    products: Mapping[int, str]  # group id -> raw products answer
    prices: Mapping[int, str]  # group id -> raw prices answer


def fetch_updated(fetcher: TextFetcher) -> datetime:
    """When tcgcsv last updated (one request, never cached)."""
    return parse_updated(fetcher.get_text(f"{BASE_URL}/last-updated.txt").text)


def fetch_dump(fetcher: TextFetcher, source_updated_at: datetime, *, force: bool = False, progress: Callable[[str], None] | None = None) -> RawDump:
    """Every group's products and prices. Cached under the dump's own folder, so the same dump is never fetched twice (`force` re-pulls)."""
    stamp = stamp_of(source_updated_at)
    groups_text = fetcher.get_text(f"{BASE_URL}/tcgplayer/{CATEGORY_ID}/groups", cache_key=f"{stamp}/groups.json", force=force).text
    groups = TypeAdapter(tuple[_Group, ...]).validate_json(json.dumps(_results(groups_text)))
    products: dict[int, str] = {}
    prices: dict[int, str] = {}
    for i, group in enumerate(groups, start=1):
        base = f"{BASE_URL}/tcgplayer/{CATEGORY_ID}/{group.groupId}"
        products[group.groupId] = fetcher.get_text(f"{base}/products", cache_key=f"{stamp}/{group.groupId}_products.json", force=force).text
        prices[group.groupId] = fetcher.get_text(f"{base}/prices", cache_key=f"{stamp}/{group.groupId}_prices.json", force=force).text
        if progress is not None:
            progress(f"{i}/{len(groups)} {group.abbreviation or group.name}")
    return RawDump(source_updated_at, groups_text, products, prices)


# ---- parsing -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TcgProduct:
    """One TCGPlayer product, read from tcgcsv. Internal: only the chosen price per card is stored."""

    product_id: ProductId
    group_id: int
    group: str  # the group's abbreviation, or its name when it has none
    name: str
    card_number: CardNumber | None  # None for sealed products
    rarity_raw: str | None
    rarity: Rarity | None
    alt_art_level: int  # 0, or 1 / 2 from a trailing "+" / "++" in the rarity
    promo: bool
    price_cents: int | None  # market price in cents (the cheapest row if there are several); None without one

    @property
    def buyable(self) -> bool:
        return self.card_number is not None and self.alt_art_level == 0 and not self.promo and self.price_cents is not None


def parse_rarity(raw: str) -> tuple[Rarity | None, int]:
    """`Legend Rare` -> (LR, 0); `LR+` -> (LR, 1); `LR++` -> (LR, 2); an unknown base -> (None, level)."""
    text = raw.strip()
    level = 0
    if text.endswith("++"):
        level, text = 2, text[:-2].strip()
    elif text.endswith("+"):
        level, text = 1, text[:-1].strip()
    return _BASE_RARITY.get(text), level


def parse_dump(dump: RawDump) -> tuple[tuple[TcgProduct, ...], tuple[Issue, ...]]:
    issues: list[Issue] = []
    groups = {g.groupId: g for g in TypeAdapter(tuple[_Group, ...]).validate_json(json.dumps(_results(dump.groups)))}
    products: list[TcgProduct] = []
    for group_id, text in sorted(dump.products.items()):
        group = groups[group_id]
        label = group.abbreviation or group.name
        promo = PROMO_WORD in group.name.lower()
        rows = TypeAdapter(tuple[_Price, ...]).validate_json(json.dumps(_results(dump.prices[group_id])))
        cents: dict[int, list[int]] = {}
        for row in rows:
            if row.marketPrice is None:
                issues.append(Issue(IssueKind.NULL_PRICE, f"{label} product {row.productId}"))
                continue
            cents.setdefault(row.productId, []).append(round(row.marketPrice * 100))
        for product in TypeAdapter(tuple[_Product, ...]).validate_json(json.dumps(_results(text))):
            fields = {e.name: e.value for e in product.extendedData}
            number: CardNumber | None = None
            if "Number" in fields:
                try:
                    number = CardNumber(fields["Number"].strip())
                except ValueError:
                    issues.append(Issue(IssueKind.BAD_NUMBER, f"{label} {product.name}: {fields['Number']!r}"))
            rarity_raw = fields.get("Rarity")
            rarity, level = parse_rarity(rarity_raw) if rarity_raw is not None else (None, 0)
            if rarity_raw is not None and rarity is None:
                issues.append(Issue(IssueKind.UNKNOWN_RARITY, f"{label} {product.name}: {rarity_raw!r}"))
            prices = cents.get(product.productId, [])
            if len(prices) > 1:
                issues.append(Issue(IssueKind.MULTIPLE_PRICE_ROWS, f"{label} {product.name}: {len(prices)} rows"))
            if number is not None and not prices:
                issues.append(Issue(IssueKind.NO_PRICE_ROW, f"{label} {product.name}"))
            products.append(TcgProduct(
                product_id=ProductId(product.productId), group_id=group_id, group=label, name=product.name, card_number=number,
                rarity_raw=rarity_raw, rarity=rarity, alt_art_level=level, promo=promo, price_cents=min(prices) if prices else None,
            ))  # fmt: skip
    return tuple(sorted(products, key=lambda p: p.product_id)), tuple(issues)


# ---- choosing the price for each card ------------------------------------------------------------------------------
def buyable_by_card(products: Collection[TcgProduct]) -> dict[CardNumber, list[TcgProduct]]:
    """Every buyable product for each card number, cheapest first."""
    found: dict[CardNumber, list[TcgProduct]] = {}
    for p in products:
        if p.buyable and p.card_number is not None:
            found.setdefault(p.card_number, []).append(p)
    return {n: sorted(ps, key=lambda p: (p.price_cents or 0, p.product_id)) for n, ps in found.items()}


def choose_prices(
    products: Collection[TcgProduct], catalog_numbers: Collection[CardNumber], fetched_at: datetime
) -> tuple[tuple[CardPrice, ...], tuple[CardNumber, ...], tuple[Issue, ...]]:
    """One price per catalog card (the cheapest buyable product), the catalog cards with none, and products whose number is not in the catalog."""
    known = set(catalog_numbers)
    buyable = buyable_by_card(products)
    prices = tuple(
        CardPrice(card_number=n, price_cents=ps[0].price_cents or 0, product_id=ps[0].product_id, name=ps[0].name, set_code=ps[0].group, fetched_at=fetched_at)
        for n, ps in sorted(buyable.items())
        if n in known
    )
    unknown = sorted({p.card_number for p in products if p.card_number is not None and p.card_number not in known})
    issues = tuple(Issue(IssueKind.NUMBER_NOT_IN_CATALOG, str(n)) for n in unknown)
    priced = {p.card_number for p in prices}
    return prices, tuple(sorted(n for n in known if n not in priced)), issues


def why_unpriced(number: CardNumber, products: Collection[TcgProduct]) -> str:
    """Why a card has no price, in words (for the coverage report and `price`)."""
    mine = [p for p in products if p.card_number == number]
    if not mine:
        return "no TCGPlayer product with this card number"
    if all(p.alt_art_level > 0 for p in mine):
        return "only alt-art products (never bought)"
    if all(p.promo or p.alt_art_level > 0 for p in mine):
        return "only promo or alt-art products"
    return "no price row for its products"
