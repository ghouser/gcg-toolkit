"""Packages and archetypes: how decks are built (see tools/gundam_packages/design.md).

    .venv/bin/python -m tools.gundam_packages.cli build                     # GD05 packages + archetypes (default era gd05)
    .venv/bin/python -m tools.gundam_packages.cli build --source online     # the same analysis on the weighted online example decks
    .venv/bin/python -m tools.gundam_packages.cli compare                   # tournament vs online: each package's rate in both
    (every lookup below also takes --source online)
    .venv/bin/python -m tools.gundam_packages.cli packages                  # packages with core/optional members and variants
    .venv/bin/python -m tools.gundam_packages.cli archetypes                # package combinations with typical picks
    .venv/bin/python -m tools.gundam_packages.cli synergy              # cards with a structural tie to a package
    .venv/bin/python -m tools.gundam_packages.cli package-synergy           # packages that work together, with bridge cards
    .venv/bin/python -m tools.gundam_packages.cli free                      # free-floating cards (good on their own)
    .venv/bin/python -m tools.gundam_packages.cli squads                 # cards that do the same job (every pair are peers)
    .venv/bin/python -m tools.gundam_packages.cli card GD03-056             # one card: its package, archetypes, partners, appearance rates
    .venv/bin/python -m tools.gundam_packages.cli package "Mikazuki Barbatos"   # one package: appearance rate of every card played with it
    .venv/bin/python -m tools.gundam_packages.cli drift --from gd05 --to gd05_5   # how the new era changes the packages
    .venv/bin/python -m tools.gundam_packages.cli report --from gd05 --to gd05_5  # markdown meta report by color combination + adjustments
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from shared.basetypes import CardNumber
from shared.samejob.pilots import is_pilot
from tools.gundam_cards.models import CardModel, CardsFile, UnitCard, color_of, names_of
from tools.gundam_cards.store import OUT_DIR as CARDS_DIR
from tools.gundam_cards.store import load_cards_with_prices, load_sets, release_dates
from tools.gundam_meta.dedupe import combined_events
from tools.gundam_meta.eras import EraError, find_era, load_era_defs, resolve_eras
from tools.gundam_meta.models import Era, EraId, Tier
from tools.gundam_meta.store import load_decks_snapshot, load_events
from tools.gundam_packages.build import (
    ALL_TIERS,
    ONLINE_PARAMS,
    build_from_decks,
    build_packages,
    card_colors,
    copy_decks,
    deck_sets,
    make_window,
    online_copy_decks,
    online_window,
    window_events,
)
from tools.gundam_packages.drift import compute_drift, introduced_dates
from tools.gundam_packages.discover import Deck
from tools.gundam_packages.compare import match_packages
from tools.gundam_packages.models import DataSource, DriftFile, OtherRole, PackageRates, PackagesFile, RatesFile
from tools.gundam_packages.naming import PackageNamer
from tools.gundam_packages.rates import compute_rates
from tools.gundam_packages.report import render_report
from tools.gundam_packages.store import OUT_DIR, load_name_overrides, load_packages, load_rates, write_drift, write_packages, write_rates
from tools.gundam_packages.synergy import build_graph


def _cards() -> dict[CardNumber, CardModel]:
    path = CARDS_DIR / "cards.json"
    if not path.is_file():
        raise SystemExit(f"{path} not found; run `python -m tools.gundam_cards.cli sync` first")
    return {c.number: c for c in CardsFile.model_validate_json(path.read_text(encoding="utf-8")).data}


def _eras() -> dict[EraId, Era]:
    sets = load_sets()
    if not sets:
        raise SystemExit("no sets.json; run `python -m tools.gundam_cards.cli sync --only sets` first")
    return {e.id: e for e in resolve_eras(load_era_defs(), release_dates(sets))}


def _tiers(value: str) -> tuple[Tier, ...]:
    return ALL_TIERS if value == "all" else (Tier(value),)


def _source(args: argparse.Namespace) -> DataSource:
    return DataSource(getattr(args, "source", DataSource.TOURNAMENT.value))


def _loaded(args: argparse.Namespace) -> PackagesFile:
    source = _source(args)
    file = load_packages(source=source)
    if file is None:
        raise SystemExit(f"no {source.value} packages yet; run `build{' --source online' if source is DataSource.ONLINE else ''}` first")
    return file


def _label(file: PackagesFile | RatesFile) -> str:
    """What the decks are: the era for tournaments, the example-decks window for online."""
    if file.source is DataSource.ONLINE:
        return f"online example decks since {file.window.start}, per {file.window.decks} decks"
    return f"era {file.window.era}"


def _with_colors(name: str, colors: str) -> str:
    """The name with its colors, unless the name already says them (`Haman Qubeley (green)`)."""
    return name if "(" in name else f"{name} ({colors})"


def _pct(x: float) -> str:
    return f"{100 * x:3.0f}%"


def _build_online(args: argparse.Namespace) -> int:
    snapshot = load_decks_snapshot()
    if snapshot is None or not any(a.sides_analyzed is not None for a in snapshot.archetypes):
        print("no weighted example decks stored (shared/data/gundam_meta/example_decks/ is missing or has no weights)", file=sys.stderr)
        return 2
    cards = _cards()
    decks, lists_used = online_copy_decks(snapshot, cards)
    now = datetime.now(UTC)
    file, _ = build_from_decks([frozenset(d) for d in decks], online_window(snapshot, len(decks)), cards, ONLINE_PARAMS,
                               overrides=load_name_overrides(), generated_at=now, source=DataSource.ONLINE)
    path = write_packages(file)
    rates_path = write_rates(compute_rates(file, decks, now))
    print(f"online (example decks, {snapshot.fetched_at:%Y-%m-%d}, {snapshot.window_days} days): {lists_used} weighted lists as {len(decks)} online decks "
          f"(each deck is 0.01% of the field) -> {path}, {rates_path}")
    print(f"{len(file.packages)} packages, {len(file.package_synergies)} synergistic package pairs, {len(file.synergy_cards)} synergy ties, "
          f"{len(file.free_floating)} free-floating cards, {len(file.archetypes)} archetypes ({file.rare_cards} cards too rare to classify)")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    if _source(args) is DataSource.ONLINE:
        return _build_online(args)
    cards, eras = _cards(), _eras()
    try:
        era = eras[EraId(args.era)]
    except KeyError:
        print(f"unknown era {args.era!r} (known: {', '.join(map(str, eras))})", file=sys.stderr)
        return 2
    events = combined_events(load_events())
    file, _ = build_packages(events, cards, era, _tiers(args.tier), overrides=load_name_overrides(), generated_at=datetime.now(UTC))
    path = write_packages(file)
    listed, _ = copy_decks(window_events(events, era, _tiers(args.tier)), cards)
    rates_path = write_rates(compute_rates(file, listed, datetime.now(UTC)))
    w = file.window
    print(f"{era.definition.label} ({w.start} to {w.end or 'today'}): {w.events} events, {w.decks} decks -> {path}, {rates_path}")
    print(f"{len(file.packages)} packages, {len(file.package_synergies)} synergistic package pairs, {len(file.synergy_cards)} synergy ties, {len(file.free_floating)} free-floating cards, "
          f"{len(file.archetypes)} archetypes ({file.rare_cards} cards too rare to classify)")
    return 0


def cmd_packages(args: argparse.Namespace) -> int:
    file, cards = _loaded(args), _cards()
    print(f"== packages, {_label(file)} ({file.window.decks} decks) ==")
    for p in file.packages[: args.limit]:
        colors = "/".join(c.value for c in p.colors)
        ties = Counter(e.kind.relation.value for e in p.edges)
        print(f"\n{p.name}  [{p.id}]  {p.decks_running} decks ({_pct(p.deck_share)})  {colors}")
        print("    ties: " + (", ".join(f"{n} {r.replace('_', ' ')}" for r, n in sorted(ties.items())) or "none"))
        for m in p.members:
            print(f"    {m.role.value:8} {m.card_number}  {cards[m.card_number].name:34} {_pct(m.share)}")
        for v in p.variants[:3]:
            names = ", ".join(cards[c].name for c in v.optional_members) or "core only"
            print(f"    variant: {names}  ({v.decks} decks)")
    return 0


def cmd_archetypes(args: argparse.Namespace) -> int:
    file, cards = _loaded(args), _cards()
    print(f"== archetypes (package combinations), {_label(file)}, {file.window.decks} decks ==")
    for a in file.archetypes[: args.limit]:
        print(f"\n{a.decks:3} decks ({_pct(a.share)})  {a.name}")
        if a.synergy_cards:
            print("      synergy: " + ", ".join(f"{cards[r.card_number].name} {_pct(r.share)}" for r in a.synergy_cards[:6]))
        if a.free_floating:
            print("      free floating: " + ", ".join(f"{cards[r.card_number].name} {_pct(r.share)}" for r in a.free_floating[:6]))
    return 0


def cmd_synergy_cards(args: argparse.Namespace) -> int:
    file, cards = _loaded(args), _cards()
    names = {p.id: p.name for p in file.packages}
    shown = sorted((h for h in file.synergy_cards if h.share >= args.min_share), key=lambda h: (-h.share, names[h.package], h.card_number))
    print(f"== synergy cards (a tie to the package and in its decks; the score is the share of its decks), {_label(file)}: {len(shown)} ==")
    for h in shown[: args.limit]:
        ties = ", ".join(sorted({f"{e.kind.value}: {e.detail}" for e in h.edges}))
        print(f"{names[h.package]:26} + {cards[h.card_number].name:28} in {_pct(h.share)} of its decks  ({ties})")
    return 0


def cmd_package_synergy(args: argparse.Namespace) -> int:
    file, cards = _loaded(args), _cards()
    names = {p.id: p.name for p in file.packages}
    colors = {p.id: "/".join(c.value for c in p.colors) for p in file.packages}
    print(f"== synergistic packages (tied, and run together), {_label(file)} ==")
    for s in file.package_synergies[: args.limit]:
        print(f"\n{_with_colors(names[s.package_a], colors[s.package_a])} + {_with_colors(names[s.package_b], colors[s.package_b])}: {s.decks_both} decks "
              f"({_pct(s.share_of_a)} of the first's, {_pct(s.share_of_b)} of the second's)")
        if s.edges:
            print("      direct ties: " + ", ".join(sorted({f"{e.kind.value}: {e.detail}" for e in s.edges})))
        for b in s.bridges:
            ties = ", ".join(sorted({f"{e.kind.value}: {e.detail}" for e in (*b.edges_a, *b.edges_b)}))
            print(f"      bridge: {cards[b.card_number].name} in {_pct(b.share)} of them ({ties})")
    return 0


def cmd_free(args: argparse.Namespace) -> int:
    file, cards = _loaded(args), _cards()
    names = {p.id: p.name for p in file.packages}
    print(f"== free-floating cards, {_label(file)} ==")
    for f in file.free_floating[: args.limit]:
        goes = ", ".join(f"{names[a.package]} {_pct(a.share)}" for a in f.affinities)
        print(f"{f.card_number}  {cards[f.card_number].name:30} {_pct(f.deck_share)} of decks" + (f"  (often with: {goes})" if goes else ""))
    return 0


def cmd_squads(args: argparse.Namespace) -> int:
    file, cards = _loaded(args), _cards()
    print(f"== squads: cards that do the same job, every pair are peers; a card can be in several squads; {_label(file)} (players run some of each) ==")
    for g in file.squads[: args.limit]:
        print(f"\n{_pct(g.share_with_any)} of decks run at least one")
        for c in g.cards:
            print(f"    {c.card_number}  {cards[c.card_number].name:32} {_color_of(cards[c.card_number]):7} in {c.decks} decks")
    return 0


def _color_of(card: CardModel) -> str:
    color = color_of(card)
    return color.value if color is not None else ""


def cmd_pairs(args: argparse.Namespace) -> int:
    """Pairing: the pilots that satisfy a Unit's Link, or the Units a pilot Links, ranked by how often decks run them together."""
    from tools.gundam_packages.pairing import pilots_for, rates_with, units_for

    priced = {p.card.number: p for p in load_cards_with_prices()}
    cards = {n: p.card for n, p in priced.items()}
    number = CardNumber(args.card)
    card = cards.get(number)
    if card is None:
        print(f"no such card: {number}", file=sys.stderr)
        return 1
    if isinstance(card, UnitCard):
        if card.link is None:
            print(f"{number} {card.name} has no Link: it needs no pilot")
            return 0
        found: list[CardModel] = pilots_for(card, cards.values())
        print(f"== pilots that make {number} {card.name} Link ({', '.join(str(r) for r in card.link.any_of)}) ==")
    elif is_pilot(card):
        found = list(units_for(card, cards.values()))
        print(f"== Units that {number} {card.name} (answers to {', '.join(names_of(card))}) Links ==")
    else:
        print(f"{number} {card.name} is neither a Unit nor a pilot", file=sys.stderr)
        return 1
    rates = load_rates(source=_source(args))
    seen = rates_with(rates, number) if rates is not None else {}

    def price(n: CardNumber) -> float:
        quote = priced[n].latest_tcg_price
        return quote.price_cents / 100 if quote is not None else float("inf")

    print(f"   rate = how often decks that run {number} also run it ({_label(rates) if rates else 'no rates built'}); price = TCGPlayer market\n")
    for c in sorted(found, key=lambda c: (-seen.get(c.number, 0.0), price(c.number), c.number))[: args.limit]:
        cost = price(c.number)
        shown = _rate(seen[c.number]) if c.number in seen else "  not seen with it"
        print(f"   {c.number}  {c.name:34} {_color_of(c):7} {c.kind.value:8} {shown:>8}  {'$' + format(cost, '.2f') if cost != float('inf') else 'unpriced'}")
    if len(found) > args.limit:
        print(f"   ... and {len(found) - args.limit} more (--limit)")
    if not found:
        print("   none")
    return 0


