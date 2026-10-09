from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.basetypes import PackageId, PrintingId
from tools.gundam_cards.build import SourcePage
from tools.gundam_cards.parse_detail import RawDetail, parse_detail_html

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def load_raw(printing_id: str) -> RawDetail:
    return parse_detail_html((FIXTURES / f"{printing_id}.html").read_text(encoding="utf-8"))


@pytest.fixture
def raw() -> Callable[[str], RawDetail]:
    return load_raw


@pytest.fixture
def page() -> Callable[[str], SourcePage]:
    def _page(printing_id: str) -> SourcePage:
        return SourcePage(PrintingId(printing_id), load_raw(printing_id), FETCHED_AT, (PackageId("616001"),))

    return _page
