"""`RawDetail` pages -> typed `Card` models. This is the boundary where strings become domain types.

Every rule here is documented in tools/gundam_cards/design.md ("Parser rules" and "Which text wins").
Anything the parser can't classify raises `ParseError` (and the card is reported) or lands in `unknown_tags`.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import NamedTuple, TypedDict, TypeVar
from urllib.parse import urljoin, urlsplit, urlunsplit

from shared.basetypes import CardNumber, PackageId, PilotName, PrintingId, SetCode, SourceTitle, Trait
from tools.gundam_cards.models import (
    BaseCard,
    Block,
    CardKind,
    CardModel,
    Color,
    CommandCard,
    ExBaseCard,
    ExResourceCard,
    Faq,
    Keyword,
    LinkCondition,
    LinkRequirement,
    PilotCard,
    PilotNameLink,
    PilotProfile,
    Printing,
    Rarity,
    ResourceCard,
    TextVersion,
    TraitLink,
    UnitCard,
    UnitTokenCard,
    Zone,
)
from tools.gundam_cards.parse_detail import RawDetail

_T = TypeVar("_T")
DETAIL_URL = "https://www.gundam-gcg.com/en/cards/detail.php?detailSearch={}"


class ParseError(Exception):
    def __init__(self, subject: str, detail: str) -> None:
        super().__init__(f"{subject}: {detail}")
        self.subject = subject
        self.detail = detail


class IssueKind(StrEnum):
    PARSE_FAILURE = "parse_failure"
    UNKNOWN_TAG = "unknown_tag"
    PRINTING_ATTRIBUTE_MISMATCH = "printing_attribute_mismatch"
    AMBIGUOUS_RECENCY = "ambiguous_recency"
    KEYWORDS_CHANGED = "keywords_changed_between_versions"
    NO_BASE_PRINTING = "no_base_printing"  # a card number Bandai only lists as alt arts; the lowest one is the reference


@dataclass(frozen=True)
class Issue:
    kind: IssueKind
    subject: str
    detail: str


@dataclass(frozen=True)
class SourcePage:
    printing_id: PrintingId
    raw: RawDetail
    fetched_at: datetime
    package_ids: tuple[PackageId, ...]


@dataclass(frozen=True)
class BuildResult:
    card: CardModel
    issues: tuple[Issue, ...]


# ---- field parsers -------------------------------------------------------------------------------
def parse_int(value: str, subject: str, label: str) -> int | None:
    """`3`, `+2`, `-3`, fullwidth `３` -> int; `-` -> None."""
    v = unicodedata.normalize("NFKC", value).strip()
    if v == "-":
        return None
    if re.fullmatch(r"[+-]?\d+", v) is None:
        raise ParseError(subject, f"{label} is not a number: {value!r}")
    return int(v)


def _require(value: _T | None, subject: str, label: str) -> _T:
    if value is None:
        raise ParseError(subject, f"{label} is required here but the page shows none")
    return value


_TRAIT_GROUP = re.compile(r"\(([^()]+)\)")


def parse_traits(value: str, subject: str) -> tuple[Trait, ...]:
    """`(Earth Federation) (White Base Team)` -> traits; `-` -> ()."""
    if value == "-":
        return ()
    if re.fullmatch(r"(?:\([^()]+\)\s*)+", value) is None:
        raise ParseError(subject, f"unrecognized Trait format: {value!r}")
    return tuple(Trait(m.strip()) for m in _TRAIT_GROUP.findall(value))


def parse_link(value: str, subject: str) -> LinkCondition | None:
    """`[Amuro Ray]`, `(G Generation) Trait`, or alternatives joined by ` / ` (`/` means "or"). `-` -> no link.

    Decided rule: a parenthesized alternative is a trait whether or not "Trait" follows it, so
    `(Teiwaz) / (Tekkadan) Trait` means the Teiwaz trait or the Tekkadan trait.
    """
    if value == "-":
        return None
    requirements: list[LinkRequirement] = []
    for part in value.split(" / "):
        part = part.strip()
        pilot = re.fullmatch(r"\[(.+)\]", part)
        trait = re.fullmatch(r"\(([^()]+)\)(?:\s*Trait)?", part)
        if pilot:
            requirements.append(PilotNameLink(fragment=PilotName(pilot.group(1).strip())))
        elif trait:
            requirements.append(TraitLink(trait=Trait(trait.group(1).strip())))
        else:
            raise ParseError(subject, f"unrecognized Link requirement {part!r} in {value!r}")
    return LinkCondition(any_of=tuple(requirements))


def parse_zones(value: str, subject: str) -> frozenset[Zone]:
    if value == "-":
        return frozenset()
    try:
        return frozenset(Zone(token.lower()) for token in value.split())
    except ValueError as e:
        raise ParseError(subject, f"unknown Zone in {value!r}") from e


def parse_color(value: str, subject: str) -> Color | None:
    if value == "-":
        return None
    try:
        return Color(value.lower())
    except ValueError as e:
        raise ParseError(subject, f"unknown color {value!r}") from e


class ParsedRarity(NamedTuple):
    rarity: Rarity
    alt_art_level: int  # number of "+": 0, 1 or 2
    link_art: bool  # "LK" prefix


_RARITY = re.compile(r"(LK)?(C|U|R|LR|P)(?:\s*(\+{1,2}))?")


def parse_rarity(value: str, subject: str) -> ParsedRarity:
    """`C` -> C; `C +` -> C, alt art level 1; `LR ++` -> LR, level 2; `LKR +` -> R with link art, level 1."""
    match = _RARITY.fullmatch(value)
    if match is None:
        raise ParseError(subject, f"unrecognized rarity {value!r}")
    return ParsedRarity(Rarity(match.group(2)), len(match.group(3) or ""), match.group(1) is not None)


def parse_block(value: str, subject: str) -> Block | None:
    if value in ("", "-"):
        return None
    try:
        return Block(value)
    except ValueError as e:
        raise ParseError(subject, f"unknown block {value!r} (a new block means a new rules era: review the enums)") from e


_KIND_BY_TYPE = {
    "UNIT": CardKind.UNIT,
    "PILOT": CardKind.PILOT,
    "COMMAND": CardKind.COMMAND,
    "BASE": CardKind.BASE,
    "EX BASE": CardKind.EX_BASE,
    "RESOURCE": CardKind.RESOURCE,
    "EX RESOURCE": CardKind.EX_RESOURCE,
    "UNIT TOKEN": CardKind.UNIT_TOKEN,
    "UNIT・TOKEN": CardKind.UNIT_TOKEN,
}


def parse_kind(value: str, subject: str) -> CardKind:
    try:
        return _KIND_BY_TYPE[value.strip().upper()]
    except KeyError as e:
        raise ParseError(subject, f"unknown card TYPE {value!r}") from e


# ---- text analysis -------------------------------------------------------------------------------
def _split_top_level_groups(text: str) -> list[tuple[int, int]]:
    """(start, end) of each top-level balanced `( ... )` group in `text`."""
    groups: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                groups.append((start, i + 1))
    return groups


def strip_reminders(text: str, traits: frozenset[Trait]) -> tuple[str, int]:
    """Remove reminder text: top-level `(...)` groups whose content isn't exactly a known trait.

    Returns (text without reminders, number of characters removed). Trait mentions like `(G Generation)` stay.
    """
    pieces: list[str] = []
    removed = 0
    cursor = 0
    for start, end in _split_top_level_groups(text):
        inner = text[start + 1 : end - 1].strip()
        if inner in traits:
            continue  # a trait mention: keep
        pieces.append(text[cursor:start])
        cursor = end
        removed += end - start
    pieces.append(text[cursor:])
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in "".join(pieces).split("\n"))
    return "\n".join(line for line in lines if line), removed  # a removed reminder line must not leave a blank line


_QUOTE_SPACING = re.compile(r"\s*(['\u2019\"\u201c\u201d])\s*")


def comparison_core(text: str, traits: frozenset[Trait]) -> tuple[str, int]:
    """Wording with everything cosmetic removed, to decide whether two wordings really differ.

    Drops reminder text, spacing around quotes/apostrophes (`owner' s` == `owner's`) and letter case
    (`this unit` == `this Unit`). Returns (core, reminder characters removed). Stored text is never altered.
    """
    stripped, removed = strip_reminders(text, traits)
    return _QUOTE_SPACING.sub(r"\1", stripped).casefold(), removed


_ANGLE = re.compile(r"<([^<>]+)>")
_LENTICULAR = re.compile(r"【([^】]*)】")
_ANGLE_KEYWORDS = {
    "repair": Keyword.REPAIR,
    "breach": Keyword.BREACH,
    "support": Keyword.SUPPORT,
    "blocker": Keyword.BLOCKER,
    "first strike": Keyword.FIRST_STRIKE,
    "high-maneuver": Keyword.HIGH_MANEUVER,
    "suppression": Keyword.SUPPRESSION,
    "development": Keyword.DEVELOPMENT,
}
_TAG_KEYWORDS = {
    "activate・main": Keyword.ACTIVATE_MAIN,
    "activate・action": Keyword.ACTIVATE_ACTION,
    "main": Keyword.MAIN,
    "action": Keyword.ACTION,
    "burst": Keyword.BURST,
    "deploy": Keyword.DEPLOY,
    "attack": Keyword.ATTACK,
    "destroyed": Keyword.DESTROYED,
    "when paired": Keyword.WHEN_PAIRED,
    "during pair": Keyword.DURING_PAIR,
    "when linked": Keyword.WHEN_LINKED,
    "during link": Keyword.DURING_LINK,
    "once per turn": Keyword.ONCE_PER_TURN,
}
_TAGS_LONGEST_FIRST = sorted(_TAG_KEYWORDS, key=len, reverse=True)


def extract_keywords(text: str, traits: frozenset[Trait]) -> tuple[frozenset[Keyword], tuple[str, ...]]:
    """Keywords in the text (reminder text excluded, values dropped) and any tokens that aren't keywords.

    `【Pilot】` is not a keyword (it marks a Command's pilot effect) and is ignored here.
    """
    body, _ = strip_reminders(text, traits)
    found: set[Keyword] = set()
    unknown: list[str] = []
    for inner in _ANGLE.findall(body):
        name = re.sub(r"\s*\d+\s*$", "", inner).strip().lower()
        keyword = _ANGLE_KEYWORDS.get(name)
        if keyword is None:
            unknown.append(f"<{inner}>")
        else:
            found.add(keyword)
    for inner in _LENTICULAR.findall(body):
        tag = re.sub(r"\s+", " ", inner.replace("･", "・")).strip().lower()
        if tag == "pilot":
            continue
        for known in _TAGS_LONGEST_FIRST:
            if tag == known or tag.startswith(known + "・"):
                found.add(_TAG_KEYWORDS[known])
                rest = tag[len(known) :].lstrip("・")
                if rest.startswith("development"):
                    found.add(Keyword.DEVELOPMENT)
                break  # anything else after the keyword is a pilot qualification, kept in the raw text
        else:
            if tag.startswith("development"):
                found.add(Keyword.DEVELOPMENT)
            else:
                unknown.append(f"【{inner}】")
    return frozenset(found), tuple(dict.fromkeys(unknown))


def referenced_traits(text: str, traits: frozenset[Trait]) -> frozenset[Trait]:
    """Known traits mentioned in the text as `(Trait)`, including inside reminder text."""
    return frozenset(Trait(m) for m in _TRAIT_GROUP.findall(text) if m.strip() in traits)


_PILOT_EFFECT = re.compile(r"【\s*Pilot\s*】\s*\[([^\]]+)\]")


def pilot_name_in_text(text: str) -> PilotName | None:
    """The `[Name]` of a Command's `【Pilot】[Name]` effect, if it has one."""
    match = _PILOT_EFFECT.search(text)
    return PilotName(match.group(1).strip()) if match else None


# ---- printing and text-version assembly -------------------------------------------------------------
_SET_CODE_IN_TEXT = re.compile(r"\[([A-Z]{2,4})-?(\d{2}[A-Z]?)\]")  # [GD05], [PB01], [PC02A], [EVX-01] -> EVX01
_COMPARED_FIELDS = ("TYPE", "COLOR", "Lv.", "COST", "AP", "HP", "Trait", "Link", "Zone")  # not Source Title: per printing


def _image_url(printing_id: PrintingId, src: str | None) -> str | None:
    if src is None:
        return None
    absolute = urljoin(DETAIL_URL.format(printing_id), src)
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))  # drop the cache-busting query