LOW_DECKS = 6


def _rate(x: float) -> str:
    return f"{100 * x:5.1f}%"


def _loaded_rates(args: argparse.Namespace) -> RatesFile:
    rates = load_rates(source=_source(args))
    if rates is None:
        raise SystemExit(f"no {_source(args).value} rates yet; run `build{' --source online' if _source(args) is DataSource.ONLINE else ''}` first")
    return rates


def _find_package(rates: RatesFile, query: str) -> PackageRates | None:
    q = query.lower()
    exact = [p for p in rates.packages if q in (str(p.package).lower(), p.name.lower())]
    found = exact or [p for p in rates.packages if q in p.name.lower()]
    if len(found) == 1:
        return found[0]
    known = ", ".join(f"{p.name} [{p.package}]" for p in (found or rates.packages))
    print(f"{'ambiguous' if found else 'no such'} package {query!r}; {'matches' if found else 'known'}: {known}", file=sys.stderr)
    return None


def cmd_package(args: argparse.Namespace) -> int:
    rates, cards = _loaded_rates(args), _cards()
    x = _find_package(rates, args.package)
    if x is None:
        return 1
    names = {p.package: p.name for p in rates.packages}

    def nm(n: CardNumber) -> str:
        return f"{cards[n].name} ({n})"

    flag = "  (FEW DECKS)" if x.package_decks < LOW_DECKS else ""
    print(f"{x.name}  [{x.package}]: played in {x.package_decks} of {rates.total_decks} decks = {_rate(x.rate)}{flag}")
    print(f"  played with no other package: {x.alone_decks} of {x.package_decks} decks = {_rate(x.alone_rate)}")
    print(f"\nits own cards (copies of {4 * x.package_decks} possible = 4 x {x.package_decks} decks):")
    for m in x.members:
        print(f"  {m.role.value:8} {nm(m.card_number):44} {m.copies:4}/{m.possible:<4} {_rate(m.rate)}")
    print("\nplayed with (rates add up to more than 100% when decks run 3+ packages; each partner is its own view):")
    for w in x.partners:
        few = "  (few decks)" if w.pair_decks < LOW_DECKS else ""
        print(f"\n  with {names[w.package]}: {w.pair_decks} of {x.package_decks} decks = {_rate(w.combined_rate)} of {x.name}'s decks "
              f"(joint {_rate(w.joint_rate)} of all){'  [synergistic]' if w.synergistic else ''}{few}")
        for c in w.cards:
            print(f"      {nm(c.card_number):44} {_rate(c.rate_in_combo)} in those decks -> {_rate(c.rate_from_x)} from {x.name}")
        for b in w.bridges:
            print(f"      bridge: {nm(b.card_number):36} {_rate(b.rate_in_combo)} in those decks -> {_rate(b.rate_from_x)} from {x.name}, to {names[w.package]}")
    print(f"\nother cards in its decks (copies of {4 * x.package_decks} possible), top {args.limit}:")
    for o in x.others[: args.limit]:
        stray = f", a {names[o.belongs_to]} card" if o.belongs_to else ""
        print(f"  {nm(o.card_number):44} {o.copies:4}/{o.possible:<4} {_rate(o.rate)}  ({o.role.value.replace('_', ' ')}{stray})")
    return 0


