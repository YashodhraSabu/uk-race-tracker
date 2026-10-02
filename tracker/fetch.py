"""Polite page fetching: identifies itself, honours robots.txt, rate limits per host."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "RunClubRaceBot/0.1 (+https://github.com/ukracetracker/uk-race-tracker)"
ROBOTS_AGENT = "RunClubRaceBot"
TIMEOUT = 20.0
MIN_DELAY = 3.0  # seconds between requests to the same host


class FetchStatus(str, Enum):
    ok = "ok"
    blocked_by_robots = "blocked_by_robots"
    http_error = "http_error"
    network_error = "network_error"
    not_html = "not_html"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: FetchStatus
    html: str | None = None
    http_status: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == FetchStatus.ok

    def describe(self) -> str:
        if self.status == FetchStatus.http_error:
            return f"HTTP {self.http_status}"
        if self.error:
            return f"{self.status.value}: {self.error}"
        return self.status.value


class Fetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_delay: float = MIN_DELAY,
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.8"},
            follow_redirects=True,
            timeout=TIMEOUT,
        )
        self._sleep = sleep
        self._clock = clock
        self._min_delay = min_delay
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def fetch(self, url: str) -> FetchResult:
        robots = self._robots_for(url)
        if robots is not None and not robots.can_fetch(ROBOTS_AGENT, url):
            return FetchResult(url, FetchStatus.blocked_by_robots)

        try:
            response = self._get(url)
        except httpx.HTTPError as exc:
            return FetchResult(url, FetchStatus.network_error, error=type(exc).__name__)

        if response.status_code >= 400:
            return FetchResult(url, FetchStatus.http_error, http_status=response.status_code)
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            return FetchResult(url, FetchStatus.not_html, http_status=response.status_code, error=content_type)
        return FetchResult(url, FetchStatus.ok, html=response.text, http_status=response.status_code)

    def _robots_for(self, url: str) -> RobotFileParser | None:
        """The parsed robots.txt for this host, or None when there are no rules to follow."""
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host in self._robots:
            return self._robots[host]

        parser: RobotFileParser | None = RobotFileParser()
        try:
            response = self._get(f"{host}/robots.txt")
        except httpx.HTTPError:
            parser.disallow_all = True  # can't read the rules, so don't crawl
        else:
            if response.status_code >= 500:
                parser.disallow_all = True
            elif response.status_code >= 400:
                parser = None  # no robots.txt: no restrictions
            else:
                parser.parse(response.text.splitlines())
        self._robots[host] = parser
        return parser

    def _get(self, url: str) -> httpx.Response:
        host = urlsplit(url).netloc
        delay = self._min_delay
        robots = self._robots.get(f"{urlsplit(url).scheme}://{host}")
        if robots is not None:
            crawl_delay = robots.crawl_delay(ROBOTS_AGENT)
            if crawl_delay:
                delay = max(delay, float(crawl_delay))
        last = self._last_request.get(host)
        if last is not None:
            wait = last + delay - self._clock()
            if wait > 0:
                self._sleep(wait)
        try:
            return self._client.get(url)
        finally:
            self._last_request[host] = self._clock()
