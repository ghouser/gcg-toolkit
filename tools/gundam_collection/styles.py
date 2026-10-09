"""What a deck does: ratings for its curve, pressure, interaction and advantage (and finisher and resilience), the plan they add up to, and its colors.

Everything is computed from the deck's card table (core, staples and half-weight options) and the card text; nothing is guessed. Each rating
is 0 to 100 from one measured number mapped between two named anchors (so it is easy to tune against decks I know), and the numbers are
kept so the label can always be explained (design.md, "Deck style").

- **Curve**: an aggressive curve is lots of small Units: the share of Unit copies at Lv3 or less, and how little of the deck is Lv6+.
- **Pressure**: Units that hit harder than they take (AP greater than HP) or have Breach, Suppression or High-Maneuver, minus Units that are built to
  take hits (AP less than HP).
- **Interaction**: Commands, and Units that answer the opponent: Blockers and Units whose abilities hit the board (damage, destroy, bounce, -AP, rest).
  Units you just turn sideways are low interaction.
- **Advantage**: cards that put a new card in your hand ("draw N", "add ... to your hand"): see `advantage_weight`. A condition halves it: an "if" that gates
  the card (not "if you do" after a cost), a "when ..." trigger, a Destroyed trigger, a filtered search ("reveal ... among them"), or a pick from the
  trash. "Look at the top N" alone is not advantage, and neither is deploying a card from the trash.
- **Finisher** (not used for the plan): Lv7+ Units, and half for Lv6, as a share of Units: a way to top out.
- **Resilience** (not used for the plan): Bases, Repair Units and protect effects: surviving while you set up.

Plan, after "Who's the Beatdown": one **beatdown-to-control axis**, the mean of four ratings: curve, pressure, low interaction (100 minus it) and low
advantage (100 minus it). A pure beatdown wants a fast curve and pressure and does not need answers or cards; a control deck wants answers and a steady
supply of cards. **Aggro** = 60 or more, **Control** = 38 or less, **Midrange** = everything between (it can play either role).
Pure functions over the deck's requirements and the card catalog.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from shared.basetypes import CardNumber
from shared.samejob import effect_features, native_keywords
from shared.samejob.vocabulary import base_core_text
from tools.gundam_cards.models import BaseCard, CardKind, CardModel, CommandCard, Keyword, UnitCard, color_of
from tools.gundam_collection.decks import Layer, Requirement

OPTION_WEIGHT = 0.5  # an option card counts half: not every list runs it
PRESSURE_KEYWORDS = frozenset({Keyword.BREACH, Keyword.SUPPRESSION, Keyword.HIGH_MANEUVER})
INTERACTION_FEATURES = frozenset({"damage", "damage all", "destroy", "destroy all", "bounce", "-AP", "-AP all", "rest", "rest all", "attack target"})
HAND_ADD = re.compile(r"\bdraw (?:\d+|x)\b|\badd (?!this card\b)[^.]{0,80}\bto your hand", re.I)  # puts a card in my hand (draw N, add ... to hand)
CONDITION = re.compile(r"\bif\b(?!\s+you do)|\bwhen\b|\breveal\b|\bamong them\b|\bfrom your trash\b", re.I)  # a condition on getting the card
CONDITIONAL_WEIGHT = 0.5
_TOKEN_STATS = re.compile(r"\bAP(\d+)\W+HP(\d+)")  # a deployed token: [Tallgeese]((OZ)･AP4･HP2)
_REMINDER = re.compile(r"\([^()]*\)")
_LEADING_TAGS = re.compile(r"^(?:【[^】]*】\s*)+")
RESILIENCE_FEATURES = frozenset({"protect", "recover", "recover all"})
LETTERS = {"red": "R", "blue": "B", "green": "G", "white": "W", "purple": "P"}
COLOR_MIN_SHARE = 0.20  # a color is named when it is at least this share of the colored copies
MAX_COLORS = 3

# anchors: the measured number that maps to rating 0 and to rating 100 (linear in between, clamped)
CURVE = (0.35, 0.85)
PRESSURE = (-0.35, 0.35)
INTERACTION = (0.15, 0.65)
ADVANTAGE = (0.0, 0.35)
FINISHER = (0.0, 0.25)
RESILIENCE = (0.0, 0.25)
HIGH = 60  # a beatdown score at or above this is aggro
LOW = 40  # a beatdown score at or below this is control (40, then 38, then 40 again: at 38 Master Asia + Domon Shining and Barbatos + Kira Strike Freedom, both at 39, were midrange; both read control)


class Plan(StrEnum):
    AGGRO = "aggro"
    MIDRANGE = "midrange"
    CONTROL = "control"


@dataclass(frozen=True)
class Style:
    colors: tuple[str, ...]  # letters, most copies first: ("R", "G")
    curve: int
    pressure: int
    interaction: int
    advantage: int
    finisher: int
    resilience: int
    plan: Plan
    beatdown: int  # the axis: 0 pure control .. 100 pure beatdown
    facts: Mapping[str, float]  # the measured numbers behind the ratings
    links: int = 0  # Link pairs: pilots that can pair with Linked Units (not part of the plan axis: every plan wants them)

    @property
    def color_text(self) -> str:
        return "/".join(self.colors)


def satisfies(unit: CardModel, pilot: CardModel) -> bool:
    """Whether the pilot's name (aliases included) or traits satisfy the Unit's Link."""
    from shared.samejob.pilots import identity

    if not isinstance(unit, UnitCard) or unit.link is None:
        return False
    names, traits = identity(pilot)
    return unit.link.satisfied_by_any(names, traits)


def link_pairs(chosen: Mapping[CardNumber, int], catalog: Mapping[CardNumber, CardModel]) -> tuple[int, int, int]:
    """(Link pairs possible, Linked Unit copies, pilot copies): each pilot copy pairs with one Unit copy whose Link it satisfies."""
    from shared.samejob.pilots import is_pilot

    units = {c: n for c, n in chosen.items() if isinstance(catalog[c], UnitCard) and catalog[c].link is not None}  # type: ignore[union-attr]
    pilots = {c: n for c, n in chosen.items() if is_pilot(catalog[c])}
    left = dict(units)
    pairs = 0
    for pilot in sorted(pilots, key=lambda p: (sum(left[u] for u in units if satisfies(catalog[u], catalog[p])), p)):  # the most constrained pilot first
        for _ in range(pilots[pilot]):
            target = next((u for u in sorted(units) if left[u] > 0 and satisfies(catalog[u], catalog[pilot])), None)
            if target is not None:
                left[target] -= 1
                pairs += 1
    return pairs, sum(units.values()), sum(pilots.values())


LINKS = (0.0, 12.0)  # Link pairs rated 0..10: none to a dozen


def scale(x: float, anchors: tuple[float, float]) -> int:
    low, high = anchors
    return round(100 * min(1.0, max(0.0, (x - low) / (high - low))))


def advantage_weight(text: str) -> float:
    """1.0 if the card puts a new card in my hand without a condition, 0.5 if every way it does so has a condition, 0 if it never does.

    Per ability (a line of text): sentences are read in order, and a hand-adding sentence is conditional if it, or a sentence before it in the same
    ability, has a condition (an "if" that is not "if you do", "when", "reveal ... among them", "from your trash") or the ability is a Destroyed trigger.
    A card is as good as its best ability."""
    best = 0.0
    for line in text.split("\n"):
        tags = _LEADING_TAGS.match(line.strip())
        tag_text = tags.group(0) if tags else ""
        body = line.strip()[len(tag_text) :]
        previous = None
        while previous != body:
            previous, body = body, _REMINDER.sub(" ", body)
        gated = "Destroyed" in tag_text
        for sentence in re.split(r"(?<=[.])\s+", body):
            gated = gated or bool(CONDITION.search(sentence))
            if HAND_ADD.search(sentence):
                best = max(best, CONDITIONAL_WEIGHT if gated else 1.0)
    return best


def _share(n: float, d: float) -> float:
    return n / d if d else 0.0


def beatdown_score(curve: int, pressure: int, interaction: int, advantage: int) -> int:
    """0 (pure control) to 100 (pure beatdown): the mean of curve, pressure, low interaction and low advantage."""
    return round((curve + pressure + (100 - interaction) + (100 - advantage)) / 4)


def plan_of(curve: int, pressure: int, interaction: int, advantage: int) -> Plan:
    """Aggro at 60 or more on the beatdown axis, control at 40 or less (LOW), midrange in between."""
    score = beatdown_score(curve, pressure, interaction, advantage)
    return Plan.AGGRO if score >= HIGH else Plan.CONTROL if score <= LOW else Plan.MIDRANGE


@dataclass(frozen=True)
class CardSignals:
    """What one card contributes to the ratings (the same tests as the deck rating, on a single card). Shared by `style_of` and the deck builder."""

    kind: CardKind
    letter: str | None  # color letter (R B G W P)
    low: bool = False  # a Unit at Lv3 or less
    top: bool = False  # a Unit at Lv6 or more
    finisher: float = 0.0  # 1 for Lv7+, half for Lv6
    pushing: bool = False  # AP over HP, or Breach / Suppression / High-Maneuver
    sturdy: bool = False  # AP under HP
    blocker: bool = False
    interactive: bool = False  # a Unit that is a Blocker or has a board-hitting ability (a Command always interacts)
    advantage: float = 0.0  # 1.0 a card in hand, 0.5 if conditional
    resilient: bool = False

    @property
    def is_unit(self) -> bool:
        return self.kind is CardKind.UNIT

    @property
    def is_command(self) -> bool:
        return self.kind is CardKind.COMMAND

    @property
    def is_base(self) -> bool:
        return self.kind is CardKind.BASE


def card_signals(card: CardModel) -> CardSignals | None:
    """None for cards that are not part of a deck's 50 (resources, tokens)."""
    if card.kind not in (CardKind.UNIT, CardKind.COMMAND, CardKind.BASE, CardKind.PILOT):
        return None
    color = color_of(card)
    letter = LETTERS[color.value] if color is not None else None
    text = base_core_text(card.text) if isinstance(card, BaseCard) else card.text  # a Base's baseline (Shield to hand) is not an effect
    features = effect_features(text, grants=isinstance(card, CommandCard | BaseCard))
    advantage = advantage_weight(text)
    if isinstance(card, UnitCard):
        keywords = native_keywords(card.text)
        return CardSignals(
            card.kind, letter, low=card.level <= 3, top=card.level >= 6, finisher=1.0 if card.level >= 7 else (0.5 if card.level == 6 else 0.0),
            pushing=(card.ap is not None and card.ap > card.hp) or bool(keywords & PRESSURE_KEYWORDS), sturdy=card.ap is not None and card.ap < card.hp,
            blocker=Keyword.BLOCKER in keywords, interactive=Keyword.BLOCKER in keywords or bool(features & INTERACTION_FEATURES), advantage=advantage,
            resilient=Keyword.REPAIR in keywords or bool(features & RESILIENCE_FEATURES),
        )  # fmt: skip
    if isinstance(card, CommandCard):
        return CardSignals(card.kind, letter, advantage=advantage, resilient=bool(features & RESILIENCE_FEATURES))
    if isinstance(card, BaseCard):
        # A Base counts toward the same ratings as a body: cheap is a low curve, a token with AP over HP is pressure (AP under HP is sturdy), and a Base that
        # hits the opponent's board is interaction (Gundam Fight). Its Shield-to-hand baseline is not advantage (base_core_text removed it above).
        tokens = [(int(ap), int(hp)) for ap, hp in _TOKEN_STATS.findall(text)]
        return CardSignals(
            card.kind, letter, low=card.level <= 3, pushing=any(ap > hp for ap, hp in tokens), sturdy=bool(tokens) and all(ap < hp for ap, hp in tokens),
            interactive=bool(features & INTERACTION_FEATURES), advantage=advantage, resilient=True,
        )  # fmt: skip
    return CardSignals(card.kind, letter, advantage=advantage)


