"""Refresh the per-printing TCGPlayer prices from tcgcsv, all or nothing. See `.claude/feature-design/refresh-prices.md`.

Three phases, like `refresh.py`: fetch (only fills the git-ignored raw cache), plan (matching, the guard and the report, pure), write
(one atomic per-printing snapshot). A refused, failed or interrupted run leaves the dataset byte-identical and never touches a tracked file.

    .venv/bin/python -m tools.gundam_cards.cli refresh-prices [--dry-run] [--force] [--allow-anomaly]
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.basetypes import CardNumber, PrintingId, ProductId, SetCode
from shared.dataset import NoData, write_atomic
from shared.fetch import FetchError, Response, TextFetcher
from tools.gundam_cards.models import CardModel, PrintingPrice, PrintingPriceFile
from tools.gundam_cards.store import (
    load_catalog_or_fail,
    load_printing_prices,
    load_sets,
    raw_dump_stamps,
    read_raw_dump,
    write_printing_prices,
)
from tools.gundam_cards.tcgcsv import RawDump, TcgcsvError, TcgProduct, fetch_dump, fetch_updated, parse_dump, stamp_of

MATCH_DROP_SHARE = 0.05  # refuse when more than 1 printing in 20 of the newest snapshot is no longer matched
REQUEST_DELAY_S = 1.0  # between tcgcsv requests (tcgcsv asks for 0.1 s; the fetcher never goes under 0.5 s)
PULL_INTERVAL = timedelta(hours=24)  # at most one pull in this time, unless forced
BIGGEST_MOVES = 10  # price moves listed in the report
BETA_SUFFIX = "_b"  # a tcgcsv group abbreviation ending so is the Edition Beta printing of that set
BETA_SET = SetCode("BETA")
MARKER = "pulled-at.txt"  # in each saved dump's folder: when we pulled it


@dataclass(frozen=True)
class Unmatched:
    """A product that took no part in the snapshot, and why."""

    product_id: ProductId
    name: str
    group: str
    number: str  # the product's Number, "-" when it has none
    reason: str

    def __str__(self) -> str:
        return f"{self.group} {self.number} {self.name}: {self.reason}"


@dataclass(frozen=True)
class Matched:
    rows: tuple[PrintingPrice, ...]  # sorted by printing id
    unmatched: tuple[Unmatched, ...]
    sealed: int  # products with no card number: counted, not reported


@dataclass(frozen=True)
class Move:
    printing_id: PrintingId
    old_cents: int
    new_cents: int


@dataclass(frozen=True)
class PriceReport:
    dry_run: bool
    complete: bool = True
    failure: str | None = None
    skipped: str | None = None  # why nothing was fetched or written (pulled within 24 hours)
    source_updated_at: datetime | None = None
    products: int = 0
    sealed: int = 0
    matched: int = 0
    unmatched: tuple[Unmatched, ...] = ()
    new: int = 0  # matched printings the newest snapshot did not have
    changed: int = 0  # matched printings whose price differs from the newest snapshot's
    moves: tuple[Move, ...] = ()
    previous: int = 0  # printings in the newest snapshot (0: none yet)
    dropped: int = 0  # printings of the newest snapshot not matched now
    missing_groups: tuple[str, ...] = ()  # groups that gave the newest snapshot rows and are not in this pull
    guard_trips: bool = False
    refused: bool = False
    written: bool = False
    stored: bool = False  # a snapshot was added (False on a run that adds nothing: same day or same prices)
    requests: int = 0


# ---- plan (pure) --------------------------------------------------------------------------------------------------------
def group_set(group: str, set_codes: Collection[SetCode]) -> SetCode | None:
    """The set a tcgcsv group stands for: its abbreviation when that is a known set code; an abbreviation ending `_b` is Edition Beta
    (`BETA`); otherwise none (the group is reported, never guessed)."""
    if group.endswith(BETA_SUFFIX):
        return BETA_SET
    code = SetCode(group) if SetCode.pattern.fullmatch(group) else None
    return code if code is not None and code in set_codes else None


def match_products(
    products: Sequence[TcgProduct], catalog: Collection[CardModel], set_codes: Collection[SetCode], fetched_at: datetime
) -> Matched:
    """Match every priced card product to one printing by set, card number and art tier (a printing's tier is its `alt_art_level`, and
    link art has one, so it matches as an alt art). Anything not matched exactly once, both ways, is reported and takes no part."""
    printings = {c.number: c.printings for c in catalog}
    unmatched: list[Unmatched] = []
    claims: dict[PrintingId, list[TcgProduct]] = defaultdict(list)
    sealed = 0

    def refuse(p: TcgProduct, reason: str) -> None:
        unmatched.append(Unmatched(p.product_id, p.name, p.group, str(p.card_number), reason))

    for p in products:
        if p.card_number is None:
            sealed += 1
        elif p.promo:
            refuse(p, "promo group")
        elif p.card_number not in printings:
            refuse(p, "card number is not in the catalog")
        elif p.rarity_raw is None or p.rarity is None:
            refuse(p, f"unrecognized rarity {p.rarity_raw!r}")
        elif (code := group_set(p.group, set_codes)) is None:
            refuse(p, "group maps to no set")
        elif p.unknown_price_kind is not None:
            refuse(p, f"unrecognized price kind {p.unknown_price_kind!r}")
        elif p.price_cents is None:
            refuse(p, "no market price")
        else:
            found = [x for x in printings[p.card_number] if x.set_code == code and x.alt_art_level == p.alt_art_level]
            if len(found) == 1:
                claims[found[0].id].append(p)
            else:
                refuse(p, f"{len(found)} printings in set {code} with art tier {p.alt_art_level}, not exactly one")
    rows: list[PrintingPrice] = []
    levels = {x.id: x.alt_art_level for card in catalog for x in card.printings}
    for printing_id, claimed in sorted(claims.items()):
        if len(claimed) > 1:
            for p in claimed:
                refuse(p, f"{len(claimed)} products match printing {printing_id}")
            continue
        p = claimed[0]
        rows.append(PrintingPrice(
            printing_id=printing_id, price_cents=p.price_cents or 0, product_id=p.product_id, name=p.name, set_code=p.group,
            alt_art_level=levels[printing_id], fetched_at=fetched_at,
        ))  # fmt: skip
    return Matched(tuple(rows), tuple(sorted(unmatched, key=str)), sealed)


def product_verdicts(matched: Matched) -> dict[ProductId, str]:
    """What the matching did with each product, in words: the printing it prices, or why it took no part."""
    verdicts = {r.product_id: f"matched to {r.printing_id} (${r.price_cents / 100:.2f})" for r in matched.rows}
    verdicts.update({u.product_id: u.reason for u in matched.unmatched})
    return verdicts


def why_unpriced(number: CardNumber, products: Sequence[TcgProduct], matched: Matched) -> str:
    """Why a card has no price, in words, from what the matching did with its products (for `price`)."""
    ids = {p.product_id for p in products if p.card_number == number}
    if not ids:
        return "no TCGPlayer product with this card number"
    if any(r.product_id in ids for r in matched.rows):
        return "only alt-art printings matched (never bought)"
    reasons = sorted({u.reason for u in matched.unmatched if u.product_id in ids})
    return "no product matched a printing: " + "; ".join(reasons)


def plan_report(
    dump_products: Sequence[TcgProduct], matched: Matched, groups: Collection[str], previous: PrintingPriceFile | None, *,
    allow_anomaly: bool, dry_run: bool, source_updated_at: datetime,
) -> PriceReport:
    """The counts, the biggest moves and the guard's verdict, against the newest snapshot."""
    old = {r.printing_id: r for r in previous.data} if previous else {}
    now = {r.printing_id: r for r in matched.rows}
    moves = sorted(
        (Move(i, old[i].price_cents, r.price_cents) for i, r in now.items() if i in old and old[i].price_cents != r.price_cents),
        key=lambda m: (-abs(m.new_cents - m.old_cents), str(m.printing_id)),
    )
    dropped = sum(1 for i in old if i not in now)
    missing = tuple(sorted({r.set_code for r in old.values()} - set(groups)))
    trips = bool(old) and (dropped / len(old) > MATCH_DROP_SHARE or bool(missing))
    return PriceReport(
        dry_run=dry_run, source_updated_at=source_updated_at, products=len(dump_products), sealed=matched.sealed,
        matched=len(matched.rows), unmatched=matched.unmatched, new=sum(1 for i in now if i not in old), changed=len(moves),
        moves=tuple(moves[:BIGGEST_MOVES]), previous=len(old), dropped=dropped, missing_groups=missing,
        guard_trips=trips, refused=trips and not allow_anomaly and not dry_run,
    )  # fmt: skip


