"""Checking a collection file against the card catalog: every line valid, duplicates and oddities reported (no network).

Errors make the file unusable (unknown card, bad quantity, a printing the card doesn't have). Warnings are probably mistakes
(the same card on two lines, a zero). Info is worth knowing (a resource card, an unusually large total). Nothing is ever guessed
or fixed silently: a card number the catalog doesn't know is reported with close matches as suggestions only.
"""
from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardKind, CardModel
from tools.gundam_collection.models import (
    Art,
    CardInfo,
    CheckReport,
    CollectionFile,
    Entry,
    Issue,
    IssueCode,
    KindTotal,
    OwnedCard,
    OwnedPrinting,
    Severity,
)
from tools.gundam_collection.parse import parse_lines

MANY_COPIES_ABOVE = 12  # a total above this for one card number is reported (info): several starters, or a typo
MAX_SUGGESTIONS = 3


def catalog_info(cards: Iterable[CardModel]) -> dict[CardNumber, CardInfo]:
    """What the check needs from the catalog: name, kind and the arts each card is printed in."""
    info: dict[CardNumber, CardInfo] = {}
    for card in cards:
        arts = {Art.BASE}
        for printing in card.printings:
            if printing.link_art:
                arts.add(Art.LINK)
            elif printing.alt_art_level == 1:
                arts.add(Art.ALT)
            elif printing.alt_art_level == 2:
                arts.add(Art.ALT_PLUS)
        info[card.number] = CardInfo(name=card.name, kind=card.kind, arts=frozenset(arts))
    return info


def _lines(numbers: Iterable[int]) -> str:
    return ", ".join(str(n) for n in numbers)


def check_lines(lines: Iterable[str], catalog: Mapping[CardNumber, CardInfo], file: str = "") -> CheckReport:
    entries, issues, line_count = parse_lines(lines)
    found: list[Issue] = list(issues)
    usable: list[Entry] = []

    for entry in entries:
        info = catalog.get(entry.card_number)
        if info is None:
            close = difflib.get_close_matches(entry.card_number, [str(n) for n in catalog], n=MAX_SUGGESTIONS, cutoff=0.7)
            hint = f" (close: {', '.join(f'{n} {catalog[CardNumber(n)].name}' for n in close)})" if close else ""
            found.append(Issue(line=entry.line, severity=Severity.ERROR, code=IssueCode.UNKNOWN_CARD,
                               message=f"{entry.card_number} is not in the catalog{hint}"))  # fmt: skip
            continue
        if entry.art not in info.arts:
            have = ", ".join(sorted(a.value for a in info.arts))
            found.append(Issue(line=entry.line, severity=Severity.ERROR, code=IssueCode.NO_SUCH_PRINTING,
                               message=f"{entry.card_number} {info.name} has no {entry.art.value!r} printing (it has: {have})"))  # fmt: skip
            continue
        if entry.copies is None:
            found.append(Issue(line=entry.line, severity=Severity.WARNING, code=IssueCode.INCOMPLETE,
                               message=f"{entry.card_number} {info.name}: quantity is still ?"))  # fmt: skip
            continue
        usable.append(entry)

    by_line: dict[tuple[CardNumber, Art], list[Entry]] = defaultdict(list)
    for entry in usable:
        by_line[(entry.card_number, entry.art)].append(entry)
    for (number, art), group in sorted(by_line.items()):
        if len(group) > 1:
            total = sum(e.copies or 0 for e in group)
            label = number if art is Art.BASE else f"{number}{art.value}"
            found.append(Issue(line=group[1].line, severity=Severity.WARNING, code=IssueCode.DUPLICATE,
                               message=f"{label} {catalog[number].name} is on lines {_lines(e.line for e in group)}; "
                                       f"they add up to {total} (typed twice?)"))  # fmt: skip

    totals: dict[CardNumber, int] = defaultdict(int)
    for entry in usable:
        totals[entry.card_number] += entry.copies or 0
    for number, total in sorted(totals.items()):
        info = catalog[number]
        first = min(e.line for e in usable if e.card_number == number)
        if total > MANY_COPIES_ABOVE:
            found.append(Issue(line=first, severity=Severity.INFO, code=IssueCode.MANY_COPIES,
                               message=f"{number} {info.name}: {total} copies in total"))  # fmt: skip
        if not info.kind.is_deck_card:
            found.append(Issue(line=first, severity=Severity.INFO, code=IssueCode.NON_DECK_CARD,
                               message=f"{number} {info.name} is a {info.kind.value.replace('_', ' ')}: kept, but not used for deck building"))  # fmt: skip

    kinds: dict[CardKind, list[int]] = defaultdict(lambda: [0, 0])
    for number, total in totals.items():
        kinds[catalog[number].kind][0] += 1
        kinds[catalog[number].kind][1] += total
    order = {k: i for i, k in enumerate(CardKind)}
    return CheckReport(
        file=file,
        lines_read=line_count,
        entries=tuple(usable),
        issues=tuple(sorted(found, key=lambda i: (i.line or 0, i.code.value, i.message))),
        distinct_cards=len(totals),
        total_copies=sum(totals.values()),
        by_kind=tuple(KindTotal(kind=k, cards=v[0], copies=v[1]) for k, v in sorted(kinds.items(), key=lambda kv: order[kv[0]])),
    )


def set_template(cards: Iterable[CardModel], set_code: str) -> tuple[CardNumber, ...]:
    """The cards with a normal (non-alt-art) printing in the given set: the unique cards a product contains, to fill quantities in for."""
    return tuple(sorted(
        c.number for c in cards
        if any(p.set_code is not None and str(p.set_code) == set_code and p.alt_art_level == 0 and not p.link_art for p in c.printings)
    ))  # fmt: skip


def build_collection(report: CheckReport, generated_at: datetime) -> CollectionFile:
    """The structured collection from a clean check: copies per card, summed across lines, with the arts they came in."""
    by_art: dict[CardNumber, dict[Art, int]] = defaultdict(lambda: defaultdict(int))
    for entry in report.entries:
        by_art[entry.card_number][entry.art] += entry.copies or 0
    order = {a: i for i, a in enumerate(Art)}
    return CollectionFile(
        generated_at=generated_at,
        source_file=report.file,
        data=tuple(
            OwnedCard(
                card_number=number,
                copies=sum(arts.values()),
                printings=tuple(OwnedPrinting(art=a, copies=n) for a, n in sorted(arts.items(), key=lambda kv: order[kv[0]])),
            )
            for number, arts in sorted(by_art.items())
        ),
    )
