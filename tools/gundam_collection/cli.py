"""Collection tools (see tools/gundam_collection/design.md).

    .venv/bin/python -m tools.gundam_collection.cli check                     # validate my_tcg_collection: bad lines, unknown cards, duplicates
    .venv/bin/python -m tools.gundam_collection.cli check --file other.txt    # check another file
    .venv/bin/python -m tools.gundam_collection.cli template ST05 ST06        # the unique cards in a product, as "CARD ?" lines to fill in
    .venv/bin/python -m tools.gundam_collection.cli import                    # my_tcg_collection -> collection.json (refuses if the file has errors)
    .venv/bin/python -m tools.gundam_collection.cli coverage [--source both]  # how complete each package is, home/adjacent/new, cost to complete
    .venv/bin/python -m tools.gundam_collection.cli card GD01-026             # one card: facts, price, what I own, associations, coverage
    .venv/bin/python -m tools.gundam_collection.cli value [--bands 0.5,1,5,10]   # what my collection is worth: cards by price band, with totals
    .venv/bin/python -m tools.gundam_collection.cli decks                     # decks I support, decks I am close to (a deck needs its core and staples)
    .venv/bin/python -m tools.gundam_collection.cli deck "Barbatos Tekkadan"  # one deck: what is missing, and the picks to get (never a 50-card list)

The collection file is hand-typed, one card per line: `GD02-041 1` (card number, quantity; either order, `#` starts a comment).
`check` reads only local files (the card catalog and your list), never the network. It exits 1 when the file has errors.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, CardsFile, PricedCard, color_of, cost_of, level_of
from tools.gundam_cards.legality import Rules
from tools.gundam_cards.store import OUT_DIR as CARDS_DIR
from tools.gundam_cards.store import load_restrictions
from tools.gundam_cards.store import load_cards_with_prices
from tools.gundam_collection.alternatives import candidates, owned_alternatives
from tools.gundam_collection.bands import BANDS, THRESHOLDS, Band, NextBand
from tools.gundam_collection.check import build_collection, catalog_info, check_lines, set_template
from tools.gundam_collection.decks import (
    anchor_of,
    LAYERS,
    Deck,
    DeckSlot,
    MIN_PLAY_RATE,
    PREMIUM_CENTS,
    DeckCoverage,
    Layer,
    build_decks,
    find_decks,
    is_played,
    label_decks,
    coverage,
    needed_by,
    overview,
    package_stages,
    picks,
)
from tools.gundam_collection.archetypes import assign_archetypes, group_archetypes
from tools.gundam_collection.buy import BuyPlan, Line, Step, archetype_names, decks_with_package, mass_entry, plan_buy
from tools.gundam_collection.styles import LETTERS, Plan, Style, style_of
from tools.gundam_collection.suggest import KINDS, Pick, Prefer, Suggestion, build_suggestion, pairs_for
from tools.gundam_collection.link import (
    HOME_MIN_OWNED,
    PackageCoverage,
    Slot,
    associated_cards,
    classify,
    package_coverage,
)
from tools.gundam_collection.models import CheckReport, Severity, Stage
from tools.gundam_collection.store import COLLECTION_PATH, OUT_DIR, REPO_ROOT, load_collection, load_deck_names, owned_copies, save_deck_names, write_collection
from tools.gundam_collection.value import DEFAULT_THRESHOLDS, SELL_MIN_CENTS, ValueReport, analyze
from tools.gundam_packages.models import DataSource, PackageId, PackageRates, PackagesFile, RatesFile, Squad, typical_copies
from tools.gundam_packages.store import load_packages, load_rates


def _cards() -> list[CardModel]:
    path = CARDS_DIR / "cards.json"
    if not path.is_file():
        raise SystemExit(f"{path} not found; run `python -m tools.gundam_cards.cli sync` first")
    return list(CardsFile.model_validate_json(path.read_text(encoding="utf-8")).data)


def _print_report(report: CheckReport, quiet: bool) -> None:
    print(f"{report.file}: {report.lines_read} lines read, {report.distinct_cards} distinct cards, {report.total_copies} copies counted")
    if report.by_kind:
        print("  " + ", ".join(f"{k.kind.value.replace('_', ' ')} {k.cards} cards / {k.copies} copies" for k in report.by_kind))
    shown = [i for i in report.issues if not (quiet and i.severity is Severity.INFO)]
    for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        group = [i for i in shown if i.severity is severity]
        if not group:
            continue
        print(f"\n{severity.value.upper()} ({len(group)})")
        for i in group:
            print(f"  line {i.line}: {i.message}" if i.line else f"  {i.message}")
    verdict = "OK" if report.ok else f"{len(report.errors)} error(s) to fix"
    warnings = sum(1 for i in report.issues if i.severity is Severity.WARNING)
    print(f"\n{verdict}" + (f", {warnings} warning(s) to look at" if warnings else ""))


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    cards = _cards()
    report = check_lines(path.read_text(encoding="utf-8").splitlines(), catalog_info(cards), file=_portable(path))
    _print_report(report, args.quiet)
    return 0 if report.ok else 1


def cmd_template(args: argparse.Namespace) -> int:
    cards = _cards()
    names = {c.number: c.name for c in cards}
    for code in args.sets:
        numbers = set_template(cards, code.upper())
        if not numbers:
            print(f"# {code.upper()}: no cards found (check the set code; `python -m tools.gundam_cards.cli sets` lists them)", file=sys.stderr)
            continue
        print(f"# {code.upper()}: {len(numbers)} unique cards with a normal printing in this set. Replace each ? with the quantity,")
        print("# or delete the line if the product has none of it (some cards are only in the bonus pack).")
        for n in numbers:
            print(f"{n} ?  # {names[n]}")
        print()
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    report = check_lines(path.read_text(encoding="utf-8").splitlines(), catalog_info(_cards()), file=_portable(path))
    if not report.ok:
        _print_report(report, quiet=True)
        print("\nnot imported: fix the errors above first", file=sys.stderr)
        return 1
    out = write_collection(build_collection(report, datetime.now(UTC)))
    warnings = sum(1 for i in report.issues if i.severity is Severity.WARNING)
    print(f"imported {report.distinct_cards} cards, {report.total_copies} copies -> {out}" + (f" ({warnings} warning(s); run `check` to see them)" if warnings else ""))
    return 0


# ---- the linked views ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Layers:
    """Everything the views join, loaded once."""

    cards: Mapping[CardNumber, PricedCard]
    prices: Mapping[CardNumber, int]
    owned: Mapping[CardNumber, int]
    have_collection: bool


def _portable(path: Path) -> str:
    """A path as stored and printed: relative to the repository when inside it, so data files do not carry one machine's home folder."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _refresh_collection(cards: Mapping[CardNumber, PricedCard]) -> None:
    """Pick up edits to the hand-typed file: when it is newer than the last import and has no errors, import it again (a derived file, nothing is
    guessed); with errors, keep the last good import and say so. Says what it did on stderr, never silently."""
    source = COLLECTION_PATH
    out = OUT_DIR / "collection.json"
    if not source.is_file() or (out.is_file() and source.stat().st_mtime <= out.stat().st_mtime):
        return
    report = check_lines(source.read_text(encoding="utf-8").splitlines(), catalog_info(c.card for c in cards.values()), file=_portable(source))
    if not report.ok:
        print(f"note: my_tcg_collection has errors, so the last good import is used (run `check`): {len(report.errors)} error(s)", file=sys.stderr)
        return
    write_collection(build_collection(report, datetime.now(UTC)))
    print(f"note: my_tcg_collection changed, re-imported {report.distinct_cards} cards, {report.total_copies} copies", file=sys.stderr)


def _layers() -> Layers:
    priced = load_cards_with_prices()
    cards = {p.card.number: p for p in priced}
    prices = {n: p.latest_tcg_price.price_cents for n, p in cards.items() if p.latest_tcg_price is not None}
    _refresh_collection(cards)
    collection = load_collection()
    return Layers(cards, prices, owned_copies(collection), collection is not None)