class _Counting:
    """A fetcher that counts the requests that reached the network (an answer from the cache is not one), whatever fetcher it wraps."""

    def __init__(self, inner: TextFetcher) -> None:
        self.inner = inner
        self.requests = 0

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response:
        response = self.inner.get_text(url, cache_key=cache_key, force=force)
        self.requests += 0 if response.from_cache else 1
        return response


# ---- fetch and write (the shell) ---------------------------------------------------------------------------------------
def pull_time(stamp: str, raw_dir: Path) -> datetime | None:
    """When a saved dump was pulled (its marker), or None when it has none (a dry run saved it, or it is older than the marker)."""
    marker = raw_dir / "tcgcsv" / stamp / MARKER
    return datetime.fromisoformat(marker.read_text(encoding="utf-8").strip()) if marker.is_file() else None


def saved_dump(stamp: str, raw_dir: Path) -> RawDump | None:
    """A saved dump read back, or None when it is not there or only partly saved (an interrupted pull: it is fetched again)."""
    try:
        return read_raw_dump(stamp, raw_dir)
    except NoData:
        return None


def readable(dump: RawDump) -> bool:
    """Whether a saved dump parses (a cached answer that was garbled is fetched again, not used for ever)."""
    try:
        parse_dump(dump)
    except (TcgcsvError, ValueError):
        return False
    return True


