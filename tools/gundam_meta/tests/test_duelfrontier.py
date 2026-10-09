from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.fetch import FetchError, Response
from tools.gundam_meta.duelfrontier import (
    API,
    ListedEvent,
    deck_key,
    event_key,
    parse_event,
    parse_event_page,
    sync_events,
)
from tools.gundam_meta.models import EventId, EventType, Source, Tier

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
MKE = "regional-milwaukee-2026"
WCQ = "wcq-grand-final-2526"
PUBLIC_WINNER, PRIVATE, PUBLIC_THIRD = "HpzTfC4PVUyq4esVEg5akg", "VsjpJtulV0aSbIlXHooXmg", "lPP8hvB2D06UYRBcJxnZSg"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _decks(*slugs: str) -> dict[str, str | None]:
    return {s: _read(f"df_deck_{s}.json") for s in slugs}


def _wcq_deck_slug() -> str:
    return str(json.loads(_read("df_event_wcq_grand_final.json"))["data"]["players"][0]["deckSlug"])


def test_event_list_page() -> None:
    events, pages = parse_event_page(_read("df_events_list.json"))
    assert len(events) == 4 and pages > 1
    assert events[0] == ListedEvent(EventId(MKE), date(2026, 10, 3), date(2026, 10, 4), 16)


def test_regional_with_a_private_deck() -> None:
    event = parse_event(_read("df_event_regional_milwaukee.json"), _decks(PUBLIC_WINNER, PRIVATE, PUBLIC_THIRD), NOW)
    assert (event.source, str(event.id), event.event_type, event.tier) == (Source.DUELFRONTIER, MKE, EventType.REGIONAL, Tier.MAJOR)
    assert (event.name, event.start_date, event.end_date, event.country, event.city, event.players) == (
        "Regional Milwaukee 2026", date(2026, 10, 3), date(2026, 10, 4), "US", "Milwaukee, WI", 500,
    )  # fmt: skip
    assert event.type_raw == "16" and event.warnings == ()

    winner, private, third = event.decks
    assert (winner.placement, winner.name, winner.available, winner.counted) == (1, "B/P Z'Gok Aggro", True, True)
    assert sum(c.qty for c in winner.main) == 50 and winner.side == ()
    assert (private.placement, private.available, private.counted, private.main) == (2, False, False, ())  # recorded, not bypassed
    assert third.available and sum(c.qty for c in third.main) == 50


def test_deck_entries_are_aggregated_per_card() -> None:
    event = parse_event(_read("df_event_regional_milwaukee.json"), _decks(PUBLIC_WINNER, PRIVATE, PUBLIC_THIRD), NOW)
    main = {str(c.card_number): c.qty for c in event.decks[0].main}
    assert main["ST01-015"] == 1 and main["ST02-016"] == 2 and len(main) == len(event.decks[0].main)  # one entry per card


def test_a_missing_deck_response_is_unavailable() -> None:
    event = parse_event(_read("df_event_regional_milwaukee.json"), {PUBLIC_WINNER: None}, NOW)
    assert not any(d.available for d in event.decks)


def test_world_championship_event_with_a_sideboard() -> None:
    slug = _wcq_deck_slug()
    event = parse_event(_read("df_event_wcq_grand_final.json"), _decks(slug), NOW)
    assert (event.event_type, event.tier) == (EventType.WORLD_CHAMPIONSHIP, Tier.MAJOR)  # qualifiers count as major
    deck = event.decks[0]
    assert (sum(c.qty for c in deck.main), sum(c.qty for c in deck.side)) == (50, 10)  # the sideboard is kept and counted
    assert deck.counted and event.warnings == ()


def test_unrecognized_event_type_is_kept_as_other_with_a_warning() -> None:
    text = _read("df_event_regional_milwaukee.json").replace('"type": 16', '"type": 999')
    event = parse_event(text, _decks(PUBLIC_WINNER, PRIVATE, PUBLIC_THIRD), NOW)
    assert (event.event_type, event.tier, event.type_raw) == (EventType.OTHER, Tier.OTHER, "999")
    assert "unrecognized event type code 999" in event.warnings


def test_odd_deck_sizes_are_warned_about() -> None:
    deck = _read(f"df_deck_{PUBLIC_WINNER}.json")
    short = deck.replace('"section": 0', '"section": 1', 1)  # moves one card to the sideboard: 49 main
    event = parse_event(_read("df_event_regional_milwaukee.json"), {PUBLIC_WINNER: short}, NOW)
    assert any("main deck has 49 cards" in w for w in event.warnings)