def _sources(choice: str) -> list[DataSource]:
    return [DataSource.TOURNAMENT, DataSource.ONLINE] if choice == "both" else [DataSource(choice)]


def _load_source(source: DataSource) -> tuple[PackagesFile, RatesFile] | None:
    packages, rates = load_packages(source=source), load_rates(source=source)
    if packages is None or rates is None:
        print(f"no {source.value} packages yet; run `python -m tools.gundam_packages.cli build{' --source online' if source is DataSource.ONLINE else ''}` first", file=sys.stderr)
        return None
    return packages, rates


def _usd(cents: int | None) -> str:
    return f"${cents / 100:,.2f}" if cents is not None else "   -  "


def _label(source: DataSource, packages: PackagesFile) -> str:
    return f"online (example decks, {packages.window.start} on)" if source is DataSource.ONLINE else f"tournament ({packages.window.era})"


def _coverages(packages: PackagesFile, rates: RatesFile, layers: Layers) -> tuple[dict[PackageId, PackageCoverage], dict[PackageId, Stage]]:
    catalog = {n: c.card for n, c in layers.cards.items()}
    found = {p.package: package_coverage(p, packages.squads, layers.owned, layers.prices, catalog) for p in rates.packages}
    return found, classify(found, rates)


def cmd_coverage(args: argparse.Namespace) -> int:
    layers = _layers()
    if not layers.have_collection:
        print("no collection.json yet; run `import` first", file=sys.stderr)
        return 2
    for source in _sources(args.source):
        loaded = _load_source(source)
        if loaded is None:
            return 2
        packages, rates = loaded
        coverage, stages = _coverages(packages, rates, layers)
        print(f"\n== coverage, {_label(source, packages)} ==")
        print(f"   critical copies = the core members at the number of copies half of their decks run; home = I own at least {HOME_MIN_OWNED:.0%} of them;")
        print("   band: perfect 100%, complete 90%, playable 75% (with every core card at half its copies), reachable 50%, long shot 25%; cost = the cheapest copies that reach the next band\n")
        print(f"{'package':32} {'band':13} {'stage':9} {'critical':>9} {'share':>6}  {'cost to the next band(s)':40} played in")
        by_id = {p.package: p for p in rates.packages}
        def cost_key(c: PackageCoverage) -> tuple[bool, int]:
            up = c.next_band
            return (up is not None and up.unpriced > 0, up.cost_cents if up else 0)

        def order_key(kv: tuple[PackageId, PackageCoverage]) -> tuple[object, ...]:
            pid, c = kv
            by_rate = -by_id[pid].rate
            return (BANDS.index(c.band), by_rate, *cost_key(c), pid) if args.sort == "played" or c.band is Band.PERFECT else (BANDS.index(c.band), *cost_key(c), by_rate, pid)

        for pid, c in sorted(((k, v) for k, v in coverage.items() if by_id[k].rate >= args.min_rate), key=order_key)[: args.limit]:
            print(f"{c.name:32} {c.band.value:13} {stages[pid].value:9} {c.critical_have:>4}/{c.critical_need:<4} {100 * c.share:5.0f}%  {_ahead(c.ahead):40} {100 * by_id[pid].rate:4.1f}% of decks")
    return 0


def _packages_for_card(number: CardNumber, rates: RatesFile) -> list[PackageRates]:
    """The package the card is in, or else the (up to two) packages whose decks play it most."""
    owner = rates.card_index.get(number)
    if owner is not None:
        return [p for p in rates.packages if p.package == owner]
    played = sorted(((o.rate, p) for p in rates.packages for o in p.others if o.card_number == number), key=lambda r: (-r[0], r[1].package))
    return [p for _, p in played[:2]]


def cmd_card(args: argparse.Namespace) -> int:
    layers = _layers()
    number = CardNumber(args.card)
    if number not in layers.cards:
        print(f"no such card: {number}", file=sys.stderr)
        return 1
    priced = layers.cards[number]
    card = priced.card
    color, level, cost = color_of(card), level_of(card), cost_of(card)
    stats = ", ".join(x for x in (color.value if color else None, f"Lv{level}" if level is not None else None, f"cost {cost}" if cost is not None else None) if x)
    print(f"{number}  {card.name}  ({card.kind.value.replace('_', ' ')}{', ' + stats if stats else ''})")
    price = priced.latest_tcg_price
    print(f"  price:  {_usd(price.price_cents) + f'  (TCGPlayer market, product {price.product_id}, pulled {price.fetched_at:%Y-%m-%d})' if price else 'no TCGPlayer price (not a buyable single)'}")
    have = layers.owned.get(number, 0)
    print(f"  owned:  {have} copies" + ("" if layers.have_collection else "  (no collection.json yet: run `import`)"))
    for source in _sources(args.source):
        loaded = _load_source(source)
        if loaded is None:
            continue
        packages, rates = loaded
        coverage, stages = _coverages(packages, rates, layers)
        names = {p.package: p.name for p in rates.packages}
        homes = _packages_for_card(number, rates)
        print(f"\n  --- {_label(source, packages)} ---")
        if not homes:
            print("  not played in these decks")
            continue
        member = rates.card_index.get(number) is not None
        for pkg in homes:
            cov = coverage[pkg.package]
            role = next((m.role.value for m in pkg.members if m.card_number == number), None)
            print(f"  {'in package' if member else 'played with'} {pkg.name} ({100 * pkg.rate:.1f}% of decks){f' as {"an" if role == "optional" else "a"} {role} card' if role else ''}  [{stages[pkg.package].value}]")
            print(f"    I own {cov.critical_have} of {cov.critical_need} critical copies ({100 * cov.share:.0f}%): {cov.band.value}; {_ahead(cov.ahead)}; to complete: {_usd(cov.cost_cents)}" + (f" + {cov.unpriced_missing} unpriced" if cov.unpriced_missing else ""))
            for s in cov.slots:
                if s.critical_missing:
                    similar = f"; similar cards, not counted: {', '.join(layers.cards[n].card.name + ' ' + n for n in s.similar[:3])}" if s.similar else ""
                    print(f"      missing {s.critical_missing} x {_slot_label(s, layers.cards)} @ {_usd(s.unit_cents)}{similar}")
            rows = associated_cards(pkg, names, layers.owned, layers.prices, limit=args.limit, skip=number)
            print(f"    associated cards ({'rate' } = how often played with {pkg.name}; need = copies half the decks run):")
            print(f"      {'card':50} {'why':26} {'rate':>6} {'need':>4} {'own':>3} {'price':>9}")
            for r in rows:
                need = "-" if r.needed is None else str(r.needed)
                print(f"      {layers.cards[r.card].card.name[:36] + ' (' + r.card + ')':50} {r.why[:26]:26} {100 * r.rate:5.1f}% {need:>4} {r.owned:>3} {_usd(r.price_cents):>9}")
    return 0


def _parse_bands(text: str) -> tuple[int, ...]:
    """`0.5,1,5,10` (dollars) -> (50, 100, 500, 1000) cents."""
    try:
        values = tuple(round(float(x) * 100) for x in text.split(","))
    except ValueError:
        raise SystemExit(f"--bands wants increasing dollar amounts like 0.5,1,5,10, not {text!r}") from None
    if not values or values[0] <= 0 or any(a >= b for a, b in zip(values, values[1:], strict=False)):
        raise SystemExit(f"--bands wants increasing dollar amounts like 0.5,1,5,10, not {text!r}")
    return values


def _label_of(name: str, number: CardNumber, width: int = 36) -> str:
    """`Name (NUMBER)`, with a long name cut short so the number always shows."""
    return f"{name if len(name) <= width else name[: width - 1] + '…'} ({number})"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _print_value(report: ValueReport, limit: int | None) -> None:
    for band in reversed(report.bands):
        print(f"\n== {band.label}: {_plural(band.cards, 'card')}, {_plural(band.copies, 'copy').replace('copys', 'copies')}, worth {_usd(band.total_cents)} ==")
        if not band.lines:
            print("   none")
            continue
        print(f"   {'card':52} {'copies':>6} {'each':>9} {'worth':>10}")
        for line in band.lines[:limit]:
            note = f"  (you own {line.alt_art_copies} as an alt art; priced as the base card)" if line.alt_art_copies else ""
            print(f"   {_label_of(line.name, line.card):52} {line.copies:>6} {_usd(line.unit_cents):>9} {_usd(line.total_cents):>10}{note}")
        if limit is not None and len(band.lines) > limit:
            print(f"   ... and {len(band.lines) - limit} more")
    b = report.bulk
    print(f"\n== {b.label}: {_plural(b.cards, 'card')}, {_plural(b.copies, 'copy').replace('copys', 'copies')}, worth {_usd(b.total_cents)} (not listed; use --bulk to list) ==")


