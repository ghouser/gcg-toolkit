"""Gundam card catalog CLI.

    .venv/bin/python -m tools.gundam_cards.cli sync               # sets, package lists, new printing pages, then reparse (network)
    .venv/bin/python -m tools.gundam_cards.cli sync --only sets   # just release dates and packages (network)
    .venv/bin/python -m tools.gundam_cards.cli refetch --card ST01-001   # re-pull pages we already have (--package GD05, --all)
    .venv/bin/python -m tools.gundam_cards.cli sets               # list sets with release dates (no network)
    .venv/bin/python -m tools.gundam_cards.cli reparse            # rebuild sets/cards/traits from saved pages (no network)
    .venv/bin/python -m tools.gundam_cards.cli show ST01-001      # print one card
    .venv/bin/python -m tools.gundam_cards.cli changes            # cards whose wording differs between printings (to read)
    .venv/bin/python -m tools.gundam_cards.cli sync-tcgplayer     # latest TCGPlayer market price per card from tcgcsv (network; once a day)
    .venv/bin/python -m tools.gundam_cards.cli reparse-tcgplayer  # rebuild prices.json from the saved tcgcsv files (no network)
    .venv/bin/python -m tools.gundam_cards.cli sync-restrictions  # banned / restricted cards from Bandai's announcement (network, one request)
    .venv/bin/python -m tools.gundam_cards.cli restrictions       # show the banned / restricted list
    .venv/bin/python -m tools.gundam_cards.cli price GD05-002 --explain   # a card's latest price and every product considered (no network)
    .venv/bin/python -m tools.gundam_cards.cli search --keyword blocker --trait "G Generation" --kind unit --color blue
    .venv/bin/python -m tools.gundam_cards.cli search --mentions-trait Marine --pilot --json   # all filters AND together
"""
from __future__ import annotations

import argparse
import collections
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime

from shared.basetypes import CardNumber, SetCode, Trait
from shared.fetch import Fetcher
from tools.gundam_cards.build import Issue, build_catalog
from tools.gundam_cards.changes import format_change, text_changes
from tools.gundam_cards.models import CardKind, CardsFile, Color, Keyword, Rarity
from tools.gundam_cards.printings import read_packages, refetch_printings, select_printings, sync_printings
from tools.gundam_cards.search import SearchQuery, format_table, search
from tools.gundam_cards.sets import SetsBuild, sets_from_raw, sync_sets
from tools.gundam_cards.models import PriceFile, RestrictionsFile
from tools.gundam_cards.restrictions import NEWS_URL, RestrictionsError, parse_restrictions, vanilla_cards
from tools.gundam_cards.store import (
    load_restrictions,
    write_restrictions,
    OUT_DIR,
    RAW_DIR,
    load_prices,
    load_sets,
    load_source_pages,
    raw_dump_stamps,
    read_raw_dump,
    release_dates,
    write_atomic,
    write_catalog,
    write_prices,
    write_sets,
)
from tools.gundam_cards.tcgcsv import (
    RawDump,
    TcgcsvError,
    TcgProduct,
    choose_prices,
    fetch_dump,
    fetch_updated,
    parse_dump,
    stamp_of,
    why_unpriced,
)


def _print_issues(issues: Sequence[Issue]) -> None:
    by_kind = collections.Counter(i.kind for i in issues)
    print(f"{len(issues)} issue(s): " + (", ".join(f"{k.value}={n}" for k, n in sorted(by_kind.items())) or "none"))
    for issue in issues:
        print(f"  [{issue.kind.value}] {issue.subject}: {issue.detail}")


def _save_sets(build: SetsBuild) -> None:
    write_sets(build.sets, datetime.now(tz=UTC))
    print(f"{len(build.sets)} sets -> {OUT_DIR / 'sets.json'}")
    _print_issues(build.issues)


def cmd_sync(args: argparse.Namespace) -> int:
    fetcher = Fetcher(RAW_DIR, min_interval_s=0.5)
    code = 0
    if args.only in (None, "sets"):
        build = sync_sets(fetcher)
        _save_sets(build)
        code = 1 if build.issues else 0
        if args.only == "sets":
            print(f"{fetcher.network_requests} network request(s)")
            return code
    packages = read_packages(RAW_DIR)
    if not packages:
        print("no cached package list; run `sync` (without --only printings) first", file=sys.stderr)
        return 2
    report = sync_printings(fetcher, RAW_DIR, packages, progress=lambda m: print(m, flush=True))
    print(
        f"{report.listed} printings: {report.already_cached} already cached, {report.fetched} fetched, "
        f"{len(report.failures)} failed; {fetcher.network_requests} network request(s)"
    )
    for printing_id, detail in report.failures:
        print(f"  FAILED {printing_id}: {detail}")
    return max(code, 1 if report.failures else 0, cmd_reparse(args))


