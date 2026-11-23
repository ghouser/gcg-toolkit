"""toolkit-hardening AC-2: with GCG_TOOL_DATA_DIR pointed at a temp folder, the cards and meta commands read and write their raw caches
and tracked files only there; the repository's tracked sets.json, restrictions.json and popularity.json stay byte-identical and its raw
folders unchanged. Unset, the folders are the repository's own.

The commands run for real (`main` with arguments; real fetcher, parsers and writers) over saved fixture pages copied into the temp
folder, or with only the network faked: `urllib.request.urlopen` serves small saved pages, so the real `Fetcher` writes its cache
wherever the command points it. After every command, whether it succeeds or fails, the real files are checked."""
from __future__ import annotations

import email.message
import json
import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path

import pytest

from shared.basetypes import PackageId, PrintingId, SetCode
from shared.dataset import TOOL_DATA_VAR
from shared.fetch import Fetcher
from shared.test_read_commands_on_dataset import dataset_tree
from tools.gundam_cards import cli as cards_cli
from tools.gundam_cards import store as cards_store
from tools.gundam_cards.models import CardSet, CardsFile, RestrictionsFile, SetKind, SetsFile
from tools.gundam_cards.printings import DETAIL_URL, LIST_URL, detail_page_key, list_page_key
from tools.gundam_cards.sets import CARDS_URL, LANDING_KEY, PRODUCTS_URL
from tools.gundam_cards.tcgcsv import BASE_URL, CATEGORY_ID, stamp_of
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai, detail
from tools.gundam_cards.tests.test_export import TCGCSV_AT, tcgcsv_dump
from tools.gundam_cards.tests.test_restrictions import PAGE as RESTRICTIONS_PAGE
from tools.gundam_meta import cli as meta_cli
from tools.gundam_meta import store as meta_store
from tools.gundam_meta.duelfrontier import API as DF_API
from tools.gundam_meta.duelfrontier import LIST_PAGE_SIZE
from tools.gundam_meta.egm import TOURNAMENTS_URL
from tools.gundam_meta.models import Source

Main = Callable[[Sequence[str] | None], int]

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tools" / "gundam_cards" / "tests" / "fixtures"
TRACKED = ("shared/data/gundam_cards/sets.json", "shared/data/gundam_cards/restrictions.json", "shared/data/gundam_meta/popularity.json")
REAL_RAW = (REPO / "tools" / "gundam_cards" / "data" / "raw", REPO / "tools" / "gundam_meta" / "data" / "raw")
PAGES = ("GD01-005", "GD01-005_p2", "ST01-001", "ST01-001_p5", "R-002")


def tracked_bytes() -> dict[str, bytes | None]:
    return {p: (REPO / p).read_bytes() if (REPO / p).is_file() else None for p in TRACKED}


def raw_listing() -> dict[str, tuple[int, int]]:
    """Every file in the real raw folders with its size and modification time (only listed, never opened)."""
    found: dict[str, tuple[int, int]] = {}
    for root in REAL_RAW:
        for folder, _, files in os.walk(root):
            for name in files:
                st = Path(folder, name).stat()
                found[str(Path(folder, name))] = (st.st_size, st.st_mtime_ns)
    return found


@pytest.fixture
def tool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "tool-data"
    monkeypatch.setenv(TOOL_DATA_VAR, str(folder))
    monkeypatch.setenv("GCG_DATA_DIR", str(tmp_path / "dataset"))
    return folder