def last_pull(raw_dir: Path) -> tuple[datetime, str] | None:
    """When, and which dump, the newest recorded pull was (by its marker), or None when nothing was pulled."""
    pulls = [(t, s) for s in raw_dump_stamps(raw_dir) if (t := pull_time(s, raw_dir)) is not None]
    return max(pulls) if pulls else None


def refresh_prices(
    fetcher: TextFetcher,
    raw_dir: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    allow_anomaly: bool = False,
    now: datetime | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> PriceReport:
    """Pull tcgcsv (at most once in 24 hours), match it to the printings, check the result and add one per-printing snapshot.
    `raw_dir` is the tool's raw folder (the dumps are under `tcgcsv/`). Raises `NoData` when there is no catalog."""
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    counted = _Counting(fetcher)
    catalog = load_catalog_or_fail().data  # before any request: nothing to match against means nothing to fetch
    set_codes = {s.code for s in load_sets()}
    previous = load_printing_prices()
    last = last_pull(raw_dir)
    recent = last is not None and now - last[0] < PULL_INTERVAL and not force
    from_saved = recent and (dry_run or allow_anomaly)  # inside 24 hours only a dry run or an override works, from the saved dump
    if last is not None and recent and not from_saved:
        return PriceReport(dry_run=False, skipped=f"the last pull was {last[0]:%Y-%m-%d %H:%M} UTC, within 24 hours: nothing fetched, nothing "
                           "written (--allow-anomaly writes it from the saved dump if the guard refused it; --force pulls again)")
    dump: RawDump | None = None
    if last is not None and from_saved:  # inside 24 hours: the saved dump or nothing, never a download (that takes --force)
        dump = saved_dump(last[1], raw_dir)
        if dump is None or not readable(dump):
            return PriceReport(dry_run=dry_run, complete=False, failure=f"the saved dump {last[1]} is unreadable or incomplete, and the last pull was within "
                               "24 hours: nothing fetched, nothing written (rerun with --force to pull again)")
    try:
        if dump is None:
            updated = fetch_updated(counted)
            cached = None if force else saved_dump(stamp_of(updated), raw_dir)
            if cached is not None and readable(cached):
                dump = cached
            else:  # an unreadable saved dump is pulled again whole; a partly saved one resumes from what is cached
                dump = fetch_dump(counted, updated, force=force or cached is not None, progress=progress)
        products, _ = parse_dump(dump)
    except (TcgcsvError, FetchError, ValueError) as e:
        return PriceReport(dry_run=dry_run, complete=False, failure=f"tcgcsv: {e}")
    stamp = stamp_of(dump.source_updated_at)
    pulled = pull_time(stamp, raw_dir) or now
    if not dry_run and pull_time(stamp, raw_dir) is None:
        write_atomic(raw_dir / "tcgcsv" / stamp / MARKER, pulled.isoformat() + "\n")  # a pull happened, whatever the plan says
    matched = match_products(products, catalog, set_codes, pulled)
    groups = {p.group for p in products}
    report = replace(
        plan_report(products, matched, groups, previous, allow_anomaly=allow_anomaly, dry_run=dry_run, source_updated_at=dump.source_updated_at),
        requests=counted.requests,
    )
    if dry_run or report.refused:
        return report
    stored = write_printing_prices(PrintingPriceFile(generated_at=pulled, source_updated_at=dump.source_updated_at, data=matched.rows))
    return replace(report, written=True, stored=stored is not None)


def _usd(cents: int) -> str:
    return f"${cents / 100:.2f}"


def format_report(report: PriceReport) -> list[str]:
    if report.skipped:
        return [report.skipped]
    if not report.complete:
        return [f"incomplete, nothing written: {report.failure}"]
    mode = "dry run" if report.dry_run else "real run"
    lines = [
        f"{mode}: tcgcsv dump of {report.source_updated_at:%Y-%m-%d %H:%M} UTC, {report.requests} request(s): {report.products} products "
        f"({report.sealed} without a card number)",
        f"{report.matched} printing(s) matched, {len(report.unmatched)} product(s) unmatched or ambiguous; against the newest snapshot "
        f"({report.previous} printings): {report.new} new, {report.changed} changed, {report.dropped} no longer matched",
        *(f"  unmatched {u}" for u in report.unmatched),
        *(f"  move {m.printing_id}: {_usd(m.old_cents)} -> {_usd(m.new_cents)}" for m in report.moves),
    ]
    if report.guard_trips:
        why = [f"{report.dropped} of {report.previous} printings no longer matched (limit {MATCH_DROP_SHARE:.0%})"] if (
            report.previous and report.dropped / report.previous > MATCH_DROP_SHARE) else []
        if report.missing_groups:
            why.append("groups missing from the pull: " + ", ".join(report.missing_groups))
        lines.append("guard: " + ("refused" if report.refused else "would refuse" if report.dry_run else "overridden") + ": " + "; ".join(why))
    else:
        lines.append("guard: ok")
    if report.refused:
        lines.append("refused by the guard, nothing written (rerun with --allow-anomaly to write it from the saved dump, with no new request)")
    elif report.dry_run:
        lines.append("dry run: nothing written")
    elif report.stored:
        lines.append("snapshot written")
    else:
        lines.append("no new snapshot (that UTC day is stored already, or the prices are unchanged)")
    return lines