def cmd_refetch(args: argparse.Namespace) -> int:
    packages = read_packages(RAW_DIR)
    if not packages:
        print("no cached package list; run `sync` first", file=sys.stderr)
        return 2
    try:
        ids = select_printings(RAW_DIR, packages, card=CardNumber(args.card) if args.card else None, package=args.package)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if not ids:
        print("nothing matches", file=sys.stderr)
        return 1
    print(f"refetching {len(ids)} printing page(s) from Bandai")
    fetcher = Fetcher(RAW_DIR, min_interval_s=0.5)
    report = refetch_printings(fetcher, RAW_DIR, ids, progress=lambda m: print(m, flush=True))
    print(f"{len(report.changed)} changed, {len(report.unchanged)} unchanged, {len(report.failures)} failed")
    for printing_id in report.changed[:50]:
        print(f"  changed: {printing_id}")
    for printing_id, detail in report.failures:
        print(f"  FAILED {printing_id}: {detail}")
    return max(1 if report.failures else 0, cmd_reparse(args) if report.changed else 0)


def cmd_sets(_: argparse.Namespace) -> int:
    sets = load_sets()
    if not sets:
        print("no sets.json yet; run `sync --only sets` first", file=sys.stderr)
        return 2
    today = date.today()
    print(f"{'code':7} {'kind':15} {'release':11} {'status':10} name")
    for s in sorted(sets, key=lambda s: (s.release_date is None, -(s.release_date.toordinal() if s.release_date else 0))):
        status = "unknown" if s.release_date is None else ("released" if s.released_on(today) else "upcoming")
        print(f"{s.code:7} {s.kind.value:15} {str(s.release_date or '-'):11} {status:10} {s.name}")
    return 0


def cmd_reparse(_: argparse.Namespace) -> int:
    issues: list[Issue] = []
    rebuilt = sets_from_raw(RAW_DIR)
    if rebuilt is not None:
        _save_sets(rebuilt)
        issues.extend(rebuilt.issues)
    sets = rebuilt.sets if rebuilt is not None else load_sets()
    dates = release_dates(sets)

    loaded = load_source_pages()
    result = build_catalog(loaded.pages, dates)
    write_catalog(result, datetime.now(tz=UTC))
    issues.extend([*loaded.issues, *result.issues])
    print(f"{len(loaded.pages)} pages -> {len(result.cards)} cards, {len(result.trait_vocabulary)} traits -> {OUT_DIR}")
    if not dates:
        print("note: no set release dates available yet (run `sync --only sets`), so wording recency uses the block only")
    _print_issues(issues)
    return 1 if any(i.kind.value == "parse_failure" for i in issues) else 0


def cmd_search(args: argparse.Namespace) -> int:
    path = OUT_DIR / "cards.json"
    if not path.is_file():
        print(f"{path} not found; run `reparse` first", file=sys.stderr)
        return 2
    query = SearchQuery(
        name=args.name,
        text=args.text,
        kinds=frozenset(CardKind(k) for k in args.kind),
        colors=frozenset(Color(c) for c in args.color),
        level=args.level,
        cost=args.cost,
        traits=frozenset(Trait(t) for t in args.trait),
        mentions=frozenset(Trait(t) for t in args.mentions_trait),
        keywords=frozenset(Keyword(k) for k in args.keyword),
        set_code=SetCode(args.set) if args.set else None,
        rarity=Rarity(args.rarity) if args.rarity else None,
        alt_art=args.alt_art,
        pilot=args.pilot,
    )
    found = search(CardsFile.model_validate_json(path.read_text(encoding="utf-8")).data, query)
    shown = found[: args.limit] if args.limit else found
    if args.json:
        print("[" + ",".join(card.model_dump_json() for card in shown) + "]")
    else:
        print(format_table(shown))
        print(f"{len(found)} card(s)" + (f", showing {len(shown)}" if len(shown) < len(found) else ""), file=sys.stderr)
    return 0