def cmd_value(args: argparse.Namespace) -> int:
    layers = _layers()
    collection = load_collection()
    if collection is None:
        print("no collection.json yet; run `import` first", file=sys.stderr)
        return 2
    thresholds = _parse_bands(args.bands)
    report = analyze(collection.data, layers.prices, {n: c.card.name for n, c in layers.cards.items()}, thresholds)
    pulled = max((c.latest_tcg_price.fetched_at for c in layers.cards.values() if c.latest_tcg_price), default=None)
    owned_total = sum(c.copies for c in collection.data)
    sell_value, sell_cards, sell_copies = report.sellable(SELL_MIN_CENTS)
    bulk_value, bulk_cards, bulk_copies = report.bulk_below(SELL_MIN_CENTS)
    print(f"== my collection: {len(collection.data)} cards, {owned_total} copies, worth {_usd(report.total_cents)} at TCGPlayer market prices"
          + (f" (pulled {pulled:%Y-%m-%d %H:%M} UTC)" if pulled else "") + " ==")
    print(f"   with the bulk ignored (cards of {_usd(SELL_MIN_CENTS)} or more, the ones worth selling): {_usd(sell_value)} from {sell_cards} cards, {sell_copies} copies")
    print(f"   bulk (under {_usd(SELL_MIN_CENTS)} a card): {_usd(bulk_value)} from {bulk_cards} cards, {bulk_copies} copies; the total above includes it")
    print("   each card is valued at the cheapest regular printing's market price, so an alt art or a pricier printing is valued as the base card")
    _print_value(report, args.limit)
    if args.bulk:
        print(f"\n   {report.bulk.label}:")
        for line in report.bulk.lines:
            print(f"   {_label_of(line.name, line.card):52} {line.copies:>6} {_usd(line.unit_cents):>9} {_usd(line.total_cents):>10}")
    if report.unpriced:
        kinds = ", ".join(f"{n} {name}" for n, name, _ in report.unpriced[:6])
        print(f"\n   {len(report.unpriced)} owned cards have no price (resources, EX cards or tokens: not sold as singles): {kinds}{', ...' if len(report.unpriced) > 6 else ''}")
    return 0


# ---- decks --------------------------------------------------------------------------------------------------------------
def _deck_context(choice: str, min_rate: float) -> tuple[Layers, list[DeckCoverage], dict[DataSource, dict[PackageId, Stage]]] | None:
    layers = _layers()
    if not layers.have_collection:
        print("no collection.json yet; run `import` first", file=sys.stderr)
        return None
    sources: dict[DataSource, tuple[PackagesFile, RatesFile]] = {}
    for source in _sources(choice):
        loaded = _load_source(source)
        if loaded is None:
            return None
        sources[source] = loaded
    stages = {s: _coverages(packages, rates, layers)[1] for s, (packages, rates) in sources.items()}
    groups = [g for packages, _ in sources.values() for g in packages.squads]
    catalog = {n: c.card for n, c in layers.cards.items()}
    restrictions = load_restrictions()
    rules = Rules.of(restrictions.data if restrictions else None, catalog)
    named = assign_archetypes(label_decks(build_decks(sources, 0.0, rules), catalog, load_deck_names()), catalog)  # name and group over all decks...
    decks = [d for d in named if is_played(d, min_rate)]  # ...then the floor
    return layers, [coverage(d, groups, layers.owned, layers.prices, catalog) for d in decks], stages


def _to_next(up: NextBand | None) -> str:
    """`$3.72 to playable` (a + when some copies have no price), or a dash for Perfect."""
    if up is None:
        return "-"
    return f"{_usd(up.cost_cents)}{'+' if up.unpriced else ''} to {up.band.value}"


def _ahead(steps: Sequence[NextBand]) -> str:
    """The cost to the next band and, for Reachable and Playable, the one after: `$1.53 to playable, $4.20 to complete`."""
    return ", ".join(_to_next(step) for step in steps) if steps else "-"


IDW = 34  # width of the id column


def _r10(rating: int) -> str:
    """A 0-100 rating shown out of 10 with one decimal: 42 -> ` 4.2`."""
    return f"{rating / 10:4.1f}"


def _style_line(st: Style) -> str:
    return (f"{st.color_text or '-':7} {st.plan.value:9} beatdown {_r10(st.beatdown)}  curve {_r10(st.curve)}  pressure {_r10(st.pressure)}  "
            f"interaction {_r10(st.interaction)}  advantage {_r10(st.advantage)}  links {_r10(st.links)}  (finisher {_r10(st.finisher).strip()}, resilience {_r10(st.resilience).strip()})")


def cmd_styles(args: argparse.Namespace) -> int:
    """Colors, ratings and plan for the most played decks (so the labels can be checked against what I know of the meta)."""
    context = _deck_context(args.source, args.min_rate)
    if context is None:
        return 2
    layers, coverages, _ = context
    catalog = {n: p.card for n, p in layers.cards.items()}
    print("== what the decks do: ratings are out of 10 (curve: lots of small Units; pressure: Units that hit harder than they take or have Breach / Suppression /")
    print("   High-Maneuver; interaction: Commands, Blockers and board-hitting abilities; advantage: cards that put a card in your hand, halved by a condition).")
    print("   beatdown = the mean of curve, pressure, low interaction and low advantage: aggro 6.0 or more, control 4.0 or less, midrange in between ==\n")
    for c in sorted(coverages, key=lambda c: (-c.deck.top_rate, c.deck.name))[: args.limit]:
        st = style_of(c.deck.requirements, catalog)
        ident = f"{c.deck.id:{IDW}} " if args.ids else ""
        print(f"{c.deck.name[:46]:46} {ident}{_played(c.deck.rates):>14}  {_style_line(st)}")
        if args.explain:
            print("      " + "; ".join(f"{k} {v:.2f}" if v < 5 else f"{k} {v:.0f}" for k, v in st.facts.items()))
    return 0


def _line_text(ln: Line, layers: Layers, meta: Mapping[CardNumber, tuple[str, str]]) -> str:
    name, set_code = meta.get(ln.card, (layers.cards[ln.card].card.name, str(ln.card).split("-")[0]))
    also = f"; also needed by {len(ln.also)} other deck(s) of this archetype" if ln.also else ""
    star = "  ★ PREMIUM" if ln.premium else ""
    return f"{ln.copies} x {name} [{set_code}]  {_usd(ln.unit_cents)} = {_usd(ln.line_cents)}   {'; '.join(ln.why)[:46]}{also}{star}"


