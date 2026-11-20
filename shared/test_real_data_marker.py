"""The `real_data` marker: a marked test runs only with GCG_TEST_REAL_DATA=1 and is then the only kind that sees the real dataset."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

MODULE = """
import os

import pytest

@pytest.mark.real_data
def test_reads_the_real_dataset() -> None:
    assert os.environ["GCG_DATA_DIR"] == os.environ["OUTER_DATA_DIR"]

def test_uses_small_fixtures() -> None:
    assert os.environ["GCG_DATA_DIR"] != os.environ["OUTER_DATA_DIR"]
"""


@pytest.fixture
def project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    pytester.makeconftest((REPO / "conftest.py").read_text())
    pytester.makeini("[pytest]\nmarkers =\n    real_data: reads the real local dataset\n")
    pytester.makepyfile(test_example=MODULE)
    monkeypatch.setenv("PYTHONPATH", str(REPO))  # the conftest imports shared.dataset
    real = pytester.mkdir("real-dataset")
    monkeypatch.setenv("GCG_DATA_DIR", str(real))  # stands in for the real dataset
    monkeypatch.setenv("OUTER_DATA_DIR", str(real))
    return pytester


def test_a_real_data_test_is_skipped_when_the_variable_is_unset(project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCG_TEST_REAL_DATA", raising=False)
    result = project.runpytest_subprocess("-rs")
    result.assert_outcomes(passed=1, skipped=1)
    result.stdout.fnmatch_lines(["*real-data test: set GCG_TEST_REAL_DATA=1 to run it*"])


def test_a_real_data_test_is_skipped_when_the_variable_is_not_1(project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_TEST_REAL_DATA", "yes")
    project.runpytest_subprocess().assert_outcomes(passed=1, skipped=1)


def test_with_the_variable_1_the_real_data_test_runs_on_the_dataset_and_the_others_keep_an_empty_one(project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_TEST_REAL_DATA", "1")
    project.runpytest_subprocess().assert_outcomes(passed=2)