def cmd_changes(args: argparse.Namespace) -> int:
    path = OUT_DIR / "cards.json"
    if not path.is_file():
        print(f"{path} not found; run `reparse` first", file=sys.stderr)
        return 2
    cards = CardsFile.model_validate_json(path.read_text(encoding="utf-8")).data
    changes = [c for c in text_changes(cards) if args.card is None or c.number == args.card]
    for change in changes[: args.limit] if args.limit else changes:
        print(format_change(change) + "\n")
    print(f"{len(changes)} older wording(s) on {len({c.number for c in changes})} card(s)", file=sys.stderr)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = OUT_DIR / "cards.json"
    if not path.is_file():
        print(f"{path} not found; run `reparse` first", file=sys.stderr)
        return 2
    cards = CardsFile.model_validate_json(path.read_text(encoding="utf-8"))
    wanted = CardNumber(args.card)
    for card in cards.data:
        if card.number == wanted:
            print(card.model_dump_json(indent=2))
            return 0
    print(f"no such card: {wanted}", file=sys.stderr)
    return 1


# ---- TCGPlayer prices (tcgcsv) --------------------------------------------------------------------------------------
def _catalog() -> dict[CardNumber, str] | None:
    """Card number -> name for the whole catalog, or None when cards.json is missing."""
    path = OUT_DIR / "cards.json"
    if not path.is_file():
        print(f"{path} not found; run `sync` and `reparse` first", file=sys.stderr)
        return None
    return {c.number: c.name for c in CardsFile.model_validate_json(path.read_text(encoding="utf-8")).data}


def _build_prices(dump: RawDump, pulled_at: datetime, names: dict[CardNumber, str]) -> int:
    products, parse_issues = parse_dump(dump)
    prices, unpriced, catalog_issues = choose_prices(products, names, pulled_at)
    path = write_prices(PriceFile(generated_at=pulled_at, source_updated_at=dump.source_updated_at, data=prices))
    sealed = sum(1 for p in products if p.card_number is None)
    alt = sum(1 for p in products if p.alt_art_level > 0)
    promo = sum(1 for p in products if p.promo)
    print(f"tcgcsv dump of {dump.source_updated_at:%Y-%m-%d %H:%M} UTC, pulled {pulled_at:%Y-%m-%d %H:%M} UTC: {len(products)} products "
          f"({sealed} without a card number, {alt} alt arts, {promo} in promo groups) -> {path}")
    print(f"priced {len(prices)} of {len(names)} catalog cards")
    if unpriced:
        print(f"{len(unpriced)} catalog cards have no price:")
        for number in unpriced[:15]:
            print(f"  {number} {names[number]}: {why_unpriced(number, products)}")
        if len(unpriced) > 15:
            print(f"  ... and {len(unpriced) - 15} more")
    issues = [*parse_issues, *catalog_issues]
    by_kind = collections.Counter(i.kind for i in issues)
    print(f"{len(issues)} issue(s): " + (", ".join(f"{k.value}={n}" for k, n in sorted(by_kind.items())) or "none"))
    for kind in by_kind:
        for issue in [i for i in issues if i.kind is kind][:5]:
            print(f"  [{kind.value}] {issue.detail}")
    return 0


def cmd_sync_restrictions(args: argparse.Namespace) -> int:
    """Banned / restricted cards from Bandai's announcement page (one request, cached; give the new URL when Bandai publishes a new list)."""
    path = OUT_DIR / "cards.json"
    if not path.is_file():
        print(f"{path} not found; run `sync` and `reparse` first", file=sys.stderr)
        return 2
    catalog = {c.number: c for c in CardsFile.model_validate_json(path.read_text(encoding="utf-8")).data}
    fetcher = Fetcher(RAW_DIR / "restrictions", min_interval_s=0.5)
    key = args.url.rstrip("/").rsplit("/", 1)[-1]
    html = fetcher.get_text(args.url, cache_key=key, force=args.force).text
    try:
        found, published = parse_restrictions(html)
    except RestrictionsError as e:
        print(f"could not read the page: {e}", file=sys.stderr)
        return 1
    problems = [str(n) for n in (*found.banned, *[x.card for x in found.limited], *[c for p in found.banned_pairs for c in (p.a, p.b)], *found.vanilla_group) if n not in catalog]
    derived = vanilla_cards(catalog)
    listed = set(found.vanilla_group)
    write_restrictions(RestrictionsFile(generated_at=datetime.now(UTC).replace(microsecond=0), source_url=args.url, published=published, data=found))
    print(f"{fetcher.network_requests} request(s); list of {published}: {len(found.banned)} banned, {len(found.limited)} restricted, {len(found.banned_pairs)} banned pairs, vanilla group of {len(listed)}")
    if problems:
        print(f"  warning: not in the catalog: {', '.join(problems)}", file=sys.stderr)
    if derived != listed:
        print(f"  warning: the description matches {len(derived)} catalog cards but the page lists {len(listed)}: only on the page {sorted(listed - derived)}, only in the catalog {sorted(derived - listed)}", file=sys.stderr)
    else:
        print(f"  the vanilla description ({found.vanilla_description}) matches exactly the {len(listed)} cards the page lists")
    return 0