def cmd_buy(args: argparse.Namespace) -> int:
    """What to buy to play more of an archetype: a path of decks, cheapest to make Playable first, never including premium cards unasked."""
    context = _deck_context(args.source, args.min_rate)
    if context is None:
        return 2
    layers, coverages, _ = context
    decks = [c.deck for c in coverages]
    names = archetype_names(decks, " ".join(args.archetype)) if args.archetype else []
    chosen: dict[str, Deck] = {d.id: d for d in decks if d.archetype in names}
    for text in args.package or []:
        for d in decks_with_package(decks, text):
            chosen.setdefault(d.id, d)
    for text in args.deck or []:
        for d in find_decks(decks, text):
            chosen.setdefault(d.id, d)
    asked = " ".join([*args.archetype, *(f"--package {t}" for t in args.package or []), *(f"--deck {t}" for t in args.deck or [])])
    if not chosen:
        print(f"no deck or archetype matches {asked!r}; the biggest archetypes are:", file=sys.stderr)
        for a in group_archetypes(decks)[:12]:
            print(f"  {a.name:36} {_played(a.rates)}", file=sys.stderr)
        return 1
    left_out = [d for d in decks if d.id in chosen and d.illegal]
    members = [d for d in decks if d.id in chosen and not d.illegal]
    names = names or [f"decks matching {asked}"]
    for d in left_out:
        print(f"note: {d.name} is left out: not legal as found ({d.illegal[0]})", file=sys.stderr)
    if not members:
        print("no legal deck matches", file=sys.stderr)
        return 1
    catalog = {n: p.card for n, p in layers.cards.items()}
    groups = [g for source in _sources(args.source) if (loaded := _load_source(source)) is not None for g in loaded[0].squads]

    def coverage_of(deck: Deck, owned: Mapping[CardNumber, int]) -> DeckCoverage:
        return coverage(deck, groups, owned, layers.prices, catalog)

    plan = plan_buy(members, coverage_of, layers.owned, include_premium=args.include_premium, steps=args.steps, polish=args.polish)
    meta = {n: (p.latest_tcg_price.name, p.latest_tcg_price.set_code) for n, p in layers.cards.items() if p.latest_tcg_price is not None and p.latest_tcg_price.name}
    _print_plan(plan, names, members, layers, meta, catalog, args.include_premium, round(args.alt_from * 100))
    if args.export is not None:
        path = Path(args.export) if args.export else OUT_DIR / f"buy_{re.sub(r'[^a-z0-9]+', '_', asked.casefold()).strip('_')}.txt"
        entry = mass_entry(plan, meta, {n: p.card.name for n, p in layers.cards.items()})
        path.write_text("\n".join(entry) + ("\n" if entry else ""), encoding="utf-8")
        print(f"\nwrote {len(entry)} Mass Entry line(s) to {path}")
    return 0


def _alternatives_lines(card: CardNumber, deck: Deck | Sequence[Deck], layers: Layers, catalog: Mapping[CardNumber, CardModel]) -> list[str]:
    """Same-job alternatives for a card to buy (never counted, never a reason to skip it): the cheapest, with what I own of each, and any I already own."""
    decks = [deck] if isinstance(deck, Deck) else list(deck)
    required = sorted({r.card for d in decks for r in d.requirements})  # a card any of these decks already runs is not an alternative
    lines: list[str] = []

    def color_note(c: object) -> str:
        c_in = getattr(c, "in_deck_colors", True)
        color = getattr(c, "color", None)
        return "" if c_in else f"  [needs {color.value if color else '?'}]"

    for c in candidates(card, required, catalog, layers.prices, limit=3, owned=layers.owned):
        mine = f"  (you own {c.owned})" if c.owned else ""
        lines.append(f"alternative (not counted): {catalog[c.card].name} ({c.card}) {_usd(layers.prices.get(c.card))} {c.standing.value}{color_note(c)}{mine}")
    have = owned_alternatives(card, required, catalog, layers.owned)
    if not lines and not have:
        return ["no same-job alternative found (checked every card against this deck's pilots and Links)"]
    if have:
        lines.append("you already own: " + ", ".join(f"{c.owned} x {catalog[c.card].name} ({c.card}) {c.standing.value}{color_note(c)}" for c in have[:4]))
    return lines


def _print_plan(plan: BuyPlan, names: Sequence[str], members: Sequence[Deck], layers: Layers, meta: Mapping[CardNumber, tuple[str, str]], catalog: Mapping[CardNumber, CardModel], include_premium: bool, alt_from_cents: int) -> None:
    print(f"== buy: {', '.join(names)}  ({len(members)} decks) ==")
    print("   greedy and deterministic: the deck cheapest to make Playable first; its copies then count as bought, and the next deck is chosen by its extra cost.")
    print(f"   {'premium cards ($10+) are planned like any other' if include_premium else 'premium cards ($10+) are considered but SKIPPED (not bought, not in the totals) until you approve them'}; near mint, cheapest printing, never past 4 copies.")
    if plan.already:
        print("\n-- you can already play --")
        for deck, band in plan.already:
            print(f"   {deck.name[:60]:60} {band.value}")
    if not plan.steps:
        print("\n   nothing to buy for these decks")

    def show(label: str, step: Step, goal: str) -> None:
        skipped = _usd(sum(ln.line_cents or 0 for ln in step.held_back))
        print(f"\n-- {label}: {step.deck.name}  [{step.deck.id}]  {_played(step.deck.rates)} --")
        copies = sum(ln.copies for ln in step.lines)
        if copies:
            print(f"   to make it {goal}: {_usd(step.cost_cents)}{'+' if step.unpriced else ''} for {copies} copies   (running total {_usd(step.running_cents)})")
        else:
            print(f"   nothing else to buy to make it {goal}: only the skipped premium card(s) below   (running total {_usd(step.running_cents)})")
        for ln in step.lines:
            print(f"      {_line_text(ln, layers, meta)}")
            if (ln.unit_cents or 0) >= alt_from_cents:  # a card worth looking for a cheaper way around (never skipped: only premium cards are)
                for text in _alternatives_lines(ln.card, step.deck, layers, catalog):
                    print(f"         {text}")
        for ln in step.held_back:
            print(f"      SKIPPED, needs your approval: {_line_text(ln, layers, meta)}")
        if step.held_back:
            print(f"      -> not {goal} until the skipped premium card(s) ({skipped}) are approved" + ("; the copies above still count toward it" if copies else ""))
        for name, was, now in step.also_moves:
            print(f"      also moves {name}: {was.value} -> {now.value}")

    unpriced = 0
    for i, step in enumerate(plan.steps, start=1):
        show(f"step {i}", step, "Playable")
        unpriced += step.unpriced
    for i, step in enumerate(plan.polish, start=1):
        show(f"polish {i}", step, "Complete")
        unpriced += step.unpriced
    skipped: dict[CardNumber, tuple[Line, list[Deck]]] = {}
    for step in (*plan.steps, *plan.polish):
        for ln in step.held_back:
            known = skipped.get(ln.card)
            skipped[ln.card] = (ln if known is None or ln.copies > known[0].copies else known[0], [*(known[1] if known else []), step.deck])
    if skipped:
        print("\n-- skipped premium cards ($10+): they need your approval (`--include-premium` plans them) --")
        for card, (ln, held) in sorted(skipped.items(), key=lambda kv: -(kv[1][0].line_cents or 0)):
            print(f"   {_line_text(ln, layers, meta)}")
            print(f"      holds back {len(held)} deck(s): {', '.join(dict.fromkeys(d.name for d in held))[:150]}")
            for text in _alternatives_lines(card, held, layers, catalog):
                print(f"      {text}")
    last = (plan.polish or plan.steps)[-1].running_cents if (plan.polish or plan.steps) else 0
    skipped_total = sum((ln.line_cents or 0) * 1 for ln, _ in skipped.values())
    print(f"\n   total (without the skipped premium cards): {_usd(last)}{'+ (some copies have no price)' if unpriced else ''}" + (f"; skipped premium cards: {_usd(skipped_total)}" if skipped else ""))


_PLAN_WORDS = {"aggro": Plan.AGGRO, "midrange": Plan.MIDRANGE, "mid": Plan.MIDRANGE, "control": Plan.CONTROL}
_LETTER_COLOR = {"R": "red", "B": "blue", "G": "green", "W": "white", "P": "purple"}