def build_printing(page: SourcePage) -> Printing:
    subject = str(page.printing_id)
    parsed_rarity = parse_rarity(page.raw.rarity, subject)
    source_title = page.raw.fields.get("Source Title", "-")
    where = page.raw.fields.get("Where to get it", "")
    set_match = _SET_CODE_IN_TEXT.search(where)
    return Printing(
        id=page.printing_id,
        variant=page.printing_id.variant,
        rarity=parsed_rarity.rarity,
        alt_art_level=parsed_rarity.alt_art_level,
        link_art=parsed_rarity.link_art,
        block=parse_block(page.raw.block, subject),
        source_title=None if source_title == "-" else SourceTitle(source_title),
        where_to_get=where,
        set_code=SetCode(set_match.group(1) + set_match.group(2)) if set_match else None,
        package_ids=page.package_ids,
        image_url=_image_url(page.printing_id, page.raw.image_src),
    )


@dataclass
class _Group:
    text: str
    pages: list[SourcePage] = field(default_factory=list)
    printings: list[Printing] = field(default_factory=list)

    def block(self) -> Block | None:
        blocks = [p.block for p in self.printings if p.block is not None]
        return max(blocks, key=lambda b: b.rank) if blocks else None

    def as_of(self, release_dates: Mapping[SetCode, date]) -> date | None:
        dates = [release_dates[p.set_code] for p in self.printings if p.set_code is not None and p.set_code in release_dates]
        return max(dates) if dates else None

    def rank(self, release_dates: Mapping[SetCode, date]) -> tuple[int, date]:
        """(block rank, release date): newest wins. Alt arts don't establish recency (their wording has been
        slightly off before), so a wording's age comes from its non-alt-art printings when it has any."""
        basis = [p for p in self.printings if not p.alt_art] or self.printings
        blocks = [p.block for p in basis if p.block is not None]
        dates = [release_dates[p.set_code] for p in basis if p.set_code is not None and p.set_code in release_dates]
        return (max(b.rank for b in blocks) if blocks else -1, max(dates) if dates else date.min)

    def has_non_alt_art(self) -> bool:
        return any(not p.alt_art for p in self.printings)


