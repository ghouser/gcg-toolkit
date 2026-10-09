"""The CLI parses arguments sensibly (commands that touch the network or real data are covered elsewhere)."""
from __future__ import annotations

import pytest

from tools.gundam_cards.cli import main


def test_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    for command in ("sync", "refetch", "sets", "reparse", "search", "show"):
        assert command in out


@pytest.mark.parametrize(
    "argv",
    [
        ["refetch"],  # needs --card, --package or --all
        ["refetch", "--card", "ST01-001", "--all"],  # mutually exclusive
        ["search", "--kind", "spaceship"],  # not a card kind
        ["search", "--keyword", "teleport"],  # not a keyword
        ["sync", "--only", "everything"],
    ],
)
def test_bad_arguments_are_rejected(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(argv)
    assert info.value.code == 2