def cmd_restrictions(args: argparse.Namespace) -> int:
    file = load_restrictions()
    if file is None:
        print("no restrictions.json yet; run `sync-restrictions` first", file=sys.stderr)
        return 2
    names = _catalog() or {}

    def nm(n: CardNumber) -> str:
        return f"{n} {names.get(n, '')}".strip()

    r = file.data
    print(f"== banned / restricted cards, list of {file.published} ({file.source_url}) ==")
    print("   banned (no copies): " + ", ".join(nm(n) for n in r.banned))
    for lim in r.limited:
        print(f"   restricted ({lim.copies} copies at most): {nm(lim.card)}")
    for pair in r.banned_pairs:
        print(f"   banned pair: {nm(pair.a)}  +  {nm(pair.b)}")
    print(f"   vanilla group ({r.vanilla_description}): any two different ones are a banned pair; at most {r.group_max_copies} copies of one: {len(r.vanilla_group)} cards")
    return 0


def cmd_sync_tcgplayer(args: argparse.Namespace) -> int:
    names = _catalog()
    if names is None:
        return 2
    fetcher = Fetcher(RAW_DIR / "tcgcsv", min_interval_s=0.5)
    try:
        updated = fetch_updated(fetcher)
        stored = load_prices()
        if stored is not None and stored.source_updated_at == updated and not args.force:
            print(f"up to date: tcgcsv last updated {updated:%Y-%m-%d %H:%M} UTC and prices.json already has it ({fetcher.network_requests} request)")
            return 0
        dump = fetch_dump(fetcher, updated, force=args.force, progress=lambda m: print(f"  {m}", flush=True))
        pulled_at = datetime.now(UTC).replace(microsecond=0)
        write_atomic(RAW_DIR / "tcgcsv" / stamp_of(updated) / "pulled-at.txt", pulled_at.isoformat() + "\n")
        print(f"{fetcher.network_requests} request(s)")
        return _build_prices(dump, pulled_at, names)
    except TcgcsvError as e:
        print(f"tcgcsv: {e}", file=sys.stderr)
        return 1


def _pulled_at(stamp: str) -> datetime:
    marker = RAW_DIR / "tcgcsv" / stamp / "pulled-at.txt"
    if marker.is_file():
        return datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)  # a dump saved before this marker existed: use the dump's own time


def cmd_reparse_tcgplayer(_: argparse.Namespace) -> int:
    names = _catalog()
    if names is None:
        return 2
    stamps = raw_dump_stamps()
    if not stamps:
        print("no saved tcgcsv dump; run `sync-tcgplayer` first", file=sys.stderr)
        return 2
    return _build_prices(read_raw_dump(stamps[-1]), _pulled_at(stamps[-1]), names)


