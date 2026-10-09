"""Parsing and checking the collection file on a tiny fake catalog."""
from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardKind
from tools.gundam_collection.check import check_lines
from tools.gundam_collection.models import Art, CardInfo, Entry, Issue, IssueCode, Severity
from tools.gundam_collection.parse import parse_line

N = CardNumber
CATALOG = {
    N("GD02-041"): CardInfo(name="Gundam Aerial", kind=CardKind.UNIT, arts=frozenset({Art.BASE, Art.ALT})),
    N("GD05-002"): CardInfo(name="Strike Freedom Gundam", kind=CardKind.UNIT, arts=frozenset({Art.BASE})),
    N("ST01-010"): CardInfo(name="Amuro Ray", kind=CardKind.PILOT, arts=frozenset({Art.BASE, Art.ALT, Art.LINK})),
    N("R-001"): CardInfo(name="Resource", kind=CardKind.RESOURCE, arts=frozenset({Art.BASE})),
}


def codes(report_lines: list[str]) -> list[tuple[int | None, IssueCode]]:
    return [(i.line, i.code) for i in check_lines(report_lines, CATALOG).issues]


def test_the_users_format_and_the_other_orders_all_parse() -> None:
    expected = {"GD05-002 1": 1, "4 GD05-002": 4, "GD05-002 x2": 2, "GD05-002 3x": 3, "gd05-002, 2": 2, "GD05-002\t5": 5}
    for raw, copies in expected.items():
        entry = parse_line(1, raw)
        assert isinstance(entry, Entry), raw
        assert (entry.card_number, entry.copies) == (N("GD05-002"), copies), raw


def test_art_markers_blank_lines_and_comments() -> None:
    plus = parse_line(3, "ST01-010+ 2  # my alt art")
    assert isinstance(plus, Entry) and (plus.art, plus.copies) == (Art.ALT, 2)
    assert parse_line(1, "   ") is None and parse_line(2, "# a note") is None
    assert isinstance(parse_line(4, "ST01-010LK 1"), Entry)
    assert parse_line(5, "GD05-002 ?") == Entry(line=5, card_number=N("GD05-002"), art=Art.BASE, copies=None)


def test_unreadable_lines_are_errors_with_their_line_numbers() -> None:
    bad = ["GD05-002", "GD05-002 1 2", "hello 3", "GD05-002 many", "GD05-002 100", "GD05-002 GD02-041"]
    results = [parse_line(i, raw) for i, raw in enumerate(bad, start=1)]
    assert all(isinstance(r, Issue) and r.severity is Severity.ERROR for r in results)
    assert [r.code for r in results if isinstance(r, Issue)] == [IssueCode.BAD_LINE, IssueCode.BAD_LINE, IssueCode.BAD_CARD_NUMBER,
                                                                 IssueCode.BAD_QUANTITY, IssueCode.BAD_QUANTITY, IssueCode.BAD_QUANTITY]  # fmt: skip


def test_an_unknown_card_is_an_error_with_a_suggestion_but_is_not_applied() -> None:
    report = check_lines(["GD05-003 1", "GD02-014 2"], CATALOG)
    assert [i.code for i in report.errors] == [IssueCode.UNKNOWN_CARD, IssueCode.UNKNOWN_CARD]
    assert "GD05-002" in report.errors[0].message  # a close card is only suggested
    assert report.entries == () and report.distinct_cards == 0 and not report.ok


def test_a_printing_the_card_does_not_have_is_an_error() -> None:
    report = check_lines(["GD05-002+ 1", "GD02-041+ 1"], CATALOG)
    assert [(i.line, i.code) for i in report.errors] == [(1, IssueCode.NO_SUCH_PRINTING)]
    assert len(report.entries) == 1


def test_the_same_card_on_two_lines_is_a_duplicate_warning_and_adds_up() -> None:
    report = check_lines(["GD02-041 1", "GD05-002 2", "GD02-041 3", "GD02-041+ 1"], CATALOG)
    dup = [i for i in report.issues if i.code is IssueCode.DUPLICATE]
    assert len(dup) == 1 and dup[0].severity is Severity.WARNING and "lines 1, 3" in dup[0].message and "4" in dup[0].message
    assert report.total_copies == 7 and report.distinct_cards == 2  # the + art is a different line, the same card number
    assert report.ok  # a duplicate is a warning, not an error


def test_placeholders_zero_copies_resources_and_large_totals() -> None:
    report = check_lines(["GD05-002 ?", "GD02-041 0", "R-001 5", "ST01-010 13"], CATALOG)
    got = {i.code for i in report.issues}
    assert {IssueCode.INCOMPLETE, IssueCode.ZERO_COPIES, IssueCode.NON_DECK_CARD, IssueCode.MANY_COPIES} <= got
    assert report.ok and report.total_copies == 18 and report.distinct_cards == 2
    assert {k.kind: (k.cards, k.copies) for k in report.by_kind} == {CardKind.PILOT: (1, 13), CardKind.RESOURCE: (1, 5)}


def test_checking_is_deterministic_and_never_changes_the_input() -> None:
    lines = ["GD02-041 1", "GD05-002 2", "GD02-041 3", "GD99-001 1", "oops"]
    assert check_lines(lines, CATALOG) == check_lines(list(lines), CATALOG)
