"""The catalog export: the versioned JSON a separate UI app reads (`gundam_cards export`). See docs/catalog-export.md for the contract.

Pure: built from the stored catalog, the sets and the price snapshots handed in; `store.write_catalog_export` writes it.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Literal

from shared.basetypes import CardNumber, FrozenModel, PrintingId, SetCode
from tools.gundam_cards.events import names_release_event
from tools.gundam_cards.models import (
    CardKind,
    CardModel,
    CardPrice,
    CardSet,
    CardsFile,
    Color,
    PriceFile,
    PrintingPriceFile,
    Rarity,
    SetKind,
    color_of,
    cost_of,
    level_of,
)

EXPORT_SCHEMA_VERSION: Literal[1] = 1  # see "Version policy" in docs/catalog-export.md
_EDITION_BETA = SetCode("BETA")  # teaching copies, never bought or sold: never a card's reference printing (nor, if avoidable, an event printing)


class ExportPrinting(FrozenModel):
    id: PrintingId
    rarity: Rarity
    set_code: SetCode | None = None
    variant: int | None = None  # this and the next two: only on a non-base printing
    alt_art_level: int | None = None
    link_art: bool | None = None
    image_url: str | None = None
    price_cents: int | None = None  # with price_as_of, only when the store has a price for this printing
    price_as_of: date | None = None


class ExportCard(FrozenModel):
    number: CardNumber
    name: str
    kind: CardKind
    no_longer_listed: Literal[True] | None = None
    set_code: SetCode | None = None  # the reference printing's: the first one whose set is not Edition Beta
    color: Color | None = None  # color, level, cost: deck kinds only
    level: int | None = None
    cost: int | None = None
    printings: tuple[ExportPrinting, ...]


class ExportSet(FrozenModel):
    code: SetCode
    name: str
    kind: SetKind
    release_date: date | None = None
    provisional: Literal[True] | None = None  # found by a refresh, not yet in the reviewed sets.json; the name is Bandai's


class ExportKind(FrozenModel):
    kind: CardKind
    deck: bool


class ExportReference(FrozenModel):
    sets: tuple[ExportSet, ...]
    kinds: tuple[ExportKind, ...]
    colors: tuple[Color, ...]
    rarities: tuple[Rarity, ...]


class CatalogExport(FrozenModel):
    schema_version: Literal[1] = EXPORT_SCHEMA_VERSION
    generated_at: datetime
    reference: ExportReference
    cards: tuple[ExportCard, ...]


class MissingSetCodes(Exception):
    """Set codes on cards or printings that the export's `reference.sets` does not have."""

    def __init__(self, codes: tuple[SetCode, ...]) -> None:
        self.codes = codes
        super().__init__("set codes missing from the reference sets: " + ", ".join(codes))


def printing_prices(card: CardModel, rows: tuple[CardPrice, ...]) -> dict[PrintingId, tuple[int, date]]:
    """Price (cents, as-of date) per printing of the card, from the newest of the card's price rows (oldest first) that prices it.

    The store keeps one price per card, from one TCGPlayer product, with that product's set; it is the price of the card's one
    non-alt-art printing in that set, and of no printing when there are none or several (never guessed)."""
    found: dict[PrintingId, tuple[int, date]] = {}
    for row in rows:
        if row.card_number == card.number:
            matches = [p for p in card.printings if p.alt_art_level == 0 and not p.link_art and p.set_code == row.set_code]
            if len(matches) == 1:
                found[matches[0].id] = (row.price_cents, row.fetched_at.date())
    return found


def _sets(tracked: tuple[CardSet, ...], provisional: tuple[CardSet, ...]) -> tuple[ExportSet, ...]:
    tracked_codes = {s.code for s in tracked}
    entries = [(s, False) for s in tracked] + [(s, True) for s in provisional if s.code not in tracked_codes]
    return tuple(
        ExportSet(code=s.code, name=s.name, kind=s.kind, release_date=s.release_date, provisional=True if is_provisional else None)
        for s, is_provisional in sorted(entries, key=lambda e: str(e[0].code))
    )


def _reference_set_code(card: CardModel) -> SetCode | None:
    """The card's set: that of its first printing that is neither Edition Beta nor a release-event printing. When every printing is one
    of those, the first non-Beta printing's (an event-only card is PROMO); None when there is none (or only Beta printings)."""
    non_beta = [p for p in card.printings if p.set_code != _EDITION_BETA]
    ordinary = [p for p in non_beta if not names_release_event(p.where_to_get)]
    return next((p.set_code for p in ordinary or non_beta), None)


def _card(card: CardModel, no_longer_listed: bool, prices: dict[PrintingId, tuple[int, date]]) -> ExportCard:
    printings = tuple(
        ExportPrinting(
            id=p.id,
            rarity=p.rarity,
            set_code=p.set_code,
            variant=p.variant,
            alt_art_level=None if p.variant is None else p.alt_art_level,
            link_art=None if p.variant is None else p.link_art,
            image_url=p.image_url,
            price_cents=prices[p.id][0] if p.id in prices else None,
            price_as_of=prices[p.id][1] if p.id in prices else None,
        )
        for p in card.printings
    )
    return ExportCard(
        number=card.number,
        name=card.name,
        kind=card.kind,
        no_longer_listed=True if no_longer_listed else None,
        set_code=_reference_set_code(card),
        color=color_of(card),
        level=level_of(card),
        cost=cost_of(card),
        printings=printings,
    )


def build_export(
    catalog: CardsFile,
    tracked_sets: tuple[CardSet, ...],
    provisional_sets: tuple[CardSet, ...],
    price_history: tuple[PriceFile, ...],
    printing_price_history: tuple[PrintingPriceFile, ...],
    generated_at: datetime,
) -> CatalogExport:
    """Every catalog card (those no longer listed included and flagged) and the reference section. Raises `MissingSetCodes` when a
    printing's set code is not in the reference sets."""
    sets = _sets(tracked_sets, provisional_sets)
    known = {s.code for s in sets}
    missing = sorted({p.set_code for c in catalog.data for p in c.printings if p.set_code is not None and p.set_code not in known})
    if missing:
        raise MissingSetCodes(tuple(missing))
    unlisted = {r.number for r in catalog.records if r.no_longer_listed}
    reference = ExportReference(
        sets=sets,
        kinds=tuple(ExportKind(kind=k, deck=k.is_deck_card) for k in CardKind),
        colors=tuple(Color),
        rarities=tuple(Rarity),
    )
    if printing_price_history:  # each printing's own price, from the newest per-printing snapshot: no stopgap
        own = {r.printing_id: (r.price_cents, r.fetched_at.date()) for r in printing_price_history[-1].data}
        cards = tuple(_card(c, c.number in unlisted, {p.id: own[p.id] for p in c.printings if p.id in own}) for c in catalog.data)
    else:  # until the first per-printing snapshot: the per-card snapshots, matched to the card's one printing in the product's set
        rows: dict[CardNumber, list[CardPrice]] = defaultdict(list)
        for snapshot in price_history:
            for row in snapshot.data:
                rows[row.card_number].append(row)
        cards = tuple(_card(c, c.number in unlisted, printing_prices(c, tuple(rows[c.number]))) for c in catalog.data)
    return CatalogExport(generated_at=generated_at, reference=reference, cards=cards)


def export_json(export: CatalogExport) -> str:
    """The export as indented JSON with every field that does not apply left out (no `null` anywhere)."""
    return json.dumps(json.loads(export.model_dump_json(exclude_none=True)), ensure_ascii=False, indent=1) + "\n"
