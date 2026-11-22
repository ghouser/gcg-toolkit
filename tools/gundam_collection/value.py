"""What my collection is worth, by price band (no network): my copies times each card's latest TCGPlayer market price.

Each owned printing is valued at its own price when the store has one, else at its card's price: the cheapest buyable (non-alt-art,
non-promo) product's market price for the card number (see gundam_cards design; a stopgap until prices are stored per printing), so an
alt art with no price of its own is valued as the base card. Printings with neither (resources, EX cards, tokens) have no price and
are listed apart.

Bands are contiguous, in whole cents, split at increasing thresholds, and every threshold *opens* the band above it: a card priced at
a threshold or more is in the higher band ("$0.50 and above"). With the default thresholds $0.50, $1, $5 and $10 the bands are:

    under $0.50 | $0.50 to under $1 | $1 to under $5 | $5 to under $10 | $10 or more
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

from shared.basetypes import CardNumber, PrintingId

DEFAULT_THRESHOLDS = (50, 100, 500, 1000)  # cents
SELL_MIN_CENTS = 50  # a card worth at least this is worth selling: the value with the bulk ignored counts only those


@dataclass(frozen=True)
class ValueLine:
    printing: PrintingId
    name: str
    copies: int
    unit_cents: int

    @property
    def total_cents(self) -> int:
        return self.copies * self.unit_cents


@dataclass(frozen=True)
class Band:
    label: str
    lines: tuple[ValueLine, ...]  # most valuable first

    @property
    def cards(self) -> int:
        return len(self.lines)

    @property
    def copies(self) -> int:
        return sum(line.copies for line in self.lines)

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)


@dataclass(frozen=True)
class ValueReport:
    thresholds: tuple[int, ...]
    tiers: tuple[Band, ...]  # lowest price first; one more than the thresholds
    unpriced: tuple[tuple[PrintingId, str, int], ...]  # (printing, name, copies): owned, no price

    @property
    def bulk(self) -> Band:
        """The lowest band (not listed by default)."""
        return self.tiers[0]

    @property
    def bands(self) -> tuple[Band, ...]:
        """Every band above bulk, lowest price first."""
        return self.tiers[1:]

    @property
    def total_cents(self) -> int:
        return sum(b.total_cents for b in self.tiers)

    def sellable(self, min_cents: int = SELL_MIN_CENTS) -> tuple[int, int, int]:
        """Cards priced at `min_cents` or more (the ones worth selling): (value, cards, copies). The value with the bulk ignored."""
        lines = [ln for b in self.tiers for ln in b.lines if ln.unit_cents >= min_cents]
        return sum(ln.total_cents for ln in lines), len(lines), sum(ln.copies for ln in lines)

    def bulk_below(self, min_cents: int = SELL_MIN_CENTS) -> tuple[int, int, int]:
        """Cards priced under `min_cents` (not worth selling): (value, cards, copies)."""
        lines = [ln for b in self.tiers for ln in b.lines if ln.unit_cents < min_cents]
        return sum(ln.total_cents for ln in lines), len(lines), sum(ln.copies for ln in lines)


def _usd(cents: int) -> str:
    return f"${cents // 100:,}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def labels(thresholds: tuple[int, ...]) -> tuple[str, ...]:
    """One label per band, lowest first: `under $0.50`, `$0.50 to under $1`, ..., `$10 or more`."""
    out = [f"under {_usd(thresholds[0])}"]
    out += [f"{_usd(low)} to under {_usd(high)}" for low, high in pairwise(thresholds)]
    out.append(f"{_usd(thresholds[-1])} or more")
    return tuple(out)


def band_index(cents: int, thresholds: tuple[int, ...]) -> int:
    """0 = bulk (under the first threshold), then one more per threshold the price reaches (a price at a threshold is in the band above it)."""
    return sum(1 for t in thresholds if cents >= t)


def analyze(
    owned: Mapping[PrintingId, int],
    printing_prices: Mapping[PrintingId, int],
    prices: Mapping[CardNumber, int],
    names: Mapping[CardNumber, str],
    thresholds: tuple[int, ...] = DEFAULT_THRESHOLDS,
) -> ValueReport:
    if not thresholds or thresholds[0] <= 0 or any(a >= b for a, b in pairwise(thresholds)):
        raise ValueError(f"thresholds must be increasing and positive: {thresholds}")
    grouped: list[list[ValueLine]] = [[] for _ in range(len(thresholds) + 1)]
    unpriced: list[tuple[PrintingId, str, int]] = []
    for printing, copies in owned.items():
        card = printing.card_number
        name = names.get(card, str(card))
        cents = printing_prices.get(printing, prices.get(card))
        if cents is None:
            unpriced.append((printing, name, copies))
            continue
        line = ValueLine(printing, name, copies, cents)
        grouped[band_index(cents, thresholds)].append(line)
    names_ = labels(thresholds)
    made = [Band(names_[i], tuple(sorted(g, key=lambda ln: (-ln.total_cents, -ln.unit_cents, ln.printing)))) for i, g in enumerate(grouped)]
    return ValueReport(thresholds, tuple(made), tuple(sorted(unpriced)))
