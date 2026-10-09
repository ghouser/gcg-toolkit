"""Shared nominal types and base model config.

Identifiers are `str` subclasses that validate their format on construction and inside pydantic models, so a
`CardNumber` can never be passed where a `SetCode` is expected, and a malformed value can't exist at all.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, NewType, Self, TypeVar

from pydantic import BaseModel, ConfigDict, GetCoreSchemaHandler, PlainSerializer
from pydantic_core import CoreSchema, core_schema


class ValidatedStr(str):
    """A `str` whose value must match `pattern`. Subclass and set `pattern` (and `label` for error messages)."""

    pattern: ClassVar[re.Pattern[str]]
    label: ClassVar[str]

    def __new__(cls, value: str) -> Self:
        if cls is ValidatedStr:
            raise TypeError("ValidatedStr is abstract; use a subclass")
        if not isinstance(value, str) or cls.pattern.fullmatch(value) is None:
            raise ValueError(f"not a valid {cls.label}: {value!r}")
        return super().__new__(cls, value)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(strict=True),
            serialization=core_schema.plain_serializer_function_ser_schema(str, return_schema=core_schema.str_schema()),
        )


class CardNumber(ValidatedStr):
    """`GD05-111`, `ST01-001`, `EB01-076`, `R-016` (resource), `T-022` (token), `EXB-002`, `EXBP-001`."""

    pattern = re.compile(r"[A-Z]+\d*-\d{3}")
    label = "card number"


class PrintingId(ValidatedStr):
    """A Bandai printing id: a card number, optionally followed by `_p<N>` for a parallel/alt-art printing."""

    pattern = re.compile(r"[A-Z]+\d*-\d{3}(?:_p\d+)?")
    label = "printing id"

    @property
    def card_number(self) -> CardNumber:
        return CardNumber(self.split("_p", 1)[0])

    @property
    def variant(self) -> int | None:
        _, sep, n = self.partition("_p")
        return int(n) if sep else None


class SetCode(ValidatedStr):
    """`GD05`, `ST11`, `EB01`, `SC01`, `PB01`, or a synthetic code for packages without one (`PROMO`, `BETA`)."""

    pattern = re.compile(r"[A-Z][A-Z0-9]+")
    label = "set code"


class PackageId(ValidatedStr):
    """Bandai's numeric package id, e.g. `616105`."""

    pattern = re.compile(r"\d+")
    label = "package id"


class NonEmptyStr(ValidatedStr):
    """Base for open-vocabulary names: non-empty, no leading/trailing whitespace, no line breaks."""

    pattern = re.compile(r"\S(?:[^\n\r]*\S)?")
    label = "name"


class Trait(NonEmptyStr):
    """A card trait as the rules call it, e.g. `G Generation`, `Earth Federation`. Open vocabulary (see traits.json)."""

    label = "trait"


class PilotName(NonEmptyStr):
    """A pilot's name, e.g. `Amuro Ray`, `Amate Yuzuriha (Machu)`."""

    label = "pilot name"


class SourceTitle(NonEmptyStr):
    """The TV series or game a card is from, e.g. `Mobile Suit Gundam SEED`."""

    label = "source title"


ProductId = NewType("ProductId", int)
Cents = NewType("Cents", int)


class FrozenModel(BaseModel):
    """Base for all models: immutable, no unknown fields, no implicit coercion."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


_T = TypeVar("_T")


def _sorted_list(values: frozenset[Any]) -> list[Any]:
    return sorted(values)


# A frozenset that serializes as a sorted list, so files are deterministic.
SortedFrozenSet = Annotated[frozenset[_T], PlainSerializer(_sorted_list, return_type=list[Any])]
