"""The identifier examples shipped for other apps (docs/identifier-examples.json) against both the patterns the catalog contract
documents (docs/catalog-export.md, Identifiers) and the toolkit's own identifier types: every valid value matches both, every invalid
one matches neither. Reading the contract here is the stated exception in docs/testing.md.

toolkit-hardening AC-1: an identifier with a non-ASCII digit (Arabic-Indic, fullwidth) is invalid, in the contract and in the toolkit."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, PrintingId, SetCode, ValidatedStr

DOCS = Path(__file__).resolve().parents[1] / "docs"
EXAMPLES = json.loads((DOCS / "identifier-examples.json").read_text(encoding="utf-8"))
TYPES: dict[str, type[ValidatedStr]] = {"card_number": CardNumber, "printing_id": PrintingId, "set_code": SetCode}
ROWS = {"Card number": "card_number", "Printing id": "printing_id", "Set code": "set_code"}
VALID = [(kind, value) for kind in TYPES for value in EXAMPLES[kind]["valid"]]
INVALID = [(kind, value) for kind in TYPES for value in EXAMPLES[kind]["invalid"]]


def documented_patterns() -> dict[str, re.Pattern[str]]:
    """The shape column of the contract's identifier table, by identifier."""
    text = (DOCS / "catalog-export.md").read_text(encoding="utf-8")
    found = {ROWS[name]: re.compile(shape) for name, shape in re.findall(r"^\| ([^|]+?) \| `([^`]+)` \|", text, flags=re.M) if name in ROWS}
    assert set(found) == set(TYPES)
    return found


@pytest.mark.parametrize(("kind", "value"), VALID)
def test_every_valid_example_matches_the_contract_and_the_toolkit(kind: str, value: str) -> None:
    assert documented_patterns()[kind].fullmatch(value) is not None
    assert TYPES[kind](value) == value


@pytest.mark.parametrize(("kind", "value"), INVALID)
def test_every_invalid_example_matches_neither_the_contract_nor_the_toolkit(kind: str, value: str) -> None:
    assert documented_patterns()[kind].fullmatch(value) is None
    with pytest.raises(ValueError):
        TYPES[kind](value)


def test_the_examples_include_the_specs_own() -> None:
    valid = {v for kind in TYPES for v in EXAMPLES[kind]["valid"]}
    invalid = {v for kind in TYPES for v in EXAMPLES[kind]["invalid"]}
    assert {"ST01-001", "ST01-001_p5", "R-016", "T-022", "EXB-002"} <= valid
    assert {"st01-001", "ST01-1", "ST01-001_p", "ST01-001_5"} <= invalid


def test_the_invalid_examples_include_non_ascii_digits_in_every_digit_position() -> None:
    card, printing, code = (set(EXAMPLES[k]["invalid"]) for k in ("card_number", "printing_id", "set_code"))
    assert {"ST٠١-001", "ST01-٠٠١"} <= card  # after the set letters; in the three-digit part
    assert {"ST٠١-001_p5", "ST01-٠٠١_p5", "ST01-001_p٥"} <= printing  # ... and in the _p number
    assert {"GD０５", "ST٠١"} <= code