def cmd_price(args: argparse.Namespace) -> int:
    names = _catalog()
    if names is None:
        return 2
    number = CardNumber(args.card)
    if number not in names:
        print(f"no such card: {number}", file=sys.stderr)
        return 1
    stored = load_prices()
    row = next((p for p in stored.data if p.card_number == number), None) if stored else None
    products: tuple[TcgProduct, ...] = ()
    stamps = raw_dump_stamps()
    if stamps and (args.explain or row is None):
        products, _ = parse_dump(read_raw_dump(stamps[-1]))
    if row is not None:
        print(f"{number} {names[number]}: ${row.price_cents / 100:.2f}  (TCGPlayer market price, product {row.product_id}, pulled {row.fetched_at:%Y-%m-%d %H:%M} UTC)")
    elif stored is None:
        print(f"{number} {names[number]}: no prices yet; run `sync-tcgplayer` first")
    else:
        print(f"{number} {names[number]}: no price ({why_unpriced(number, products) if products else 'no saved dump to explain it'})")
    if args.explain:
        for p in (p for p in products if p.card_number == number):
            verdict = "buyable" if p.buyable else ("alt art" if p.alt_art_level else "promo group" if p.promo else "no price")
            price = f"${p.price_cents / 100:.2f}" if p.price_cents is not None else "-"
            print(f"    product {p.product_id:>7} {p.group:8} {p.name:34} {p.rarity_raw or '-':14} {price:>8}  {verdict}")
    return 0 if row is not None else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="fetch data from Bandai (network), then rebuild the catalog files")
    sync.add_argument("--only", choices=["sets", "printings"], help="sync just one part (default: everything)")
    sync.set_defaults(func=cmd_sync)
    refetch = sub.add_parser("refetch", help="re-pull cached pages from Bandai (network) when data looks wrong, then rebuild")
    target = refetch.add_mutually_exclusive_group(required=True)
    target.add_argument("--card", help="all printings of one card, e.g. ST01-001")
    target.add_argument("--package", help="one package, by Bandai package id (616105) or set code (GD05)")
    target.add_argument("--all", action="store_true", help="every listed printing (about 2,000 requests)")
    refetch.set_defaults(func=cmd_refetch)
    sub.add_parser("sets", help="list sets with release dates (no network)").set_defaults(func=cmd_sets)
    sub.add_parser("reparse", help="rebuild sets/cards/traits files from the saved raw pages (no network)").set_defaults(
        func=cmd_reparse
    )
    search_p = sub.add_parser("search", help="filter the local catalog (no network); all filters AND together")
    search_p.add_argument("--name", help="substring of the card name")
    search_p.add_argument("--text", help="substring of the current card text")
    search_p.add_argument("--kind", action="append", default=[], choices=[k.value for k in CardKind], help="repeatable: any of")
    search_p.add_argument("--color", action="append", default=[], choices=[c.value for c in Color], help="repeatable: any of")
    search_p.add_argument("--level", type=int)
    search_p.add_argument("--cost", type=int)
    search_p.add_argument("--trait", action="append", default=[], help="the card has this trait (repeatable: all of)")
    search_p.add_argument("--mentions-trait", action="append", default=[], help="the text mentions this trait (repeatable: all of)")
    search_p.add_argument("--keyword", action="append", default=[], choices=[k.value for k in Keyword], help="repeatable: all of")
    search_p.add_argument("--set", help="some printing is from this set code, e.g. GD05")
    search_p.add_argument("--rarity", choices=[r.value for r in Rarity], help="some printing has this rarity")
    search_p.add_argument("--alt-art", action=argparse.BooleanOptionalAction, default=None, help="some printing is / is not an alt art")
    search_p.add_argument("--pilot", action=argparse.BooleanOptionalAction, default=None, help="Pilot cards and Commands with a pilot effect")
    search_p.add_argument("--limit", type=int, help="show at most this many cards")
    search_p.add_argument("--json", action="store_true", help="print full card JSON instead of a table")
    search_p.set_defaults(func=cmd_search)
    changes = sub.add_parser("changes", help="list cards whose wording differs between printings, as word diffs (no network)")
    changes.add_argument("--card", help="only this card number")
    changes.add_argument("--limit", type=int, help="show at most this many")
    changes.set_defaults(func=cmd_changes)
    show = sub.add_parser("show", help="print one card from cards.json")
    show.add_argument("card", help="card number, e.g. ST01-001")
    show.set_defaults(func=cmd_show)
    tcg = sub.add_parser("sync-tcgplayer", help="latest TCGPlayer market price per card, from tcgcsv (network; skips if tcgcsv has nothing new)")
    tcg.add_argument("--force", action="store_true", help="pull again even if tcgcsv has nothing new")
    tcg.set_defaults(func=cmd_sync_tcgplayer)
    rs = sub.add_parser("sync-restrictions", help="banned / restricted cards from Bandai's announcement page (network, one request)")
    rs.add_argument("--url", default=NEWS_URL, help=f"the announcement page (default {NEWS_URL})")
    rs.add_argument("--force", action="store_true", help="fetch again even if the page is cached")
    rs.set_defaults(func=cmd_sync_restrictions)
    sub.add_parser("restrictions", help="show the banned / restricted list (no network)").set_defaults(func=cmd_restrictions)
    sub.add_parser("reparse-tcgplayer", help="rebuild prices.json from the saved tcgcsv files (no network)").set_defaults(func=cmd_reparse_tcgplayer)
    price = sub.add_parser("price", help="a card's latest TCGPlayer price (no network)")
    price.add_argument("card", help="card number, e.g. GD05-002")
    price.add_argument("--explain", action="store_true", help="list every TCGPlayer product for the card and whether it is buyable")
    price.set_defaults(func=cmd_price)
    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
