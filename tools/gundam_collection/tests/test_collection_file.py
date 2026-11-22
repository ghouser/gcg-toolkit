"""The collection file reader: the schema, what is refused, the text-list fallback, and the card and printing views."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.basetypes import PrintingId
from shared.dataset import REPO_ROOT, TOOL_DATA_VAR
from tools.gundam_collection.collection_file import (
    ENV_VAR,
    CollectionRefused,
    Source,
    collection_file_path,
    parse_collection_file,
    parse_text_list,
    read_owned,
    text_list_path,
)

P = PrintingId
EXAMPLE = REPO_ROOT / "docs" / "collection-file.example.json"
KNOWN = {P("ST01-001"), P("ST01-001_p5"), P("GD02-041"), P("R-001_p4")}


def doc(**changes: object) -> str:
    base: dict[str, object] = {"schema_version": 1, "updated_at": "2026-11-22T18:30:00Z", "counts": {"ST01-001": 2}}
    return json.dumps({**base, **changes})


def test_the_documented_example_is_a_valid_file() -> None:
    assert parse_collection_file(EXAMPLE.read_text(encoding="utf-8")) == {P("ST01-001"): 2, P("ST01-001_p5"): 1, P("GD02-041"): 4}


def test_an_unsupported_version_is_refused_naming_the_version_found_and_those_supported() -> None:
    with pytest.raises(CollectionRefused, match=r"schema_version is 2; .*supports version 1"):
        parse_collection_file(doc(schema_version=2))


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "not a JSON object"),
        (doc(schema_version=True), "schema_version"),
        (doc(updated_at=None), "updated_at"),
        (doc(updated_at="yesterday"), "updated_at"),
        (doc(counts=[]), "counts"),
        (doc(counts={"ST01-001": 0}), "ST01-001: the count must be 1 or more"),
        (doc(counts={"ST01-001": -1}), "1 or more"),
        (doc(counts={"ST01-001": None}), "ST01-001: the count must be an integer"),
        (doc(counts={"ST01-001": 1.5}), "must be an integer"),
        (doc(counts={"ST01-001": 2.0}), "must be an integer"),
        (doc(counts={"ST01-001": "2"}), "must be an integer"),
        (doc(counts={"ST01-001": True}), "must be an integer"),
        (doc(counts={"st01-001": 1}), "'st01-001' is not a printing id"),
        (doc(counts={"ST01-001_p": 1}), "is not a printing id"),
    ],
)
def test_a_file_that_is_invalid_in_any_other_way_is_refused_naming_the_problem(text: str, problem: str) -> None:
    with pytest.raises(CollectionRefused, match=problem):
        parse_collection_file(text)


def test_an_empty_collection_and_unknown_extra_fields_are_valid() -> None:
    assert parse_collection_file(doc(counts={}, note="hi")) == {}


def test_the_path_is_read_from_the_environment_each_time(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "a.json"))
    assert collection_file_path() == tmp_path / "a.json"
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "b.json"))
    assert collection_file_path() == tmp_path / "b.json"
    monkeypatch.delenv(ENV_VAR)
    assert collection_file_path() == Path.home() / ".gcg" / "collection.json"


def test_counts_are_printing_to_count_with_card_totals_adding_up_printings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(doc(counts={"ST01-001": 2, "ST01-001_p5": 1, "GD02-041": 4}), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(path))
    owned = read_owned(KNOWN)
    assert owned.source is Source.FILE and owned.unknown == ()
    assert owned.printings == {P("ST01-001"): 2, P("ST01-001_p5"): 1, P("GD02-041"): 4}
    assert owned.cards == {"ST01-001": 3, "GD02-041": 4}  # any printing is the card; copies of printings add up


def test_an_alternate_alone_counts_as_its_card(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(doc(counts={"ST01-001_p5": 1}), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(path))
    assert read_owned(KNOWN).cards == {"ST01-001": 1}


def test_ids_the_catalog_does_not_know_are_set_apart_once_each_and_the_rest_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(doc(counts={"ST01-001": 2, "ST01-001_p9": 1, "ZZ99-999": 3}), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(path))
    owned = read_owned(KNOWN)
    assert owned.unknown == (P("ST01-001_p9"), P("ZZ99-999")) and owned.printings == {P("ST01-001"): 2}


def test_an_invalid_file_is_refused_with_its_path_and_the_text_list_is_not_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = tmp_path / "c.json"
    bad.write_text(doc(counts={"ST01-001": 0}), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(bad))
    monkeypatch.setenv(TOOL_DATA_VAR, str(tmp_path / "tool"))
    text_list_path().parent.mkdir(parents=True)
    text_list_path().write_text("ST01-001 2\n", encoding="utf-8")
    with pytest.raises(CollectionRefused, match=str(bad)):
        read_owned(KNOWN)


def test_a_file_is_read_and_never_changed_nor_joined_by_other_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "ui"
    folder.mkdir()
    path = folder / "collection.json"
    path.write_text(doc(counts={"ST01-001": 2}), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setenv(ENV_VAR, str(path))
    read_owned(KNOWN)
    assert path.read_bytes() == before and [p.name for p in folder.iterdir()] == ["collection.json"]


def test_the_text_list_is_the_fallback_and_every_line_is_a_base_printing_counting_the_markers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(TOOL_DATA_VAR, str(tmp_path))
    text_list_path().parent.mkdir(parents=True)
    text_list_path().write_text("# mine\nST01-001 2\n2 GD02-041+\nGD02-041LK x1\nST01-001 ?\nXX01-001 5\n", encoding="utf-8")
    owned = read_owned(KNOWN)
    assert owned.source is Source.TEXT_LIST and owned.markers == 2
    assert owned.printings == {P("GD02-041"): 3, P("ST01-001"): 2}
    assert owned.unknown == (P("XX01-001"),)


def test_with_neither_file_nothing_is_owned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(TOOL_DATA_VAR, str(tmp_path))
    owned = read_owned(KNOWN)
    assert owned.source is Source.NONE and owned.printings == {} and owned.cards == {}


def test_text_list_lines_that_count_as_nothing() -> None:
    assert parse_text_list("ST01-001 0\nhello\nST01-001 ?\n\n") == ({}, 0)
