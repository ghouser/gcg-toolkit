"""Edits to my_tcg_collection are picked up by the views: re-imported when newer and valid, never silently, never when it has errors."""
from __future__ import annotations

import os
from functools import partial
from pathlib import Path

import pytest

from shared.basetypes import CardNumber
from tools.gundam_cards.models import PricedCard
from tools.gundam_collection import cli
from tools.gundam_collection.store import load_collection, write_collection
from tools.gundam_packages.tests.helpers import unit

CARDS = {CardNumber("GD01-001"): PricedCard(card=unit("GD01-001", "One"), latest_tcg_price=None)}


@pytest.fixture
def where(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    source = tmp_path / "my_tcg_collection"
    monkeypatch.setattr(cli, "COLLECTION_PATH", source)
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "write_collection", partial(write_collection, out_dir=tmp_path))
    return source, tmp_path / "collection.json"


def test_a_newer_valid_file_is_imported_and_says_so(where: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    source, out = where
    source.write_text("GD01-001 3\n", encoding="utf-8")
    cli._refresh_collection(CARDS)
    assert out.is_file() and "re-imported 1 cards, 3 copies" in capsys.readouterr().err


def test_an_unchanged_file_is_not_imported_again(where: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    source, out = where
    source.write_text("GD01-001 3\n", encoding="utf-8")
    cli._refresh_collection(CARDS)
    capsys.readouterr()
    newer = out.stat().st_mtime + 10
    os.utime(source, (newer - 20, newer - 20))  # the file is older than the import
    cli._refresh_collection(CARDS)
    assert capsys.readouterr().err == ""


def test_a_file_with_errors_keeps_the_last_good_import_and_says_so(where: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    source, out = where
    source.write_text("GD01-001 3\n", encoding="utf-8")
    cli._refresh_collection(CARDS)
    capsys.readouterr()
    source.write_text("GD01-001 3\nXX99-999 1\n", encoding="utf-8")  # an unknown card
    later = out.stat().st_mtime + 10
    os.utime(source, (later, later))
    cli._refresh_collection(CARDS)
    assert "last good import is used" in capsys.readouterr().err
    collection = load_collection(out.parent)
    assert collection is not None and collection.data[0].copies == 3  # the old import stands
