"""release-event-promo: a printing whose "Where to get it" names a release event, a pre-release event or event-participation items
is PROMO whatever bracketed code the text mentions (AC-1); a card's own set skips such printings (AC-2); PROMO is a known set and
sets.json is untouched (AC-3); the price matching then matches the booster printing, not the event one (AC-4).
Fixtures are invented, with the wordings of the spec's examples. Expected values are worked out by hand."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from shared.basetypes import CardNumber, PackageId, PrintingId, ProductId, SetCode, Trait
from tools.gundam_cards import cli
from tools.gundam_cards.build import SourcePage, build_card
from tools.gundam_cards.events import names_release_event
from tools.gundam_cards.export import CatalogExport, build_export, printing_prices
from tools.gundam_cards.models import CardPrice, CardRecord, CardsFile, CardSet, Printing, Rarity, SetKind, SetsFile
from tools.gundam_cards.price_refresh import match_products
from tools.gundam_cards.store import catalog_export_path, load_catalog, pages_folder, tracked_folder
from tools.gundam_cards.tcgcsv import TcgProduct
from tools.gundam_cards.tests.test_catalog_refresh import detail
from tools.gundam_cards.tests.test_export import CATALOG_AT, printing
from tools.gundam_cards.tests.test_package_set_codes import PACKAGE_CODES, Bandai, reviewed_sets
from tools.gundam_packages.tests.helpers import unit

Page = Callable[[str], SourcePage]
TRAITS = frozenset({Trait("Earth Federation"), Trait("White Base Team")})
GD05_EVENT = "Booster Pack Freedom Ascension [GD05] Release Event Commemorative Items for Participants"
ST07_EVENT = "Starter Deck [ST07]/[ST08] Release Event"
PRE_RELEASE = "Booster Pack Invented Dawn [GD09] Pre-Release Event"  # a wording never seen in the real data
BOOSTER = "Booster Pack Freedom Ascension [GD05]"
GD05_PACKAGE = "616105"


def built(page: Page, where: str, rarity: str = "R", package: str = GD05_PACKAGE) -> Printing:
    """ST01-001's page with its text, rarity and package replaced, built with a package map where GD05 is known."""
    p = page("ST01-001")
    source = replace(p, raw=replace(p.raw, rarity=rarity, fields=dict(p.raw.fields, **{"Where to get it": where})),
                     package_ids=(PackageId(package),))  # fmt: skip
    codes = {**PACKAGE_CODES, PackageId(GD05_PACKAGE): SetCode("GD05")}
    result = build_card([source], TRAITS, {}, codes)
    assert result.issues == ()
    return result.card.printings[0]


# ---- AC-1: the wording ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("where", [
    GD05_EVENT, ST07_EVENT, PRE_RELEASE,
    "Booster Pack Invented Dawn [GD09] Prerelease Event", "Booster Pack Invented Dawn [GD09] Pre Release Events",
    "Booster Pack Invented Dawn [GD09] PRE-RELEASE EVENT", "Booster Pack Invented Dawn [GD09] release event",
    "Booster Pack Invented Dawn [GD09] Event Participation Items", "Booster Pack Invented Dawn [GD09] Event-Participation Prize",
    "Commemorative Items for Participants [GD09]",
])  # fmt: skip
def test_an_event_wording_gives_promo_whatever_set_the_text_mentions(page: Page, where: str) -> None:
    assert built(page, where).set_code == "PROMO"


def test_the_event_wording_wins_over_an_ordinary_booster_package_and_a_passing_mention(page: Page) -> None:
    assert built(page, GD05_EVENT, package=GD05_PACKAGE).set_code == "PROMO"  # the package would say GD05
    assert built(page, "Booster Pack Freedom Ascension [GD05] (also given at the Release Event)").set_code == "PROMO"


