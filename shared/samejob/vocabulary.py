"""The same-job vocabulary: critical and good-to-have keywords, effect features, and the text readers that find them.

Structure only, never wording: an effect is one of a small closed set of features (damage, draw, bounce...), an effect on *all* Units is its
own feature (`damage all`), and the main number of a few of them is kept for Commands. See design.md, "Same job".
"""
from __future__ import annotations

import re

from tools.gundam_cards.models import Keyword

STAT_SLACK = 1  # Units: Y's AP and HP may be at most this far below X's
SIZE_SLACK = 1  # Commands: the main number of a shared effect may be at most this far below X's
COST_SLACK = 1  # Commands: Y's cost may be at most this far above X's
LOSS_ALLOWED = 1  # Commands and Bases: net good-to-haves that may be lost
CRITICAL_CLASSES: dict[Keyword, str] = {
    Keyword.BLOCKER: "blocker",
    Keyword.BREACH: "offense",
    Keyword.SUPPRESSION: "offense",
    Keyword.HIGH_MANEUVER: "offense",
}
GOOD_KEYWORDS: dict[Keyword, str] = {
    Keyword.FIRST_STRIKE: "first strike",
    Keyword.REPAIR: "repair",
    Keyword.SUPPORT: "support",
    Keyword.DEVELOPMENT: "development",
}
SCOPED = ("damage", "destroy", "+AP", "-AP", "recover", "rest")  # these also exist in an "all Units" form
EFFECTS: dict[str, re.Pattern[str]] = {
    "damage": re.compile(r"\bdeals? (?:(?:\d+|x)(?: to \d+)?\s+|an amount of\s+)?damage", re.I),
    "draw": re.compile(r"\bdraw (?:\d+|x)", re.I),
    "+AP": re.compile(r"\bAP\s*\+", re.I),
    "-AP": re.compile(r"\bAP\s*-", re.I),
    "destroy": re.compile(r"\bdestroy\b", re.I),
    "recover": re.compile(r"\brecovers?\b", re.I),
    "rest": re.compile(r"\brest\b(?!\s+this\b)|\bset\b[^.]{0,30}\bactive\b", re.I),
    "bounce": re.compile(r"\breturn\b[^.]{0,60}\bowners?['’]?s?['’]?\s+hands?", re.I),
    "search": re.compile(r"\blook at the top \d+|\badd (?!this card)[^.]{0,60}to your hand", re.I),
    "protect": re.compile(r"\bcan['’]?t receive\b|\breduce [^.]{0,30}damage", re.I),
    "tokens": re.compile(r"\bdeploy\b[^.]{0,80}\bUnit tokens?\b", re.I),
    "revive": re.compile(r"\bpay its cost to deploy\b|\bdeploy it\b|\bdeploy\b[^.]{0,40}from your trash", re.I),
    "attack target": re.compile(r"\battack target\b", re.I),
    "ramp": re.compile(r"\bplace \d+ (?:rested )?(?:EX )?resource", re.I),
    "base": re.compile(r"\bdeploy \d+ EX Base\b", re.I),
}
GRANTS: dict[str, re.Pattern[str]] = {  # Commands and Bases: a Unit's own grants are its keywords (native_keywords)
    "grant offense": re.compile(r"\bgains? <\s*(?:Breach|Suppression|High-Maneuver)", re.I),
    "grant other": re.compile(r"\bgains? <\s*(?!Breach|Suppression|High-Maneuver)[A-Za-z]", re.I),
}
SIZES: dict[str, re.Pattern[str]] = {
    "damage": re.compile(r"\bdeals? (?:\d+ to )?(\d+)\s+damage", re.I),
    "draw": re.compile(r"\bdraw (\d+)", re.I),
    "+AP": re.compile(r"\bAP\s*\+(\d+)", re.I),
    "-AP": re.compile(r"\bAP\s*-(\d+)", re.I),
    "recover": re.compile(r"\brecovers? (\d+)", re.I),
}
_ALL_UNITS = re.compile(r"\ball (?:the |of )?(?:enemy |friendly |other |active |rested |damaged |your )*(?:Units?|Bases?)\b|\bto all\b|\beach (?:enemy |friendly )?Unit", re.I)
_REMINDER = re.compile(r"\([^()]*\)")
_TAGS = re.compile(r"^(?:【[^】]*】\s*)*")
_KEYWORD = re.compile(r"<\s*([A-Za-z][A-Za-z -]*?)\s*\d*\s*>")
_OWN_GRANT = re.compile(r"\bThis Unit gains? ((?:<[^>]*>[\s,]*(?:and|or)?[\s,]*)+)", re.I)
_SECTION = re.compile(r"(?=【(?:Burst|Main|Action|Pilot)】)")
_BURST_SECTION = re.compile(r"【Burst】[^【]*")  # up to the next timing tag
_BASE_BASELINE = re.compile(r"Add 1 of your Shields? to your hand\.?", re.I)  # every Base does it: not a feature


def native_keywords(text: str) -> frozenset[Keyword]:
    """Keywords the card has: at the start of a line (after timing tags, so `【Activate･Main】<Support 1>` counts) or that **this Unit
    grants itself** (`This Unit gains <Breach 3>`, also when it is activated at a cost). Keywords granted to another Unit, or only
    mentioned (`Choose 1 Unit with <Blocker>`), are not its own."""
    found: set[Keyword] = set()
    for raw in text.split("\n"):
        line = raw.strip()
        tags = _TAGS.match(line)
        rest = line[len(tags.group(0)) :] if tags else line
        names: list[str] = []
        lead = _KEYWORD.match(rest)
        if lead:
            names.append(lead.group(1))
        for group in _OWN_GRANT.findall(rest):
            names.extend(_KEYWORD.findall(group))
        for name in names:
            try:
                found.add(Keyword(name.lower().replace(" ", "_").replace("-", "_")))
            except ValueError:
                continue
    return frozenset(found)


def _body(text: str) -> str:
    previous = None
    while previous != text:
        previous, text = text, _REMINDER.sub(" ", text)
    return re.sub(r"【[^】]*】", " ", text)


def effects(text: str, *, grants: bool = False) -> tuple[frozenset[str], dict[str, int]]:
    """The effect features of a text and the main number of the sized ones. An effect on all Units is its own feature (`damage all`)."""
    found: set[str] = set()
    sizes: dict[str, int] = {}
    patterns = {**EFFECTS, **GRANTS} if grants else EFFECTS
    for sentence in re.split(r"(?<=[.])\s+|\n", _body(text)):
        area = bool(_ALL_UNITS.search(sentence))
        for name, pattern in patterns.items():
            if not pattern.search(sentence):
                continue
            label = f"{name} all" if area and name in SCOPED else name
            found.add(label)
            sized = SIZES.get(name)
            number = sized.search(sentence) if sized else None
            if number:
                sizes[label] = max(sizes.get(label, 0), int(number.group(1)))
    return frozenset(found), sizes


def effect_features(text: str, *, grants: bool = False) -> frozenset[str]:
    return effects(text, grants=grants)[0]


def command_core_text(text: str) -> str:
    """A Command's 【Main】/【Action】 sections: the Burst and Pilot sections are separate."""
    return " ".join(s for s in _SECTION.split(text) if s.strip() and not s.startswith(("【Burst】", "【Pilot】")))


def base_core_text(text: str) -> str:
    """A Base's effects: no Burst section and none of the baseline every Base has (it adds a Shield to your hand when deployed)."""
    return _BASE_BASELINE.sub(" ", _BURST_SECTION.sub(" ", text))
