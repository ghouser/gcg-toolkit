"""AC-1: the card catalog is append-only. Cards are never removed; a dropped card is kept and marked; each card keeps its first-recorded
date and only its latest data."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.models import CardModel
from tools.gundam_cards.store import load_catalog, write_catalog
from tools.gundam_packages.tests.helpers import unit

T1 = datetime(2026, 10, 1, tzinfo=UTC)
T2 = datetime(2026, 11, 1, tzinfo=UTC)
T3 = datetime(2026, 12, 1, tzinfo=UTC)


def _build(*cards: CardModel) -> CatalogResult:
    return CatalogResult(cards=cards, issues=(), trait_vocabulary=frozenset())


def _records(out: Path) -> dict[str, tuple[datetime, bool]]:
    catalog = load_catalog(out)
    assert catalog is not None
    return {str(r.number): (r.first_recorded, r.no_longer_listed) for r in catalog.records}


def test_an_update_keeps_every_card_and_marks_the_dropped_one(tmp_path: Path) -> None:
    write_catalog(_build(unit("GD01-001", "One"), unit("GD01-002", "Two", text="old text")), T1, tmp_path)
    before = load_catalog(tmp_path)
    assert before is not None
    write_catalog(_build(unit("GD01-002", "Two", text="new text"), unit("GD01-003", "Three")), T2, tmp_path)
    after = load_catalog(tmp_path)
    assert after is not None

    assert {c.number for c in before.data} <= {c.number for c in after.data}  # nothing was removed
    assert len(after.data) >= len(before.data)
    assert after.generated_at == T2  # when it was last refreshed
    assert _records(tmp_path) == {
        "GD01-001": (T1, True),  # the source no longer lists it: kept, marked
        "GD01-002": (T1, False),  # changed: keeps when it was first recorded
        "GD01-003": (T2, False),  # new
    }
    two = next(c for c in after.data if c.number == CardNumber("GD01-002"))
    assert two.text == "new text"  # latest data only, no earlier version kept
    assert "old text" not in (tmp_path / "cards.json").read_text(encoding="utf-8")
    dropped = next(c for c in after.data if c.number == CardNumber("GD01-001"))
    assert dropped == unit("GD01-001", "One")  # its last known data


def test_a_card_that_comes_back_loses_the_mark_and_keeps_its_date(tmp_path: Path) -> None:
    write_catalog(_build(unit("GD01-001", "One")), T1, tmp_path)
    write_catalog(_build(unit("GD01-002", "Two")), T2, tmp_path)
    write_catalog(_build(unit("GD01-001", "One"), unit("GD01-002", "Two")), T3, tmp_path)
    assert _records(tmp_path) == {"GD01-001": (T1, False), "GD01-002": (T2, False)}


def test_an_empty_build_removes_nothing(tmp_path: Path) -> None:
    write_catalog(_build(unit("GD01-001", "One"), unit("GD01-002", "Two")), T1, tmp_path)
    write_catalog(_build(), T2, tmp_path)
    assert _records(tmp_path) == {"GD01-001": (T1, True), "GD01-002": (T1, True)}
