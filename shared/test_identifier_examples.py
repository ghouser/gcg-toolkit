"""AC-4: the identifier examples shipped for other apps (docs/identifier-examples.json) match the toolkit's own identifier types:
every valid value is accepted and every invalid one rejected."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, PrintingId, SetCode, ValidatedStr

EXAMPLES = json.loads((Path(__file__).resolve().parents[1] / "docs" / "identifier-examples.json").read_text(encoding="utf-8"))
TYPES: dict[str, type[ValidatedStr]] = {"card_number": CardNumber, "printing_id": PrintingId, "set_code": SetCode}
VALID = [(kind, value) for kind in TYPES for value in EXAMPLES[kind]["valid"]]
INVALID = [(kind, value) for kind in TYPES for value in EXAMPLES[kind]["invalid"]]


@pytest.mark.parametrize(("kind", "value"), VALID)
def test_the_toolkit_accepts_every_valid_example(kind: str, value: str) -> None:
    assert TYPES[kind](value) == value


@pytest.mark.parametrize(("kind", "value"), INVALID)
def test_the_toolkit_rejects_every_invalid_example(kind: str, value: str) -> None:
    with pytest.raises(ValueError):
        TYPES[kind](value)


def test_the_examples_include_the_specs_own() -> None:
    valid = {v for kind in TYPES for v in EXAMPLES[kind]["valid"]}
    invalid = {v for kind in TYPES for v in EXAMPLES[kind]["invalid"]}
    assert {"ST01-001", "ST01-001_p5", "R-016", "T-022", "EXB-002"} <= valid
    assert {"st01-001", "ST01-1", "ST01-001_p", "ST01-001_5"} <= invalid