def style_of(
    requirements: Sequence[Requirement], catalog: Mapping[CardNumber, CardModel], signals: Mapping[CardNumber, CardSignals | None] | None = None
) -> Style:
    """Rate a card table. `signals` (card number -> card_signals) can be given to avoid reading the same card text again and again."""
    units = commands = bases = total = 0.0
    low = top = finisher = pushing = sturdy = blockers = unit_interactive = advantage = resilient = 0.0
    colored: dict[str, float] = defaultdict(float)
    for r in requirements:
        card = catalog.get(r.card)
        sig = (signals[r.card] if signals is not None and r.card in signals else card_signals(card)) if card is not None else None
        if sig is None:
            continue
        w = r.need * (1.0 if r.layer in (Layer.CORE, Layer.STAPLE) else OPTION_WEIGHT)
        total += w
        if sig.letter is not None:
            colored[sig.letter] += w
        advantage += w * sig.advantage
        resilient += w if sig.resilient else 0
        if sig.is_unit:
            units += w
            low += w if sig.low else 0
            top += w if sig.top else 0
            finisher += w * sig.finisher
            pushing += w if sig.pushing else 0
            sturdy += w if sig.sturdy else 0
            blockers += w if sig.blocker else 0
            unit_interactive += w if sig.interactive else 0
        elif sig.is_command:
            commands += w
        elif sig.is_base:  # a Base counts with the Units toward curve, pressure and interaction (cheap, a body in play, hitting the board)
            bases += w
            low += w if sig.low else 0
            pushing += w if sig.pushing else 0
            sturdy += w if sig.sturdy else 0
            unit_interactive += w if sig.interactive else 0
    bodies = units + bases  # Units and Bases: the cards that are bodies or sit on the board
    curve_x = 0.5 * _share(low, bodies) + 0.5 * (1 - _share(top, bodies))
    pressure_x = _share(pushing - sturdy, bodies)
    interaction_x = _share(commands + unit_interactive, total)
    advantage_x = _share(advantage, total)
    finisher_x = _share(finisher, units)
    resilience_x = _share(resilient, total)
    curve, pressure, interaction = scale(curve_x, CURVE), scale(pressure_x, PRESSURE), scale(interaction_x, INTERACTION)
    weight = sum(colored.values())
    ranked = sorted(colored.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_COLORS]
    letters = tuple(c for c, n in ranked if weight and n / weight >= COLOR_MIN_SHARE)
    facts = {
        "unit copies": units, "avg share Lv<=3": _share(low, bodies), "share Lv>=6": _share(top, bodies), "AP>HP or pressure keyword": _share(pushing, bodies),
        "AP<HP": _share(sturdy, bodies), "blockers": _share(blockers, units), "command copies": commands, "interactive units (incl. blockers)": _share(unit_interactive, units), "base copies": bases,
        "advantage cards": _share(advantage, total),
    }  # fmt: skip
    advantage_rating = scale(advantage_x, ADVANTAGE)
    chosen: dict[CardNumber, int] = defaultdict(int)
    for r in requirements:
        if r.layer in (Layer.CORE, Layer.STAPLE) and r.card in catalog:
            chosen[r.card] += r.need
    pairs = link_pairs(chosen, catalog)[0]
    facts["link pairs"] = pairs
    return Style(letters, curve, pressure, interaction, advantage_rating, scale(finisher_x, FINISHER), scale(resilience_x, RESILIENCE),
                 plan_of(curve, pressure, interaction, advantage_rating), beatdown_score(curve, pressure, interaction, advantage_rating), facts, scale(pairs, LINKS))  # fmt: skip
