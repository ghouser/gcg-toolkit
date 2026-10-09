"""Keyword, trait-mention and reminder-text analysis."""
from __future__ import annotations

from shared.basetypes import PilotName, Trait
from tools.gundam_cards.build import extract_keywords, pilot_name_in_text, referenced_traits, strip_reminders
from tools.gundam_cards.models import Keyword

TRAITS = frozenset({Trait("G Generation"), Trait("Zeon"), Trait("Neo Zeon"), Trait("Vulture")})


def test_values_are_dropped_and_reminder_text_is_ignored() -> None:
    text = "<Repair 2> (At the end of your turn, this Unit recovers 2 HP. 【Main】 is not a keyword here.)\n<Breach 3>"
    keywords, unknown = extract_keywords(text, TRAITS)
    assert keywords == {Keyword.REPAIR, Keyword.BREACH}
    assert unknown == ()


def test_slash_separated_tags_are_both_keywords() -> None:
    keywords, _ = extract_keywords("【Main】/【Action】Draw 1.", TRAITS)
    assert keywords == {Keyword.MAIN, Keyword.ACTION}


def test_activate_keywords_use_either_separator() -> None:
    keywords, _ = extract_keywords("【Activate･Main】【Once per Turn】②：Draw 1.\n【Activate・Action】Rest this.", TRAITS)
    assert keywords == {Keyword.ACTIVATE_MAIN, Keyword.ACTIVATE_ACTION, Keyword.ONCE_PER_TURN}


def test_development_rides_inside_another_keyword() -> None:
    keywords, unknown = extract_keywords("【Deploy・Development 2】■Draw 1.\n【When Paired・Development 1】■Draw 1.", TRAITS)
    assert keywords == {Keyword.DEPLOY, Keyword.DEVELOPMENT, Keyword.WHEN_PAIRED}
    assert unknown == ()


def test_pilot_qualifications_are_not_keywords_and_not_unknown() -> None:
    text = "【During Pair･(Vulture) Pilot】【Attack】Draw 1.\n【When Paired･Lv.3 or Lower Pilot】Draw 1.\n【During Pair･Purple Pilot】Draw 1."
    keywords, unknown = extract_keywords(text, TRAITS)
    assert keywords == {Keyword.DURING_PAIR, Keyword.ATTACK, Keyword.WHEN_PAIRED}
    assert unknown == ()


def test_pilot_marker_is_not_a_keyword() -> None:
    keywords, unknown = extract_keywords("【Main】Draw 1.\n【Pilot】[Lowe Guele]", TRAITS)
    assert keywords == {Keyword.MAIN}
    assert unknown == ()


def test_unknown_tokens_are_quarantined_not_dropped() -> None:
    keywords, unknown = extract_keywords("【Mystery】Do it. <Teleport 2> Also <Blocker>.", TRAITS)
    assert keywords == {Keyword.BLOCKER}
    assert unknown == ("<Teleport 2>", "【Mystery】")


def test_strip_reminders_keeps_trait_mentions() -> None:
    text = "Choose 1 friendly (G Generation) Unit. (Reminder: this (Zeon) thing happens.) Draw 1."
    stripped, removed = strip_reminders(text, TRAITS)
    assert stripped == "Choose 1 friendly (G Generation) Unit. Draw 1."
    assert removed == len("(Reminder: this (Zeon) thing happens.)")


def test_referenced_traits_only_known_traits_including_inside_reminders() -> None:
    text = "While a (Zeon)/(Neo Zeon) Unit is in play, draw 1. (At the start of the game, a (Vulture) Unit...) (Not a trait)"
    assert referenced_traits(text, TRAITS) == {Trait("Zeon"), Trait("Neo Zeon"), Trait("Vulture")}


def test_pilot_name_in_text() -> None:
    assert pilot_name_in_text("【Main】Draw 1.\n【Pilot】[Amate Yuzuriha (Machu)]") == PilotName("Amate Yuzuriha (Machu)")
    assert pilot_name_in_text("【Main】Draw 1.") is None
