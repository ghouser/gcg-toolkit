"""Cached, rate-limited HTTP fetcher. All network access in this repo goes through here.

- Identifies itself with a descriptive User-Agent.
- Waits `min_interval_s` between real network requests (cache hits are free and never wait).
- Caches successful responses on disk under `cache_dir/<cache_key>`; a cached key is never re-fetched unless `force=True`.
- Retries transient failures (429, 5xx, connection errors) with exponential backoff, then raises `FetchError`.
- Cache writes are atomic (temp file, then rename).
"""
from __future__ import annotations

import os
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

DEFAULT_USER_AGENT = "gcg-toolkit/0.1 (personal hobby tooling; polite rate-limited fetcher)"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class FetchError(Exception):
    def __init__(self, url: str, detail: str, status: int | None = None) -> None:
        super().__init__(f"{url}: {detail}")
        self.url = url
        self.status = status


@dataclass(frozen=True)
class Response:
    url: str
    text: str
    fetched_at: datetime  # when the content was fetched (file mtime for cache hits)
    from_cache: bool


class TextFetcher(Protocol):
    """What code that needs pages depends on, so tests can pass a fake instead of the network."""

    def get_text(self, url: str, *, cache_key: str | None = None, force: bool = False) -> Response: ...


class HeaderTextFetcher(TextFetcher, Protocol):
    """A fetcher that can also send request headers (for an API that needs an `Authorization` header)."""

    def get_text(
        self, url: str, *, cache_key: str | None = None, force: bool = False, headers: Mapping[str, str] | None = None
    ) -> Response: ...


class Fetcher:
    def __init__(
        self,
        cache_dir: Path | None,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_s: float = 0.5,
        timeout_s: float = 30.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache_dir = cache_dir
        self._user_agent = user_agent
        self._min_interval_s = min_interval_s
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self.network_requests = 0  # for tests and run reports

    def get_text(
        self, url: str, *, cache_key: str | None = None, force: bool = False, headers: Mapping[str, str] | None = None
    ) -> Response:
        """GET `url` as text. With a `cache_key`, a cached copy is returned without any network request.

        `headers` are sent with the request (never cached, never logged: a header may be a credential)."""
        path = self._cache_path(cache_key)
        if path is not None and not force and path.is_file():
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            return Response(url, path.read_text(encoding="utf-8"), mtime, from_cache=True)
        text = self._request(url, headers)
        fetched_at = datetime.now(tz=UTC)
        if path is not None:
            _atomic_write(path, text)
        return Response(url, text, fetched_at, from_cache=False)

    def _cache_path(self, cache_key: str | None) -> Path | None:
        if cache_key is None:
            return None
        if self._cache_dir is None:
            raise ValueError("cache_key given but this Fetcher has no cache_dir")
        key = PurePosixPath(cache_key)
        if key.is_absolute() or ".." in key.parts or not key.parts:
            raise ValueError(f"unsafe cache key: {cache_key!r}")
        return self._cache_dir.joinpath(*key.parts)

    def _wait_turn(self) -> None:
        if self._last_request_at is not None:
            remaining = self._min_interval_s - (self._monotonic() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _request(self, url: str, headers: Mapping[str, str] | None = None) -> str:
        last_detail = "no attempt made"
        for attempt in range(1, self._max_attempts + 1):
            self._wait_turn()
            self.network_requests += 1
            request = urllib.request.Request(url, headers={**(headers or {}), "User-Agent": self._user_agent})
            try:
                with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                    body: bytes = response.read()
                return body.decode("utf-8")
            except urllib.error.HTTPError as e:
                if e.code not in _RETRYABLE_STATUS:
                    raise FetchError(url, f"HTTP {e.code}", e.code) from e
                last_detail = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_detail = f"{type(e).__name__}: {e}"
            if attempt < self._max_attempts:
                self._sleep(2.0**attempt)
        raise FetchError(url, f"gave up after {self._max_attempts} attempts ({last_detail})")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