HOMES_SHOWN = 2  # for a card outside every package: the packages whose decks it is played in most, shown in full


def _named(cards: Mapping[CardNumber, CardModel], number: CardNumber) -> str:
    return f"{cards[number].name} ({number})"


def _print_package_view(x: PackageRates, number: CardNumber, rates: RatesFile, cards: Mapping[CardNumber, CardModel], limit: int) -> None:
    """Everything played with a package, from its perspective: its own cards, each linked package's cards and bridges, then stand-alone cards."""
    names = {p.package: p.name for p in rates.packages}
    print(f"\n     --- seen from {x.name} ({_rate(x.rate)} of decks; {x.package_decks} of {rates.total_decks}) ---")
    others = [m for m in x.members if m.card_number != number]
    if others:
        print(f"     {x.name}'s own cards:")
        for m in others:
            print(f"       {_named(cards, m.card_number):46} {_rate(m.rate)}  ({m.role.value})")
    linked = [w for w in x.partners if w.combined_rate >= 0.05][:6]
    if linked:
        print(f"     linked packages (played together with {x.name}):")
    for w in linked:
        print(f"       {names[w.package]}: {w.pair_decks} of {x.package_decks} decks = {_rate(w.combined_rate)}{'  [synergistic]' if w.synergistic else ''}")
        for c in sorted(w.cards, key=lambda c: -c.rate_from_x)[:limit]:
            print(f"         {_named(cards, c.card_number):44} {_rate(c.rate_from_x)} from {x.name}")
        for b in w.bridges:
            print(f"         bridge: {_named(cards, b.card_number):36} {_rate(b.rate_from_x)} from {x.name}")
    for role, title in ((OtherRole.SYNERGY, "stand-alone cards tied to the package (synergy)"), (OtherRole.FREE_FLOATING, "free-floating cards often played with it"), (OtherRole.OTHER, "other cards in its decks")):
        group = [o for o in x.others if o.role is role and o.card_number != number][:limit]
        if group:
            print(f"     {title}:")
            for o in group:
                print(f"       {_named(cards, o.card_number):46} {_rate(o.rate)}")


