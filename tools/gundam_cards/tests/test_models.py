"""Model-level guarantees: round trips, determinism, vocabularies."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.basetypes import PilotName, PrintingId, Trait
from tools.gundam_cards.build import SourcePage, build_card
from tools.gundam_cards.models import Block, CardModel, CardsFile, Keyword, LinkCondition, PilotNameLink, TraitLink

IDS = ["ST01-001", "ST01-010", "ST01-015", "GD05-111", "EB01-076", "T-001", "R-002", "EXR-002", "EXB-002", "GD01-047"]
TRAITS = frozenset(Trait(t) for t in ("Earth Federation", "White Base Team", "Newtype", "Cyber-Newtype", "G Generation"))


def _cards(page: Callable[[str], SourcePage]) -> list[CardModel]:
    return [build_card([page(i)], TRAITS, {}).card for i in IDS]


def test_cards_file_round_trips_through_json(page: Callable[[str], SourcePage]) -> None:
    original = CardsFile(generated_at=datetime(2026, 10, 6, tzinfo=UTC), data=tuple(_cards(page)))
    text = original.model_dump_json()
    assert CardsFile.model_validate_json(text) == original  # discriminated union, enums, frozensets all survive
    assert CardsFile.model_validate_json(text).model_dump_json() == text  # deterministic


def test_sets_serialize_sorted(page: Callable[[str], SourcePage]) -> None:
    card = build_card([page("ST01-001")], TRAITS, {}).card
    assert '"keywords":["during_pair","repair"]' in card.model_dump_json()


def test_models_reject_extra_fields_and_bad_identifiers(page: Callable[[str], SourcePage]) -> None:
    card_json = _cards(page)[0].model_dump_json()
    with pytest.raises(ValidationError):
        CardsFile.model_validate_json(
            '{"schema_version":1,"generated_at":"2026-10-06T00:00:00Z","data":[' + card_json[:-1] + ',"surprise":1}]}'
        )
    with pytest.raises(ValidationError):
        CardsFile.model_validate_json(
            '{"schema_version":1,"generated_at":"2026-10-06T00:00:00Z","data":[' + card_json.replace("ST01-001", "nope", 1) + "]}"
        )


def test_unknown_schema_version_is_refused(page: Callable[[str], SourcePage]) -> None:
    with pytest.raises(ValidationError):
        CardsFile.model_validate_json('{"schema_version":2,"generated_at":"2026-10-06T00:00:00Z","data":[]}')


def test_first_printing_must_be_the_base_printing(page: Callable[[str], SourcePage]) -> None:
    card = build_card([page("ST01-001"), page("ST01-001_p5")], TRAITS, {}).card
    with pytest.raises(ValidationError):
        type(card).model_validate({**card.model_dump(), "printings": list(reversed(card.model_dump()["printings"]))})


def test_keyword_vocabulary_is_the_rules_vocabulary() -> None:
    assert len(Keyword) == 21
    assert {k for k in Keyword if k.is_keyword_effect} == {
        Keyword.REPAIR, Keyword.BREACH, Keyword.SUPPORT, Keyword.BLOCKER,
        Keyword.FIRST_STRIKE, Keyword.HIGH_MANEUVER, Keyword.SUPPRESSION, Keyword.DEVELOPMENT,
    }  # fmt: skip


def test_block_order() -> None:
    assert Block.BETA.rank < Block.ONE.rank < Block.TWO.rank


def test_link_condition_needs_at_least_one_requirement() -> None:
    with pytest.raises(ValidationError):
        LinkCondition(any_of=())
    assert LinkCondition(any_of=(TraitLink(trait=Trait("Zeon")), PilotNameLink(fragment=PilotName("Char"))))


def test_printing_id_helpers() -> None:
    assert PrintingId("ST01-001_p5").card_number == "ST01-001"