def _order_text_groups(
    groups: list[_Group],
    base_id: PrintingId,
    release_dates: Mapping[SetCode, date],
    traits: frozenset[Trait],
    issues: list[Issue],
) -> list[_Group]:
    """Newest wording first. See design.md "Which text wins"."""
    ranked = sorted(groups, key=lambda g: g.rank(release_dates), reverse=True)
    top_rank = ranked[0].rank(release_dates)
    tied = [g for g in ranked if g.rank(release_dates) == top_rank]
    current = tied[0]
    if len(tied) > 1:
        cores = {comparison_core(g.text, traits)[0] for g in tied}
        if len(cores) == 1:
            # Differ only in reminder text and age can't separate them: keep the version WITH reminder text.
            current = max(tied, key=lambda g: comparison_core(g.text, traits)[1])
        elif sum(g.has_non_alt_art() for g in tied) == 1:
            current = next(g for g in tied if g.has_non_alt_art())  # decided: prefer the non-alt-art wording
        else:
            base_group = next(g for g in groups if any(p.id == base_id for p in g.printings))
            current = base_group
            issues.append(
                Issue(
                    IssueKind.AMBIGUOUS_RECENCY,
                    str(base_id.card_number),
                    f"{len(tied)} wordings tie on (block, release date) and differ substantively; "
                    f"using the base printing's text. Printings: {[[str(p.id) for p in g.printings] for g in tied]}",
                )
            )
    rest = sorted(
        (g for g in ranked if g is not current),
        key=lambda g: (g.rank(release_dates), comparison_core(g.text, traits)[1]),
        reverse=True,
    )
    return [current, *rest]


