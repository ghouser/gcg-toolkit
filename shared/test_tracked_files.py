"""AC-5: the source data is no longer tracked by git and is ignored; the set list, the restrictions file and the analysis outputs stay
tracked. Skipped outside a git checkout."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)


pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or _git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true", reason="not inside a git checkout"
)

CARDS, META, PACKAGES = "shared/data/gundam_cards", "shared/data/gundam_meta", "shared/data/gundam_packages"

# The moved sources; a folder is checked through a file that could be stored in it.
MOVED = (
    f"{CARDS}/cards.json",
    f"{CARDS}/traits.json",
    f"{CARDS}/source_titles.json",
    f"{CARDS}/prices.json",
    f"{CARDS}/prices/2026-10-09T210000Z.json",
    f"{META}/events/egm/an-event.json",
    f"{META}/online_rankings/2026-10-09T210000Z.json",
    f"{META}/example_decks/2026-10-09T210000Z.json",
)
MOVED_FOLDERS = (f"{CARDS}/prices", f"{META}/events", f"{META}/online_rankings", f"{META}/example_decks")
KEPT = (f"{CARDS}/sets.json", f"{CARDS}/restrictions.json")
ANALYSIS = (
    f"{PACKAGES}/packages.json",
    f"{PACKAGES}/packages_online.json",
    f"{PACKAGES}/rates.json",
    f"{PACKAGES}/rates_online.json",
    f"{PACKAGES}/drift.json",
    f"{PACKAGES}/gd05_meta_report.md",
    f"{META}/popularity.json",
)


@pytest.mark.parametrize("path", MOVED)
def test_moved_source_data_is_untracked_and_ignored(path: str) -> None:
    assert _git("ls-files", "--", path).stdout == ""
    assert _git("check-ignore", "--no-index", "-q", path).returncode == 0


@pytest.mark.parametrize("folder", MOVED_FOLDERS)
def test_nothing_in_a_moved_folder_is_tracked(folder: str) -> None:
    assert _git("ls-files", "--", folder).stdout == ""


@pytest.mark.parametrize("path", KEPT + ANALYSIS)
def test_the_set_list_restrictions_and_analysis_outputs_stay_tracked(path: str) -> None:
    assert _git("ls-files", "--error-unmatch", "--", path).returncode == 0
