"""Deck legality from Bandai's banned / restricted list (design.md, "Banned and restricted cards"). Pure functions; the list is data (`restrictions.json`).

- a banned card has no copies and a restricted card at most its limit; every other card at most 4;
- two cards of a banned pair cannot be in the same deck;
- the vanilla group (a Unit that is Lv2, cost 1, 2 AP, 2 HP and without effects, matched against the catalog) allows one card, up to four copies:
  any two different ones are a banned pair.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Restrictions
from tools.gundam_cards.restrictions import vanilla_cards

MAX_COPIES = 4


@dataclass(frozen=True)
class Rules:
    banned: frozenset[CardNumber]
    limits: Mapping[CardNumber, int]
    pairs: frozenset[frozenset[CardNumber]]
    vanilla: frozenset[CardNumber]

    @staticmethod
    def of(restrictions: Restrictions | None, catalog: Mapping[CardNumber, CardModel]) -> Rules:
        """The rules from the list and the catalog; with no list, everything is legal (the first sync has not happened yet)."""
        if restrictions is None:
            return NO_RULES
        return Rules(
            frozenset(restrictions.banned),
            {r.card: r.copies for r in restrictions.limited},
            frozenset(frozenset({p.a, p.b}) for p in restrictions.banned_pairs),
            vanilla_cards(dict(catalog)) | frozenset(restrictions.vanilla_group),
        )

    def copy_limit(self, card: CardNumber) -> int:
        """0 for a banned card, the restricted count, else 4."""
        return 0 if card in self.banned else self.limits.get(card, MAX_COPIES)

    def conflicts(self, card: CardNumber, others: Iterable[CardNumber]) -> tuple[str, ...]:
        """Why `card` cannot join a deck that has `others` (empty when it can)."""
        found: list[str] = []
        for other in others:
            if other == card:
                continue
            if frozenset({card, other}) in self.pairs:
                found.append(f"{card} and {other} are a banned pair")
            elif card in self.vanilla and other in self.vanilla:
                found.append(f"{card} and {other} are both in the vanilla group (one such card per deck)")
        return tuple(found)

    def violations(self, counts: Mapping[CardNumber, int]) -> tuple[str, ...]:
        """Everything illegal in a deck list: banned cards, copies above a limit, banned pairs and two different vanilla-group cards."""
        out: list[str] = []
        present = sorted(n for n, c in counts.items() if c > 0)
        for n in present:
            limit = self.copy_limit(n)
            if limit == 0:
                out.append(f"{n} is banned")
            elif counts[n] > limit:
                out.append(f"{counts[n]} copies of {n}, restricted to {limit}")
        for i, a in enumerate(present):
            out.extend(self.conflicts(a, present[i + 1 :]))
        return tuple(out)


NO_RULES = Rules(frozenset(), {}, frozenset(), frozenset())