def test_reparse_and_sets_use_only_the_temp_folder(tool_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    detail = tmp_path / "dataset" / "gundam_cards" / "pages" / "detail"  # Bandai's pages are cached in the dataset (safe-refresh)
    detail.mkdir(parents=True)
    for page in PAGES:
        shutil.copyfile(FIXTURES / f"{page}.html", detail / f"{page}.html")
    gd01 = CardSet(code=SetCode("GD01"), name="Temp Set", kind=SetKind.BOOSTER, bandai_package_id=PackageId("616101"),
                   release_date=date(2025, 7, 25), product_category_raw=None, product_url=None)  # fmt: skip
    sets_path = tool_dir / "shared" / "data" / "gundam_cards" / "sets.json"
    sets_path.parent.mkdir(parents=True)
    sets_path.write_text(SetsFile(generated_at=datetime(2026, 11, 1, tzinfo=UTC), data=(gd01,)).model_dump_json(), encoding="utf-8")
    tracked, raw = tracked_bytes(), raw_listing()

    assert cards_cli.main(["reparse"]) == 0
    catalog = CardsFile.model_validate_json((tmp_path / "dataset" / "gundam_cards" / "cards.json").read_text(encoding="utf-8"))
    assert sorted(str(c.number) for c in catalog.data) == ["GD01-005", "R-002", "ST01-001"]  # built from the temp folder's pages
    capsys.readouterr()
    assert cards_cli.main(["sets"]) == 0
    rows = capsys.readouterr().out.splitlines()[1:]
    assert [r.split()[0] for r in rows] == ["GD01"] and "Temp Set" in rows[0]  # the temp folder's sets.json, not the repository's

    assert tracked_bytes() == tracked
    assert raw_listing() == raw


def test_meta_popularity_writes_into_the_temp_folder(tool_dir: Path, tmp_path: Path) -> None:
    dataset_tree(tmp_path / "dataset")
    sets = REPO / "shared" / "data" / "gundam_cards" / "sets.json"
    (tool_dir / "shared" / "data" / "gundam_cards").mkdir(parents=True)
    shutil.copyfile(sets, tool_dir / "shared" / "data" / "gundam_cards" / "sets.json")  # the eras need release dates
    tracked, raw = tracked_bytes(), raw_listing()

    assert meta_cli.main(["popularity"]) == 0
    assert (tool_dir / "shared" / "data" / "gundam_meta" / "popularity.json").is_file()
    assert tracked_bytes() == tracked
    assert raw_listing() == raw


def test_unset_the_folders_are_the_repositorys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOOL_DATA_VAR)
    assert cards_store.raw_folder() == REPO / "tools" / "gundam_cards" / "data" / "raw"
    assert cards_store.tracked_folder() == REPO / "shared" / "data" / "gundam_cards"
    assert meta_store.raw_folder() == REPO / "tools" / "gundam_meta" / "data" / "raw"
    assert meta_store.tracked_folder() == REPO / "shared" / "data" / "gundam_meta"


# ---- every listed command, through the real fetcher with only the network faked ------------------------------------------------------
GD01 = "616101"
MKE = "regional-milwaukee-2026"
META_FIXTURES = REPO / "tools" / "gundam_meta" / "tests" / "fixtures"
RESTRICTIONS_URL = "https://www.gundam-gcg.com/en/news/temp-folder.html"


class _Body:
    def __init__(self, text: str) -> None:
        self._data = text.encode("utf-8")

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The web, as url -> page; any other url answers 404. The fetchers are the real ones, minus the wait between requests."""
    pages: dict[str, str] = {}

    def urlopen(request: urllib.request.Request, timeout: float) -> _Body:
        if request.full_url not in pages:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", email.message.Message(), None)
        return _Body(pages[request.full_url])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    for cli in (cards_cli, meta_cli):
        monkeypatch.setattr(cli, "Fetcher", partial(Fetcher, sleep=lambda _: None))
    return pages


def bandai_pages(site: FakeBandai) -> dict[str, str]:
    """Bandai's package list, listings and detail pages, as the fake from the refresh tests draws them."""
    urls = [CARDS_URL, f"{PRODUCTS_URL}?page=1"]
    urls += [LIST_URL.format(pid) for pid in site.packages]
    urls += [DETAIL_URL.format(i) for _, ids in site.packages.values() for i in ids]
    return {url: site.page(url) for url in urls}


def tcgcsv_pages() -> dict[str, str]:
    dump = tcgcsv_dump()
    base = f"{BASE_URL}/tcgplayer/{CATEGORY_ID}"
    pages = {f"{BASE_URL}/last-updated.txt": f"{TCGCSV_AT:%Y-%m-%dT%H:%M:%S}+0000", f"{base}/groups": dump.groups}
    for group, text in dump.products.items():
        pages[f"{base}/{group}/products"] = text
        pages[f"{base}/{group}/prices"] = dump.prices[group]
    return pages


