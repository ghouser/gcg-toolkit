"""Typed models for the collection file and its check report. See tools/gundam_collection/design.md."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from shared.basetypes import CardNumber, FrozenModel
from tools.gundam_cards.models import CardKind


class Art(StrEnum):
    """Which printing of a card a line records. Ownership counts by card number; the art is kept for the record."""

    BASE = "base"
    ALT = "+"
    ALT_PLUS = "++"
    LINK = "LK"


class Severity(StrEnum):
    ERROR = "error"  # the line cannot be used; fix it
    WARNING = "warning"  # usable, but probably a mistake; check it
    INFO = "info"  # worth knowing


class IssueCode(StrEnum):
    BAD_LINE = "bad_line"  # not "<card number> <quantity>"
    BAD_CARD_NUMBER = "bad_card_number"  # not shaped like a card number
    UNKNOWN_CARD = "unknown_card"  # shaped right, but not in the catalog
    BAD_QUANTITY = "bad_quantity"  # not a whole number from 1 to 99
    NO_SUCH_PRINTING = "no_such_printing"  # the card has no printing with that art marker
    ZERO_COPIES = "zero_copies"  # a quantity of 0
    INCOMPLETE = "incomplete"  # a quantity of "?": a placeholder still to fill in
    DUPLICATE = "duplicate"  # the same card and art on more than one line
    MANY_COPIES = "many_copies"  # an unusually large total for one card number
    NON_DECK_CARD = "non_deck_card"  # a resource, EX resource or token: kept, but not used for deck building


class Entry(FrozenModel):
    """One usable line of the collection file."""

    line: int = Field(ge=1)
    card_number: CardNumber
    art: Art
    copies: int | None  # None for a "?" placeholder


class Issue(FrozenModel):
    line: int | None  # None for a problem with the file as a whole
    severity: Severity
    code: IssueCode
    message: str


class CardInfo(FrozenModel):
    """What the check needs to know about a catalog card."""

    name: str
    kind: CardKind
    arts: frozenset[Art]  # the arts this card is printed in (always includes BASE)


class KindTotal(FrozenModel):
    kind: CardKind
    cards: int
    copies: int


class CheckReport(FrozenModel):
    file: str
    lines_read: int
    entries: tuple[Entry, ...]
    issues: tuple[Issue, ...]
    distinct_cards: int
    total_copies: int  # counted lines only (a "?" counts as nothing)
    by_kind: tuple[KindTotal, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---- the structured collection ---------------------------------------------------------------------------------------
class OwnedPrinting(FrozenModel):
    art: Art
    copies: int = Field(ge=1)


class OwnedCard(FrozenModel):
    """What I own of one card. Ownership counts by card number (any printing satisfies a slot); the arts are kept for the record."""

    card_number: CardNumber
    copies: int = Field(ge=1)  # total across printings
    printings: tuple[OwnedPrinting, ...]


class CollectionFile(FrozenModel):
    """`shared/data/gundam_collection/collection.json`: derived from `my_tcg_collection` by `import`; sorted by card number."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    source_file: str
    data: tuple[OwnedCard, ...]


class Stage(StrEnum):
    """Where a package stands against what I own (design.md, "Home, adjacent and new packages")."""

    HOME = "home"  # I own at least half of its critical copies
    ADJACENT = "adjacent"  # not home, but it shares a critical card or bridge with a home package
    NEW = "new"


class DeckNamesFile(FrozenModel):
    """`deck_names.json` (hand-maintained, written by the `nickname` command): nicknames for decks, by deck id (`GD02-054+ST11-001`)."""

    schema_version: Literal[1] = 1
    data: dict[str, str]
