"""Cards whose wording differs between printings, for a human to read.

Reminder-only differences are ignored. What's left are real wording differences: usually the rules being reworded
(expected), occasionally a translation slip on one printing (worth catching). The tool can't tell which; you can.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, TextVersion


@dataclass(frozen=True)
class TextChange:
    number: CardNumber
    name: str
    current: TextVersion
    older: TextVersion
    diff: str  # word-level: removed words in [-...-], added words in {+...+}, relative to the current wording


def _word_diff(older: str, current: str) -> str:
    """Show how to get from the older wording to the current one."""
    a, b = re.findall(r"\S+|\n", older), re.findall(r"\S+|\n", current)
    out: list[str] = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.extend(a[a0:a1])
            continue
        if a0 != a1:
            out.append("[-" + " ".join(w for w in a[a0:a1] if w != "\n") + "-]")
        if b0 != b1:
            out.append("{+" + " ".join(w for w in b[b0:b1] if w != "\n") + "+}")
    return " ".join(out).replace(" \n ", "\n").strip()


def text_changes(cards: Iterable[CardModel]) -> list[TextChange]:
    """One entry per older substantive wording of each card, ordered by card number."""
    changes: list[TextChange] = []
    for card in cards:
        current = card.text_versions[0]
        for older in card.text_versions[1:]:
            if older.substantive:
                changes.append(TextChange(card.number, card.name, current, older, _word_diff(older.text, current.text)))
    return sorted(changes, key=lambda c: c.number)


def format_change(change: TextChange) -> str:
    def where(v: TextVersion) -> str:
        block = v.block.value if v.block else "?"
        return f"block {block}, {', '.join(str(i) for i in v.printing_ids)}"

    return (
        f"{change.number}  {change.name}\n"
        f"  current ({where(change.current)}) vs older ({where(change.older)}):\n"
        + "\n".join("    " + line for line in change.diff.splitlines())
    )
