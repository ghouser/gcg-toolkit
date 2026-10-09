"""Whole-catalog checks against the saved Bandai pages (skipped when the raw cache isn't present).

These pin the facts of the 2026-10-06 sync: 2,011 printing pages. If Bandai's data changes, or a rule here
changes, they fail on purpose; update the expectations deliberately.
"""
from __future__ import annotations

import collections
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.gundam_cards.build import CatalogResult, IssueKind, build_catalog
from tools.gundam_cards.models import CardKind, CardsFile, CommandCard, Keyword, Rarity, SourceTitlesFile, TraitsFile
from tools.gundam_cards.store import RAW_DIR, load_source_pages, release_dates, load_sets, write_catalog

pytestmark = pytest.mark.corpus
needs_raw = pytest.mark.skipif(not (RAW_DIR / "detail").is_dir(), reason="raw Bandai crawl not present")


@pytest.fixture(scope="module")
def catalog() -> CatalogResult:
    loaded = load_source_pages()
    assert loaded.issues == ()
    return build_catalog(loaded.pages, release_dates(load_sets()))


@needs_raw
def test_every_page_becomes_a_printing(catalog: CatalogResult) -> None:
    assert [i for i in catalog.issues if i.kind is IssueKind.PARSE_FAILURE] == []
    assert len(catalog.cards) == 1152
    assert sum(len(c.printings) for c in catalog.cards) == 2011


@needs_raw
def test_kind_counts(catalog: CatalogResult) -> None:
    counts = collections.Counter(c.kind for c in catalog.cards)
    assert counts == {
        CardKind.UNIT: 600,
        CardKind.COMMAND: 157,
        CardKind.PILOT: 127,
        CardKind.BASE: 72,
        CardKind.RESOURCE: 108,  # includes R-001, which Bandai only lists as alt arts
        CardKind.EX_BASE: 30,  # includes EXB-001, likewise
        CardKind.EX_RESOURCE: 29,  # includes EXR-001, likewise
        CardKind.UNIT_TOKEN: 29,
    }
    assert sum(1 for c in catalog.cards if isinstance(c, CommandCard) and c.pilot is not None) == 68


@needs_raw
def test_vocabularies_are_complete_and_fully_used(catalog: CatalogResult) -> None:
    assert [i for i in catalog.issues if i.kind is IssueKind.UNKNOWN_TAG] == []
    assert {k for c in catalog.cards for k in c.keywords} == set(Keyword)
    assert {p.rarity for c in catalog.cards for p in c.printings} == set(Rarity)
    assert len(catalog.trait_vocabulary) == 78
    assert {t for c in catalog.cards for t in c.referenced_traits} <= catalog.trait_vocabulary


@needs_raw
def test_alt_art_levels(catalog: CatalogResult) -> None:
    levels = collections.Counter(p.alt_art_level for c in catalog.cards for p in c.printings)
    assert set(levels) == {0, 1, 2}
    link_arts = [p for c in catalog.cards for p in c.printings if p.link_art]
    assert link_arts and all(p.alt_art_level >= 1 for p in link_arts)  # every LK printing is also a "+" alt art


@needs_raw
def test_known_data_issues_and_nothing_else(catalog: CatalogResult) -> None:
    """The open cases from the first full sync. Each is explained in design.md; update deliberately."""
    found = collections.defaultdict(set)
    for issue in catalog.issues:
        found[issue.kind].add(issue.subject)
    assert dict(found) == {
        # Card numbers Bandai only lists as alt arts: the lowest alt art is the reference printing.
        IssueKind.NO_BASE_PRINTING: {"EXB-001", "EXR-001", "R-001"},
        # Keyword changed because the rules reworded Link/Pair text; expected, reported for visibility.
        IssueKind.KEYWORDS_CHANGED: {"GD01-005", "GD01-088", "ST02-010"},
        # Alt art/Beta printings whose stats or link differ from the base (Beta stats look shifted).
        IssueKind.PRINTING_ATTRIBUTE_MISMATCH: {
            "GD01-051_p1",
            "R-001_p5",
            "R-001_p6",
            "R-001_p7",
            "T-001_p1",
            "T-002_p1",
            "T-003_p1",
            "T-006_p1",
        },
    }


@needs_raw
def test_files_round_trip(catalog: CatalogResult, tmp_path: Path) -> None:
    now = datetime(2026, 10, 6, tzinfo=UTC)
    write_catalog(catalog, now, tmp_path)
    cards = CardsFile.model_validate_json((tmp_path / "cards.json").read_text(encoding="utf-8"))
    assert cards.data == catalog.cards
    traits = TraitsFile.model_validate_json((tmp_path / "traits.json").read_text(encoding="utf-8"))
    assert {t.trait for t in traits.data} <= catalog.trait_vocabulary
    titles = SourceTitlesFile.model_validate_json((tmp_path / "source_titles.json").read_text(encoding="utf-8"))
    used = {p.source_title for c in catalog.cards for p in c.printings if p.source_title is not None}
    assert {t.source_title for t in titles.data} == used
    assert all(0 < t.card_count <= len(catalog.cards) for t in titles.data)
    first = (tmp_path / "cards.json").read_bytes()
    write_catalog(catalog, now, tmp_path)
    assert (tmp_path / "cards.json").read_bytes() == first  # deterministic