def _print_card_rates(number: CardNumber, rates: RatesFile, cards: Mapping[CardNumber, CardModel], limit: int) -> None:
    names = {p.package: p.name for p in rates.packages}
    by_package = {p.package: p for p in rates.packages}
    if number not in rates.card_index:
        print(f"  RATES: not played in {_label(rates)}")
        return
    owner = rates.card_index[number]
    if owner is not None and owner in by_package:
        x = by_package[owner]
        mine = next(m for m in x.members if m.card_number == number)
        print(f"  RATES: in package {x.name} ({_rate(x.rate)} of decks: {x.package_decks} of {rates.total_decks}); this card "
              f"{mine.copies} of {mine.possible} possible copies = {_rate(mine.rate)} ({mine.role.value})")
        _print_package_view(x, number, rates, cards, limit)
        return
    played = sorted(((o.rate, x, o) for x in rates.packages for o in x.others if o.card_number == number), key=lambda r: (-r[0], r[1].package))
    bridges = [(x, w, b) for x in rates.packages for w in x.partners for b in w.bridges if b.card_number == number]
    print("  RATES: not in a package.")
    for x, w, b in bridges:
        print(f"     BRIDGE {x.name} + {names[w.package]}: {_rate(b.rate_in_combo)} of the {w.pair_decks} decks that play both -> {_rate(b.rate_from_x)} from {x.name}'s view")
    print("     where it is played (copies of the possible, per package):")
    for rate, x, o in played[:8]:
        print(f"       {x.name}'s decks: {o.copies} of {o.possible} = {_rate(rate)} ({o.role.value.replace('_', ' ')})")
    for _, x, _ in played[:HOMES_SHOWN]:
        _print_package_view(x, number, rates, cards, limit)