def test_unknown_section_is_unresolved_not_dropped() -> None:
    deck = _read(f"df_deck_{PUBLIC_WINNER}.json").replace('"section": 0', '"section": 7', 1)
    event = parse_event(_read("df_event_regional_milwaukee.json"), {PUBLIC_WINNER: deck}, NOW)
    assert event.decks[0].unresolved and not event.decks[0].counted


def test_a_changed_shape_fails_loudly() -> None:
    with pytest.raises(ValidationError):
        parse_event(_read("df_event_regional_milwaukee.json").replace('"startDate"', '"start"'), {}, NOW)


# ---- syncing ------------------------------------------------------------------------------------------------
class _FakeApi:
    """Serves the saved event and deck responses, writes the cache like the real fetcher, records every URL."""

    def __init__(self, raw_dir: Path, failing: frozenset[str] = frozenset()) -> None:
        self.raw_dir, self.failing = raw_dir, failing
        self.urls: list[str] = []
        self.events = {MKE: _read("df_event_regional_milwaukee.json"), WCQ: _read("df_event_wcq_grand_final.json")}
        self.decks = {s: _read(f"df_deck_{s}.json") for s in (PUBLIC_WINNER, PRIVATE, PUBLIC_THIRD, _wcq_deck_slug())}

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        self.urls.append(url)
        slug = url.split("?")[0].rsplit("/", 1)[1]
        if slug in self.failing:
            raise FetchError(url, "HTTP 500", 500)
        text = self.events[slug] if "/events/" in url else self.decks[slug]
        if cache_key is not None:
            path = self.raw_dir / cache_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return Response(url, text, NOW, from_cache=False)


LISTED = (
    ListedEvent(EventId(MKE), date(2026, 10, 3), date(2026, 10, 4), 16),
    ListedEvent(EventId(WCQ), date(2026, 3, 13), date(2026, 3, 14), 64),
    ListedEvent(EventId("still-running"), date(2026, 10, 5), date(2026, 10, 6), 16),
)
TODAY = date(2026, 10, 6)


def test_sync_fetches_only_new_complete_events(tmp_path: Path) -> None:
    api = _FakeApi(tmp_path)
    result = sync_events(api, tmp_path, LISTED, frozenset({EventId(WCQ)}), TODAY)
    assert [str(e.id) for e in result.events] == [MKE]
    assert (result.listed, result.already_stored, result.not_complete_yet, result.failures) == (3, 1, 1, ())
    assert api.urls == [
        f"{API}/events/{MKE}?Include=Players",
        f"{API}/decks/{PUBLIC_WINNER}?Include=Cards",
        f"{API}/decks/{PRIVATE}?Include=Cards",
        f"{API}/decks/{PUBLIC_THIRD}?Include=Cards",
    ]  # nothing for the stored event, nothing for the one still running
    assert (tmp_path / event_key(EventId(MKE))).is_file() and (tmp_path / deck_key(PRIVATE)).is_file()  # raw pages cached


def test_nothing_to_fetch_means_no_requests(tmp_path: Path) -> None:
    api = _FakeApi(tmp_path)
    result = sync_events(api, tmp_path, LISTED, frozenset({EventId(MKE), EventId(WCQ)}), TODAY)
    assert result.events == () and api.urls == []


def test_one_failing_event_does_not_stop_the_rest(tmp_path: Path) -> None:
    api = _FakeApi(tmp_path, failing=frozenset({MKE}))
    result = sync_events(api, tmp_path, LISTED, frozenset(), TODAY)
    assert [str(e.id) for e in result.events] == [WCQ]
    assert [str(i) for i, _ in result.failures] == [MKE]


def test_a_complete_event_with_no_results_yet_is_retried_later(tmp_path: Path) -> None:
    api = _FakeApi(tmp_path)
    data = json.loads(api.events[MKE])
    data["data"]["players"] = []
    api.events[MKE] = json.dumps(data)
    result = sync_events(api, tmp_path, LISTED[:1], frozenset(), TODAY)
    assert result.events == () and result.waiting_for_results == 1
    assert not (tmp_path / event_key(EventId(MKE))).exists()  # not cached, so a later sync fetches it fresh
