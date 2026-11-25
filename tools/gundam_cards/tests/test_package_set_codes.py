"""promo-beta-set-codes: a printing whose "Where to get it" names no set in brackets takes its set from its package, through the
reviewed sets.json (AC-1, AC-2); a rebuild never writes sets.json (AC-4) and the export carries the codes (AC-3, AC-5).
The commands run through `main` against the in-memory Bandai fake, in the root conftest's temp folders.
Expected values are worked out by hand from the package map below."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from shared.basetypes import PackageId, SetCode, Trait
from tools.gundam_cards import cli
from tools.gundam_cards.build import SourcePage, build_card
from tools.gundam_cards.export import CatalogExport
from tools.gundam_cards.models import CardSet, Printing, SetKind, SetsFile
from tools.gundam_cards.store import catalog_export_path, data_out_dir, load_catalog, load_provisional_sets, pages_folder, tracked_folder
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai, detail

Page = Callable[[str], SourcePage]
TRAITS = frozenset({Trait("Earth Federation"), Trait("White Base Team")})
NO_DATES: dict[SetCode, date] = {}
GD01, GD02, SC01, BASIC, PROMO, BETA, UNKNOWN = "616101", "616102", "616301", "616801", "616901", "616000", "616999"
PACKAGE_CODES = {PackageId(GD01): SetCode("GD01"), PackageId(GD02): SetCode("GD02"), PackageId(SC01): SetCode("SC01"),
                 PackageId(BASIC): SetCode("BASIC"), PackageId(PROMO): SetCode("PROMO"), PackageId(BETA): SetCode("BETA")}  # fmt: skip


def printed(page: Page, where: str, *packages: str, codes: dict[PackageId, SetCode] = PACKAGE_CODES) -> Printing:
    """ST01-001's page with its "Where to get it" text and package ids replaced, built with the package map `codes`."""
    p = page("ST01-001")
    source = replace(p, raw=replace(p.raw, fields=dict(p.raw.fields, **{"Where to get it": where})),
                     package_ids=tuple(PackageId(i) for i in packages))  # fmt: skip
    result = build_card([source], TRAITS, NO_DATES, codes)
    assert result.issues == ()
    return result.card.printings[0]


# ---- AC-1 -------------------------------------------------------------------------------------------------------------------
def test_a_bracketed_code_in_the_text_wins_over_the_package(page: Page) -> None:
    assert printed(page, "Newtype Rising [GD01]", PROMO).set_code == "GD01"
    assert printed(page, "Some Reprint[GD02]", BETA).set_code == "GD02"


def test_a_printing_in_the_promo_package_with_no_bracketed_code_gets_promo(page: Page) -> None:
    assert printed(page, "Store tournament prize", PROMO).set_code == "PROMO"


def test_a_dash_printing_gets_the_set_its_package_maps_to(page: Page) -> None:
    assert printed(page, "-", GD02).set_code == "GD02"  # R-018, R-019, T-012 on the real data


def test_a_package_the_map_lacks_gives_no_set_code_and_the_card_still_builds(page: Page) -> None:
    assert printed(page, "Store tournament prize", UNKNOWN).set_code is None


def test_a_printing_with_no_package_and_no_bracketed_code_has_no_set_code(page: Page) -> None:
    assert printed(page, "Store tournament prize").set_code is None


def test_with_no_sets_json_no_package_is_known(page: Page) -> None:
    assert printed(page, "Store tournament prize", PROMO, codes={}).set_code is None


def test_with_several_packages_the_first_one_the_map_knows_wins(page: Page) -> None:
    assert printed(page, "-", UNKNOWN, GD02, PROMO).set_code == "GD02"
    assert printed(page, "-", PROMO, GD02).set_code == "PROMO"
    assert printed(page, "-", GD02, PROMO).set_code == "GD02"


def test_without_a_package_map_the_build_reads_only_the_bracket(page: Page) -> None:
    p = page("ST01-001")
    source = replace(p, raw=replace(p.raw, fields=dict(p.raw.fields, **{"Where to get it": "-"})), package_ids=(PackageId(GD02),))
    assert build_card([source], TRAITS, NO_DATES).card.printings[0].set_code is None


# ---- AC-2 -------------------------------------------------------------------------------------------------------------------
def test_an_edition_beta_printing_gets_beta_and_nothing_else_changes(page: Page) -> None:
    with_map = printed(page, "Edition Beta", BETA)
    without_map = printed(page, "Edition Beta", BETA, codes={})
    assert with_map.set_code == "BETA"
    assert with_map == without_map.model_copy(update={"set_code": SetCode("BETA")})


# ---- AC-4 and AC-5: the rebuilds and the export, end to end -----------------------------------------------------------------
# The fake Bandai lists seven packages; the reviewed sets.json knows six of them. GD01-003 has no base page: its first printing is
# in Edition Beta, its second in the basic package (no bracketed code) and its third a bracketed SC01 reprint, as EXB-001, EXR-001
# and R-001 (the basic cards given in the starter decks) on the real data, so its card-level set is BASIC.
LISTED = {
    GD01: ("Newtype Rising [GD01]", {"GD01-001": "Newtype Rising [GD01]"}),
    GD02: ("Dueling Colonies [GD02]", {"GD02-001": "-"}),
    SC01: ("Deck Build Box [SC01]", {"GD01-003_p3": "Deck Build Box [SC01]"}),
    BASIC: ("Basic Cards", {"GD01-003_p2": "Included in each starter deck"}),
    PROMO: ("Promotion card", {"GD01-002": "Store tournament prize"}),
    BETA: ("Edition Beta", {"GD01-003_p1": "Edition Beta"}),
    UNKNOWN: ("Future Pack [GD99]", {"GD99-001": "Launch week giveaway"}),  # sets.json lacks it: the rebuild proposes GD99
}
EXPECTED_PRINTING_CODES = {"GD01-001": "GD01", "GD02-001": "GD02", "GD01-003_p2": "BASIC", "GD01-003_p3": "SC01", "GD01-002": "PROMO",
                           "GD01-003_p1": "BETA", "GD99-001": None}  # fmt: skip