@pytest.mark.parametrize(("where", "rarity", "package", "expected"), [
    (BOOSTER, "R", GD05_PACKAGE, "GD05"),
    ("Starter Deck [ST07]", "R", GD05_PACKAGE, "ST07"),
    ("Edition Beta", "R", "616000", "BETA"),
    ("-", "R", "616102", "GD02"),
    ("Deck Build Box [SC01]", "R", GD05_PACKAGE, "SC01"),
    (BOOSTER, "R +", GD05_PACKAGE, "GD05"),  # an alt-art printing of a booster
    ("Regional Event [GD05]", "R", GD05_PACKAGE, "GD05"),  # a bare "event" is not a release event
    ("Tournament participants [GD05]", "R", GD05_PACKAGE, "GD05"),
    ("Store tournament prize", "R", "616901", "PROMO"),  # already PROMO through its package
])  # fmt: skip
def test_a_text_naming_no_event_keeps_its_set_code(
    page: Page, where: str, rarity: str, package: str, expected: str
) -> None:
    assert built(page, where, rarity, package).set_code == expected


def test_the_wording_rule_is_a_pure_text_test() -> None:
    assert names_release_event(GD05_EVENT) and names_release_event(ST07_EVENT) and names_release_event(PRE_RELEASE)
    assert not names_release_event(BOOSTER) and not names_release_event("") and not names_release_event("-")


# ---- AC-1, AC-3: after reparse and refresh, in cards.json and the export ----------------------------------------------------
EVENT_LISTED = {
    "616101": (
        "Newtype Rising [GD01]",
        {
            "GD01-001": "Newtype Rising [GD01]",
            "GD01-001_p1": "Newtype Rising [GD01] Release Event Commemorative Items for Participants",
            "GD01-002_p1": "Starter Deck [GD01]/[GD02] Pre-Release Event",  # an event printing alone (no base page: the card is event-only)
            "GD01-003": "Newtype Rising [GD01]",
        },
    ),
}
EXPECTED_PRINTING_CODES = {"GD01-001": "GD01", "GD01-001_p1": "PROMO", "GD01-002_p1": "PROMO", "GD01-003": "GD01"}
EXPECTED_CARD_CODES = {"GD01-001": "GD01", "GD01-002": "PROMO", "GD01-003": "GD01"}


@pytest.fixture
def tracked() -> bytes:
    path = tracked_folder() / "sets.json"
    path.write_text(SetsFile(generated_at=datetime(2026, 11, 1, tzinfo=UTC), data=reviewed_sets()).model_dump_json(indent=1) + "\n",
                    encoding="utf-8")  # fmt: skip
    return path.read_bytes()


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Bandai:
    bandai = Bandai(pages_folder(), {pid: (label, list(items)) for pid, (label, items) in EVENT_LISTED.items()},
                    details={i: detail(i, where=where) for _, items in EVENT_LISTED.values() for i, where in items.items()})  # fmt: skip
    monkeypatch.setattr(cli, "Fetcher", lambda *_, **__: bandai)
    monkeypatch.setattr(cli, "refresh_fetcher", lambda: bandai)
    return bandai


@pytest.mark.parametrize("how", ["reparse", "refresh"])
def test_a_rebuild_gives_event_printings_promo_in_the_catalog_and_the_export_and_leaves_sets_json_alone(
    tracked: bytes, site: Bandai, how: str
) -> None:
    if how == "reparse":
        assert cli.main(["sync"]) == 0
        assert cli.main(["reparse"]) == 0
    else:
        assert cli.main(["refresh"]) == 0
    catalog = load_catalog()
    assert catalog is not None
    assert {str(p.id): p.set_code for c in catalog.data for p in c.printings} == EXPECTED_PRINTING_CODES
    assert (tracked_folder() / "sets.json").read_bytes() == tracked
    assert cli.main(["export"]) == 0
    text = catalog_export_path().read_text(encoding="utf-8")
    exported = CatalogExport.model_validate_json(text)
    known = {s.code for s in exported.reference.sets}
    assert {p.id: p.set_code for c in exported.cards for p in c.printings} == {
        PrintingId(k): SetCode(v) for k, v in EXPECTED_PRINTING_CODES.items()
    }
    assert {str(c.number): c.set_code for c in exported.cards} == EXPECTED_CARD_CODES
    assert {p.set_code for c in exported.cards for p in c.printings} <= known and "PROMO" in known


# ---- AC-2: the card's own set -----------------------------------------------------------------------------------------------
def event(pid: str, set_code: str | None, where: str = ST07_EVENT) -> Printing:
    return printing(pid, set_code).model_copy(update={"where_to_get": where})