# ---- card assembly ---------------------------------------------------------------------------------
class _Common(TypedDict):
    number: CardNumber
    name: str
    text_versions: tuple[TextVersion, ...]
    keywords: frozenset[Keyword]
    referenced_traits: frozenset[Trait]
    printings: tuple[Printing, ...]
    faq: tuple[Faq, ...]
    unknown_tags: tuple[str, ...]
    fetched_at: datetime


def _parse_faq(page: SourcePage) -> tuple[Faq, ...]:
    entries = []
    for raw in page.raw.faq:
        try:
            updated = datetime.strptime(raw.updated, "%B %d, %Y").date()
        except ValueError as e:
            raise ParseError(str(page.printing_id), f"unrecognized FAQ date {raw.updated!r}") from e
        entries.append(Faq(id=raw.id, updated=updated, question=raw.question, answer=raw.answer))
    return tuple(entries)


def _comparable_name(name: str) -> str:
    return name.replace("\u2019", "'")  # typographic vs straight apostrophe is cosmetic


def _page_text(page: SourcePage) -> str:
    """The card text; Bandai writes `-` for "no text"."""
    return "" if page.raw.text == "-" else page.raw.text


def _comparable(page: SourcePage, label: str) -> str:
    """A field's value in a form where cosmetic differences vanish: numbers as numbers (`+1` == `1`, fullwidth digits),
    the card TYPE by what it parses to (`UNIT TOKEN` == `UNIT・TOKEN`). Falls back to the raw text."""
    value = page.raw.fields.get(label, "")
    try:
        if label in ("Lv.", "COST", "AP", "HP"):
            number = parse_int(value, str(page.printing_id), label)
            return "-" if number is None else str(number)
        if label == "TYPE":
            return parse_kind(value, str(page.printing_id)).value
    except ParseError:
        pass
    return value


