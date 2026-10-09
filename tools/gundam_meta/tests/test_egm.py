from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.fetch import Response
from tools.gundam_meta.common import GRACE_DAYS, is_complete
from tools.gundam_meta.egm import TOURNAMENTS_URL, EgmParse, fetch_tournaments, parse_deck_url, parse_tournaments
from tools.gundam_meta.models import EventType, Source, Tier

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)


def _parse() -> EgmParse:
    return parse_tournaments((FIXTURES / "egm_tournaments.json").read_text(encoding="utf-8"), NOW)


def test_aggregate_rows_are_not_events() -> None:
    parsed = _parse()
    assert parsed.skipped == ("TAK Games’ Oceania Regionals",)  # a "Total Color Breakdown" row
    assert len(parsed.events) == 4


def test_event_types_and_tiers_follow_your_mapping() -> None:
    by_name = {e.name: e for e in _parse().events}
    milwaukee = by_name["Play!TCG Milwaukee Regionals"]
    assert (milwaukee.event_type, milwaukee.tier) == (EventType.LARGE_OFFICIAL, Tier.MAJOR)
    small = by_name["Olli-Baba Dusseldorf Regionals"]
    assert (small.event_type, small.tier, small.type_raw) == (EventType.SMALL_OFFICIAL, Tier.MAJOR, "Official Event")
    cup = by_name["Egman Events GD05 Cup"]
    assert (cup.event_type, cup.tier) == (EventType.UNOFFICIAL, Tier.LOCAL)


def test_event_fields() -> None:
    milwaukee = next(e for e in _parse().events if "Milwaukee" in e.name)
    assert milwaukee.source is Source.EGM
    assert (milwaukee.start_date, milwaukee.players, milwaukee.rounds) == (date(2026, 10, 5), 500, 9)
    assert milwaukee.format_label == "GD05 + ST11-14" and milwaukee.end_date is None
    assert [d.placement for d in milwaukee.decks] == [1, 6, 11]
    winner = milwaukee.decks[0]
    assert (winner.player_name, winner.name, winner.available, winner.side) == ("Taidana", "ST11-001", True, ())
    assert sum(c.qty for c in winner.main) == 50 and winner.counted


def test_decks_parse_card_by_card() -> None:
    parsed = parse_deck_url("https://deckbuilder.egmanevents.com/?deck=ST11-001:4,ST11-003:4,GD01-100:2&type=gundam")
    assert [(str(c.card_number), c.qty) for c in parsed.main] == [("ST11-001", 4), ("ST11-003", 4), ("GD01-100", 2)]
    assert parsed.side == () and parsed.unresolved == ()
    merged = parse_deck_url("https://x/?deck=ST11-001:2,ST11-001:1")
    assert [(str(c.card_number), c.qty) for c in merged.main] == [("ST11-001", 3)]


def test_a_pipe_marks_the_boundary_between_main_deck_and_sideboard() -> None:
    cup = next(e for e in _parse().events if e.name == "Egman Events GD05 Cup")
    assert len(cup.decks) == 7 and all(d.counted and not d.unresolved for d in cup.decks)
    # Evidence for the reading: main entries up to the "|" total exactly 50 and the rest is a sideboard of exactly 10.
    assert [sum(c.qty for c in d.main) for d in cup.decks] == [50] * 7
    assert [sum(c.qty for c in d.side) for d in cup.decks] == [10] * 7
    first = cup.decks[0]  # "...GD05-042:3,GD02-129:3|GD05-035:3,GD05-112:2,GD04-068:3,GD05-036:1,GD05-128:1"
    assert {str(c.card_number) for c in first.main} >= {"GD05-042", "GD02-129"} and "GD05-035" not in {str(c.card_number) for c in first.main}
    assert {str(c.card_number): c.qty for c in first.side} == {"GD05-035": 3, "GD05-112": 2, "GD04-068": 3, "GD05-036": 1, "GD05-128": 1}


def test_a_boundary_that_does_not_add_up_stays_unresolved() -> None:
    short = parse_deck_url("https://x/?deck=GD01-001:4,GD01-002:4|GD01-003:2,GD01-004:1")  # main is 8 cards, not 50
    assert short.main == () and short.unresolved == ("GD01-002:4|GD01-003:2",)
    two = parse_deck_url("https://x/?deck=GD01-001:4|GD01-002:4,GD01-003:1|GD01-004:1")
    assert two.main == () and len(two.unresolved) == 2
    odd = parse_deck_url("https://x/?deck=nonsense|GD01-003:2")
    assert odd.main == () and odd.unresolved == ("nonsense|GD01-003:2",)


def test_deck_url_without_a_deck_is_unresolved() -> None:
    assert parse_deck_url("https://x/?type=gundam").unresolved == ("https://x/?type=gundam",)


def test_a_changed_shape_fails_loudly() -> None:
    text = (FIXTURES / "egm_tournaments.json").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        parse_tournaments(text.replace('"start_date"', '"date"'), NOW)


class _OneShot:
    def __init__(self) -> None:
        self.calls = 0

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        assert url == TOURNAMENTS_URL
        self.calls += 1
        return Response(url, (FIXTURES / "egm_tournaments.json").read_text(encoding="utf-8"), NOW, from_cache=False)


def test_one_request_returns_everything() -> None:
    fetcher = _OneShot()
    raw, parsed = fetch_tournaments(fetcher)
    assert fetcher.calls == 1 and raw.startswith("[") and len(parsed.events) == 4


def test_completeness_rule() -> None:
    assert GRACE_DAYS == 2
    assert is_complete(date(2026, 10, 4), date(2026, 10, 6))
    assert not is_complete(date(2026, 10, 5), date(2026, 10, 6))
    assert not is_complete(date(2026, 10, 6), date(2026, 10, 6))
