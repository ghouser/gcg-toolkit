"""Tests never read or write the real dataset: GCG_DATA_DIR points at an empty temp folder, for the whole session and again per test.

The real-data ("corpus") tests run only with GCG_TEST_REAL_DATA=1, which leaves GCG_DATA_DIR as it is (they skip on an empty dataset).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from shared.dataset import ENV_VAR

REAL_DATA = os.environ.get("GCG_TEST_REAL_DATA") == "1"


def pytest_configure(config: pytest.Config) -> None:
    if not REAL_DATA:
        os.environ[ENV_VAR] = tempfile.mkdtemp(prefix="gcg-test-data-")  # seen by skip conditions evaluated at collection


@pytest.fixture(autouse=True)
def _empty_dataset(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path | None:
    if REAL_DATA:
        return None
    folder = tmp_path_factory.mktemp("gcg-data")
    monkeypatch.setenv(ENV_VAR, str(folder))
    return folder
