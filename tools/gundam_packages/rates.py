"""Appearance rates: why a card is played (see tools/gundam_packages/appearance-rates.md).

Everything is a count divided by a count. A *deck* is one counted deck list; a deck plays package X when it has at least `run_share`
of X's members. For perspective package X with Y decks out of Z:

- package played rate = Y / Z;  a member's rate = its copies in those decks / (4 x Y);
- partner W: pair_decks (YY) of X's decks also play W; combined rate = YY / Y, joint rate = YY / Z;
- W's cards and bridge cards, from X's perspective: combined rate x (copies in the YY decks / (4 x YY)) = copies / (4 x Y);
- synergy, free-floating and other cards: copies in X's Y decks / (4 x Y), not multiplied.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from shared.basetypes import CardNumber
from tools.gundam_packages.discover import runs_package
from tools.gundam_packages.models import (
    MAX_COPIES,
    Histogram,
    ArchetypeCard,
    ArchetypeRate,
    ArchetypeRole,
    ComboCard,
    MemberRate,
    OtherCard,
    OtherRole,
    PackageId,
    PackageRates,
    PackagesFile,
    PartnerRates,
    RatesFile,
    Role,
)

CopyDeck = Mapping[CardNumber, int]
ARCHETYPE_CARD_MIN_SHARE = 0.25  # a card is in an archetype's table when at least this share of its decks run it (package members always are)
LOW_SAMPLE_DECKS = 20  # an archetype with fewer decks has copy counts that should not be trusted


def _histogram(decks: Sequence[CopyDeck], card: CardNumber) -> Histogram:
    """How many of `decks` play 0, 1, 2, 3 and 4 copies of `card` (a deck with more than 4 fails the model's check, loudly)."""
    counts = [0, 0, 0, 0, 0]
    for d in decks:
        counts[min(d.get(card, 0), MAX_COPIES)] += 1
    return (counts[0], counts[1], counts[2], counts[3], counts[4])


def _combo_card(card: CardNumber, copies: Counter[CardNumber], pair: Sequence[CopyDeck], combined: float) -> ComboCard:
    possible = MAX_COPIES * len(pair)
    in_combo = copies[card] / possible
    return ComboCard(card_number=card, copies=copies[card], possible=possible, rate_in_combo=in_combo, rate_from_x=combined * in_combo,
                     histogram=_histogram(pair, card))  # fmt: skip


def _archetype(
    signature: tuple[PackageId, ...],
    n: int,
    total: int,
    decks: Sequence[CopyDeck],
    names: Mapping[PackageId, str],
    member_of: Mapping[CardNumber, tuple[PackageId, ArchetypeRole]],
    bridges: Mapping[tuple[PackageId, PackageId], tuple[CardNumber, ...]],
    synergy_of: set[tuple[CardNumber, PackageId]],
    floating: set[CardNumber],
) -> ArchetypeRate:
    """One archetype with the table of cards its decks run: every card of its packages that a deck runs, and every card in at least
    ARCHETYPE_CARD_MIN_SHARE of its decks, each with why it is there and its copy histogram."""
    name = " + ".join(names[p] for p in signature) or "No package"
    if not signature:
        return ArchetypeRate(packages=signature, name=name, decks=n, rate=n / total)
    bridge_cards = {c for a in signature for b in signature if a != b for c in bridges.get((a, b), ())}
    with_card: Counter[CardNumber] = Counter()
    for d in decks:
        with_card.update(c for c, q in d.items() if q > 0)
    cards: list[ArchetypeCard] = []
    for card, count in with_card.items():
        share = count / n
        if card in member_of and member_of[card][0] in signature:
            role = member_of[card][1]  # a core or optional member of one of the archetype's packages
        elif card in bridge_cards:
            role = ArchetypeRole.BRIDGE
        elif any((card, p) in synergy_of for p in signature):
            role = ArchetypeRole.SYNERGY
        elif card in floating:
            role = ArchetypeRole.FREE_FLOATING
        else:
            role = ArchetypeRole.OTHER
        if role in (ArchetypeRole.CORE, ArchetypeRole.OPTIONAL) or share >= ARCHETYPE_CARD_MIN_SHARE:
            cards.append(ArchetypeCard(card_number=card, role=role, decks=count, share=share, histogram=_histogram(decks, card)))
    order = {r: i for i, r in enumerate(ArchetypeRole)}
    cards.sort(key=lambda c: (order[c.role], -c.share, c.card_number))
    return ArchetypeRate(packages=signature, name=name, decks=n, rate=n / total, cards=tuple(cards), low_sample=n < LOW_SAMPLE_DECKS)


def compute_rates(base: PackagesFile, decks: Sequence[CopyDeck], generated_at: datetime) -> RatesFile:
    """Rates for every package in `base`, over `decks` (card -> copies), which must be the decks the packages were found in."""
    total = len(decks)
    run_share = base.params.run_share
    members_of = {p.id: [m.card_number for m in p.members] for p in base.packages}
    owner = {card: pid for pid, members in members_of.items() for card in members}
    order = {p.id: i for i, p in enumerate(base.packages)}
    names = {p.id: p.name for p in base.packages}
    plays = [frozenset(pid for pid, members in members_of.items() if runs_package(frozenset(d), members, run_share)) for d in decks]

    bridges: dict[tuple[PackageId, PackageId], tuple[CardNumber, ...]] = {}
    synergistic: set[tuple[PackageId, PackageId]] = set()
    for s in base.package_synergies:
        found = tuple(b.card_number for b in s.bridges)
        for pair in ((s.package_a, s.package_b), (s.package_b, s.package_a)):
            bridges[pair] = found
            synergistic.add(pair)
    synergy_of = {(h.card_number, h.package) for h in base.synergy_cards}
    floating = {f.card_number for f in base.free_floating}

    packages: list[PackageRates] = []
    for package in base.packages:
        x = package.id
        in_x = [i for i in range(total) if x in plays[i]]
        y = len(in_x)
        if y == 0:
            continue
        possible = MAX_COPIES * y
        copies: Counter[CardNumber] = Counter()
        for i in in_x:
            copies.update(decks[i])
        x_decks = [decks[i] for i in in_x]
        members = tuple(
            MemberRate(card_number=m.card_number, role=m.role, copies=copies[m.card_number], possible=possible, rate=copies[m.card_number] / possible,
                       histogram=_histogram(x_decks, m.card_number))
            for m in package.members
        )  # fmt: skip

        partners: list[PartnerRates] = []
        partner_members: set[CardNumber] = set()
        together = Counter(w for i in in_x for w in plays[i] if w != x)
        for w, yy in sorted(together.items(), key=lambda kv: (-kv[1], order[kv[0]])):
            both = [i for i in in_x if w in plays[i]]
            combo: Counter[CardNumber] = Counter()
            pair_list = [decks[i] for i in both]
            for d in pair_list:
                combo.update(d)
            combined = yy / y
            partner_members.update(members_of[w])
            partners.append(
                PartnerRates(
                    package=w,
                    synergistic=(x, w) in synergistic,
                    pair_decks=yy,
                    combined_rate=combined,
                    joint_rate=yy / total,
                    cards=tuple(_combo_card(c, combo, pair_list, combined) for c in members_of[w]),
                    bridges=tuple(_combo_card(c, combo, pair_list, combined) for c in bridges.get((x, w), ())),
                )
            )

        own = set(members_of[x])
        others: list[OtherCard] = []
        for card, n in copies.items():
            if card in own or card in partner_members:
                continue
            role = OtherRole.SYNERGY if (card, x) in synergy_of else OtherRole.FREE_FLOATING if card in floating else OtherRole.OTHER
            others.append(OtherCard(card_number=card, copies=n, possible=possible, rate=n / possible, role=role, belongs_to=owner.get(card)))
        others.sort(key=lambda o: (-o.rate, o.card_number))

        alone = sum(1 for i in in_x if plays[i] == {x})
        packages.append(
            PackageRates(
                package=x, name=package.name, package_decks=y, rate=y / total, alone_decks=alone, alone_rate=alone / y,
                members=members, partners=tuple(partners), others=tuple(others),
            )
        )  # fmt: skip

    sig_of = [tuple(sorted(p, key=order.__getitem__)) for p in plays]
    signatures = Counter(sig_of)
    member_of = {
        m.card_number: (p.id, ArchetypeRole.CORE if m.role is Role.CORE else ArchetypeRole.OPTIONAL) for p in base.packages for m in p.members
    }
    archetypes = tuple(
        _archetype(sig, n, total, [decks[i] for i in range(total) if sig_of[i] == sig], names, member_of, bridges, synergy_of, floating)
        for sig, n in sorted(signatures.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    seen = sorted({card for d in decks for card in d})
    return RatesFile(
        generated_at=generated_at,
        source=base.source,
        window=base.window,
        total_decks=total,
        packages=tuple(packages),
        archetypes=archetypes,
        card_index={card: owner.get(card) for card in seen},
    )
