"""Tests for shared nominal types."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.basetypes import CardNumber, FrozenModel, PackageId, PilotName, PrintingId, SetCode, SortedFrozenSet, Trait


@pytest.mark.parametrize("value", ["GD05-111", "ST01-001", "EB01-076", "R-016", "T-022", "EXB-002", "EXBP-001", "EXRP-001"])
def test_card_numbers_accepted(value: str) -> None:
    assert CardNumber(value) == value


@pytest.mark.parametrize("value", ["", "gd05-111", "GD05-11", "GD05111", "GD05-111_p1", " GD05-111"])
def test_card_numbers_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        CardNumber(value)


def test_printing_id_parts() -> None:
    base, alt = PrintingId("ST01-001"), PrintingId("ST01-001_p5")
    assert (base.card_number, base.variant) == ("ST01-001", None)
    assert (alt.card_number, alt.variant) == ("ST01-001", 5)
    assert isinstance(alt.card_number, CardNumber)


def test_other_identifiers() -> None:
    assert SetCode("GD05") and PackageId("616105") and Trait("G Generation") and PilotName("Amate Yuzuriha (Machu)")
    for bad in (lambda: SetCode("gd05"), lambda: PackageId("61a"), lambda: Trait(" padded"), lambda: Trait("")):
        with pytest.raises(ValueError):
            bad()


def test_abstract_base_cannot_be_built() -> None:
    from shared.basetypes import ValidatedStr

    with pytest.raises(TypeError):
        ValidatedStr("x")


class _Sample(FrozenModel):
    number: CardNumber
    traits: SortedFrozenSet[Trait]


def test_models_validate_identifiers_and_serialize_deterministically() -> None:
    sample = _Sample.model_validate_json('{"number": "GD05-111", "traits": ["Zeon", "ZAFT", "Zeon"]}')
    assert isinstance(sample.number, CardNumber)
    assert sample.model_dump_json() == '{"number":"GD05-111","traits":["ZAFT","Zeon"]}'
    with pytest.raises(ValidationError):
        _Sample.model_validate_json('{"number": "nope", "traits": []}')
    with pytest.raises(ValidationError):
        _Sample.model_validate_json('{"number": "GD05-111", "traits": [], "extra": 1}')