def build_card(
    pages: Sequence[SourcePage],
    traits: frozenset[Trait],
    release_dates: Mapping[SetCode, date],
) -> BuildResult:
    """Build one card from all fetched printings of it (base printing required)."""
    if not pages:
        raise ValueError("build_card needs at least one page")
    number = pages[0].printing_id.card_number
    subject = str(number)
    if any(p.printing_id.card_number != number for p in pages):
        raise ParseError(subject, "pages from different cards were passed together")
    ordered = sorted(pages, key=lambda p: -1 if p.printing_id.variant is None else p.printing_id.variant)
    base = ordered[0]  # the reference printing: the base printing, or the lowest alt art if there is no base page
    issues: list[Issue] = []
    if base.printing_id.variant is not None:
        issues.append(
            Issue(
                IssueKind.NO_BASE_PRINTING,
                subject,
                f"no base printing page exists; attributes come from {base.printing_id} (the lowest alt art)",
            )
        )
    if base.raw.card_no != number:
        raise ParseError(subject, f"page shows card number {base.raw.card_no!r}")

    # printings: the reference printing must build; an alt art that can't be parsed is reported and left out
    printings: list[Printing] = [build_printing(base)]
    kept: list[SourcePage] = [base]
    for page in ordered[1:]:
        try:
            printings.append(build_printing(page))
        except ParseError as e:
            issues.append(Issue(IssueKind.PARSE_FAILURE, e.subject, f"{e.detail} (printing left out; the card is kept)"))
            continue
        kept.append(page)
        diffs = [
            f"{label}: {before!r} != {after!r}"
            for label in _COMPARED_FIELDS
            if (before := _comparable(base, label)) != (after := _comparable(page, label))
        ]
        if _comparable_name(base.raw.name) != _comparable_name(page.raw.name):
            diffs.append(f"name: {base.raw.name!r} != {page.raw.name!r}")
        if diffs:
            issues.append(Issue(IssueKind.PRINTING_ATTRIBUTE_MISMATCH, str(page.printing_id), "; ".join(diffs)))

    # text versions, newest first
    groups: dict[str, _Group] = {}
    for page, printing in zip(kept, printings, strict=True):
        text = _page_text(page)
        group = groups.setdefault(text, _Group(text))
        group.pages.append(page)
        group.printings.append(printing)
    ordered_groups = _order_text_groups(list(groups.values()), base.printing_id, release_dates, traits, issues)
    current_core, _ = comparison_core(ordered_groups[0].text, traits)
    text_versions = tuple(
        TextVersion(
            text=g.text,
            printing_ids=tuple(p.id for p in g.printings),
            block=g.block(),
            as_of=g.as_of(release_dates),
            substantive=comparison_core(g.text, traits)[0] != current_core,
        )
        for g in ordered_groups
    )

    # keywords and trait mentions come from the current wording
    current_text = text_versions[0].text
    keywords, unknown = extract_keywords(current_text, traits)
    for tag in unknown:
        issues.append(Issue(IssueKind.UNKNOWN_TAG, subject, tag))
    for g in ordered_groups[1:]:
        other, _ = extract_keywords(g.text, traits)
        if other != keywords:
            issues.append(
                Issue(
                    IssueKind.KEYWORDS_CHANGED,
                    subject,
                    f"current {sorted(keywords)} vs older wording {sorted(other)} ({[str(p.id) for p in g.printings]})",
                )
            )

    common = _Common(
        number=number,
        name=base.raw.name,
        text_versions=text_versions,
        keywords=keywords,
        referenced_traits=referenced_traits(current_text, traits),
        printings=tuple(printings),
        faq=_parse_faq(base),
        unknown_tags=unknown,
        fetched_at=base.fetched_at,
    )
    card = _build_variant(base, common, current_text)
    return BuildResult(card, tuple(issues))