def card_set_codes(*cards: tuple[str, tuple[Printing, ...]]) -> dict[str, SetCode | None]:
    models = tuple(unit(number, "Card").model_copy(update={"printings": printings}) for number, printings in cards)
    file = CardsFile(generated_at=CATALOG_AT, data=models,
                     records=tuple(CardRecord(number=CardNumber(n), first_recorded=CATALOG_AT, no_longer_listed=False) for n, _ in cards))  # fmt: skip
    sets = tuple(CardSet(code=SetCode(c), name=c, kind=SetKind.BOOSTER, bandai_package_id=None, release_date=date(2026, 1, 1),
                         product_category_raw=None, product_url=None) for c in ("GD05", "ST07", "PROMO", "BETA"))  # fmt: skip
    result = build_export(file, sets, (), (), (), CATALOG_AT)
    return {str(c.number): c.set_code for c in result.cards}


def test_a_card_with_a_booster_printing_and_an_event_printing_keeps_the_boosters_set() -> None:
    assert card_set_codes(
        ("GD05-042", (printing("GD05-042", "GD05"), event("GD05-042_p1", "PROMO", GD05_EVENT))),
        ("ST07-002", (printing("ST07-002", "ST07"), event("ST07-002_p1", "PROMO"))),
    ) == {"GD05-042": "GD05", "ST07-002": "ST07"}


def test_the_reference_printing_is_chosen_by_kind_not_by_position() -> None:
    assert card_set_codes(("GD05-042", (event("GD05-042", "PROMO", GD05_EVENT), printing("GD05-042_p1", "GD05")))) == {
        "GD05-042": "GD05"
    }
    assert card_set_codes(("GD05-042", (printing("GD05-042", "BETA"), event("GD05-042_p1", "PROMO"), printing("GD05-042_p2", "GD05")))) == {
        "GD05-042": "GD05"}  # fmt: skip


def test_a_card_with_only_event_printings_or_beta_and_event_ones_is_promo_and_a_beta_only_card_has_none() -> None:
    assert card_set_codes(
        ("ST07-002", (event("ST07-002", "PROMO"), event("ST07-002_p1", "PROMO"))),
        ("GD05-042", (printing("GD05-042", "BETA"), event("GD05-042_p1", "PROMO", GD05_EVENT))),
        ("GD05-043", (printing("GD05-043", "BETA"),)),
    ) == {"ST07-002": "PROMO", "GD05-042": "PROMO", "GD05-043": None}


def test_an_ordinary_promo_package_printing_is_not_an_event_printing_for_the_card_level_rule() -> None:
    prize = printing("GD05-044", "PROMO").model_copy(update={"where_to_get": "Store tournament prize"})
    assert card_set_codes(("GD05-044", (prize, printing("GD05-044_p1", "GD05")))) == {
        "GD05-044": "PROMO"
    }  # first printing, as before


# ---- AC-4: the price matching -----------------------------------------------------------------------------------------------
def test_the_price_matching_matches_the_booster_printing_and_not_the_event_one(page: Page) -> None:
    booster = built(page, BOOSTER)
    event_printing = built(page, GD05_EVENT).model_copy(update={"id": PrintingId("ST01-001_p1")})
    card = unit("ST01-001", "Card").model_copy(update={"printings": (booster, event_printing)})
    assert [(p.alt_art_level, p.set_code) for p in card.printings] == [(0, "GD05"), (0, "PROMO")]
    product = TcgProduct(product_id=ProductId(90), group_id=1, group="GD05", name="Card", card_number=CardNumber("ST01-001"),
                         rarity_raw="Rare", rarity=Rarity.R, alt_art_level=0, promo=False, price_cents=125)  # fmt: skip
    result = match_products([product], [card], {SetCode("GD05"), SetCode("PROMO")}, CATALOG_AT)
    assert [str(r.printing_id) for r in result.rows] == [str(booster.id)] and result.rows[0].price_cents == 125
    assert result.unmatched == ()  # not ambiguous
    row = CardPrice(card_number=CardNumber("ST01-001"), product_id=ProductId(90), name="Card", set_code=SetCode("GD05"), price_cents=125, fetched_at=CATALOG_AT)  # fmt: skip
    assert set(printing_prices(card, (row,))) == {booster.id}