def cmd_suggest(args: argparse.Namespace) -> int:
    """Hypothetical decks: the shape from found decks, the cards chosen by the ratings; one per second color unless a color pair is named."""
    context = _deck_context(args.source, 0.0)
    if context is None:
        return 2
    layers, coverages, _ = context
    decks = [c.deck for c in coverages]
    catalog = {n: p.card for n, p in layers.cards.items()}
    plan: Plan | None = _PLAN_WORDS[args.plan] if args.plan else None
    letters: frozenset[str] = frozenset()
    words: list[str] = []
    for w in args.words:
        low = w.casefold()
        if low in _PLAN_WORDS and plan is None:
            plan = _PLAN_WORDS[low]
        elif re.fullmatch(r"[rbgwp]{2}", low) and not letters:
            letters = frozenset(low.upper())
        elif re.fullmatch(r"[rbgwp]/[rbgwp]", low) and not letters:
            letters = frozenset(low.upper().replace("/", ""))
        else:
            words.append(low)
    if args.colors:
        letters = frozenset(args.colors.upper().replace("/", ""))
    anchor = (args.package or "").upper() or None
    if anchor is None:
        found: dict[str, str] = {}
        for d in decks:
            for label, a in zip(d.package_labels, d.anchors, strict=False):
                if words and all(w in label.casefold() for w in words):
                    found.setdefault(a, label)
        if len(found) != 1:
            print(f"{'several packages match' if found else 'no package matches'} {' '.join(words)!r}" + ("; use --package with one of:" if found else ""), file=sys.stderr)
            for a, label in sorted(found.items(), key=lambda kv: kv[1])[:12]:
                print(f"  {label}  --package {a}", file=sys.stderr)
            return 1
        anchor = next(iter(found))
    sources = {s: _load_source(s) for s in _sources(args.source)}
    core: dict[CardNumber, int] = {}
    pkg_name, best_rate = anchor, -1.0
    pkg_letters: frozenset[str] = frozenset()
    for packages, rates in (v for v in sources.values() if v is not None):
        for pr in rates.packages:
            if anchor_of(pr.package) == anchor and pr.rate > best_rate:
                best_rate, pkg_name = pr.rate, pr.name
                core = {m.card_number: (m.majority_copies or typical_copies(m.histogram)) for m in pr.members if m.role.value == "core" and (m.majority_copies or typical_copies(m.histogram))}
                pkg_letters = frozenset(LETTERS[c.value] for pk in packages.packages if anchor_of(pk.id) == anchor for c in pk.colors)
    if not core:
        print(f"package {anchor} has no core cards in the data", file=sys.stderr)
        return 1
    if letters and not (pkg_letters & letters):
        print(f"{pkg_name} is {'/'.join(sorted(pkg_letters))}, so {''.join(sorted(letters))} does not include its color", file=sys.stderr)
        return 1
    seconds = [letters - pkg_letters] if letters else [frozenset({c}) for c in sorted(set("RBGWP") - pkg_letters)]
    styles = {d.id: style_of(d.requirements, catalog) for d in decks}
    restrictions = load_restrictions()
    rules = Rules.of(restrictions.data if restrictions else None, catalog)
    if plan is None:  # the plan most of this package's found decks have
        votes: dict[Plan, float] = {}
        for d in decks:
            if anchor in d.anchors:
                votes[styles[d.id].plan] = votes.get(styles[d.id].plan, 0.0) + d.top_rate
        plan = max(votes, key=lambda p: (votes[p], p.value)) if votes else Plan.MIDRANGE
    groups = [g for src in _sources(args.source) if (loaded := sources.get(src)) is not None for g in loaded[0].squads]
    print(f"== suggest: {pkg_name} {plan.value}  ({'colors ' + '/'.join(sorted(letters)) if letters else 'every second color, grouped by color'}; prefer {args.prefer}, novelty {args.novelty:g}) ==")
    for second in seconds:
        colors = frozenset(pkg_letters | second)
        refs = [d for d in decks if anchor in d.anchors and set(styles[d.id].colors) <= colors]
        plan_decks = [d for d in decks if styles[d.id].plan is plan and set(styles[d.id].colors) <= colors]
        result = build_suggestion(package=pkg_name, core=core, plan=plan, colors=colors, references=refs, plan_decks=plan_decks, catalog=catalog,
                                  owned=layers.owned, prices=layers.prices, prefer=Prefer(args.prefer), novelty=args.novelty, rules=rules)  # fmt: skip
        _print_suggestion(result, layers, catalog, groups, anchor, args)
    return 0


def _print_suggestion(sug: Suggestion, layers: Layers, catalog: Mapping[CardNumber, CardModel], groups: Sequence[Squad], anchor: str, args: argparse.Namespace) -> None:
    from tools.gundam_packages.models import DataSource as _DS

    hypothetical = Deck(name=f"{sug.package} {sug.plan.value}", package_refs=(), rates={_DS.TOURNAMENT: 0.0}, low_sample=False, requirements=sug.requirements(), anchors=(anchor,), id="hypothetical")
    cov = coverage(hypothetical, groups, layers.owned, layers.prices, catalog)
    own = sum(min(layers.owned.get(p.card, 0), p.copies) for p in sug.picks)
    print(f"\n== {'/'.join(sug.colors)}: {sug.package} {sug.plan.value} ==")
    print(f"   reference: " + (f"{len(sug.references)} found deck(s) with it in these colors: {', '.join(sug.references[:3])}{' ...' if len(sug.references) > 3 else ''}" if sug.references else "no found deck has it in these colors: every non-core card is chosen by known plan staples and plan fit"))
    print(f"   rating of this 50: {_style_line(sug.style)}")
    print(f"   you own {own} of {sug.copies} copies; band {cov.band.value}; to build the rest: {_usd(cov.cost_cents(Layer.CORE, Layer.STAPLE))}   ({_ahead(cov.ahead)})")
    for note in sug.notes:
        print(f"   note: {note}")
    pairs, linked_units, pilot_copies = sug.pairs
    print(f"   link pairs: {pairs} possible ({linked_units} Linked Unit copies, {pilot_copies} pilot copies): a Linked Unit can be used the turn it is played and takes its pilot's stats")
    chosen = {p.card: p.copies for p in sug.picks}
    sections: list[tuple[str, list[Pick]]] = [("core (the package)", [p for p in sug.picks if p.role == "core"])]
    for name in dict.fromkeys(p.group for p in sug.picks if p.group):
        sections.append((f"partner package: {name}", [p for p in sug.picks if p.group == name]))
    sections.append(("known cards (found lists)", [p for p in sug.picks if p.role == "known" and not p.group]))
    sections.append(("novel (in no found list)", [p for p in sug.picks if p.role == "novel"]))
    for title, rows in sections:
        if not rows:
            continue
        print(f"   -- {title} --")
        for pick in rows:
            card = catalog[pick.card]
            have = layers.owned.get(pick.card, 0)
            price = layers.prices.get(pick.card)
            print(f"      {pick.copies} x {card.name[:34]:34} ({pick.card}) {card.kind.value:7} own {have:>2}  {_usd(price):>8}  {pick.why}")
            if (price or 0) >= round(args.alt_from * 100):
                for text in _alternatives_lines(pick.card, hypothetical, layers, catalog):
                    print(f"            {text}")
    pilot_picks = [pick for pick in sug.picks if catalog[pick.card].kind.value == "pilot"]
    if pilot_picks:
        print("   -- pilots and who they pair with --")
        for pick in pilot_picks:
            served = pairs_for(pick.card, chosen, catalog)
            who = ", ".join(f"{catalog[u].name} ({u}) x{n}" for u, n in served) or "no Linked Unit in the deck (a stat bonus only)"
            print(f"      {pick.copies} x {catalog[pick.card].name[:30]:30} ({pick.card}) Links: {who}")
    if sug.pilot_options:
        print("   -- other pilots worth a look --")
        for o in sug.pilot_options[: args.pool or 8]:
            units = ", ".join(f"{catalog[u].name} ({u})" for u in o.units) or "no more Units"
            owned_note = f" own {layers.owned[o.card]}" if layers.owned.get(o.card) else ""
            print(f"      {catalog[o.card].name} ({o.card}){owned_note}: {sug.plan.value} fit {o.fit:.1f}; pairs with {o.pairs_in_deck} Unit copies in this deck; would also Link {units}")
    if args.pool:
        print("   -- pool: the next best cards, by kind --")
        for kind in (k for k in KINDS if k.value != "pilot"):  # pilots have their own list above
            others = sug.pool.get(kind, ())[: args.pool]
            if others:
                print(f"      {kind.value}s: " + "; ".join(f"{catalog[r.card].name} ({r.card}) {r.role}{' own ' + str(layers.owned[r.card]) if layers.owned.get(r.card) else ''}" for r in others))


