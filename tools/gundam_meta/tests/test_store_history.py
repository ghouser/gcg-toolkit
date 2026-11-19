"""AC-2 for the meta sources: online ranking and example-deck snapshots and in-person events are dated entries that are added, never
rewritten, and not duplicated."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from shared.basetypes import CardNumber
from tools.gundam_meta.models import Event, EventId, EventType, ExampleDecksSnapshot, OnlineRankedCard, OnlineRankingSnapshot, Source
from tools.gundam_meta.store import (
    data_out_dir,
    decks_as_of,
    events_as_of,
    load_decks_snapshot,
    load_snapshots,
    rankings_as_of,
    write_decks_snapshot,
    write_event,
    write_snapshot,
)

T1 = datetime(2026, 10, 6, 22, 32, 17, tzinfo=UTC)
T2 = T1 + timedelta(days=7)


def ranking(generated_at: datetime, rank: int = 1, fetched_at: datetime | None = None) -> OnlineRankingSnapshot:
    return OnlineRankingSnapshot(
        generated_at=generated_at, window_start=generated_at - timedelta(days=14), window_end=generated_at, window_days=14,
        eligible_player_games=100, cards_observed=1, stale=False, fetched_at=fetched_at or generated_at,
        cards=(OnlineRankedCard(card_number=CardNumber("GD01-001"), rank=rank, games_observed=10, appearance_rate_pct=10.0),),
    )  # fmt: skip


def decks(fetched_at: datetime, season: str = "s1") -> ExampleDecksSnapshot:
    return ExampleDecksSnapshot(fetched_at=fetched_at, window_days=14, season=season, archetypes=(), slugs_without_archetype=(),
                                unresolved_lists=())  # fmt: skip


def event(event_id: str, fetched_at: datetime) -> Event:
    return Event(
        source=Source.EGM, id=EventId(event_id), name=event_id, start_date=date(2026, 10, 1), end_date=None, country=None, city=None,
        players=None, rounds=None, event_type=next(iter(EventType)), type_raw="x", format_label=None, decks=(), fetched_at=fetched_at,
        warnings=(),
    )  # fmt: skip


def _files(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.glob("*.json"))}


def test_ranking_snapshots_are_added_and_earlier_ones_stay_byte_identical(tmp_path: Path) -> None:
    assert write_snapshot(ranking(T1), tmp_path)
    before = _files(tmp_path / "online_rankings")
    assert write_snapshot(ranking(T2, rank=2), tmp_path)
    after = _files(tmp_path / "online_rankings")
    assert len(after) == 2 and {k: after[k] for k in before} == before
    assert [s.generated_at for s in load_snapshots(tmp_path)] == [T1, T2]


def test_ranking_identical_or_same_date_adds_nothing(tmp_path: Path) -> None:
    assert write_snapshot(ranking(T1), tmp_path)
    before = _files(tmp_path / "online_rankings")
    assert not write_snapshot(ranking(T1, rank=5), tmp_path)  # same date again
    assert not write_snapshot(ranking(T1, fetched_at=T2), tmp_path)  # same ranking, fetched later
    assert _files(tmp_path / "online_rankings") == before


def test_two_ranking_stores_on_one_utc_day_keep_only_the_first_and_the_next_day_adds_one(tmp_path: Path) -> None:
    assert write_snapshot(ranking(T1), tmp_path)
    before = _files(tmp_path / "online_rankings")
    assert not write_snapshot(ranking(T1.replace(hour=1), rank=5), tmp_path)  # other ranking, same UTC day
    assert _files(tmp_path / "online_rankings") == before
    assert write_snapshot(ranking(T1 + timedelta(days=1), rank=5), tmp_path)
    after = _files(tmp_path / "online_rankings")
    assert len(after) == 2 and {k: after[k] for k in before} == before


def test_two_deck_stores_on_one_utc_day_keep_only_the_first_and_the_next_day_adds_one(tmp_path: Path) -> None:
    first = write_decks_snapshot(decks(T1), tmp_path)
    before = first.read_bytes()
    assert write_decks_snapshot(decks(T1.replace(hour=1), season="other"), tmp_path) == first  # other lists, same UTC day
    assert first.read_bytes() == before and len(_files(tmp_path / "example_decks")) == 1
    second = write_decks_snapshot(decks(T1 + timedelta(days=1), season="other"), tmp_path)
    assert second != first and first.read_bytes() == before and len(_files(tmp_path / "example_decks")) == 2


def test_events_collected_on_one_day_are_each_their_own_entry(tmp_path: Path) -> None:
    assert write_event(event("a", T1), tmp_path)
    path = tmp_path / "events" / "egm" / "a.json"
    before = path.read_bytes()
    assert write_event(event("b", T1.replace(hour=1)), tmp_path)  # another event on the same day: its own entry
    assert not write_event(event("a", T1.replace(hour=1)), tmp_path)  # the same event again that day: nothing added
    assert path.read_bytes() == before and len(list((tmp_path / "events" / "egm").glob("*.json"))) == 2


def test_example_deck_snapshots_are_added_never_rewritten_or_duplicated(tmp_path: Path) -> None:
    first = write_decks_snapshot(decks(T1), tmp_path)
    before = first.read_bytes()
    assert write_decks_snapshot(decks(T1, season="changed"), tmp_path) == first  # same date: not rewritten
    assert write_decks_snapshot(decks(T2), tmp_path) == first  # same lists, fetched later: no new entry
    assert first.read_bytes() == before and len(_files(tmp_path / "example_decks")) == 1
    second = write_decks_snapshot(decks(T2, season="s2"), tmp_path)
    assert second != first and first.read_bytes() == before
    assert load_decks_snapshot(tmp_path) == decks(T2, season="s2")


def test_events_are_one_entry_each_and_never_rewritten_by_a_store(tmp_path: Path) -> None:
    assert write_event(event("a", T1), tmp_path)
    path = tmp_path / "events" / "egm" / "a.json"
    before = path.read_bytes()
    assert not write_event(event("a", T2), tmp_path)  # stored already: unchanged
    assert write_event(event("b", T2), tmp_path)
    assert path.read_bytes() == before
    assert events_as_of(tmp_path) == T2.date()  # the newest collection date


def test_as_of_is_none_when_empty_and_the_newest_date_otherwise(tmp_path: Path) -> None:
    assert (rankings_as_of(tmp_path), decks_as_of(tmp_path), events_as_of(tmp_path)) == (None, None, None)
    write_snapshot(ranking(T1), tmp_path)
    write_snapshot(ranking(T2, rank=2), tmp_path)
    write_decks_snapshot(decks(T1), tmp_path)
    assert (rankings_as_of(tmp_path), decks_as_of(tmp_path)) == (T2.date(), T1.date())


def test_without_a_folder_the_store_writes_into_the_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_DATA_DIR", str(tmp_path / "ds"))
    assert data_out_dir() == tmp_path / "ds" / "gundam_meta"
    write_snapshot(ranking(T1))
    write_event(event("a", T1))
    assert (tmp_path / "ds" / "gundam_meta" / "online_rankings").is_dir() and (tmp_path / "ds" / "gundam_meta" / "events" / "egm" / "a.json").is_file()


def test_example_decks_report_the_newest_of_several_snapshots(tmp_path: Path) -> None:
    write_decks_snapshot(decks(T1), tmp_path)
    write_decks_snapshot(decks(T2, season="s2"), tmp_path)
    assert decks_as_of(tmp_path) == T2.date()  # not the oldest