def cmd_compare(args: argparse.Namespace) -> int:
    cards = _cards()
    tournament, online = load_packages(source=DataSource.TOURNAMENT), load_packages(source=DataSource.ONLINE)
    t_rates, o_rates = load_rates(source=DataSource.TOURNAMENT), load_rates(source=DataSource.ONLINE)
    if tournament is None or online is None or t_rates is None or o_rates is None:
        print("need both: run `build` and `build --source online` first", file=sys.stderr)
        return 2
    members = {s: {p.id: frozenset(m.card_number for m in p.members) for p in f.packages} for s, f in ((DataSource.TOURNAMENT, tournament), (DataSource.ONLINE, online))}
    pairs, only_t, only_o = match_packages(members[DataSource.TOURNAMENT], members[DataSource.ONLINE])
    t_by = {p.package: p for p in t_rates.packages}
    o_by = {p.package: p for p in o_rates.packages}
    print(f"== the same package in tournament decks ({_label(tournament)}) and in {_label(online)} ==")
    print(f"   rate = how often the package is played; matched by the cards they share (at least half)\n")
    print(f"{'package (tournament name / online name)':50} {'tournament':>10} {'online':>8} {'change':>8}  cards shared")
    for tid, oid, score in sorted(pairs, key=lambda x: -o_by[x[1]].rate):
        tp, op = t_by[tid], o_by[oid]
        names = tp.name if tp.name == op.name else f"{tp.name} / {op.name}"
        print(f"{names:50} {_rate(tp.rate):>10} {_rate(op.rate):>8} {100 * (op.rate - tp.rate):>+7.1f}  {100 * score:.0f}% same cards")
    for label, ids, by in (("online only", only_o, o_by), ("tournament only", only_t, t_by)):
        shown = sorted((by[i] for i in ids if i in by), key=lambda p: -p.rate)[: args.limit]
        print(f"\n{label} ({len(ids)} packages):")
        for p in shown:
            print(f"  {p.name:30} {_rate(p.rate)}  {', '.join(cards[m.card_number].name for m in p.members)}")
    return 0


