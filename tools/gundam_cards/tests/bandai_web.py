"""A faked Bandai network for the command tests: `urlopen` serves the pages of a small fake site and records every url asked for,
and the real `Fetcher` (no sleeping) writes the page cache wherever the command points it."""
from __future__ import annotations

import email.message
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import pytest

from shared.fetch import Fetcher
from shared.test_tool_data_dir import _Body, bandai_pages
from tools.gundam_cards import cli
from tools.gundam_cards.printings import DETAIL_URL
from tools.gundam_cards.tests.test_catalog_refresh import FakeBandai

GD01_PACKAGE = "616101"


@dataclass
class Web:
    """The network, faked at `urlopen`: url -> page, and every url requested, in order."""

    pages: dict[str, str]
    requested: list[str] = field(default_factory=list)

    def detail_requests(self) -> list[str]:
        return [u for u in self.requested if u.startswith(DETAIL_URL.split("{}")[0])]


def install_web(monkeypatch: pytest.MonkeyPatch) -> Web:
    """Fake the network with a site of one package, GD01, listing GD01-001 and GD01-002."""
    site = FakeBandai(
        Path(), {GD01_PACKAGE: ("Newtype Rising [GD01]", ["GD01-001", "GD01-002"])}, products=[("Newtype Rising [GD01]", "July 25,2025")]
    )
    fake = Web(bandai_pages(site))

    def urlopen(request: urllib.request.Request, timeout: float) -> _Body:
        fake.requested.append(request.full_url)
        if request.full_url not in fake.pages:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", email.message.Message(), None)
        return _Body(fake.pages[request.full_url])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cli, "Fetcher", partial(Fetcher, sleep=lambda _: None))
    return fake
