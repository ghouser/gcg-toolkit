"""Reading the hand-typed collection file into typed lines (no catalog needed, no network).

One card per line: a card number and a quantity, in either order. Everything after `#` is a comment and blank lines are skipped.

    GD02-041 1          card number, then quantity
    4 GD05-002          quantity, then card number
    ST01-001+ 3         a trailing +, ++ or LK marks an alternate art of the card
    ST05-004 x2         "x" before or after the quantity is allowed (x2, 2x)
    ST05-006 ?          a placeholder for a quantity still to fill in
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from shared.basetypes import CardNumber
from tools.gundam_collection.models import Art, Entry, Issue, IssueCode, Severity

MAX_QUANTITY = 99
UNKNOWN = "?"

_CARD = re.compile(r"(?P<number>[A-Z]+\d*-\d{3})(?P<art>\+\+|\+|LK)?", re.IGNORECASE)
_QUANTITY = re.compile(r"x?(?P<n>\d+)x?", re.IGNORECASE)
_ART = {"+": Art.ALT, "++": Art.ALT_PLUS, "LK": Art.LINK}


def _issue(line: int, code: IssueCode, message: str, severity: Severity = Severity.ERROR) -> Issue:
    return Issue(line=line, severity=severity, code=code, message=message)


def parse_line(line_no: int, raw: str) -> Entry | Issue | None:
    """The entry on one line, an issue if it can't be read, or None for a blank or comment-only line."""
    text = raw.split("#", 1)[0].strip()
    if not text:
        return None
    tokens = [t for t in re.split(r"[\s,;]+", text) if t]
    if len(tokens) != 2:
        return _issue(line_no, IssueCode.BAD_LINE, f"expected a card number and a quantity, got {len(tokens)} part(s): {text!r}")
    card_token = next((t for t in tokens if _CARD.fullmatch(t)), None)
    if card_token is None:
        return _issue(line_no, IssueCode.BAD_CARD_NUMBER, f"no card number (like GD05-002) in {text!r}")
    quantity_token = tokens[1] if tokens[0] == card_token else tokens[0]
    match = _CARD.fullmatch(card_token)
    assert match is not None
    number = CardNumber(match.group("number").upper())
    art = _ART.get((match.group("art") or "").upper(), Art.BASE)
    if quantity_token == UNKNOWN:
        return Entry(line=line_no, card_number=number, art=art, copies=None)
    q = _QUANTITY.fullmatch(quantity_token)
    if q is None:
        return _issue(line_no, IssueCode.BAD_QUANTITY, f"{quantity_token!r} is not a quantity (a whole number, or ? for unknown) in {text!r}")
    copies = int(q.group("n"))
    if copies == 0:
        return _issue(line_no, IssueCode.ZERO_COPIES, f"{number}: a quantity of 0; remove the line if you have none", Severity.WARNING)
    if copies > MAX_QUANTITY:
        return _issue(line_no, IssueCode.BAD_QUANTITY, f"{number}: {copies} is above {MAX_QUANTITY}; probably a typo")
    return Entry(line=line_no, card_number=number, art=art, copies=copies)


def parse_lines(lines: Iterable[str]) -> tuple[tuple[Entry, ...], tuple[Issue, ...], int]:
    """Entries and issues for every line, and how many lines were read."""
    entries: list[Entry] = []
    issues: list[Issue] = []
    count = 0
    for count, raw in enumerate(lines, start=1):
        result = parse_line(count, raw)
        if isinstance(result, Entry):
            entries.append(result)
        elif isinstance(result, Issue):
            issues.append(result)
    return tuple(entries), tuple(issues), count