def cmd_card(args: argparse.Namespace) -> int:
    file, cards = _loaded(args), _cards()
    number = CardNumber(args.card)
    if number not in cards:
        print(f"no such card: {number}", file=sys.stderr)
        return 1
    names = {p.id: p.name for p in file.packages}
    card = cards[number]
    print(f"{number}  {card.name}")
    rates = load_rates(source=_source(args))
    if rates is not None:
        _print_card_rates(number, rates, cards, args.limit)
    for squad in (g for g in file.squads if any(c.card_number == number for c in g.cards)):
        others = ", ".join(_named(cards, c.card_number) for c in squad.cards if c.card_number != number)
        print(f"  in a squad (does the same job as): {others}  ({_pct(squad.share_with_any)} of decks run at least one)")
    for p in file.packages:
        member = next((m for m in p.members if m.card_number == number), None)
        if member is not None:
            print(f"  PACKAGE: {p.name} ({member.role.value}, in {_pct(member.share)} of its decks)")
            print(f"     members: {', '.join(_named(cards, m.card_number) for m in p.members)}")
            arch = [a for a in file.archetypes if p.id in a.packages]
            print(f"     archetypes with it: " + (", ".join(f"{a.name} ({a.decks})" for a in arch[:5]) or "none"))
            return 0
    bridges = [(s, b) for s in file.package_synergies for b in s.bridges if b.card_number == number]
    for s, b in bridges:
        print(f"  BRIDGE between {names[s.package_a]} and {names[s.package_b]}: in {_pct(b.share)} of the decks that run both")
    ties = [h for h in file.synergy_cards if h.card_number == number]
    if ties:
        for h in ties:
            kinds = ", ".join(sorted({f"{e.kind.value}: {e.detail}" for e in h.edges}))
            print(f"  SYNERGY with {names[h.package]}: in {_pct(h.share)} of its decks ({kinds})")
        return 0
    free = next((f for f in file.free_floating if f.card_number == number), None)
    if free is not None:
        print(f"  FREE FLOATING: in {_pct(free.deck_share)} of decks")
        for a in free.affinities:
            print(f"     often with {names[a.package]} ({_pct(a.share)} of its decks); no structural synergy")
        return 0
    print("  not classified: too rare in this window")
    return 0


