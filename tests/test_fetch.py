import httpx

from tracker.fetch import USER_AGENT, Fetcher, FetchStatus

ROBOTS = "User-agent: *\nDisallow: /private\nCrawl-delay: 5\n"


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_fetcher(handler, clock=None):
    clock = clock or FakeClock()
    client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT})
    return Fetcher(client=client, sleep=clock.sleep, clock=clock.time), clock


def html(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})


def test_fetches_page_and_identifies_itself():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404) if request.url.path == "/robots.txt" else html("<p>hi</p>")

    fetcher, _ = make_fetcher(handler)
    result = fetcher.fetch("https://race.example/enter")
    assert result.ok and result.html == "<p>hi</p>"
    assert seen[-1].headers["User-Agent"].startswith("RunClubRaceBot/")


def test_respects_robots_disallow():
    def handler(request):
        return httpx.Response(200, text=ROBOTS) if request.url.path == "/robots.txt" else html("x")

    fetcher, _ = make_fetcher(handler)
    assert fetcher.fetch("https://race.example/private/page").status == FetchStatus.blocked_by_robots


def test_robots_server_error_means_do_not_crawl():
    def handler(request):
        return httpx.Response(503) if request.url.path == "/robots.txt" else html("x")

    fetcher, _ = make_fetcher(handler)
    assert fetcher.fetch("https://race.example/").status == FetchStatus.blocked_by_robots


def test_waits_between_requests_to_the_same_host_using_crawl_delay():
    def handler(request):
        return httpx.Response(200, text=ROBOTS) if request.url.path == "/robots.txt" else html("x")

    fetcher, clock = make_fetcher(handler)
    fetcher.fetch("https://race.example/a")
    fetcher.fetch("https://race.example/b")
    assert clock.slept == [5.0, 5.0]  # robots.txt Crawl-delay (5s) beats the 3s default


def test_reports_http_errors_and_non_html():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/blocked":
            return httpx.Response(403)
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})

    fetcher, _ = make_fetcher(handler)
    blocked = fetcher.fetch("https://race.example/blocked")
    assert blocked.status == FetchStatus.http_error and blocked.describe() == "HTTP 403"
    assert fetcher.fetch("https://race.example/pack.pdf").status == FetchStatus.not_html


def test_network_errors_are_reported_not_raised():
    def handler(request):
        raise httpx.ConnectTimeout("slow", request=request)

    fetcher, _ = make_fetcher(handler)
    assert fetcher.fetch("https://race.example/").status == FetchStatus.blocked_by_robots  # robots unreadable

    fetcher._robots["https://race.example"] = None  # pretend robots.txt allowed everything
    assert fetcher.fetch("https://race.example/").status == FetchStatus.network_error
