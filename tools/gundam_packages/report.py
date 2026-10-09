"""A markdown report of one era's meta (decks by color combination, the packages they run) and how the next era adjusts it.

Pure function of already-computed data: the base era's `PackagesFile` and decks, the next era's decks and `DriftFile`, and the card catalog.
Every number is a count of decks (a card's count is the number of decks that run it). Nothing here is judged by hand.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color, color_of
from tools.gundam_packages.discover import Deck, runs_package
from tools.gundam_packages.models import DriftFile, Package, PackageId, PackagesFile, SynergyCard

MIN_COLOR_CARDS = 4  # a color is in a deck's identity when at least this many of its cards are that color (ignores a one-card splash)
TOP_CARDS = 10
MOVERS = 8
MIN_MOVER_DECKS = 6  # a card must be in at least this many decks in one of the windows to count as a mover
NO_PACKAGE = "No package"

Combo = tuple[Color, ...]


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f}%" if total else "-"


def pts(change: float) -> str:
    """A change in share (as a fraction) in percentage points, never "-0"."""
    value = round(100 * change)
    return f"{value:+d} pts" if value else "0 pts"


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return [*lines, ""]


def combo_label(combo: Combo) -> str:
    return " / ".join(c.value.title() for c in combo) or "Colorless"


def deck_combo(deck: Deck, cards: Mapping[CardNumber, CardModel]) -> Combo:
    counts = Counter(c for n in deck if (c := color_of(cards[n])) is not None)
    chosen = sorted((c for c, k in counts.items() if k >= MIN_COLOR_CARDS), key=lambda c: c.value)
    if not chosen and counts:
        chosen = [counts.most_common(1)[0][0]]
    return tuple(chosen)


def signature(deck: Deck, packages: Sequence[Package], run_share: float) -> tuple[PackageId, ...]:
    return tuple(p.id for p in packages if runs_package(deck, [m.card_number for m in p.members], run_share))


class _Names:
    def __init__(self, cards: Mapping[CardNumber, CardModel], packages: Sequence[Package]) -> None:
        self._cards = cards
        self.package = {p.id: p.name for p in packages}

    def card(self, number: CardNumber) -> str:
        return f"{self._cards[number].name} ({number})"

    def archetype(self, sig: tuple[PackageId, ...]) -> str:
        return " + ".join(self.package[p] for p in sig) or NO_PACKAGE


def _tag(number: CardNumber, base: PackagesFile, names: _Names) -> str:
    members = {m.card_number for p in base.packages for m in p.members}
    if number in members:
        return "package"
    tied = sorted((h for h in base.synergy_cards if h.card_number == number), key=lambda h: -h.share)
    if tied:
        return f"synergy with {names.package[tied[0].package]} ({100 * tied[0].share:.0f}%)"
    if any(number == b.card_number for s in base.package_synergies for b in s.bridges):
        return "bridge"
    return "free floating" if any(f.card_number == number for f in base.free_floating) else "rare"


def _meta_section(base: PackagesFile, decks: Sequence[Deck], cards: Mapping[CardNumber, CardModel], names: _Names) -> list[str]:
    total = len(decks)
    run_share = base.params.run_share
    by_combo: dict[Combo, list[Deck]] = {}
    for deck in decks:
        by_combo.setdefault(deck_combo(deck, cards), []).append(deck)
    ordered = sorted(by_combo.items(), key=lambda kv: (-len(kv[1]), combo_label(kv[0])))
    packaged = {m.card_number for p in base.packages for m in p.members}

    out = ["## 1. The meta by color combination", "",
           f"{total} decks. A deck's colors are the colors with at least {MIN_COLOR_CARDS} cards in its main deck. Combinations are ordered by how many decks play them.", ""]
    out += table(["Colors", "Decks", "Share", "Most-played archetype"],
                 [[combo_label(c), str(len(d)), pct(len(d), total),
                   names.archetype(Counter(signature(x, base.packages, run_share) for x in d).most_common(1)[0][0])] for c, d in ordered])

    for combo, members in ordered:
        n = len(members)
        out += [f"### {combo_label(combo)}: {n} decks ({pct(n, total)})", ""]
        sigs = Counter(signature(d, base.packages, run_share) for d in members)
        out += ["**Archetypes** (the packages a deck runs):", ""]
        out += table(["Archetype", "Decks", "Share of combo"], [[names.archetype(s), str(k), pct(k, n)] for s, k in sigs.most_common()])
        used = [(p, sum(1 for d in members if runs_package(d, [m.card_number for m in p.members], run_share))) for p in base.packages]
        used = [(p, k) for p, k in used if k]
        out += ["**Packages employed:**", ""]
        out += table(["Package", "Colors", "Decks", "Share of combo", "Core cards"],
                     [[p.name, "/".join(c.value for c in p.colors), str(k), pct(k, n),
                       ", ".join(cards[m.card_number].name for m in p.members if m.role.value == "core")]
                      for p, k in sorted(used, key=lambda x: -x[1])] or [["(none)", "", "", "", ""]])
        counts = Counter(c for d in members for c in d if c not in packaged)
        out += [f"**Most-played cards outside packages** (decks of {n}):", ""]
        out += table(["Card", "Decks", "Share", "Role"],
                     [[names.card(c), str(k), pct(k, n), _tag(c, base, names)] for c, k in counts.most_common(TOP_CARDS)])
    return out


def _package_section(base: PackagesFile, cards: Mapping[CardNumber, CardModel], names: _Names) -> list[str]:
    total = base.window.decks
    out = ["## 2. Package reference", "",
           f"Each package is one color. \"Decks\" counts decks that run it (at least {100 * base.params.run_share:.0f}% of its members); each card's count is decks running the package that also play the card.", ""]
    for p in base.packages:
        out += [f"### {p.name}: {p.decks_running} decks ({pct(p.decks_running, total)}), {'/'.join(c.value for c in p.colors)}", ""]
        out += table(["Card", "Role", "Decks", "Share of package's decks"],
                     [[names.card(m.card_number), m.role.value, str(m.decks), pct(m.decks, p.decks_running)] for m in p.members])
        partners = sorted((h for h in base.synergy_cards if h.package == p.id), key=lambda h: -h.share)[:5]
        if partners:
            out.append("Synergy cards: " + ", ".join(f"{cards[h.card_number].name} {h.decks} ({100 * h.share:.0f}%)" for h in partners))
            out.append("")
        if p.variants:
            out.append("Variants: " + "; ".join(
                f"{', '.join(cards[c].name for c in v.optional_members) or 'core only'} ({v.decks})" for v in p.variants[:3]))
            out.append("")
    out += ["### Packages that work together", "",
            "Two packages are synergistic when they are tied (directly, or through a bridge card tied to both) and decks run both. A bridge is a card outside both packages that is in at least half of the decks running both.", ""]
    rows = []
    for s in base.package_synergies:
        bridges = ", ".join(f"{cards[b.card_number].name} {b.decks} ({100 * b.share:.0f}%)" for b in s.bridges) or "-"
        rows.append([f"{names.package[s.package_a]} + {names.package[s.package_b]}", str(s.decks_both),
                     f"{100 * s.share_of_a:.0f}% / {100 * s.share_of_b:.0f}%", str(len(s.edges)), bridges])
    return out + table(["Pair", "Decks with both", "Share of each's decks", "Direct ties", "Bridge cards (decks)"], rows)


def _synergy_entry(h: SynergyCard, cards: Mapping[CardNumber, CardModel]) -> str:
    return f"{cards[h.card_number].name} {h.decks} ({100 * h.share:.0f}%)"


def _adjustments_section(
    base: PackagesFile,
    base_decks: Sequence[Deck],
    drift: DriftFile,
    new_decks: Sequence[Deck],
    cards: Mapping[CardNumber, CardModel],
    names: _Names,
) -> list[str]:
    total_b, total_n = len(base_decks), len(new_decks)
    run_share = base.params.run_share
    label = f"{drift.new.era} (from {drift.new.start})"
    out = ["## 3. Meta adjustments", "",
           f"How the meta moved from {base.window.era} ({base.window.events} events, {total_b} decks) to {label}: **{drift.new.events} events, {total_n} decks**. "
           + ("**Low sample**: " + f"{total_n} decks is a snapshot, so read shifts as direction, not size. " if total_n < 100 else "")
           + "Packages are the ones found in the earlier era; counts are decks. In a small window a card tied to several packages that run together "
           "(a bridge, see section 2) can show up under more than one of them, because there are too few decks without the other package to tell them apart.", ""]

    # packages
    out += ["### Packages: before and after", ""]
    running_after = {p.id: [d for d in new_decks if runs_package(d, [m.card_number for m in p.members], run_share)] for p in base.packages}
    rows = []
    for p, change in zip(base.packages, drift.packages, strict=True):
        after = len(running_after[p.id])
        delta = 100 * (after / total_n - p.decks_running / total_b) if total_n and total_b else 0.0
        notes = []
        if change.dropped:
            notes.append("core dropped: " + ", ".join(cards[c].name for c in change.dropped))
        if change.joined:
            notes.append("new cards joined: " + ", ".join(_synergy_entry(h, cards) for h in change.joined))
        if change.new_synergy_cards:
            notes.append("newly tied: " + ", ".join(_synergy_entry(h, cards) for h in change.new_synergy_cards[:4]))
        rows.append([p.name, f"{p.decks_running} ({pct(p.decks_running, total_b)})", f"{after} ({pct(after, total_n)})", pts(delta / 100), "; ".join(notes) or "-"])
    out += table(["Package", f"{base.window.era} decks", f"{drift.new.era} decks", "Change in share", "Card changes (decks in new window)"], rows)

    out += ["### Member counts for the packages that moved most", ""]
    movers = sorted(zip(base.packages, running_after.values(), strict=True),
                    key=lambda x: -abs(len(x[1]) / max(total_n, 1) - x[0].decks_running / max(total_b, 1)))[:4]
    for p, after_decks in movers:
        out += [f"**{p.name}**: {p.decks_running} decks -> {len(after_decks)}", ""]
        out += table(["Card", f"{base.window.era}: decks (share of package's)", f"{drift.new.era}: decks (share of package's)"],
                     [[names.card(m.card_number), f"{m.decks} ({pct(m.decks, p.decks_running)})",
                       f"{(k := sum(1 for d in after_decks if m.card_number in d))} ({pct(k, len(after_decks))})"] for m in p.members])

    # new cards and emerging packages
    out += ["### New cards in play", ""]
    emerging_of = {c: e.package.name for e in drift.emerging for c in e.new_cards}
    pkg_name = names.package
    out += table(["Card", "Released", "Decks", "Share of decks", "Goes with"],
                 [[names.card(n.card_number), str(n.introduced), str(n.decks), pct(n.decks, total_n),
                   pkg_name[n.package] if n.package else (f"new package: {emerging_of[n.card_number]}" if n.card_number in emerging_of else "no package so far")] for n in drift.new_cards]) if drift.new_cards else ["(none)", ""]
    out += ["### New packages", ""]
    if drift.emerging:
        for e in drift.emerging:
            cnt = Counter(c for d in new_decks for c in d)
            out += [f"**{e.package.name}** ({'/'.join(c.value for c in e.package.colors)}): {e.package.decks_running} decks ({pct(e.package.decks_running, total_n)})"
                    + (", low sample" if e.low_sample else ""), ""]
            out += table(["Card", "New?", "Decks", "Share"],
                         [[names.card(m.card_number), "yes" if m.card_number in e.new_cards else "", str(cnt[m.card_number]), pct(cnt[m.card_number], total_n)]
                          for m in e.package.members])
    else:
        out += ["No new package emerged.", ""]

    # decks shift: colors and archetypes
    out += ["### How decks shifted", "", "**Color combinations**", ""]
    cb = Counter(deck_combo(d, cards) for d in base_decks)
    cn = Counter(deck_combo(d, cards) for d in new_decks)
    keys = sorted(set(cb) | set(cn), key=lambda c: -(cb[c] + cn[c]))
    out += table(["Colors", f"{base.window.era} decks", f"{drift.new.era} decks", "Change in share"],
                 [[combo_label(c), f"{cb[c]} ({pct(cb[c], total_b)})", f"{cn[c]} ({pct(cn[c], total_n)})",
                   pts(cn[c] / total_n - cb[c] / total_b)] for c in keys])
    out += ["**Archetypes** (the packages a deck runs)", ""]
    sb = Counter(signature(d, base.packages, run_share) for d in base_decks)
    sn = Counter(signature(d, base.packages, run_share) for d in new_decks)
    keys2 = sorted(set(sb) | set(sn), key=lambda s: -max(sb[s] / total_b, sn[s] / total_n))[:12]
    out += table(["Archetype", f"{base.window.era} decks", f"{drift.new.era} decks", "Change in share"],
                 [[names.archetype(s), f"{sb[s]} ({pct(sb[s], total_b)})", f"{sn[s]} ({pct(sn[s], total_n)})",
                   pts(sn[s] / total_n - sb[s] / total_b)] for s in keys2])

    # card movers
    fb = Counter(c for d in base_decks for c in d)
    fn = Counter(c for d in new_decks for c in d)
    shift = {c: fn[c] / total_n - fb[c] / total_b for c in set(fb) | set(fn) if max(fb[c], fn[c]) >= MIN_MOVER_DECKS}
    up = sorted(shift, key=lambda c: -shift[c])[:MOVERS]
    down = sorted(shift, key=lambda c: shift[c])[:MOVERS]
    out += ["### Card movers", "", f"Cards in at least {MIN_MOVER_DECKS} decks in either window, by change in the share of decks that play them.", ""]
    for title, group in (("Rising", up), ("Falling", down)):
        out += [f"**{title}**", ""]
        out += table(["Card", f"{base.window.era} decks", f"{drift.new.era} decks", "Change", "Role in " + str(base.window.era)],
                     [[names.card(c), f"{fb[c]} ({pct(fb[c], total_b)})", f"{fn[c]} ({pct(fn[c], total_n)})", pts(shift[c]),
                       _tag(c, base, names) if c in fb else "new card"] for c in group])
    return out


def render_report(
    base: PackagesFile,
    base_decks: Sequence[Deck],
    drift: DriftFile,
    new_decks: Sequence[Deck],
    cards: Mapping[CardNumber, CardModel],
    generated_at: datetime,
) -> str:
    names = _Names(cards, base.packages)
    w = base.window
    head = [f"# {w.era} meta report", "",
            f"Generated {generated_at:%Y-%m-%d %H:%M} by `python -m tools.gundam_packages.cli report`. "
            f"Window {w.start} to {w.end or 'today'}: {w.events} events, {w.decks} counted decks (main decks; major and local events together, de-duplicated). "
            f"{w.decks_not_counted} decks could not be counted. All numbers are deck counts.", "",
            "Vocabulary: a **package** is a one-color group of cards that go together; an **archetype** is the set of packages a deck runs; "
            "**synergy** cards are tied to a package and played in its decks; **bridge** cards sit between two packages that run together; "
            "**free floating** cards are good on their own.", ""]
    return "\n".join(head + _meta_section(base, base_decks, cards, names) + _package_section(base, cards, names)
                     + _adjustments_section(base, base_decks, drift, new_decks, cards, names)) + "\n"
