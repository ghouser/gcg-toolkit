"""The top of the meta, on the real stored data: the decks players agree on keep their plan and their shape when a constant or a rule changes.

These are the checks `docs/tuning.md` points to. Assertions use ranges, not exact numbers, so a data refresh does not break them but a
change in how decks are rated, or in how a deck is suggested, does. If one fails after a deliberate change, update it and say why in `docs/tuning.md`.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from tools.gundam_cards.store import OUT_DIR as CARDS_DIR
from tools.gundam_collection import cli
from tools.gundam_collection.decks import Deck, is_played
from tools.gundam_collection.store import COLLECTION_PATH
from tools.gundam_collection.styles import Plan, Style, style_of
from tools.gundam_packages.models import DataSource

MASTER_SHINING = "GD05-033+GD05-066"  # Master Asia + Domon Shining (white/red): the deck both sources play (about 12% of tournament and 11% of online decks)
BARBATOS_CHAR = "GD02-054+ST11-001"  # Mikazuki Barbatos + Char Aznable: a pilot-pairing aggro deck, rising online
STRIKE_FREEDOM = "GD05-002"  # Kira Strike Freedom: the tournament favorite (about 43% of top-cut decks)

pytestmark = pytest.mark.skipif(
    not (CARDS_DIR / "cards.json").is_file() or not COLLECTION_PATH.is_file(), reason="card catalog and collection not present"
)


@pytest.fixture(scope="module")
def meta(monkeypatch_module: pytest.MonkeyPatch) -> tuple[list[Deck], dict[str, Style]]:
    monkeypatch_module.setattr(cli, "_refresh_collection", lambda cards: None)  # the test must not rewrite the repository's collection file
    context = cli._deck_context("both", 0.0)
    assert context is not None
    layers, coverages, _ = context
    catalog = {n: p.card for n, p in layers.cards.items()}
    decks = [c.deck for c in coverages]
    return decks, {d.id: style_of(d.requirements, catalog) for d in decks}


@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    with pytest.MonkeyPatch.context() as mp:
        yield mp


def deck(decks: list[Deck], deck_id: str) -> Deck:
    found = [d for d in decks if d.id == deck_id]
    assert found, f"deck {deck_id} is no longer found in the meta data"
    return found[0]


def test_master_asia_and_domon_shining_is_control_and_played_in_both_sources(meta: tuple[list[Deck], dict[str, Style]]) -> None:
    decks, styles = meta
    d, st = deck(decks, MASTER_SHINING), styles[MASTER_SHINING]
    assert st.plan is Plan.CONTROL  # decided 2026-10-09: at the 40 line both this and Strike Freedom read as control, which matches how they are played
    assert st.interaction >= 70 and st.advantage >= 70 and 55 <= st.pressure <= 90  # lots of interaction and card advantage, a real but moderate push
    assert d.archetype_rates[DataSource.TOURNAMENT] >= 0.05 and d.archetype_rates[DataSource.ONLINE] >= 0.05  # the alignment between tournament and online is the tell
    assert {"GD05-033", "GD05-066"} <= set(d.anchors)


def test_barbatos_and_char_is_aggro_and_played_in_both_sources(meta: tuple[list[Deck], dict[str, Style]]) -> None:
    decks, styles = meta
    d, st = deck(decks, BARBATOS_CHAR), styles[BARBATOS_CHAR]
    assert st.plan is Plan.AGGRO and st.curve >= 85 and st.pressure >= 75 and st.interaction <= 55
    assert d.archetype_rates[DataSource.TOURNAMENT] >= 0.05 and d.archetype_rates[DataSource.ONLINE] >= 0.05
    assert st.links > 0  # Char Aznable pairs with its Units; the links rating must see it


def test_every_strike_freedom_deck_is_control_and_the_main_one_is_all_interaction_and_no_pressure(meta: tuple[list[Deck], dict[str, Style]]) -> None:
    decks, styles = meta
    strike = [d for d in decks if STRIKE_FREEDOM in d.anchors and is_played(d, 0.05)]  # the played lists, not the one-off variants
    assert strike and all(styles[d.id].plan is Plan.CONTROL for d in strike)
    main = max(strike, key=lambda d: d.top_rate)
    st = styles[main.id]
    assert st.interaction >= 65 and st.pressure <= 35
    assert main.archetype_rates[DataSource.TOURNAMENT] >= 0.05 and main.archetype_rates[DataSource.ONLINE] >= 0.05


def test_the_barbatos_aggro_suggestion_brings_the_char_package_and_its_link_pairs(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "_refresh_collection", lambda cards: None)
    assert cli.main(["suggest", "barbatos", "aggro", "PB", "--pool", "0"]) == 0
    out = capsys.readouterr().out
    assert "B/P" in out and "aggro" in out.split("rating of this 50:")[1].split("\n")[0]
    assert "of 50 copies" in out  # exactly fifty
    assert "partner package: Char Aznable" in out and "Mikazuki Augus" in out  # the Char package arrives whole, with the Barbatos pilot
    pairs = int(out.split("link pairs: ")[1].split()[0])
    assert pairs >= 6  # pilot pairs are a reason to play the deck: Augus on the Barbatos Units, Char on the Zeon Units
    assert "Sarah Zabiarov" not in out.split("-- pilots and who they pair with --")[1].split("--")[0]  # a lone filler pilot is not picked up
