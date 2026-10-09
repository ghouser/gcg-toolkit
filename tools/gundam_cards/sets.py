"""Sets: the package filter on Bandai's card page joined with the product list (release dates).

- Card packages come from the filter on `/en/cards/` (`<a data-val="616105">Freedom Ascension [GD05]</a>`).
- Release dates come from `/en/products/list.php?page=N`, which also lists announced, unreleased products.
Both are HTML; both are parsed with `html.parser`, never by eye.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from shared.basetypes import PackageId, SetCode
from shared.fetch import Fetcher
from tools.gundam_cards.build import Issue, IssueKind
from tools.gundam_cards.models import CardSet, SetKind
from tools.gundam_cards.parse_detail import clean_inline

CARDS_URL = "https://www.gundam-gcg.com/en/cards/"
PRODUCTS_URL = "https://www.gundam-gcg.com/en/products/list.php"
LANDING_KEY = "cards/landing.html"


def products_page_key(n: int) -> str:
    return f"products/page-{n}.html"


@dataclass(frozen=True)
class PackageEntry:
    id: PackageId
    label: str  # "Freedom Ascension [GD05]", "Promotion card"


@dataclass(frozen=True)
class RawProduct:
    category: str  # "BOOSTER PACK"
    title: str  # "Freedom Ascension [GD05]"
    url: str
    release_text: str  # "July 24,2026", "-", "May 29, 2026~ Available at select convention events!"


# ---- HTML parsing --------------------------------------------------------------------------------
class _PackageFilterParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current: str | None = None
        self._text: list[str] = []
        self.entries: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        value = dict(attrs).get("data-val")
        if tag == "a" and value and value.isdigit():
            self._current, self._text = value, []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            label = clean_inline("".join(self._text))
            if label:
                self.entries.setdefault(self._current, label)
            self._current = None


def parse_package_filter(html: str) -> tuple[PackageEntry, ...]:
    """Every card package in the filter on the card search page, deduplicated, in page order."""
    parser = _PackageFilterParser()
    parser.feed(html)
    return tuple(PackageEntry(PackageId(pid), label) for pid, label in parser.entries.items())


class _ProductListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.products: list[RawProduct] = []
        self.max_page = 1
        self._cap: str | None = None
        self._buf: list[str] = []
        self._category = ""
        self._url = ""
        self._title = ""
        self._wants_release = False
        self._release = ""
        self._in_product = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "div" and "productsDetail" in classes:
            self._in_product, self._category, self._url, self._title, self._release = True, "", "", "", ""
        elif self._in_product and tag == "a" and "productsDetailInner" in classes:
            self._url = a.get("href") or ""
        elif tag == "a" and "pageBtn" in classes:
            href = a.get("href") or ""
            match = re.fullmatch(r"\?page=(\d+)", href)
            if match:
                self.max_page = max(self.max_page, int(match.group(1)))
        if not self._in_product:
            return
        if tag == "span" and "cardCategory" in classes:
            self._cap, self._buf = "category", []
        elif tag == "div" and "cardTit" in classes:
            self._cap, self._buf = "title", []
        elif tag == "dt" and "cardInfoTit" in classes:
            self._cap, self._buf = "info_label", []
        elif tag == "dd" and "cardInfoTxt" in classes and self._wants_release:
            self._cap, self._buf = "release", []

    def handle_data(self, data: str) -> None:
        if self._cap is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._cap is None or tag not in ("span", "div", "dt", "dd"):
            return
        text = clean_inline("".join(self._buf))
        cap, self._cap = self._cap, None
        if cap == "category":
            self._category = text
        elif cap == "title":
            self._title = text
        elif cap == "info_label":
            self._wants_release = text == "Release Date"
        elif cap == "release":
            self._release = text
            self._wants_release = False
            if self._title:
                self.products.append(RawProduct(self._category, self._title, self._url, self._release))
            self._in_product = False


def parse_product_list(html: str) -> tuple[tuple[RawProduct, ...], int]:
    """Products on one list page, and the number of pages the pager shows."""
    parser = _ProductListParser()
    parser.feed(html)
    return tuple(parser.products), parser.max_page


# ---- field parsing ---------------------------------------------------------------------------------
_TITLE_WITH_CODE = re.compile(r"(.*?)\s*\[([A-Z]{2,4})-?(\d{2}[A-Z]?)\]\s*")
_DATE = re.compile(r"([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})")


def split_title(title: str) -> tuple[str, SetCode | None]:
    """`Freedom Ascension [GD05]` -> (`Freedom Ascension`, GD05); `Stardust Trails[GD06]`; `... [EVX-01]` -> EVX01."""
    match = _TITLE_WITH_CODE.fullmatch(title)
    if match is None:
        return title, None
    return match.group(1), SetCode(match.group(2) + match.group(3))


def parse_release_date(text: str) -> date | None:
    """`July 24,2026` / `January 30, 2026` / `May 29, 2026~ Available at ...` -> date. `-` or empty -> None.

    Raises ValueError for anything else, so a new format is noticed instead of silently dropped.
    """
    text = text.strip()
    if text in ("", "-"):
        return None
    match = _DATE.match(text)
    if match is None:
        raise ValueError(f"unrecognized release date {text!r}")
    return datetime.strptime(" ".join(match.groups()), "%B %d %Y").date()


_PREFIX_KINDS = {"GD": SetKind.BOOSTER, "ST": SetKind.STARTER, "EB": SetKind.EXTRA_BOOSTER, "SC": SetKind.DECK_BUILD_BOX}
_SYNTHETIC_PACKAGES = {
    "Promotion card": (SetCode("PROMO"), SetKind.PROMO),
    "Edition Beta": (SetCode("BETA"), SetKind.BETA),
    "Basic Cards": (SetCode("BASIC"), SetKind.OTHER),
    "Other Product Card": (SetCode("OTHER"), SetKind.OTHER),
}


# Products with no `[CODE]` in their title that are the product behind a synthetic package.
_SYNTHETIC_PRODUCT_TITLES = {"GUNDAM CARD GAME Edition Beta": SetCode("BETA")}


def kind_for_code(code: SetCode) -> SetKind:
    prefix = re.match(r"[A-Z]+", code)
    return _PREFIX_KINDS.get(prefix.group(0) if prefix else "", SetKind.OTHER)


# ---- the join ----------------------------------------------------------------------------------------
@dataclass
class _Draft:
    name: str
    kind: SetKind
    package_id: PackageId | None = None
    release_date: date | None = None
    category: str | None = None
    url: str | None = None
    product_joined: bool = False


@dataclass(frozen=True)
class SetsBuild:
    sets: tuple[CardSet, ...]
    issues: tuple[Issue, ...] = field(default_factory=tuple)


def build_sets(packages: tuple[PackageEntry, ...], products: tuple[RawProduct, ...]) -> SetsBuild:
    """Join card packages (identity, card list) with products (release dates) on the set code."""
    drafts: dict[SetCode, _Draft] = {}
    issues: list[Issue] = []

    for package in packages:
        name, code = split_title(package.label)
        if code is not None:
            drafts[code] = _Draft(name, kind_for_code(code), package_id=package.id)
        elif package.label in _SYNTHETIC_PACKAGES:
            synthetic_code, kind = _SYNTHETIC_PACKAGES[package.label]
            drafts[synthetic_code] = _Draft(package.label, kind, package_id=package.id)
        else:
            issues.append(Issue(IssueKind.PARSE_FAILURE, f"package {package.id}", f"unknown uncoded package {package.label!r}"))

    for product in products:
        name, code = split_title(product.title)
        if code is None:
            code = _SYNTHETIC_PRODUCT_TITLES.get(product.title)
            if code is None:
                continue  # sleeves, playmats, dice: no set code, no cards
            name = drafts[code].name if code in drafts else name  # keep the package's name ("Edition Beta")
        try:
            released = parse_release_date(product.release_text)
        except ValueError as e:
            issues.append(Issue(IssueKind.PARSE_FAILURE, f"product {code}", str(e)))
            released = None
        draft = drafts.get(code)
        if draft is None:
            draft = drafts[code] = _Draft(name, kind_for_code(code))
        elif draft.product_joined:
            issues.append(Issue(IssueKind.PARSE_FAILURE, f"product {code}", "two products share this set code"))
            continue
        draft.name, draft.release_date, draft.url = name, released, product.url
        draft.category = product.category or None
        draft.product_joined = True

    sets = tuple(
        CardSet(
            code=code,
            name=d.name,
            kind=d.kind,
            bandai_package_id=d.package_id,
            release_date=d.release_date,
            product_category_raw=d.category,
            product_url=d.url,
        )
        for code, d in sorted(drafts.items())
    )
    return SetsBuild(sets, tuple(issues))


# ---- fetching ----------------------------------------------------------------------------------------
def sync_sets(fetcher: Fetcher) -> SetsBuild:
    """Fetch the package filter and every product list page (always fresh: new sets get announced), then join."""
    landing = fetcher.get_text(CARDS_URL, cache_key=LANDING_KEY, force=True)
    first = fetcher.get_text(f"{PRODUCTS_URL}?page=1", cache_key=products_page_key(1), force=True)
    products, pages = parse_product_list(first.text)
    all_products = list(products)
    for n in range(2, pages + 1):
        page = fetcher.get_text(f"{PRODUCTS_URL}?page={n}", cache_key=products_page_key(n), force=True)
        all_products.extend(parse_product_list(page.text)[0])
    return build_sets(parse_package_filter(landing.text), tuple(all_products))


def sets_from_raw(raw_dir: Path) -> SetsBuild | None:
    """Rebuild from the cached pages with no network; None if they haven't been fetched yet."""
    landing = raw_dir / LANDING_KEY
    first = raw_dir / products_page_key(1)
    if not landing.is_file() or not first.is_file():
        return None
    products, pages = parse_product_list(first.read_text(encoding="utf-8"))
    all_products = list(products)
    for n in range(2, pages + 1):
        path = raw_dir / products_page_key(n)
        if not path.is_file():
            return None
        all_products.extend(parse_product_list(path.read_text(encoding="utf-8"))[0])
    return build_sets(parse_package_filter(landing.read_text(encoding="utf-8")), tuple(all_products))
