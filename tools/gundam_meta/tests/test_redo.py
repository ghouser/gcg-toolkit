"""Reparse (from saved raw responses, no network) and refetch (from the source), with what each reports as changed."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.fetch import FetchError, Response
from tools.gundam_meta import duelfrontier, egm
from tools.gundam_meta.models import Deck, DeckCard, EventId, Source
from tools.gundam_meta.redo import (
    refetch_duelfrontier,
    refetch_egm,
    reparse_all,
    reparse_duelfrontier,
    reparse_egm,
    same_content,
)
from tools.gundam_meta.store import load_events, load_snapshots, snapshot_key, write_event, write_snapshot

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED = datetime(2026, 10, 6, 20, 0, 0, 123456, tzinfo=UTC)
MKE = EventId("regional-milwaukee-2026")
DECKS = ("HpzTfC4PVUyq4esVEg5akg", "VsjpJtulV0aSbIlXHooXmg", "lPP8hvB2D06UYRBcJxnZSg")


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _seed_duelfrontier_raw(raw: Path) -> None:
    for key, name in [(duelfrontier.event_key(MKE), "df_event_regional_milwaukee.json")] + [
        (duelfrontier.deck_key(d), f"df_deck_{d}.json") for d in DECKS
    ]:
        (raw / key).parent.mkdir(parents=True, exist_ok=True)
        (raw / key).write_text(_read(name), encoding="utf-8")


def _egm_raw(raw: Path) -> None:
    path = egm.egm_raw_path(raw, FETCHED)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_read("egm_tournaments.json"), encoding="utf-8")


# ---- reparse -----------------------------------------------------------------------------------------------------
def test_reparse_duelfrontier_builds_stores_and_is_then_unchanged(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _seed_duelfrontier_raw(raw)
    first = reparse_duelfrontier(raw, out)
    assert first.changed == (f"duelfrontier:{MKE}",) and first.failures == ()  # new: stored
    stored = load_events(out, Source.DUELFRONTIER)
    assert [str(e.id) for e in stored] == [str(MKE)] and len(stored[0].decks) == 3
    second = reparse_duelfrontier(raw, out)
    assert second.changed == () and second.unchanged == (f"duelfrontier:{MKE}",)


def test_reparse_repairs_a_corrupted_stored_event(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _seed_duelfrontier_raw(raw)
    reparse_duelfrontier(raw, out)
    good = load_events(out, Source.DUELFRONTIER)[0]
    broken = good.model_copy(update={"decks": (Deck(id=good.decks[0].id, player_name="x", placement=1, name=None, available=True,
                                                    main=(DeckCard(card_number=good.decks[0].main[0].card_number, qty=1),), side=(), unresolved=()),)})  # fmt: skip
    write_event(broken, out, replace=True)
    report = reparse_duelfrontier(raw, out)
    assert report.changed == (f"duelfrontier:{MKE}",)
    assert load_events(out, Source.DUELFRONTIER)[0] == good


def test_reparse_with_a_missing_raw_deck_fails_and_writes_nothing(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _seed_duelfrontier_raw(raw)
    (raw / duelfrontier.deck_key(DECKS[2])).unlink()
    report = reparse_duelfrontier(raw, out)
    assert report.changed == () and len(report.failures) == 1 and "raw deck page missing" in report.failures[0][1]
    assert load_events(out, Source.DUELFRONTIER) == ()  # a missing page must not silently become a private deck


def test_reparse_egm_uses_the_raw_response_each_event_was_stored_from(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _egm_raw(raw)
    events = egm.parse_tournaments(_read("egm_tournaments.json"), FETCHED).events
    for e in events:
        write_event(e, out)
    clean = reparse_egm(raw, out)
    assert clean.changed == () and len(clean.unchanged) == 4

    tampered = events[0].model_copy(update={"players": 1})
    write_event(tampered, out, replace=True)
    fixed = reparse_egm(raw, out)
    assert fixed.changed == (f"egm:{events[0].id}",)
    assert load_events(out, Source.EGM)[0].players == events[0].players or any(e.players == events[0].players for e in load_events(out, Source.EGM))


def test_reparse_egm_without_its_raw_response_fails(tmp_path: Path) -> None:
    out = tmp_path / "out"
    for e in egm.parse_tournaments(_read("egm_tournaments.json"), FETCHED).events:
        write_event(e, out)
    report = reparse_egm(tmp_path / "raw", out)
    assert report.changed == () and len(report.failures) == 4 and "raw response missing" in report.failures[0][1]


def test_reparse_all_combines_every_source(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _seed_duelfrontier_raw(raw)
    assert len(reparse_all(raw, out).changed) == 1  # DuelFrontier's event; nothing stored for EGM


# ---- refetch -----------------------------------------------------------------------------------------------------
class _Api:
    def __init__(self, texts: dict[str, str], failing: frozenset[str] = frozenset()) -> None:
        self.texts, self.failing = texts, failing
        self.calls: list[tuple[str, bool]] = []

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        self.calls.append((url, force))
        if any(bad in url for bad in self.failing):
            raise FetchError(url, "HTTP 500", 500)
        return Response(url, self.texts[url.split("?")[0]], FETCHED, from_cache=False)


def _df_texts() -> dict[str, str]:
    texts = {f"{duelfrontier.API}/events/{MKE}": _read("df_event_regional_milwaukee.json")}
    texts.update({f"{duelfrontier.API}/decks/{d}": _read(f"df_deck_{d}.json") for d in DECKS})
    return texts


def test_refetch_duelfrontier_replaces_only_what_changed(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _seed_duelfrontier_raw(raw)
    reparse_duelfrontier(raw, out)
    api = _Api(_df_texts())
    same = refetch_duelfrontier(api, raw, out, [MKE])
    assert same.unchanged == (f"duelfrontier:{MKE}",) and all(force for _, force in api.calls)  # always bypasses the cache

    # The source now serves a corrected winning deck (one card swapped): the stored event is replaced.
    corrected = _df_texts()
    key = f"{duelfrontier.API}/decks/{DECKS[0]}"
    corrected[key] = corrected[key].replace('"code": "ST01-015"', '"code": "ST01-011"', 1)
    changed = refetch_duelfrontier(_Api(corrected), raw, out, [MKE])
    assert changed.changed == (f"duelfrontier:{MKE}",)
    new = {str(c.card_number) for c in load_events(out, Source.DUELFRONTIER)[0].decks[0].main}
    assert "ST01-011" in new and "ST01-015" not in new


def test_refetch_duelfrontier_failure_leaves_the_stored_event_alone(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _seed_duelfrontier_raw(raw)
    reparse_duelfrontier(raw, out)
    before = load_events(out, Source.DUELFRONTIER)
    report = refetch_duelfrontier(_Api(_df_texts(), failing=frozenset({DECKS[1]})), raw, out, [MKE])
    assert report.changed == () and len(report.failures) == 1
    assert load_events(out, Source.DUELFRONTIER) == before


def test_refetch_egm_replaces_changed_events_only(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    events = egm.parse_tournaments(_read("egm_tournaments.json"), FETCHED).events
    for e in events:
        write_event(e, out)
    text = _read("egm_tournaments.json")
    assert refetch_egm(_Api({egm.TOURNAMENTS_URL: text}), raw, out).changed == ()  # identical content: nothing replaced

    data = json.loads(text)
    data[0]["player_count"] = 777
    report = refetch_egm(_Api({egm.TOURNAMENTS_URL: json.dumps(data)}), raw, out)
    assert report.changed == (f"egm:{data[0]['id']}",) and len(report.unchanged) == 3
    assert any(e.players == 777 for e in load_events(out, Source.EGM))
    assert any(p.suffix == ".json" for p in (raw / "egm").iterdir())  # raw response kept


def test_refetch_egm_for_chosen_ids_reports_unknown_ones(tmp_path: Path) -> None:
    out = tmp_path / "out"
    events = egm.parse_tournaments(_read("egm_tournaments.json"), FETCHED).events
    for e in events:
        write_event(e, out)
    report = refetch_egm(_Api({egm.TOURNAMENTS_URL: _read("egm_tournaments.json")}), tmp_path / "raw", out, frozenset({events[0].id, EventId("gone")}))
    assert report.unchanged == (f"egm:{events[0].id}",) and report.failures == (("egm:gone", "not in EGM's current list"),)


def test_same_content_ignores_only_the_fetch_time() -> None:
    event = egm.parse_tournaments(_read("egm_tournaments.json"), FETCHED).events[0]
    assert same_content(event, event.model_copy(update={"fetched_at": datetime(2020, 1, 1, tzinfo=UTC)}))
    assert not same_content(event, event.model_copy(update={"name": "other"}))
