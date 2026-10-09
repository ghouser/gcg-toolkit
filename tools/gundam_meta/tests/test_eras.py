from __future__ import annotations

from datetime import date

import pytest

from shared.basetypes import SetCode
from tools.gundam_cards.store import load_sets, release_dates
from tools.gundam_meta.eras import EraError, current_era, era_on, find_era, load_era_defs, resolve_eras
from tools.gundam_meta.models import EraDef, EraId

DATES = {
    SetCode("GD05"): date(2026, 7, 24),
    SetCode("ST11"): date(2026, 9, 25),
    SetCode("ST12"): date(2026, 9, 25),
    SetCode("ST13"): date(2026, 9, 25),
    SetCode("ST14"): date(2026, 9, 25),
    SetCode("GD06"): date(2026, 10, 30),
}


def test_the_agreed_eras_resolve_to_the_agreed_dates() -> None:
    eras = resolve_eras(load_era_defs(), DATES)
    assert [(str(e.id), e.definition.label, str(e.start), str(e.end)) for e in eras] == [
        ("gd05", "GD05", "2026-07-24", "2026-09-25"),
        ("gd05_5", "GD05.5", "2026-09-25", "2026-10-30"),
        ("gd06", "GD06", "2026-10-30", "None"),
    ]


def test_current_era_follows_the_calendar() -> None:
    eras = resolve_eras(load_era_defs(), DATES)
    assert current_era(eras, date(2026, 10, 6)) == eras[1]  # GD05.5 today
    assert current_era(eras, date(2026, 10, 29)) == eras[1]
    assert current_era(eras, date(2026, 10, 30)) == eras[2]  # GD06 starts a new window on its release date
    assert current_era(eras, date(2026, 7, 23)) is None  # before the first era
    assert era_on(eras, date(2026, 9, 24)) == eras[0] and era_on(eras, date(2026, 9, 25)) == eras[1]


def test_an_era_whose_anchors_have_no_date_is_left_out() -> None:
    partial = {k: v for k, v in DATES.items() if k != "GD06"}
    assert [str(e.id) for e in resolve_eras(load_era_defs(), partial)] == ["gd05", "gd05_5"]
    # a multi-set era needs every anchor dated
    del partial[SetCode("ST14")]
    assert [str(e.id) for e in resolve_eras(load_era_defs(), partial)] == ["gd05"]


def test_the_latest_anchor_date_starts_the_era() -> None:
    defs = (EraDef(id=EraId("x"), label="X", anchor_sets=(SetCode("GD05"), SetCode("ST11"))),)
    assert resolve_eras(defs, DATES)[0].start == date(2026, 9, 25)


def test_same_start_day_is_an_error() -> None:
    defs = (
        EraDef(id=EraId("a"), label="A", anchor_sets=(SetCode("ST11"),)),
        EraDef(id=EraId("b"), label="B", anchor_sets=(SetCode("ST12"),)),
    )
    with pytest.raises(EraError):
        resolve_eras(defs, DATES)


def test_find_era() -> None:
    eras = resolve_eras(load_era_defs(), DATES)
    assert find_era(eras, EraId("gd05_5")).start == date(2026, 9, 25)
    with pytest.raises(EraError, match="unknown"):
        find_era(eras, EraId("gd99"))


def test_real_sets_json_produces_the_same_eras() -> None:
    sets = load_sets()
    if not sets:
        pytest.skip("sets.json not generated yet")
    eras = resolve_eras(load_era_defs(), release_dates(sets))
    assert [str(e.start) for e in eras] == ["2026-07-24", "2026-09-25", "2026-10-30"]