def meta_pages(event_name: str = "Regional Milwaukee 2026") -> dict[str, str]:
    """EGM's tournament list and one DuelFrontier event (listed alone) with its decks, from the saved fixtures."""
    listing = json.loads((META_FIXTURES / "df_events_list.json").read_text(encoding="utf-8"))
    listing.update(data=[e for e in listing["data"] if e["slug"] == MKE], totalPages=1)
    event = json.loads((META_FIXTURES / "df_event_regional_milwaukee.json").read_text(encoding="utf-8"))
    event["data"]["name"] = event_name
    pages = {f"{DF_API}/events?PageNumber=1&PageSize={LIST_PAGE_SIZE}": json.dumps(listing),
             f"{DF_API}/events/{MKE}?Include=Players": json.dumps(event),
             TOURNAMENTS_URL: (META_FIXTURES / "egm_tournaments.json").read_text(encoding="utf-8")}  # fmt: skip
    for player in event["data"]["players"]:
        slug = player["deckSlug"]
        pages[f"{DF_API}/decks/{slug}?Include=Cards"] = (META_FIXTURES / f"df_deck_{slug}.json").read_text(encoding="utf-8")
    return pages


class Runner:
    """Runs a command and then checks that the real tracked files and raw folders are as they were before the first run."""

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self.capsys, self.tracked, self.raw = capsys, tracked_bytes(), raw_listing()

    def __call__(self, main: Main, argv: list[str], code: int = 0) -> str:
        assert main(argv) == code
        assert tracked_bytes() == self.tracked
        assert raw_listing() == self.raw
        return self.capsys.readouterr().out


