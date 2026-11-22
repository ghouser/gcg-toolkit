"""Tests never read or write the real dataset: GCG_DATA_DIR points at an empty temp folder, for the whole session and again per test.

Tests marked `real_data` run only with GCG_TEST_REAL_DATA=1, and only they then see GCG_DATA_DIR as it is (they still skip on an empty
dataset); every other test keeps its empty temp folder. This is the only place that variable is read; test modules use the marker.

No test writes the real catalog export: GCG_CATALOG_FILE points at a temp file for every test, real-data ones included.

No test reads the real collection file: GCG_COLLECTION_FILE points at a temp path (absent unless the test writes it) for every test,
real-data ones included.

No test touches the cards and meta tools' real raw caches or tracked files: GCG_TOOL_DATA_DIR points at a temp folder, handled like
GCG_DATA_DIR (real-data tests see it as it is). Each test's folder holds a copy of the tracked set list and restrictions file, the
tracked inputs that tests read; a test that writes them writes the copy.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from shared.dataset import ENV_VAR, REPO_ROOT, TOOL_DATA_VAR
from tools.gundam_cards.store import CATALOG_FILE_VAR
from tools.gundam_collection.collection_file import ENV_VAR as COLLECTION_FILE_VAR

pytest_plugins = ["pytester"]  # for testing this file's own hooks

REAL_DATA_VAR = "GCG_TEST_REAL_DATA"
REAL_DATA = os.environ.get(REAL_DATA_VAR) == "1"
TRACKED_INPUTS = ("shared/data/gundam_cards/sets.json", "shared/data/gundam_cards/restrictions.json")


def _tool_data_folder(folder: Path) -> Path:
    """A stand-in for the repository's tool data folders, holding copies of the tracked inputs."""
    for relative in TRACKED_INPUTS:
        if (REPO_ROOT / relative).is_file():
            (folder / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, folder / relative)
    return folder


def pytest_configure(config: pytest.Config) -> None:
    if not REAL_DATA:
        os.environ[ENV_VAR] = tempfile.mkdtemp(prefix="gcg-test-data-")  # seen by skip conditions evaluated at collection
        os.environ[TOOL_DATA_VAR] = str(_tool_data_folder(Path(tempfile.mkdtemp(prefix="gcg-test-tool-data-"))))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if REAL_DATA:
        return
    skip = pytest.mark.skip(reason=f"real-data test: set {REAL_DATA_VAR}=1 to run it")
    for item in items:
        if item.get_closest_marker("real_data") is not None:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _empty_dataset(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path | None:
    monkeypatch.setenv(CATALOG_FILE_VAR, str(tmp_path_factory.mktemp("gcg-export") / "catalog.json"))
    monkeypatch.setenv(COLLECTION_FILE_VAR, str(tmp_path_factory.mktemp("gcg-collection") / "collection.json"))
    if REAL_DATA and request.node.get_closest_marker("real_data") is not None:
        return None
    folder = tmp_path_factory.mktemp("gcg-data")
    monkeypatch.setenv(ENV_VAR, str(folder))
    monkeypatch.setenv(TOOL_DATA_VAR, str(_tool_data_folder(tmp_path_factory.mktemp("gcg-tool-data"))))
    return folder
