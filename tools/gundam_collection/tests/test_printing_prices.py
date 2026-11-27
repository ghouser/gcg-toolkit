"""refresh-prices AC-3: `value`, `buy` (with its Mass Entry export) and `suggest` print the same over a per-printing price snapshot as over the
old per-card one, and read only the newest per-printing snapshot. The commands run through `main` over the packages fixture dataset."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.dataset import ENV_VAR
from shared.test_read_commands_on_dataset import packages_dataset_tree, write_collection_file
from tools.gundam_cards.models import PrintingPrice, PrintingPriceFile
from tools.gundam_cards.store import load_catalog_or_fail, load_prices, write_printing_prices
from tools.gundam_collection import cli as collection_cli
from tools.gundam_collection.tests.test_data_folders import COLLECTION, tool_data

COMMANDS = (
    ["value"],
    ["buy", "amuro", "--min-rate", "0"],
    ["buy", "amuro", "--min-rate", "0", "--export"],
    ["suggest", "amuro", "aggro", "BW", "--pool", "0"],
)


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(ENV_VAR, str(packages_dataset_tree(tmp_path / "dataset")))
    write_collection_file(tmp_path, monkeypatch)
    return tool_data(tmp_path / "tool-data", monkeypatch)


def run_all(temp: Path, capsys: pytest.CaptureFixture[str]) -> list[tuple[int, str]]:
    """Every command's exit code and output, and the text of the Mass Entry export the third one writes."""
    outputs: list[tuple[int, str]] = []
    for argv in COMMANDS:
        capsys.readouterr()
        code = collection_cli.main(argv)
        outputs.append((code, capsys.readouterr().out))
    outputs.append((0, (temp / COLLECTION / "buy_amuro.txt").read_text(encoding="utf-8")))
    return outputs


def per_printing_snapshot_of_the_per_card_one() -> PrintingPriceFile:
    """The per-printing snapshot that says what the dataset's per-card snapshot says: each card's price on its first non-alt-art printing."""
    old = load_prices()
    assert old is not None
    cards = {c.number: c for c in load_catalog_or_fail().data}
    rows = []
    for price in old.data:
        printing = next(p for p in cards[price.card_number].printings if not p.alt_art)
        rows.append(
            PrintingPrice(
                printing_id=printing.id,
                price_cents=price.price_cents,
                product_id=price.product_id,
                name=price.name,
                set_code=price.set_code,
                alt_art_level=0,
                fetched_at=price.fetched_at,
            )
        )
    return PrintingPriceFile(generated_at=old.generated_at, source_updated_at=old.source_updated_at, data=tuple(rows))


def test_value_buy_buy_export_and_suggest_print_the_same_over_a_per_printing_snapshot(
    temp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = run_all(temp, capsys)
    assert [code for code, _ in before] == [0, 0, 0, 0, 0]
    assert (
        "$" in before[0][1] and "$" in before[1][1] and "[GD01]" in before[-1][1]
    )  # prices and the Mass Entry names and set codes were in play
    snapshot = per_printing_snapshot_of_the_per_card_one()
    assert write_printing_prices(snapshot) is not None
    assert run_all(temp, capsys) == before
