"""Whole-dataset checks against the real synced data (skipped when it isn't present).

These pin facts of the 2026-10-06 sync (184 DuelFrontier events, 83 EGM events). Update deliberately when data is added.
"""
from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

import pytest

from tools.gundam_cards.models import CardsFile
from tools.gundam_cards.store import OUT_DIR as CARDS_DIR
from tools.gundam_meta import egm
from tools.gundam_meta.dedupe import combined_events, find_duplicate_groups
from tools.gundam_meta.models import PopularityFile, Source, Tier
from tools.gundam_meta.redo import reparse_duelfrontier, same_content
from tools.gundam_meta.store import OUT_DIR, RAW_DIR, load_events, load_snapshots

pytestmark = pytest.mark.corpus
needs_data = pytest.mark.skipif(
    not (OUT_DIR / "events" / "duelfrontier").is_dir() or not (CARDS_DIR / "cards.json").is_file(),
    reason="synced meta data or card catalog not present",
)


@needs_data
def test_stored_event_counts() -> None:
    events = load_events()
    counts = Counter((e.source, e.tier) for e in events)
    assert counts[(Source.DUELFRONTIER, Tier.MAJOR)] + counts[(Source.DUELFRONTIER, Tier.LOCAL)] == 184
    assert sum(1 for e in events if e.source is Source.EGM) >= 83
    assert not any(e.tier is Tier.OTHER for e in events)  # every event type is one we know
    assert [w for e in events for w in e.warnings] == []  # no odd deck sizes, unknown types or sections


@needs_data
def test_every_deck_card_is_in_the_card_catalog() -> None:
    known = {c.number for c in CardsFile.model_validate_json((CARDS_DIR / "cards.json").read_text(encoding="utf-8")).data}
    used = {c.card_number for e in load_events() for d in e.decks for c in (*d.main, *d.side)}
    assert used <= known, sorted(map(str, used - known))


@needs_data
def test_counted_decks_are_50_card_main_decks() -> None:
    sizes = Counter(sum(c.qty for c in d.main) for e in load_events() for d in e.decks if d.counted)
    assert set(sizes) == {50}


@needs_data
def test_the_only_uncounted_decks_are_private_ones() -> None:
    causes = Counter("unresolved" if d.unresolved else "private" for e in load_events() for d in e.decks if not d.counted)
    assert causes["unresolved"] == 0  # EGM's "A|B" main/sideboard boundary is understood now
    assert causes["private"] >= 1


@needs_data
def test_sideboards_have_at_most_ten_cards() -> None:
    sides = Counter(sum(c.qty for c in d.side) for e in load_events() for d in e.decks if d.counted)
    assert max(sides) <= 10 and sides[10] >= 25  # includes the 25 EGM decks that use the boundary notation


@needs_data
def test_duplicate_events_are_found_and_collapsed() -> None:
    events = load_events()
    groups = find_duplicate_groups(events)
    assert len(groups) == 36
    assert all({g.canonical.source, g.others[0].source} == {Source.DUELFRONTIER, Source.EGM} for g in groups)
    assert len(combined_events(events)) == len(events) - 36
    assert all(g.evidence for g in groups)


@needs_data
def test_popularity_file_loads_and_covers_the_eras() -> None:
    popularity = PopularityFile.model_validate_json((OUT_DIR / "popularity.json").read_text(encoding="utf-8"))
    assert popularity.msa is not None and len(popularity.msa.cards) == 282
    assert {str(t.era) for t in popularity.tournaments} == {"gd05", "gd05_5"}  # gd06 hasn't started
    for t in popularity.tournaments:
        assert t.total_copies == sum(c.copies for c in t.cards)
        assert sum(c.share for c in t.cards) == pytest.approx(1.0)


@needs_data
def test_reparse_from_raw_reproduces_every_stored_duelfrontier_event() -> None:
    if not (RAW_DIR / "duelfrontier" / "events").is_dir():
        pytest.skip("raw DuelFrontier pages not present")
    stored = {e.id: e for e in load_events(source=Source.DUELFRONTIER)}
    with tempfile.TemporaryDirectory() as tmp:
        report = reparse_duelfrontier(RAW_DIR, Path(tmp))
        rebuilt = {e.id: e for e in load_events(Path(tmp), Source.DUELFRONTIER)}
    assert report.failures == ()
    assert rebuilt.keys() == stored.keys()
    assert all(same_content(rebuilt[i], stored[i]) for i in stored)


@needs_data
def test_egm_events_reproduce_from_their_raw_response() -> None:
    stored = load_events(source=Source.EGM)
    for fetched_at in {e.fetched_at for e in stored}:
        path = egm.egm_raw_path(RAW_DIR, fetched_at)
        if not path.is_file():
            pytest.skip("raw EGM response not present")
        rebuilt = {e.id: e for e in egm.parse_tournaments(path.read_text(encoding="utf-8"), fetched_at).events}
        assert all(same_content(rebuilt[e.id], e) for e in stored if e.fetched_at == fetched_at)


@needs_data
def test_online_ranking_snapshot_is_stored() -> None:
    snapshots = load_snapshots()
    assert snapshots and all(len(s.cards) == len({c.card_number for c in s.cards}) for s in snapshots)
