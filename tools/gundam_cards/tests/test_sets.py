"""Sets: package filter + product list -> CardSet, from saved Bandai pages."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from shared.basetypes import PackageId, SetCode
from tools.gundam_cards.models import CardSet, SetKind
from tools.gundam_cards.sets import (
    PackageEntry,
    RawProduct,
    build_sets,
    kind_for_code,
    parse_package_filter,
    parse_product_list,
    parse_release_date,
    split_title,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sets"


def _products() -> tuple[RawProduct, ...]:
    products: list[RawProduct] = []
    for n in range(1, 5):
        products.extend(parse_product_list((FIXTURES / f"products-{n}.html").read_text(encoding="utf-8"))[0])
    return tuple(products)


def _packages() -> tuple[PackageEntry, ...]:
    return parse_package_filter((FIXTURES / "landing.html").read_text(encoding="utf-8"))


def test_package_filter_is_deduplicated_and_complete() -> None:
    packages = _packages()
    assert len(packages) == 25
    labels = {p.id: p.label for p in packages}
    assert labels[PackageId("616105")] == "Freedom Ascension [GD05]"
    assert labels[PackageId("616901")] == "Promotion card"


def test_product_list_pages() -> None:
    first, pages = parse_product_list((FIXTURES / "products-1.html").read_text(encoding="utf-8"))
    assert pages == 4 and len(first) == 12
    assert first[0] == RawProduct("BOOSTER PACK", "Blazing Fist [GD07]", "https://www.gundam-gcg.com/en/products/gd07.html", "January 29,2027")
    assert len(_products()) == 47  # 12 + 12 + 12 + 11, including the uncoded Edition Beta product


@pytest.mark.parametrize(
    ("title", "name", "code"),
    [
        ("Freedom Ascension [GD05]", "Freedom Ascension", "GD05"),
        ("Stardust Trails[GD06]", "Stardust Trails", "GD06"),
        ("Accessory and Card Set 01 FIRST COMBAT [EVX-01]", "Accessory and Card Set 01 FIRST COMBAT", "EVX01"),
        ("Premium Card Collection GUNDAM ASSEMBLE Set -Mobile Suit Gundam GQuuuuuuX- [PC02A]", "Premium Card Collection GUNDAM ASSEMBLE Set -Mobile Suit Gundam GQuuuuuuX-", "PC02A"),
        ("Official Card Sleeves 02", "Official Card Sleeves 02", None),
    ],
)
def test_split_title(title: str, name: str, code: str | None) -> None:
    assert split_title(title) == (name, None if code is None else SetCode(code))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("July 24,2026", date(2026, 7, 24)),
        ("January 30, 2026", date(2026, 1, 30)),
        ("September 25,2026", date(2026, 9, 25)),
        ("May 29, 2026~ Available at select convention events!", date(2026, 5, 29)),
        ("-", None),
        ("", None),
    ],
)
def test_parse_release_date(text: str, expected: date | None) -> None:
    assert parse_release_date(text) == expected


def test_unrecognized_release_date_raises() -> None:
    with pytest.raises(ValueError):
        parse_release_date("Coming soon")


def test_kind_for_code() -> None:
    kinds = {c: kind_for_code(SetCode(c)) for c in ("GD05", "ST11", "EB01", "SC01", "PB01", "EVX08", "PC01A")}
    assert kinds == {
        "GD05": SetKind.BOOSTER, "ST11": SetKind.STARTER, "EB01": SetKind.EXTRA_BOOSTER, "SC01": SetKind.DECK_BUILD_BOX,
        "PB01": SetKind.OTHER, "EVX08": SetKind.OTHER, "PC01A": SetKind.OTHER,
    }  # fmt: skip


def test_built_sets_join_packages_with_release_dates() -> None:
    build = build_sets(_packages(), _products())
    assert build.issues == ()
    by_code: dict[str, CardSet] = {s.code: s for s in build.sets}
    assert len(build.sets) == 42

    gd05 = by_code["GD05"]
    assert (gd05.name, gd05.kind, gd05.release_date) == ("Freedom Ascension", SetKind.BOOSTER, date(2026, 7, 24))
    assert gd05.bandai_package_id == "616105" and gd05.product_category_raw == "BOOSTER PACK"

    # Announced but unreleased: a product with no card list yet.
    gd06 = by_code["GD06"]
    assert gd06.bandai_package_id is None and gd06.release_date == date(2026, 10, 30)
    assert not gd06.released_on(date(2026, 10, 6)) and gd06.released_on(date(2026, 10, 30))

    # Era anchors from the design: ST11-ST14 all released together on 2026-09-25.
    assert {by_code[c].release_date for c in ("ST11", "ST12", "ST13", "ST14")} == {date(2026, 9, 25)}

    # Synthetic codes stand in for uncoded packages; those with no product page keep an unknown date.
    for code, kind in (("PROMO", SetKind.PROMO), ("BETA", SetKind.BETA), ("BASIC", SetKind.OTHER), ("OTHER", SetKind.OTHER)):
        assert by_code[code].kind is kind and by_code[code].bandai_package_id
    assert all(by_code[c].release_date is None for c in ("PROMO", "BASIC", "OTHER"))

    # The Edition Beta product has no [CODE] in its title; it attaches to the BETA package by explicit title mapping.
    beta = by_code["BETA"]
    assert (beta.name, beta.release_date, beta.product_category_raw) == ("Edition Beta", date(2024, 12, 7), None)


def test_only_card_introducing_kinds_start_eras() -> None:
    assert {k for k in SetKind if k.introduces_cards} == {SetKind.BOOSTER, SetKind.STARTER, SetKind.EXTRA_BOOSTER}


def test_unknown_uncoded_package_is_reported_not_guessed() -> None:
    build = build_sets((PackageEntry(PackageId("999999"), "Mystery Pack"),), ())
    assert build.sets == () and len(build.issues) == 1 and "Mystery Pack" in build.issues[0].detail


def test_unparseable_release_date_is_reported_and_the_set_is_kept() -> None:
    product = RawProduct("BOOSTER PACK", "Future Set [GD09]", "https://example.test/gd09.html", "Coming soon")
    build = build_sets((), (product,))
    assert [s.code for s in build.sets] == ["GD09"] and build.sets[0].release_date is None
    assert len(build.issues) == 1 and "Coming soon" in build.issues[0].detail
