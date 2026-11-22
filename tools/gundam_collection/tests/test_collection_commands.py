"""The collection commands read the collection file (or the text list until it exists) and never write either."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, PrintingId, ProductId
from tools.gundam_cards.build import CatalogResult
from tools.gundam_cards.models import CardPrice, PriceFile
from tools.gundam_cards.store import write_catalog, write_prices
from tools.gundam_collection import cli
from tools.gundam_collection.collection_file import ENV_VAR, text_list_path
from tools.gundam_packages.tests.helpers import unit

NOW = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """No packages are built (the tracked ones describe the real catalog). ST01-001 with an alternate printing ST01-001_p5 priced at $0.25 as a card, and GD01-001 with no price."""
    monkeypatch.setattr(cli, "load_packages", lambda *a, **k: None)
    monkeypatch.setattr(cli, "load_rates", lambda *a, **k: None)
    first = unit("ST01-001", "Gundam")
    alternate = first.printings[0].model_copy(update={"id": PrintingId("ST01-001_p5"), "variant": 5, "alt_art_level": 1})
    write_catalog(CatalogResult(cards=(first.model_copy(update={"printings": (*first.printings, alternate)}), unit("GD01-001", "Zaku")),
                                issues=(), trait_vocabulary=frozenset()), NOW)  # fmt: skip
    row = CardPrice(card_number=CardNumber("ST01-001"), price_cents=25, product_id=ProductId(7), fetched_at=NOW)
    write_prices(PriceFile(generated_at=NOW, source_updated_at=NOW, data=(row,)), None)


def write_file(monkeypatch: pytest.MonkeyPatch, folder: Path, counts: dict[str, object], **top: object) -> Path:
    path = folder / "collection.json"
    path.write_text(json.dumps({"schema_version": 1, "updated_at": "2026-11-22T00:00:00Z", "counts": counts, **top}), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(path))
    return path


def write_text_list(text: str) -> Path:
    text_list_path().parent.mkdir(parents=True, exist_ok=True)
    text_list_path().write_text(text, encoding="utf-8")
    return text_list_path()


def test_the_counts_in_the_file_are_what_the_commands_report_as_owned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_file(monkeypatch, tmp_path, {"ST01-001": 2, "ST01-001_p5": 1})
    before = path.read_bytes()
    assert cli.main(["card", "ST01-001"]) == 0
    captured = capsys.readouterr()
    assert "owned:  3 copies" in captured.out
    assert "not in the catalog" not in captured.err  # a well-formed file with known ids reports nothing of the kind
    assert path.read_bytes() == before and [p.name for p in tmp_path.iterdir()] == ["collection.json"]  # unchanged, nothing beside it


def test_a_card_owned_only_as_an_alternate_counts_as_the_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_file(monkeypatch, tmp_path, {"ST01-001_p5": 1})
    assert cli.main(["card", "ST01-001"]) == 0
    assert "owned:  1 copies" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["card", "ST01-001"], ["value"], ["coverage"], ["decks"], ["buy", "x"], ["deck", "x"], ["archetypes"], ["suggest", "x"]])
@pytest.mark.parametrize(
    ("counts", "top", "named"),
    [({"ST01-001": 1}, {"schema_version": 2}, "schema_version is 2"), ({"ST01-001": 0}, {}, "ST01-001: the count must be 1 or more")],
)
def test_a_refused_file_stops_every_collection_command_without_the_text_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    argv: list[str], counts: dict[str, object], top: dict[str, object], named: str,
) -> None:  # fmt: skip
    path = write_file(monkeypatch, tmp_path, counts, **top)
    text = write_text_list("ST01-001 5\n")
    assert cli.main(argv) != 0
    captured = capsys.readouterr()
    assert named in captured.err and str(path) in captured.err
    assert "owned" not in captured.out and "text list" not in captured.err  # nothing was read, no fallback
    assert text.read_text(encoding="utf-8") == "ST01-001 5\n"


def test_a_file_that_is_not_json_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "collection.json"
    path.write_text("{oops", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(path))
    assert cli.main(["value"]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_an_unknown_printing_id_is_named_once_and_the_rest_is_used_without_changing_the_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_file(monkeypatch, tmp_path, {"ST01-001": 2, "ST01-001_p9": 1, "ZZ99-999": 3})
    assert cli.main(["card", "ST01-001"]) == 0
    captured = capsys.readouterr()
    assert "owned:  2 copies" in captured.out
    assert [line for line in captured.err.splitlines() if "ST01-001_p9" in line] == ["note: ST01-001_p9 in the collection file is not in the catalog and was left out"]
    assert captured.err.count("ZZ99-999") == 1


def test_with_no_collection_file_the_text_list_is_read_read_only_and_the_notice_counts_the_markers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = write_text_list("ST01-001 2\nST01-001+ 1\nGD01-001LK 1\n")
    folder = text.parent
    before = sorted(p.name for p in folder.iterdir())
    assert cli.main(["card", "ST01-001"]) == 0
    captured = capsys.readouterr()
    assert "owned:  3 copies" in captured.out  # the marker line counts as the base printing
    notices = [line for line in captured.err.splitlines() if "text list" in line]
    assert len(notices) == 1 and "2 marker lines" in notices[0]
    assert text.read_text(encoding="utf-8") == "ST01-001 2\nST01-001+ 1\nGD01-001LK 1\n"
    assert sorted(p.name for p in folder.iterdir()) == before and not Path(tmp_path / "collection.json").exists()


def test_when_the_file_exists_the_text_list_is_not_read_and_the_two_are_never_merged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_file(monkeypatch, tmp_path, {"ST01-001": 1})
    write_text_list("ST01-001 4\nGD01-001 3\n")
    assert cli.main(["card", "GD01-001"]) == 0
    captured = capsys.readouterr()
    assert "owned:  0 copies" in captured.out and "text list" not in captured.err
    assert cli.main(["card", "ST01-001"]) == 0
    assert "owned:  1 copies" in capsys.readouterr().out


def test_import_points_to_the_ui_writes_nothing_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["import"]) == 0  # neither file exists
    assert "UI" in capsys.readouterr().out
    text = write_text_list("ST01-001 2\n")
    path = write_file(monkeypatch, tmp_path, {"ST01-001": 1})
    assert cli.main(["import"]) == 0
    assert "UI" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8").count("ST01-001") == 1 and text.read_text(encoding="utf-8") == "ST01-001 2\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["collection.json"] and sorted(p.name for p in text.parent.iterdir()) == ["my_tcg_collection"]


def test_value_prices_an_owned_alternate_with_no_price_of_its_own_at_its_cards_price(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_file(monkeypatch, tmp_path, {"ST01-001": 1, "ST01-001_p5": 2})
    assert cli.main(["value"]) == 0
    out = capsys.readouterr().out
    assert "my collection: 1 cards, 3 copies, worth $0.75" in out  # 3 x $0.25: the alternate is valued as the card
    assert "owned cards have no price" not in out


def test_value_prices_a_printing_at_its_own_price_when_the_store_gives_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The store's rule (`export.printing_prices`) gives the same cents as the card's price today, so the store is stood in for here:
    # it gives the alternate its own price of $50.00, and the command must use it rather than the card's $0.25.
    monkeypatch.setattr(cli, "prices_of_printings", lambda card, rows: {PrintingId("ST01-001_p5"): (5000, date(2026, 10, 9))} if card.number == "ST01-001" else {})
    write_file(monkeypatch, tmp_path, {"ST01-001": 1, "ST01-001_p5": 2})
    assert cli.main(["value"]) == 0
    out = capsys.readouterr().out
    assert "my collection: 1 cards, 3 copies, worth $100.25" in out  # 1 x $0.25 + 2 x $50.00
    assert "ST01-001_p5)" in out and "$50.00" in out


def test_with_no_collection_at_all_the_commands_say_where_it_would_be(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["value"]) == 2
    assert "no collection yet" in capsys.readouterr().err


def test_check_and_the_fallback_read_the_same_text_list(capsys: pytest.CaptureFixture[str]) -> None:
    write_text_list("ST01-001 2\nST01-001+ 1\n")  # under GCG_TOOL_DATA_DIR
    assert cli.main(["check"]) == 0
    assert "2 lines read, 1 distinct cards, 3 copies counted" in capsys.readouterr().out
    assert cli.main(["card", "ST01-001"]) == 0
    assert "owned:  3 copies" in capsys.readouterr().out
