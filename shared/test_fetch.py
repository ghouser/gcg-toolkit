"""Tests for the cached, rate-limited fetcher, using a real local HTTP server (no internet)."""
from __future__ import annotations

import socketserver
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from shared.fetch import FetchError, Fetcher


class _Handler(BaseHTTPRequestHandler):
    hits: dict[str, int] = {}

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self.hits[self.path] = self.hits.get(self.path, 0) + 1
        if self.path == "/ok":
            body = "héllo".encode()
            self.send_response(200)
        elif self.path == "/flaky" and self.hits[self.path] < 3:
            body = b"try again"
            self.send_response(503)
        elif self.path == "/flaky":
            body = b"finally"
            self.send_response(200)
        else:
            body = b"nope"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # silence test output
        return


class _Server(HTTPServer):
    def server_bind(self) -> None:
        # HTTPServer.server_bind does a reverse-DNS lookup (socket.getfqdn) that takes ~35s on some machines.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), port


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.hits = {}
    httpd = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _fetcher(cache: Path | None, sleeps: list[float], min_interval_s: float = 0.5) -> Fetcher:
    clock = {"t": 0.0}

    def fake_sleep(s: float) -> None:
        sleeps.append(s)
        clock["t"] += s

    return Fetcher(cache, min_interval_s=min_interval_s, sleep=fake_sleep, monotonic=lambda: clock["t"])


def test_cache_hit_makes_no_second_request(server: str, tmp_path: Path) -> None:
    f = _fetcher(tmp_path, [])
    first = f.get_text(f"{server}/ok", cache_key="a/b.html")
    second = f.get_text(f"{server}/ok", cache_key="a/b.html")
    assert (first.text, first.from_cache) == ("héllo", False)
    assert (second.text, second.from_cache) == ("héllo", True)
    assert _Handler.hits["/ok"] == 1 and f.network_requests == 1
    assert (tmp_path / "a" / "b.html").read_text(encoding="utf-8") == "héllo"


def test_force_refetches(server: str, tmp_path: Path) -> None:
    f = _fetcher(tmp_path, [])
    f.get_text(f"{server}/ok", cache_key="x.html")
    f.get_text(f"{server}/ok", cache_key="x.html", force=True)
    assert _Handler.hits["/ok"] == 2


def test_rate_limit_waits_between_network_requests_only(server: str, tmp_path: Path) -> None:
    sleeps: list[float] = []
    f = _fetcher(tmp_path, sleeps, min_interval_s=0.5)
    f.get_text(f"{server}/ok", cache_key="1")
    f.get_text(f"{server}/ok", cache_key="1")  # cache hit: no wait
    f.get_text(f"{server}/ok", cache_key="2")
    assert sleeps == [0.5]


def test_retries_transient_errors_with_backoff(server: str) -> None:
    sleeps: list[float] = []
    f = _fetcher(None, sleeps, min_interval_s=0.0)
    assert f.get_text(f"{server}/flaky").text == "finally"
    assert _Handler.hits["/flaky"] == 3
    assert sleeps == [2.0, 4.0]


def test_non_retryable_error_raises_and_is_not_cached(server: str, tmp_path: Path) -> None:
    f = _fetcher(tmp_path, [])
    with pytest.raises(FetchError) as info:
        f.get_text(f"{server}/missing", cache_key="m.html")
    assert info.value.status == 404
    assert not (tmp_path / "m.html").exists()


@pytest.mark.parametrize("bad", ["../escape", "/abs/path", ""])
def test_unsafe_cache_keys_rejected(bad: str, tmp_path: Path) -> None:
    f = _fetcher(tmp_path, [])
    with pytest.raises(ValueError):
        f.get_text("http://127.0.0.1:9/x", cache_key=bad)