def cmd_archetypes(args: argparse.Namespace) -> int:
    """The meta as archetypes: decks grouped by their most-played package and their plan, with how close I am to the closest deck in each."""
    context = _deck_context(args.source, 0.0)
    if context is None:
        return 2
    _, coverages, _ = context
    by_deck = {id(c.deck): c for c in coverages}
    print("== archetypes: decks grouped by their most-played package and their plan (every deck is in exactly one); share = how often they are played together ==\n")
    shown = [a for a in group_archetypes([c.deck for c in coverages]) if a.top_rate >= args.min_share][: args.limit]
    for arch in shown:
        members = [by_deck[id(d)] for d in arch.decks]
        closest = min(members, key=lambda c: (BANDS.index(c.band), c.next_band.cost_cents if c.next_band else 0, -c.deck.top_rate))
        print(f"{arch.name:38} {_played(arch.rates):>14}   {len(members):>2} decks   my closest: {closest.band.value} ({_to_next(closest.next_band)})")
        for c in members[: args.members]:
            print(f"      {c.deck.name[:60]:60} {_played(c.deck.rates):>14}  {c.band.value:13} {_ahead(c.ahead)}")
        if len(members) > args.members:
            print(f"      ... and {len(members) - args.members} more decks")
    covered = {src: sum(a.rates.get(src, 0.0) for a in group_archetypes([c.deck for c in coverages])) for src in DataSource}
    print(f"\n   (all archetypes together: {100 * covered[DataSource.TOURNAMENT]:.0f}% T / {100 * covered[DataSource.ONLINE]:.0f}% O of decks)")
    return 0


def cmd_nickname(args: argparse.Namespace) -> int:
    """Give a deck a nickname (kept in deck_names.json by deck id), remove one, or list them."""
    context = _deck_context("both", 0.0)
    if context is None:
        return 2
    _, coverages, _ = context
    names = load_deck_names()
    if args.list or not args.deck:
        by_id = {c.deck.id: c.deck for c in coverages}
        print(f"== deck nicknames ({len(names)}) ==")
        for ident, nick in sorted(names.items(), key=lambda kv: kv[1].casefold()):
            deck = by_id.get(ident)
            print(f"   {nick:24} {ident:34} {deck.plain_name if deck else '(no such deck any more)'}")
        return 0
    cov = _find_deck(coverages, args.deck)
    if cov is None:
        return 1
    deck = cov.deck
    if args.remove:
        if names.pop(deck.id, None) is None:
            print(f"{deck.id} has no nickname")
            return 0
        save_deck_names(names)
        print(f"removed the nickname of {deck.plain_name} ({deck.id})")
        return 0
    if not args.name:
        print("give a nickname, or --remove, or --list", file=sys.stderr)
        return 2
    taken = [i for i, n in names.items() if n.casefold() == args.name.casefold() and i != deck.id]
    if taken:
        print(f"{args.name!r} is already the nickname of {taken[0]}", file=sys.stderr)
        return 1
    names[deck.id] = args.name
    save_deck_names(names)
    print(f"{deck.plain_name} ({deck.id}) is now {args.name!r}")
    return 0


def _played(rates: Mapping[DataSource, float]) -> str:
    t, o = rates.get(DataSource.TOURNAMENT), rates.get(DataSource.ONLINE)
    return f"{'-' if t is None else f'{100 * t:.0f}%'} T / {'-' if o is None else f'{100 * o:.0f}%'} O"


def cmd_decks(args: argparse.Namespace) -> int:
    context = _deck_context(args.source, args.min_rate)
    if context is None:
        return 2
    layers, coverages, _ = context
    catalog = {n: p.card for n, p in layers.cards.items()}
    groups = overview(coverages, args.sort)
    print(f"== decks, played in at least {args.min_rate:.0%} of decks in a source (T = tournament, O = online); * = few decks, copy counts uncertain ==")
    print("   a deck needs its core (core package cards and the bridges between them) and its staples (cards at least half its lists run); options are not counted")
    print("   band = share of those copies I own: perfect 100%, complete 90%, playable 75% (every core card at half its copies), reachable 50%, long shot 2")
    print("   C curve, P pressure, I interaction, A advantage: ratings out of 10 (see `styles --explain`); plan = aggro / midrange / control;")
    print("   archetype % = how often decks with the same most-played package and the same plan are played together (see `archetypes`);")
    print("   ! = not legal under the banned / restricted list as found (the data predates it or it breaks a banned pair); see `deck`\n")
    shown = [b for b in BANDS if args.all or THRESHOLDS[b] >= THRESHOLDS[Band.REACHABLE]]
    for band in shown:
        rows = groups[band]
        print(f"-- {band.value}: {len(rows)} --")
        if not rows:
            print("   none\n")
            continue
        print(f"   {'deck':50} {'id' if args.ids else '':{IDW if args.ids else 0}}{' ' if args.ids else ''}{'played in':>14} {'archetype %':>14} {'colors':6} {'plan':9} {'C':>4} {'P':>4} {'I':>4} {'A':>4} {'core':>7} {'all':>8} {'options':>8}  {'cost to the next band(s)':40}")
        for c in rows[: args.limit]:
            name = c.deck.name + (" *" if c.deck.low_sample else "") + (" !" if c.deck.illegal else "")
            st = style_of(c.deck.requirements, catalog)
            print(f"   {name[:50]:50} {c.deck.id if args.ids else '':{IDW if args.ids else 0}}{' ' if args.ids else ''}{_played(c.deck.rates):>14} {_played(c.deck.archetype_rates):>14} {st.color_text:6} {st.plan.value:9} {_r10(st.curve)} {_r10(st.pressure)} {_r10(st.interaction)} {_r10(st.advantage)} {c.have(Layer.CORE)}/{c.need(Layer.CORE):<5} {c.have(Layer.CORE, Layer.STAPLE)}/{c.need(Layer.CORE, Layer.STAPLE):<6} "
                  f"{c.have(Layer.OPTION)}/{c.need(Layer.OPTION):<6}  {_ahead(c.ahead)}")
        print()
    return 0


def _find_deck(coverages: Sequence[DeckCoverage], text: str) -> DeckCoverage | None:
    """The one deck a text means (an id, a nickname, a name, or its words); several are listed with their ids, never guessed."""
    by_deck = {id(c.deck): c for c in coverages}
    found = [by_deck[id(d)] for d in find_decks([c.deck for c in coverages], text)]
    if len(found) == 1:
        return found[0]
    shown = found if found else list(coverages)
    print(f"{'several decks match' if found else 'no deck matches'} {text!r}; " + ("they are" if found else "some decks are") + ":", file=sys.stderr)
    for c in shown[:12]:
        print(f"  {c.deck.name}  {c.deck.id}  ({_played(c.deck.rates)})", file=sys.stderr)
    return None


def _slot_label(s: DeckSlot | Slot, cards: Mapping[CardNumber, PricedCard]) -> str:
    """`Name (NUMBER)`, plus the stand-ins that count toward it (option cards only)."""
    label = " + ".join(f"{cards[n].card.name} ({n})" for n in s.members)
    return label + (f"  [also counts: {', '.join(f'{cards[n].card.name} ({n})' for n in s.alternates)}]" if s.alternates else "")


