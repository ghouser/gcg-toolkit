"""The `real_data` marker: a marked test runs only with GCG_TEST_REAL_DATA=1 and is then the only kind that sees the real dataset.

With the variable unset nothing sees the real dataset, not even code run at collection (module level, `skipif` conditions); with it
set, the repo's real-data tests skip rather than fail on an empty dataset.
"""
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

# Read when the module is imported, as the real-data modules' `skipif` conditions are.
COLLECTION_MODULE = """
import os

import pytest

AT_COLLECTION = os.environ["GCG_DATA_DIR"]

@pytest.mark.skipif(os.environ["GCG_DATA_DIR"] == os.environ["OUTER_DATA_DIR"], reason="saw the real dataset at collection")
def test_collection_saw_an_empty_dataset() -> None:
    assert AT_COLLECTION != os.environ["OUTER_DATA_DIR"]
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


@pytest.mark.parametrize("value", [None, "yes"])
def test_with_the_variable_not_1_collection_never_sees_the_real_dataset(
    project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("GCG_TEST_REAL_DATA", raising=False)
    else:
        monkeypatch.setenv("GCG_TEST_REAL_DATA", value)
    project.makepyfile(test_collection=COLLECTION_MODULE)
    result = project.runpytest_subprocess("test_collection.py", "-rs")
    result.assert_outcomes(passed=1)  # a skip here means the skipif condition saw the real dataset


def test_a_real_data_test_is_skipped_when_the_variable_is_not_1(project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_TEST_REAL_DATA", "yes")
    project.runpytest_subprocess().assert_outcomes(passed=1, skipped=1)


def test_with_the_variable_1_the_real_data_test_runs_on_the_dataset_and_the_others_keep_an_empty_one(project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCG_TEST_REAL_DATA", "1")
    project.runpytest_subprocess().assert_outcomes(passed=2)


def test_with_the_variable_1_the_repos_real_data_tests_skip_and_do_not_fail_on_an_empty_dataset(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCG_TEST_REAL_DATA", "1")
    monkeypatch.setenv("GCG_DATA_DIR", str(pytester.mkdir("empty-dataset")))
    result = pytester.runpytest_subprocess(str(REPO), "-m", "real_data", "-p", "no:cacheprovider")
    outcomes = result.parseoutcomes()
    assert outcomes.get("failed", 0) == 0 and outcomes.get("errors", 0) == 0, result.stdout.str()
    assert outcomes.get("skipped", 0) > 0  # the real-data tests were collected and skipped, not silently deselected