KINDS = {"GD01": SetKind.BOOSTER, "GD02": SetKind.BOOSTER, "SC01": SetKind.DECK_BUILD_BOX, "BASIC": SetKind.OTHER,
         "PROMO": SetKind.PROMO, "BETA": SetKind.BETA}


def reviewed_sets() -> tuple[CardSet, ...]:
    return tuple(
        CardSet(code=code, name=f"{code} (reviewed)", kind=KINDS[code], bandai_package_id=package_id, release_date=None,
                product_category_raw=None, product_url=None)
        for package_id, code in PACKAGE_CODES.items()
    )  # fmt: skip


class Bandai(FakeBandai):
    network_requests = 0  # read by `sync` for its summary


@pytest.fixture
def tracked() -> bytes:
    """The reviewed sets.json in the root conftest's temp tracked folder; its bytes, to compare after each run."""
    path = tracked_folder() / "sets.json"
    path.write_text(SetsFile(generated_at=datetime(2026, 11, 1, tzinfo=UTC), data=reviewed_sets()).model_dump_json(indent=1) + "\n",
                    encoding="utf-8")  # fmt: skip
    return path.read_bytes()


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Bandai:
    bandai = Bandai(
        pages_folder(),
        {pid: (label, list(printings)) for pid, (label, printings) in LISTED.items()},
        details={i: detail(i, where=where) for _, printings in LISTED.values() for i, where in printings.items()},
    )
    monkeypatch.setattr(cli, "Fetcher", lambda *_, **__: bandai)
    monkeypatch.setattr(cli, "refresh_fetcher", lambda: bandai)
    return bandai


def rebuild(how: str) -> None:
    if how == "reparse":
        assert cli.main(["sync"]) == 0  # caches the pages
        assert cli.main(["reparse"]) == 0
    else:
        assert cli.main(["refresh"]) == 0


def catalog_printing_codes() -> dict[str, str | None]:
    catalog = load_catalog()
    assert catalog is not None
    return {str(p.id): p.set_code for c in catalog.data for p in c.printings}


@pytest.mark.parametrize("how", ["reparse", "refresh"])
def test_a_rebuild_gives_package_codes_and_leaves_sets_json_byte_identical(tracked: bytes, site: Bandai, how: str) -> None:
    rebuild(how)
    assert (tracked_folder() / "sets.json").read_bytes() == tracked
    assert catalog_printing_codes() == EXPECTED_PRINTING_CODES  # GD99-001: a package sets.json lacks gives no code
    assert {str(s.code) for s in load_provisional_sets()} == {"GD99"}  # the provisional record is what it was before this change


def test_reparse_reports_the_provisional_sets_as_before(tracked: bytes, site: Bandai, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sync"]) == 0
    capsys.readouterr()
    assert cli.main(["reparse"]) == 0
    assert f"7 sets on Bandai's list, 1 provisional -> {data_out_dir() / 'provisional_sets.json'}" in capsys.readouterr().out.splitlines()


def test_with_no_sets_json_the_rebuild_gives_only_bracketed_codes_and_creates_none(site: Bandai) -> None:
    (tracked_folder() / "sets.json").unlink()  # the root conftest's copy
    rebuild("reparse")
    assert not (tracked_folder() / "sets.json").exists()
    assert catalog_printing_codes() == {"GD01-001": "GD01", "GD02-001": None, "GD01-003_p2": None, "GD01-003_p3": "SC01",
                                        "GD01-002": None, "GD01-003_p1": None, "GD99-001": None}  # fmt: skip
    assert {str(s.code) for s in load_provisional_sets()} == {"GD01", "GD02", "SC01", "BASIC", "PROMO", "BETA", "GD99"}


@pytest.mark.parametrize("how", ["reparse", "refresh"])
def test_the_export_after_a_rebuild_is_valid_and_carries_the_new_codes(tracked: bytes, site: Bandai, how: str) -> None:
    rebuild(how)
    assert cli.main(["export"]) == 0
    text = catalog_export_path().read_text(encoding="utf-8")
    CatalogExport.model_validate_json(text)
    data = json.loads(text)
    known = {s["code"] for s in data["reference"]["sets"]}
    printing_codes = {p["id"]: p.get("set_code") for c in data["cards"] for p in c["printings"]}
    card_codes = {c["number"]: c.get("set_code") for c in data["cards"]}
    assert {c for c in [*printing_codes.values(), *card_codes.values()] if c is not None} <= known
    assert printing_codes == EXPECTED_PRINTING_CODES
    assert card_codes == {"GD01-001": "GD01", "GD02-001": "GD02", "GD01-002": "PROMO", "GD01-003": "BASIC", "GD99-001": None}