def _print_card_list(cov: DeckCoverage, layers: Layers) -> None:
    """Every card the deck wants, one row per card number: what I own, what the deck needs, the price. Same-job cards are redundant, not
    substitutes: each row stands on its own; an option card notes the stand-ins that count toward it."""
    slot_of = {m: s for s in cov.slots for m in s.members}
    print("\n-- every card, by layer (a card number is a card; same-job cards are redundant, not substitutes) --")
    print(f"   {'card':44} {'number':9} {'layer':7} {'need':>4} {'own':>4} {'short':>5} {'price':>9}  note")
    for layer in LAYERS:
        for r in (r for r in cov.deck.requirements if r.layer is layer):
            own = layers.owned.get(r.card, 0)
            slot = slot_of[r.card]
            note = ""
            if slot.alternates:
                note = f"also counts: {', '.join(f'{n} (own {layers.owned.get(n, 0)})' for n in slot.alternates)}; cheapest: {slot.option} {_usd(slot.unit_cents)}"
            short = max(r.need - own, 0)
            flag = " ★ PREMIUM" if (slot.unit_cents or 0) >= PREMIUM_CENTS and slot.missing(layer) else ""
            print(f"   {layers.cards[r.card].card.name[:44]:44} {r.card:9} {layer.value:7} {r.need:>4} {own:>4} {short if short else '':>5} {_usd(layers.prices.get(r.card)):>9}  {note}{flag}")
    totals = {layer: sum(r.need for r in cov.deck.requirements if r.layer is layer) for layer in LAYERS}
    print(f"\n   copies needed: core {totals[Layer.CORE]}, staples {totals[Layer.STAPLE]} (core + staples {totals[Layer.CORE] + totals[Layer.STAPLE]}), options {totals[Layer.OPTION]}")