def test_the_cards_network_commands_read_and_write_only_the_temp_folder(
    tool_dir: Path, tmp_path: Path, network: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    raw_dir, tracked_dir = tool_dir / "tools" / "gundam_cards" / "data" / "raw", tool_dir / "shared" / "data" / "gundam_cards"
    pages = tmp_path / "dataset" / "gundam_cards" / "pages"  # Bandai's pages are cached in the dataset (safe-refresh)
    site = FakeBandai(Path(), {GD01: ("Newtype Rising [GD01]", ["GD01-001", "GD01-002"])}, products=[("Newtype Rising [GD01]", "July 25,2025")])
    network.update({**bandai_pages(site), **tcgcsv_pages(), RESTRICTIONS_URL: RESTRICTIONS_PAGE})
    run = Runner(capsys)

    run(cards_cli.main, ["sync"])
    assert (pages / LANDING_KEY).is_file() and (pages / list_page_key(PackageId(GD01))).is_file()  # the fetcher's cache
    assert (pages / detail_page_key(PrintingId("GD01-002"))).is_file()  # sync_printings' pages
    (pages / detail_page_key(PrintingId("GD01-002"))).unlink()
    # sync_printings reads the temp dataset's cache: one page there, one missing (the repository's folder would differ)
    assert "2 printings: 1 already cached, 1 fetched, 0 failed" in run(cards_cli.main, ["sync"])

    network[DETAIL_URL.format("GD01-001")] = detail("GD01-001", name="Refetched Name")
    assert "1 changed, 0 unchanged, 0 failed" in run(cards_cli.main, ["refetch", "--card", "GD01-001"])
    assert "Refetched Name" in (pages / detail_page_key(PrintingId("GD01-001"))).read_text(encoding="utf-8")
    # refetch_printings compares with the temp dataset's cached copy, which now matches what Bandai serves
    assert "0 changed, 1 unchanged, 0 failed" in run(cards_cli.main, ["refetch", "--card", "GD01-001"])

    assert not raw_dir.exists()  # no Bandai page in the checkout's raw folder

    run(cards_cli.main, ["sync-tcgplayer"])
    dump = raw_dir / "tcgcsv" / stamp_of(TCGCSV_AT)
    assert (dump / "groups.json").is_file() and (dump / "pulled-at.txt").is_file()
    (dump / "pulled-at.txt").write_text("2026-11-05T09:30:00+00:00\n", encoding="utf-8")
    assert "pulled 2026-11-05 09:30 UTC" in run(cards_cli.main, ["reparse-tcgplayer"])  # the temp folder's dump and its marker

    run(cards_cli.main, ["sync-restrictions", "--url", RESTRICTIONS_URL])
    assert (raw_dir / "restrictions" / "temp-folder.html").is_file()
    stored = RestrictionsFile.model_validate_json((tracked_dir / "restrictions.json").read_text(encoding="utf-8"))
    assert stored.source_url == RESTRICTIONS_URL
    assert RESTRICTIONS_URL in run(cards_cli.main, ["restrictions"])  # read from the temp tracked folder


def test_the_meta_network_commands_read_and_write_only_the_temp_folder(
    tool_dir: Path, tmp_path: Path, network: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_tree(tmp_path / "dataset")  # a catalog, and an EGM event whose raw response is not saved (so `reparse` reports it failed)
    (tool_dir / "shared" / "data" / "gundam_cards").mkdir(parents=True)
    shutil.copyfile(REPO / "shared" / "data" / "gundam_cards" / "sets.json", tool_dir / "shared" / "data" / "gundam_cards" / "sets.json")
    raw_dir = tool_dir / "tools" / "gundam_meta" / "data" / "raw"
    saved = raw_dir / "duelfrontier" / "events" / f"{MKE}.json"
    network.update(meta_pages())
    run = Runner(capsys)

    def stored_name() -> str:
        return next(e.name for e in meta_store.load_events(source=Source.DUELFRONTIER) if e.id == MKE)

    run(meta_cli.main, ["sync"])
    assert saved.is_file() and len(list((raw_dir / "egm").glob("*.json"))) == 1

    renamed = json.loads(saved.read_text(encoding="utf-8"))
    renamed["data"]["name"] = "Temp Folder Event"
    saved.write_text(json.dumps(renamed), encoding="utf-8")
    run(meta_cli.main, ["reparse"], code=1)
    assert stored_name() == "Temp Folder Event"  # rebuilt from the temp folder's saved page

    network.update(meta_pages(event_name="Refetched Event"))
    run(meta_cli.main, ["refetch", "--source", "duelfrontier", "--event", MKE])
    assert "Refetched Event" in saved.read_text(encoding="utf-8") and stored_name() == "Refetched Event"
    run(meta_cli.main, ["refetch", "--source", "egm", "--all"])
    assert len(list((raw_dir / "egm").glob("*.json"))) == 2


FAILING: list[tuple[Main, list[str]]] = [
    (cards_cli.main, ["sync"]),
    (cards_cli.main, ["refresh"]),
    (cards_cli.main, ["refetch", "--card", "GD01-001"]),
    (cards_cli.main, ["reparse"]),
    (cards_cli.main, ["sync-tcgplayer"]),
    (cards_cli.main, ["sync-restrictions"]),
    (meta_cli.main, ["sync"]),
    (meta_cli.main, ["reparse"]),
    (meta_cli.main, ["refetch", "--source", "duelfrontier", "--all"]),
    (meta_cli.main, ["refetch", "--source", "egm", "--all"]),
]


@pytest.mark.parametrize(("main", "argv"), FAILING, ids=[f"{m.__module__.split('.')[1]} {' '.join(a)}" for m, a in FAILING])
def test_a_command_that_fails_leaves_the_real_files_unchanged(
    tool_dir: Path, tmp_path: Path, network: dict[str, str], main: Main, argv: list[str]
) -> None:
    """The network answers 404 to everything, and the temp dataset's Bandai page cache holds a page that is not a card page."""
    dataset_tree(tmp_path / "dataset")  # a catalog and events, so each command gets as far as the network or the raw pages
    bad = tmp_path / "dataset" / "gundam_cards" / "pages" / detail_page_key(PrintingId("GD01-001"))
    bad.parent.mkdir(parents=True)
    bad.write_text("<html><body>not a card</body></html>", encoding="utf-8")
    tracked, raw = tracked_bytes(), raw_listing()
    try:
        code: int | None = main(argv)
    except (Exception, SystemExit):  # a fetch failure, or a missing input, that the command lets through
        code = None
    assert code != 0
    assert tracked_bytes() == tracked
    assert raw_listing() == raw
