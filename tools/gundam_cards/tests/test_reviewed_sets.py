"""toolkit-hardening AC-3: no rebuild writes the reviewed sets.json. `sync --only sets`, `sync`, `reparse`, `refetch` and `refresh` leave
it byte-identical; a set it lacks goes into the dataset's provisional record (a new PB code as promo); a reviewed set Bandai no longer
lists, or lists differently, stays as it is and gets one informational line, with the exit code unchanged.

Bandai is the fake from test_catalog_refresh (no network); the commands run through `main`, in the root conftest's temp folders."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, PackageId, SetCode
from tools.gundam_cards import cli
from tools.gundam_cards.models import CardSet, SetKind, SetsFile
from tools.gundam_cards.store import catalog_export_path, load_catalog, load_provisional_sets, raw_folder, tracked_folder
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai, detail

GD01, GD09, PB04 = "616101", "616109", "616904"
URL = "https://example.test/p"  # the fake's product url
PB03_LINE = "reviewed set PB03 is not on Bandai's list"
GD01_LINE = "reviewed set GD01 differs from Bandai: name, release date"


class Bandai(FakeBandai):
    network_requests = 0  # read by `sync` for its summary


def reviewed() -> tuple[CardSet, ...]:
    """GD01 reviewed by hand (its name and release date differ from Bandai's); PB03, which Bandai does not list."""
    return (
        CardSet(code=SetCode("GD01"), name="Newtype Rising (reviewed)", kind=SetKind.BOOSTER, bandai_package_id=PackageId(GD01),
                release_date=date(2025, 7, 25), product_category_raw="BOOSTER PACK", product_url=URL),
        CardSet(code=SetCode("PB03"), name="1st Anniversary Set", kind=SetKind.PROMO, bandai_package_id=None,
                release_date=date(2026, 7, 1), product_category_raw=None, product_url=None),
    )  # fmt: skip


def sets_json() -> Path:
    return tracked_folder() / "sets.json"


@pytest.fixture
def tracked() -> bytes:
    """The reviewed sets.json in the temp tracked folder; its bytes, to compare after each run."""
    sets_json().write_text(
        json.dumps(json.loads(SetsFile(generated_at=datetime(2026, 11, 1, tzinfo=UTC), data=reviewed()).model_dump_json()), indent=1) + "\n",
        encoding="utf-8",
    )
    return sets_json().read_bytes()


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Bandai:
    bandai = Bandai(
        raw_folder(),
        {GD01: ("Newtype Rising [GD01]", ["GD01-001"]), GD09: ("Future Pack [GD09]", ["GD09-001"]),
         PB04: ("Premium Pack [PB04]", ["PB04-001"])},
        details={"GD09-001": detail("GD09-001", where="Future Pack [GD09]"), "PB04-001": detail("PB04-001", where="Premium Pack [PB04]")},
        products=[("Newtype Rising [GD01]", "August 1,2025"), ("Future Pack [GD09]", "March 5,2027")],
    )  # fmt: skip
    monkeypatch.setattr(cli, "Fetcher", lambda *_, **__: bandai)
    monkeypatch.setattr(cli, "refresh_fetcher", lambda: bandai)
    return bandai


def provisional() -> dict[str, CardSet]:
    return {str(s.code): s for s in load_provisional_sets()}


@pytest.mark.parametrize("argv", [["sync", "--only", "sets"], ["sync"], ["refresh"]], ids=" ".join)
def test_a_rebuild_leaves_sets_json_byte_identical_and_proposes_new_sets(
    tracked: bytes, site: Bandai, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert sets_json().read_bytes() == tracked
    assert PB03_LINE in out.splitlines() and GD01_LINE in out.splitlines()
    found = provisional()
    assert set(found) >= {"GD09", "PB04"} and "GD01" not in found and "PB03" not in found  # Bandai's GD01 is recorded nowhere
    assert (found["GD09"].kind, found["GD09"].name, found["GD09"].release_date) == (SetKind.BOOSTER, "Future Pack", date(2027, 3, 5))
    assert found["PB04"].kind is SetKind.PROMO  # a new PB code is a promo set


def test_reparse_and_refetch_leave_sets_json_byte_identical_and_take_release_dates_from_it(
    tracked: bytes, site: Bandai, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["sync"]) == 0  # caches the pages
    capsys.readouterr()
    for argv in (["reparse"], ["refetch", "--card", "GD01-001"]):
        site.details["GD01-001"] = detail("GD01-001", name="Renamed on Bandai")  # so the refetch finds a change and reparses
        assert cli.main(argv) == 0
        lines = capsys.readouterr().out.splitlines()
        assert sets_json().read_bytes() == tracked
        assert PB03_LINE in lines and GD01_LINE in lines
    catalog = load_catalog()
    assert catalog is not None
    [gd01_001] = [c for c in catalog.data if c.number == CardNumber("GD01-001")]
    assert gd01_001.text_versions[0].as_of == date(2025, 7, 25)  # the sets.json date, not Bandai's August 1


def test_a_matching_list_gives_the_same_exit_code_and_no_report_line(site: Bandai, capsys: pytest.CaptureFixture[str]) -> None:
    gd01 = reviewed()[0].model_copy(update={"name": "Newtype Rising", "release_date": date(2025, 8, 1)})
    sets_json().write_text(SetsFile(generated_at=datetime(2026, 11, 1, tzinfo=UTC), data=(gd01,)).model_dump_json(), encoding="utf-8")
    assert cli.main(["sync", "--only", "sets"]) == 0
    assert "reviewed set" not in capsys.readouterr().out


def test_a_later_rebuild_updates_a_provisional_set_and_keeps_one_bandai_no_longer_lists(tracked: bytes, site: Bandai) -> None:
    assert cli.main(["sync", "--only", "sets"]) == 0
    site.packages[GD09] = ("Future Pack Renamed [GD09]", ["GD09-001"])
    site.products[1] = ("Future Pack Renamed [GD09]", "March 5,2027")
    del site.packages[PB04]
    assert cli.main(["sync", "--only", "sets"]) == 0
    found = provisional()
    assert found["GD09"].name == "Future Pack Renamed" and found["PB04"].kind is SetKind.PROMO
    assert sets_json().read_bytes() == tracked


def test_the_export_still_builds_with_a_reviewed_set_bandai_does_not_list(tracked: bytes, site: Bandai) -> None:
    assert cli.main(["sync"]) == 0
    assert cli.main(["export"]) == 0
    codes = {s["code"] for s in json.loads(catalog_export_path().read_text(encoding="utf-8"))["reference"]["sets"]}
    assert {"GD01", "PB03", "GD09", "PB04"} <= codes


def test_with_no_tracked_set_list_every_set_is_proposed_and_none_is_created(site: Bandai, capsys: pytest.CaptureFixture[str]) -> None:
    sets_json().unlink()  # the root conftest's copy
    assert cli.main(["sync", "--only", "sets"]) == 0
    assert not sets_json().exists()
    assert set(provisional()) == {"GD01", "GD09", "PB04"}
    capsys.readouterr()
    assert cli.main(["sets"]) == 0
    captured = capsys.readouterr()
    assert "no tracked set list" in captured.err and "run `sync --only sets` first" not in captured.err
    assert sorted(line.split()[0] for line in captured.out.splitlines()[1:]) == ["GD01", "GD09", "PB04"]
