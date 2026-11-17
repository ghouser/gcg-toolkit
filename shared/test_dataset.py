"""The dataset location and the shared snapshot rule (AC-2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from shared.dataset import Kind, NoData, add_snapshot, data_dir, newest_snapshot


def test_the_dataset_is_gcg_data_dir_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_DATA_DIR", str(tmp_path / "elsewhere"))
    assert data_dir() == tmp_path / "elsewhere"


def test_the_dataset_defaults_to_dot_gcg_data_in_the_home_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCG_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert data_dir() == tmp_path / ".gcg" / "data"


def test_the_dataset_is_never_inside_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("GCG_DATA_DIR", raising=False)
    assert repo not in data_dir().resolve().parents


def test_a_snapshot_is_added_once_and_earlier_ones_are_untouched(tmp_path: Path) -> None:
    never_same = lambda old: False  # noqa: E731
    first = add_snapshot(tmp_path, "2026-10-01T000000Z", "one\n", never_same)
    assert first is not None and first.read_text() == "one\n"
    assert add_snapshot(tmp_path, "2026-10-01T000000Z", "changed\n", never_same) is None  # same date: not rewritten
    assert first.read_text() == "one\n"
    second = add_snapshot(tmp_path, "2026-10-02T000000Z", "two\n", never_same)
    assert second is not None and newest_snapshot(tmp_path) == second and first.read_text() == "one\n"


def test_data_identical_to_the_newest_adds_nothing(tmp_path: Path) -> None:
    add_snapshot(tmp_path, "2026-10-01T000000Z", "same\n", lambda old: False)
    assert add_snapshot(tmp_path, "2026-10-02T000000Z", "same\n", lambda old: old == "same\n") is None
    assert [p.name for p in tmp_path.iterdir()] == ["2026-10-01T000000Z.json"]


def test_no_data_names_the_source() -> None:
    assert str(NoData(Kind.PRICES)).startswith("no data: prices")