def _build_variant(base: SourcePage, common: _Common, current_text: str) -> CardModel:
    subject = str(base.printing_id)
    f = base.raw.fields

    def field_value(label: str) -> str:
        if label not in f:
            raise ParseError(subject, f"page has no {label!r} field")
        return f[label]

    kind = parse_kind(field_value("TYPE"), subject)
    ap = parse_int(f.get("AP", "-"), subject, "AP")
    hp = parse_int(f.get("HP", "-"), subject, "HP")

    def colored() -> tuple[Color, int, int]:
        return (
            _require(parse_color(field_value("COLOR"), subject), subject, "COLOR"),
            _require(parse_int(field_value("Lv."), subject, "Lv."), subject, "Lv."),
            _require(parse_int(field_value("COST"), subject, "COST"), subject, "COST"),
        )

    match kind:
        case CardKind.UNIT:
            color, level, cost = colored()
            zones = parse_zones(field_value("Zone"), subject)
            if not zones:
                raise ParseError(subject, "a Unit must have at least one Zone")
            return UnitCard(
                **common,
                color=color,
                level=level,
                cost=cost,
                ap=ap,
                hp=_require(hp, subject, "HP"),
                zones=zones,
                traits=parse_traits(field_value("Trait"), subject),
                link=parse_link(field_value("Link"), subject),
            )
        case CardKind.PILOT:
            color, level, cost = colored()
            return PilotCard(
                **common,
                color=color,
                level=level,
                cost=cost,
                ap_bonus=_require(ap, subject, "AP"),
                hp_bonus=_require(hp, subject, "HP"),
                traits=parse_traits(field_value("Trait"), subject),
            )
        case CardKind.COMMAND:
            color, level, cost = colored()
            pilot_name = pilot_name_in_text(current_text)
            pilot: PilotProfile | None = None
            if pilot_name is not None:
                pilot = PilotProfile(
                    name=pilot_name,
                    ap_bonus=_require(ap, subject, "AP (needed for the 【Pilot】 effect)"),
                    hp_bonus=_require(hp, subject, "HP (needed for the 【Pilot】 effect)"),
                )
            elif ap is not None or hp is not None:
                raise ParseError(subject, "Command shows AP/HP but its text has no 【Pilot】[Name] effect")
            return CommandCard(
                **common, color=color, level=level, cost=cost, traits=parse_traits(field_value("Trait"), subject), pilot=pilot
            )
        case CardKind.BASE:
            color, level, cost = colored()
            return BaseCard(
                **common,
                color=color,
                level=level,
                cost=cost,
                hp=_require(hp, subject, "HP"),
                zones=parse_zones(field_value("Zone"), subject),
                traits=parse_traits(field_value("Trait"), subject),
            )
        case CardKind.EX_BASE:
            return ExBaseCard(**common, hp=_require(hp, subject, "HP"))
        case CardKind.RESOURCE:
            return ResourceCard(**common)
        case CardKind.EX_RESOURCE:
            return ExResourceCard(**common)
        case CardKind.UNIT_TOKEN:
            return UnitTokenCard(
                **common, ap=ap, hp=_require(hp, subject, "HP"), traits=parse_traits(field_value("Trait"), subject)
            )


