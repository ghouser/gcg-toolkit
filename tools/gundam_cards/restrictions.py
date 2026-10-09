"""Reading Bandai's banned / restricted announcement into data, and the vanilla-group description (see design.md, "Banned and restricted cards").

The page is read as text lines, not summarized: sections are `Banned Cards`, `Restricted Cards〈N〉`, `Banned pair` (lines `A`, a card, `B`, a card), then the cards
that match the vanilla-group description. Pure functions; the fetch is in the CLI.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from shared.basetypes import CardNumber
from tools.gundam_cards.models import BannedPair, CardModel, LimitedCard, Restrictions, UnitCard

NEWS_URL = "https://www.gundam-gcg.com/en/news/01_279.html"
HEADING = "##H"
_CARD_LINE = re.compile(r"^([A-Z]{1,4}\d{2}-\d{3})\s+\S.*$")
_DESCRIPTION = re.compile(r"description\s+[\"“](.+?)[\"”]", re.I)


class RestrictionsError(Exception):
    pass


def page_lines(html: str) -> list[str]:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<h4[^>]*>", "\n" + HEADING + " ", text)  # section headings are the h4 tags (the navigation buttons repeat their words, so text alone cannot tell them apart)
    text = re.sub(r"</(p|h\d|div|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n") if line.strip()]


def parse_published(lines: list[str]) -> date:
    for line in lines:
        try:
            return datetime.strptime(line, "%B %d, %Y").date()
        except ValueError:
            continue
    raise RestrictionsError("no publication date found on the page")


def parse_restrictions(html: str) -> tuple[Restrictions, date]:
    """The banned cards, restricted cards (with their copy limit), banned pairs and the vanilla group, and the page's date."""
    lines = page_lines(html)
    published = parse_published(lines)
    banned: list[CardNumber] = []
    limited: list[LimitedCard] = []
    pairs: list[BannedPair] = []
    group: list[CardNumber] = []
    description = ""
    section = ""
    copies = 0
    pending: dict[str, CardNumber] = {}
    expect = ""
    for line in lines:
        if line.startswith(HEADING):
            title = line[len(HEADING) :].strip()
            if title == "Banned Cards":
                section = "banned"
            elif title.startswith("Restricted Cards"):
                match = re.search(r"〈(\d+)〉", title)
                section, copies = "limited", int(match.group(1)) if match else 0
            elif title == "Banned pair":
                section = "pairs"
            else:
                section = ""
        elif section == "pairs" and line in ("A", "B"):
            expect = line
        elif section in ("pairs", "group") and line.startswith("All combinations of cards"):
            found = _DESCRIPTION.search(line)
            description = found.group(1) if found else line
            section = "done"
        elif (card := _CARD_LINE.match(line)) and section:
            number = CardNumber(card.group(1))
            if section == "banned":
                banned.append(number)
            elif section == "limited":
                limited.append(LimitedCard(card=number, copies=copies))
            elif section in ("pairs", "group"):
                if expect:
                    pending[expect] = number
                    expect = ""
                    if len(pending) == 2:
                        pairs.append(BannedPair(a=pending["A"], b=pending["B"]))
                        pending = {}
                else:
                    section = "group"
                    group.append(number)
    if not banned and not limited and not pairs:
        raise RestrictionsError("found no banned, restricted or pair sections: has the page changed?")
    return Restrictions(banned=tuple(banned), limited=tuple(limited), banned_pairs=tuple(pairs), vanilla_description=description, vanilla_group=tuple(group)), published


def matches_vanilla(card: CardModel) -> bool:
    """A Unit card that is Lv.2 with cost 1, 2 AP, 2 HP and without effects (the vanilla group's description)."""
    return isinstance(card, UnitCard) and card.level == 2 and card.cost == 1 and card.ap == 2 and card.hp == 2 and not card.text.strip()


def vanilla_cards(catalog: dict[CardNumber, CardModel]) -> frozenset[CardNumber]:
    """Every card in the catalog that matches the description (the rule), whatever the page lists."""
    return frozenset(n for n, c in catalog.items() if matches_vanilla(c))