def _drift_for(base: PackagesFile, new_era: Era, cards: dict[CardNumber, CardModel]) -> tuple[DriftFile, list[Deck]]:
    release = release_dates(load_sets())
    events = window_events(combined_events(load_events()), new_era, ALL_TIERS)
    decks, not_counted = deck_sets(events, cards)
    graph = build_graph(list(cards.values()))
    drift = compute_drift(base, decks, make_window(new_era, ALL_TIERS, events, len(decks), not_counted), graph,
                          introduced_dates(cards, release), card_colors(cards), PackageNamer(cards, load_name_overrides()), datetime.now(UTC))
    return drift, decks


def _base_and_new(args: argparse.Namespace, cards: dict[CardNumber, CardModel]) -> tuple[PackagesFile, Era] | int:
    eras = _eras()
    base = load_packages()
    if base is None or str(base.window.era) != args.base:
        print(f"run `build --era {args.base}` first (packages.json is for era {base.window.era if base else 'none'})", file=sys.stderr)
        return 2
    try:
        return base, eras[EraId(args.new)]
    except KeyError:
        print(f"unknown era {args.new!r}", file=sys.stderr)
        return 2


def cmd_report(args: argparse.Namespace) -> int:
    cards = _cards()
    picked = _base_and_new(args, cards)
    if isinstance(picked, int):
        return picked
    base, new_era = picked
    drift, new_decks = _drift_for(base, new_era, cards)
    base_era = _eras()[EraId(args.base)]
    base_decks, _ = deck_sets(window_events(combined_events(load_events()), base_era, ALL_TIERS), cards)
    text = render_report(base, base_decks, drift, new_decks, cards, datetime.now().astimezone())
    out = Path(args.out) if args.out else OUT_DIR / f"{args.base}_meta_report.md"
    out.write_text(text, encoding="utf-8")
    print(f"{len(base_decks)} {args.base} decks, {len(new_decks)} {args.new} decks -> {out}")
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    cards = _cards()
    picked = _base_and_new(args, cards)
    if isinstance(picked, int):
        return picked
    base, new_era = picked
    drift, _ = _drift_for(base, new_era, cards)
    path = write_drift(drift)

    def nm(number: CardNumber) -> str:
        return cards[number].name

    print(f"== drift: {base.window.era} -> {new_era.definition.label}: {drift.new.events} events, {drift.new.decks} decks"
          f"{'  (LOW SAMPLE)' if drift.new.decks < 100 else ''} ==")
    for p in drift.packages:
        extra = ""
        if p.dropped:
            extra += " | dropped: " + ", ".join(nm(c) for c in p.dropped)
        if p.joined:
            extra += " | new cards joining: " + ", ".join(f"{nm(h.card_number)} {_pct(h.share)}" for h in p.joined)
        if p.new_synergy_cards:
            extra += " | newly tied: " + ", ".join(f"{nm(h.card_number)} {_pct(h.share)}" for h in p.new_synergy_cards)
        print(f"  {p.name:26} {_pct(p.share_before)} -> {_pct(p.share_after)}{extra}")
    print("\n  new cards in play:")
    names = {p.id: p.name for p in base.packages}
    for n in drift.new_cards[: args.limit]:
        print(f"    {n.card_number}  {nm(n.card_number):28} in {n.decks} decks ({_pct(n.deck_share)})  "
              + (f"goes with {names[n.package]}" if n.package else "free floating so far"))
    for e in drift.emerging:
        print(f"\n  EMERGING package{' (low sample)' if e.low_sample else ''}: {e.package.name}: "
              f"{', '.join(nm(m.card_number) for m in e.package.members)}  (new: {', '.join(nm(c) for c in e.new_cards)})")
    print(f"\n-> {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="discover packages and archetypes for an era and save them")
    build.add_argument("--era", default="gd05", help="era id (default gd05)")
    build.add_argument("--tier", default="all", choices=["all", "major", "local"])
    build.add_argument("--source", choices=[s.value for s in DataSource], default="tournament",
                       help="tournament: an era's events (default); online: the weighted example decks (--era/--tier are ignored)")
    build.set_defaults(func=cmd_build)
    for name, func, helptext in (
        ("packages", cmd_packages, "list packages"),
        ("archetypes", cmd_archetypes, "list package combinations"),
        ("synergy", cmd_synergy_cards, "cards with a tie to a package and a score for how often they are in its decks"),
        ("package-synergy", cmd_package_synergy, "packages that work together, with bridge cards"),
        ("free", cmd_free, "free-floating cards"),
        ("squads", cmd_squads, "cards that do basically the same thing"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--limit", type=int, default=25)
        if name == "synergy":
            sp.add_argument("--min-share", type=float, default=0.0, help="only cards in at least this share of the package's decks (default 0)")
        sp.add_argument("--source", choices=[s.value for s in DataSource], default="tournament", help="which decks (default tournament)")
        sp.set_defaults(func=func)
    package = sub.add_parser("package", help="one package: appearance rate of every card played with it")
    package.add_argument("package", help="package name (or part of it) or id, e.g. 'Mikazuki Barbatos' or pkg:GD02-054")
    package.add_argument("--limit", type=int, default=20, help="how many other cards to list")
    package.add_argument("--source", choices=[s.value for s in DataSource], default="tournament", help="which decks (default tournament)")
    package.set_defaults(func=cmd_package)
    compare = sub.add_parser("compare", help="each package's rate in tournament decks and online decks, side by side")
    compare.add_argument("--limit", type=int, default=12, help="how many unmatched packages to list on each side")
    compare.set_defaults(func=cmd_compare)
    card = sub.add_parser("card", help="where one card fits: package, archetypes, or free floating")
    card.add_argument("card", help="card number, e.g. GD03-056")
    card.add_argument("--source", choices=[s.value for s in DataSource], default="tournament", help="which decks (default tournament)")
    card.add_argument("--limit", type=int, default=10, help="cards shown per group (default 10)")
    card.set_defaults(func=cmd_card)
    pairs = sub.add_parser("pairs", help="pairing: the pilots that make a Unit Link, or the Units a pilot Links, with how often decks run them")
    pairs.add_argument("card", help="a Unit or pilot card number, e.g. GD01-044")
    pairs.add_argument("--source", choices=[s.value for s in DataSource], default="tournament", help="which decks (default tournament)")
    pairs.add_argument("--limit", type=int, default=15)
    pairs.set_defaults(func=cmd_pairs)
    drift = sub.add_parser("drift", help="how a later era changes the packages (needs `build` for the base era first)")
    drift.add_argument("--from", dest="base", default="gd05")
    drift.add_argument("--to", dest="new", default="gd05_5")
    drift.add_argument("--limit", type=int, default=15)
    drift.set_defaults(func=cmd_drift)
    report = sub.add_parser("report", help="write a markdown meta report: decks by color combination and packages, then adjustments in a later era")
    report.add_argument("--from", dest="base", default="gd05")
    report.add_argument("--to", dest="new", default="gd05_5")
    report.add_argument("--out", help="output path (default shared/data/gundam_packages/<from>_meta_report.md)")
    report.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
