"""Tests never read or write the real dataset: GCG_DATA_DIR points at an empty temp folder, for the whole session and again per test.

Tests marked `real_data` run only with GCG_TEST_REAL_DATA=1, and only they then see GCG_DATA_DIR as it is (they still skip on an empty
dataset); every other test keeps its empty temp folder. This is the only place that variable is read; test modules use the marker.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from shared.dataset import ENV_VAR

pytest_plugins = ["pytester"]  # for testing this file's own hooks

REAL_DATA_VAR = "GCG_TEST_REAL_DATA"
REAL_DATA = os.environ.get(REAL_DATA_VAR) == "1"


def pytest_configure(config: pytest.Config) -> None:
    if not REAL_DATA:
        os.environ[ENV_VAR] = tempfile.mkdtemp(prefix="gcg-test-data-")  # seen by skip conditions evaluated at collection


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if REAL_DATA:
        return
    skip = pytest.mark.skip(reason=f"real-data test: set {REAL_DATA_VAR}=1 to run it")
    for item in items:
        if item.get_closest_marker("real_data") is not None:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _empty_dataset(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path | None:
    if REAL_DATA and request.node.get_closest_marker("real_data") is not None:
        return None
    folder = tmp_path_factory.mktemp("gcg-data")
    monkeypatch.setenv(ENV_VAR, str(folder))
    return folder
