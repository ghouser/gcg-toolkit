"""The card catalog is append-only. Cards are never removed; each card keeps its first-recorded date and only its latest data.
A rebuild without listings (`reparse`) never marks a card; marking takes two consecutive complete refreshes (refresh-cards AC-3)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.models import CardModel
from tools.gundam_cards.store import load_catalog, merge_catalog, save_catalog, write_catalog
from tools.gundam_packages.tests.helpers import unit

T1 = datetime(2026, 10, 1, tzinfo=UTC)
T2 = datetime(2026, 11, 1, tzinfo=UTC)
T3 = datetime(2026, 12, 1, tzinfo=UTC)


def _build(*cards: CardModel) -> CatalogResult:
    return CatalogResult(cards=cards, issues=(), trait_vocabulary=frozenset())


def _refresh(build: CatalogResult, when: datetime, out: Path, listed: frozenset[CardNumber]) -> None:
    """What a complete refresh writes: the build merged with the cards it saw listed."""
    save_catalog(merge_catalog(load_catalog(out), build.cards, when, listed), out)


def _records(out: Path) -> dict[str, tuple[datetime, bool]]:
    catalog = load_catalog(out)
    assert catalog is not None
    return {str(r.number): (r.first_recorded, r.no_longer_listed) for r in catalog.records}


def _missed(out: Path) -> dict[str, tuple[bool, bool]]:
    catalog = load_catalog(out)
    assert catalog is not None
    return {str(r.number): (r.missed_once, r.no_longer_listed) for r in catalog.records}


def test_an_update_keeps_every_card_and_does_not_mark_without_listings(tmp_path: Path) -> None:
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
        "GD01-001": (T1, False),  # not in this build: kept (only complete refreshes mark a card)
        "GD01-002": (T1, False),  # changed: keeps when it was first recorded
        "GD01-003": (T2, False),  # new
    }
    two = next(c for c in after.data if c.number == CardNumber("GD01-002"))
    assert two.text == "new text"  # latest data only, no earlier version kept
    assert "old text" not in (tmp_path / "cards.json").read_text(encoding="utf-8")
    dropped = next(c for c in after.data if c.number == CardNumber("GD01-001"))
    assert dropped == unit("GD01-001", "One")  # its last known data


def test_two_complete_misses_mark_a_card_and_listing_it_again_clears_the_mark(tmp_path: Path) -> None:
    one, two = CardNumber("GD01-001"), CardNumber("GD01-002")
    _refresh(_build(unit("GD01-001", "One"), unit("GD01-002", "Two")), T1, tmp_path, frozenset({one, two}))
    _refresh(_build(unit("GD01-002", "Two")), T2, tmp_path, frozenset({two}))
    assert _missed(tmp_path) == {"GD01-001": (True, False), "GD01-002": (False, False)}  # missed once: nothing visible
    _refresh(_build(unit("GD01-002", "Two")), T3, tmp_path, frozenset({two}))
    assert _missed(tmp_path) == {"GD01-001": (True, True), "GD01-002": (False, False)}  # second miss in a row: marked
    _refresh(_build(unit("GD01-001", "One"), unit("GD01-002", "Two")), T3, tmp_path, frozenset({one, two}))
    assert _missed(tmp_path) == {"GD01-001": (False, False), "GD01-002": (False, False)}
    assert _records(tmp_path)["GD01-001"] == (T1, False)  # keeps its date


def test_a_rebuild_without_listings_keeps_the_marks(tmp_path: Path) -> None:
    one = CardNumber("GD01-001")
    _refresh(_build(unit("GD01-001", "One")), T1, tmp_path, frozenset({one}))
    _refresh(_build(), T2, tmp_path, frozenset())
    write_catalog(_build(unit("GD01-001", "One")), T3, tmp_path)  # reparse: no listings
    assert _missed(tmp_path) == {"GD01-001": (True, False)}


def test_an_empty_build_removes_nothing(tmp_path: Path) -> None:
    write_catalog(_build(unit("GD01-001", "One"), unit("GD01-002", "Two")), T1, tmp_path)
    write_catalog(_build(), T2, tmp_path)
    assert _records(tmp_path) == {"GD01-001": (T1, False), "GD01-002": (T1, False)}