# ---- whole catalog ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class CatalogResult:
    cards: tuple[CardModel, ...]
    issues: tuple[Issue, ...]
    trait_vocabulary: frozenset[Trait]


def build_trait_vocabulary(pages: Iterable[SourcePage]) -> frozenset[Trait]:
    """Pass 1: every trait that appears in any card's `Trait` field."""
    vocabulary: set[Trait] = set()
    for page in pages:
        vocabulary.update(parse_traits(page.raw.fields.get("Trait", "-"), str(page.printing_id)))
    return frozenset(vocabulary)


def build_catalog(pages: Sequence[SourcePage], release_dates: Mapping[SetCode, date]) -> CatalogResult:
    """Pass 1 builds the trait vocabulary; pass 2 builds every card. Parse failures are issues, not crashes."""
    issues: list[Issue] = []
    usable: list[SourcePage] = []
    for page in pages:
        try:
            parse_traits(page.raw.fields.get("Trait", "-"), str(page.printing_id))
            usable.append(page)
        except ParseError as e:
            issues.append(Issue(IssueKind.PARSE_FAILURE, e.subject, e.detail))
    vocabulary = build_trait_vocabulary(usable)

    by_card: dict[CardNumber, list[SourcePage]] = defaultdict(list)
    for page in usable:
        by_card[page.printing_id.card_number].append(page)

    cards: list[CardModel] = []
    for number in sorted(by_card):
        try:
            result = build_card(by_card[number], vocabulary, release_dates)
        except (ParseError, ValueError) as e:
            subject = e.subject if isinstance(e, ParseError) else str(number)
            detail = e.detail if isinstance(e, ParseError) else str(e)
            issues.append(Issue(IssueKind.PARSE_FAILURE, subject, detail))
            continue
        cards.append(result.card)
        issues.extend(result.issues)
    return CatalogResult(tuple(cards), tuple(issues), vocabulary)