def cmd_deck(args: argparse.Namespace) -> int:
    context = _deck_context(args.source, 0.0)  # every deck can be asked for; the overview floor does not apply
    if context is None:
        return 2
    layers, coverages, stages = context
    cov = _find_deck(coverages, args.deck)
    if cov is None:
        return 1
    floor = [c for c in coverages if c.deck.top_rate >= args.min_rate]
    durable = needed_by(floor)
    cards = layers.cards
    deck = cov.deck
    core, working = (Layer.CORE,), (Layer.CORE, Layer.STAPLE)
    print(f"== {deck.name}{' *' if deck.low_sample else ''}  [{cov.band.value.upper()}] ==")
    print(f"   id: {deck.id}" + (f"   nickname: {deck.nickname} (generated name: {deck.plain_name})" if deck.nickname else ""))
    print(f"   archetype: {deck.archetype}, {_played(deck.archetype_rates)} of decks (this deck: {_played(deck.rates)})")
    for why in deck.illegal:
        print(f"   NOT LEGAL as found: {why} (banned / restricted list; the found lists may predate it)")
    pkgs = ", ".join(f"{n} [{s.value}]" for n, s in package_stages(deck, stages))
    print(f"   packages: {pkgs}\n   played in: {_played(deck.rates)}" + ("   (* few decks: copy counts are uncertain)" if deck.low_sample else ""))
    print("   style: " + _style_line(style_of(deck.requirements, {n: p.card for n, p in layers.cards.items()})))
    print(f"   core {cov.have(*core)}/{cov.need(*core)} copies   core + staples {cov.have(*working)}/{cov.need(*working)} ({100 * cov.working_share:.0f}%)   "
          f"options {cov.have(Layer.OPTION)}/{cov.need(Layer.OPTION)}")
    more = " + unpriced copies" if cov.unpriced_missing(*working) else ""
    print(f"   to finish the core: {_usd(cov.cost_cents(*core))}   to finish core + staples: {_usd(cov.cost_cents(*working))}{more}")
    for i, up in enumerate(cov.ahead):
        buys = ", ".join(f"{copies} x {cards[card].card.name} ({card})" for card, copies in up.buys) if i == 0 else ""
        print(f"   to {up.band.value}: {_usd(up.cost_cents)}{'+' if up.unpriced else ''} for {up.copies} copies" + (f": {buys}" if buys else ""))
    titles = {Layer.CORE: "core (core package cards and the bridges between them)", Layer.STAPLE: "staples (cards at least half of its lists run, most-run first)",
              Layer.OPTION: "options (optional package cards and cards in a quarter to half of its lists)"}
    for layer in LAYERS:
        if layer is Layer.OPTION and not args.options:
            print(f"\n-- options: {cov.have(Layer.OPTION)}/{cov.need(Layer.OPTION)} copies owned (use --options to list) --")
            continue
        rows = [s for s in cov.slots if s.need(layer)]
        print(f"\n-- {titles[layer]} --")
        print(f"   {'card':62} {'have':>6} {'price':>9}  why")
        for s in rows:
            flag = "  ★ PREMIUM" if s.unit_cents is not None and s.unit_cents >= PREMIUM_CENTS and s.missing(layer) else ""
            print(f"   {_slot_label(s, cards)[:62]:62} {s.have(layer):>2}/{s.need(layer):<3} {_usd(s.unit_cents):>9}  {'; '.join(s.why[layer])[:50]}{flag}")
    if args.cards:
        _print_card_list(cov, layers)
        return 0
    buy = picks(cov, durable)
    print(f"\n-- picks: what to get for this deck, in order ({sum(p.copies for p in buy)} copies) --")
    if not buy:
        print("   nothing: every core and staple copy is owned" if cov.band is Band.PERFECT else "   nothing missing")
    total = 0
    count = 0
    alt_from_cents = round(args.alt_from * 100)
    last = {layer: max((i for i, p in enumerate(buy) if p.layer is layer), default=-1) for layer in LAYERS}
    for i, p in enumerate(buy, start=1):
        count += p.copies
        total += p.line_cents or 0
        flag = "  ★ PREMIUM" if p.premium else ""
        also = f"  also needed by {len(p.also_needed_by)} other deck(s): {', '.join(p.also_needed_by[:3])}" if p.also_needed_by else ""
        print(f"   {i:>2}. {p.copies} x {cards[p.card].card.name} ({p.card}) @ {_usd(p.unit_cents)} = {_usd(p.line_cents)}   [{p.layer.value}] {'; '.join(p.why)[:60]}{flag}{also}")
        if (p.unit_cents or 0) >= alt_from_cents:  # a card worth looking for a cheaper way around (same as `buy`; never skipped)
            for text in _alternatives_lines(p.card, deck, layers, {n: c.card for n, c in cards.items()}):
                print(f"          {text}")
        if last[p.layer] == i - 1 and p.layer in working:
            done = p.layer is Layer.STAPLE or last[Layer.STAPLE] < 0  # no staple picks follow: this completes the working deck
            what = "the working deck (core + staples) is complete" if done else "the core is complete"
            print(f"       -> with these {count} copies ({_usd(total)}), {what}")
    if args.alternatives:
        catalog = {n: p.card for n, p in layers.cards.items()}
        required = [r.card for r in deck.requirements]
        print("\n-- alternatives: same-job cards for the missing core and staple cards (never counted toward the deck; each card is still needed) --")
        for sl in cov.slots:
            if not (sl.missing(Layer.CORE) or sl.missing(Layer.STAPLE)):
                continue
            card = sl.members[0]
            print(f"   {_slot_label(sl, cards)} {_usd(sl.unit_cents)}:")
            found = candidates(card, required, catalog, layers.prices, limit=5)
            shown = {c.card for c in found}
            for c in found:
                other = catalog[c.card]
                where = "" if c.in_deck_colors else f"  [needs {c.color.value if c.color else '?'}: not a color this deck plays]"
                print(f"       {other.name} ({c.card}) {_usd(layers.prices.get(c.card))}  {c.standing.value}{where}")
            for n in sl.similar:
                if n not in shown:
                    print(f"       {cards[n].card.name} ({n}) {_usd(layers.prices.get(n))}  peer in real decks, but not a stand-in for this deck's pilots or Links")
            if not found and not sl.similar:
                print("       none")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate the collection file: bad lines, unknown cards, duplicates (no network)")
    check.add_argument("--file", default=str(COLLECTION_PATH), help="the collection file (default shared/data/gundam_collection/my_tcg_collection)")
    check.add_argument("--quiet", action="store_true", help="hide info-level notes (resource cards, large totals)")
    check.set_defaults(func=cmd_check)
    template = sub.add_parser("template", help="print the unique cards in a product with ? quantities to fill in")
    template.add_argument("sets", nargs="+", help="set codes, e.g. ST05 SC01")
    template.set_defaults(func=cmd_template)
    imp = sub.add_parser("import", help="turn my_tcg_collection into collection.json (refuses if the file has errors)")
    imp.add_argument("--file", default=str(COLLECTION_PATH), help="the collection file")
    imp.set_defaults(func=cmd_import)
    cov = sub.add_parser("coverage", help="how complete each package is, its stage (home/adjacent/new) and the cost to complete (no network)")
    cov.add_argument("--source", choices=["tournament", "online", "both"], default="tournament")
    cov.add_argument("--limit", type=int, default=40)
    cov.add_argument("--sort", choices=["cost", "played"], default="cost", help="within each band: cheapest to move up first (default) or most played first (meta coverage)")
    cov.add_argument("--min-rate", type=float, default=0.0, help="leave out packages played in less than this share of decks (default 0: all)")
    cov.set_defaults(func=cmd_coverage)
    one = sub.add_parser("card", help="one card across all layers: facts, price, what I own, associations and coverage (no network)")
    one.add_argument("card", help="card number, e.g. GD01-026")
    one.add_argument("--source", choices=["tournament", "online", "both"], default="both")
    one.add_argument("--limit", type=int, default=6, help="cards shown per group")
    one.set_defaults(func=cmd_card)
    dk = sub.add_parser("decks", help="which decks my collection supports and which it is close to (no network)")
    dk.add_argument("--source", choices=["tournament", "online", "both"], default="both")
    dk.add_argument("--min-rate", type=float, default=MIN_PLAY_RATE, help="leave out fringe decks: those whose own play rate and whose archetype's play rate are both below this in every source (default 0.05)")
    dk.add_argument("--sort", choices=["cost", "played", "archetype"], default="cost", help="within each band: cheapest to move up first (default), most played first (meta coverage), or biggest archetype first")
    dk.add_argument("--ids", action=argparse.BooleanOptionalAction, default=True, help="show each deck's id, usable in `deck` (default on; --no-ids hides it)")
    dk.add_argument("--all", action="store_true", help="also list the decks I am far from")
    dk.add_argument("--limit", type=int, default=40, help="decks per group")
    dk.set_defaults(func=cmd_decks)
    sty = sub.add_parser("styles", help="what the decks do: colors, ratings (curve, pressure, interaction, advantage) and the plan (aggro / midrange / control)")
    sty.add_argument("--source", choices=["tournament", "online", "both"], default="both")
    sty.add_argument("--min-rate", type=float, default=MIN_PLAY_RATE, help="leave out decks played in less than this share of decks in every source (default 0.05)")
    sty.add_argument("--limit", type=int, default=20)
    sty.add_argument("--explain", action="store_true", help="also print the measured numbers behind the ratings")
    sty.add_argument("--ids", action=argparse.BooleanOptionalAction, default=True, help="show each deck's id (default on; --no-ids hides it)")
    sty.set_defaults(func=cmd_styles)
    sug = sub.add_parser("suggest", help="hypothetical decks: name a package, a plan and a color pair (`suggest barbatos aggro PB`); the shape comes from found decks, the cards from the ratings (no network)")
    sug.add_argument("words", nargs="*", help="package words, a plan (aggro / midrange / control) and a color pair (PB): any order")
    sug.add_argument("--package", help="the package by its anchor card, e.g. GD02-054 (instead of words)")
    sug.add_argument("--plan", choices=list(_PLAN_WORDS), help="the plan (or put it in the words)")
    sug.add_argument("--colors", help="the color pair, e.g. PB (or put it in the words); omit to build one deck per second color")
    sug.add_argument("--novelty", type=float, default=0.2, help="0 to 1: how many cards in no found list may be swapped in to reach the plan (default 0.2: about 2)")
    sug.add_argument("--prefer", choices=[p.value for p in Prefer], default="fit", help="fit (ratings decide), owned (cards I own win near-ties) or cost (cheaper cards win near-ties)")
    sug.add_argument("--pool", type=int, default=6, help="other cards shown per kind (0 to hide)")
    sug.add_argument("--alt-from", type=float, default=5.0, metavar="DOLLARS", help="alternatives under every card of at least this price (default 5.00)")
    sug.add_argument("--source", choices=["tournament", "online", "both"], default="both")
    sug.set_defaults(func=cmd_suggest)
    arch = sub.add_parser("archetypes", help="the meta as archetypes (most-played package + plan), with how close I am to each (no network)")
    arch.add_argument("--source", choices=["tournament", "online", "both"], default="both")
    arch.add_argument("--min-share", type=float, default=0.02, help="leave out archetypes played in less than this share of decks in every source (default 0.02)")
    arch.add_argument("--limit", type=int, default=20, help="archetypes to show")
    arch.add_argument("--members", type=int, default=3, help="decks shown under each archetype")
    arch.set_defaults(func=cmd_archetypes)
    buy = sub.add_parser("buy", help="what to buy to play more of an archetype (words of its name), cheapest path to Playable first (no network)")
    buy.add_argument("archetype", nargs="*", help="words of an archetype name, e.g. suletta (or use --package / --deck)")
    buy.add_argument("--package", action="append", metavar="PKG", help="every deck that contains this package, in any role: its anchor card (ST11-001) or words of its name as decks show it ('char aznable (b)'); repeatable")
    buy.add_argument("--deck", action="append", metavar="DECK", help="a specific deck: its id, nickname or words of its name; repeatable")
    buy.add_argument("--source", choices=["tournament", "online", "both"], default="both")
    buy.add_argument("--min-rate", type=float, default=MIN_PLAY_RATE, help="leave out fringe decks (default 0.05; see `decks`)")
    buy.add_argument("--steps", type=int, default=3, help="how many decks to plan, one after another (default 3)")
    buy.add_argument("--polish", action="store_true", help="after the Playable steps, also what takes those decks to Complete")
    buy.add_argument("--alt-from", type=float, default=5.0, metavar="DOLLARS", help="show same-job alternatives, and any you already own, for every card of at least this price (default 5.00; never skips the card, only premium cards are skipped)")
    buy.add_argument("--include-premium", action="store_true", help="plan premium cards ($10+) like any other (otherwise they are held back)")
    buy.add_argument("--export", nargs="?", const="", default=None, metavar="PATH", help="write TCGPlayer Mass Entry lines (default shared/data/gundam_collection/buy_<words>.txt)")
    buy.set_defaults(func=cmd_buy)
    nick = sub.add_parser("nickname", help="give a deck a nickname (by id), remove it, or list them")
    nick.add_argument("deck", nargs="?", help="the deck: its id, nickname, name or words of the name")
    nick.add_argument("name", nargs="?", help="the nickname")
    nick.add_argument("--remove", action="store_true", help="remove the deck's nickname")
    nick.add_argument("--list", action="store_true", help="list every nickname")
    nick.set_defaults(func=cmd_nickname)
    one_deck = sub.add_parser("deck", help="one deck: what is missing and what to get, in order (no network)")
    one_deck.add_argument("deck", help="words from the deck's name, e.g. 'Barbatos Tekkadan'")
    one_deck.add_argument("--source", choices=["tournament", "online", "both"], default="both")
    one_deck.add_argument("--min-rate", type=float, default=MIN_PLAY_RATE, help="decks counted when asking which other decks need a card (default 0.05)")
    one_deck.add_argument("--options", action="store_true", help="list the option cards too")
    one_deck.add_argument("--cards", action="store_true", help="just list every card the deck wants: my copies of each number, the copies needed, the price")
    one_deck.add_argument("--alternatives", action="store_true", help="list same-job alternatives (never counted) for every missing core and staple card, at any price")
    one_deck.add_argument("--alt-from", type=float, default=5.0, metavar="DOLLARS", help="under each pick of at least this price show same-job alternatives, and any you already own (default 5.00; as in `buy`)")
    one_deck.set_defaults(func=cmd_deck)
    val = sub.add_parser("value", help="what my collection is worth, by price band (no network)")
    val.add_argument("--bands", default=",".join(str(c / 100).rstrip("0").rstrip(".") for c in DEFAULT_THRESHOLDS), help="increasing dollar thresholds (default 0.5,1,5,10)")
    val.add_argument("--limit", type=int, help="show at most this many cards per band")
    val.add_argument("--bulk", action="store_true", help="also list the cards in the lowest band")
    val.set_defaults(func=cmd_value)
    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
