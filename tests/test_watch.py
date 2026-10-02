from datetime import datetime, timezone

from tracker.fetch import FetchResult, FetchStatus
from tracker.models import Race
from tracker.watch import StateStore, check_pages, page_key, watched_pages

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)


class FakeFetcher:
    def __init__(self, pages: dict[str, str | int]):
        self.pages = pages

    def fetch(self, url: str) -> FetchResult:
        page = self.pages[url]
        if isinstance(page, int):
            return FetchResult(url, FetchStatus.http_error, http_status=page)
        return FetchResult(url, FetchStatus.ok, html=page, http_status=200)


def race(confirmed_race, **changes):
    """A race whose source page is its official page, unless changed."""
    return Race.model_validate({**confirmed_race, "source_url": confirmed_race["official_url"], **changes})


def test_watched_pages_skips_manual_done_and_missing_urls(confirmed_race):
    races = [
        race(confirmed_race),
        race(confirmed_race, id="other-race-2027", name="Other Race"),  # same URL: grouped
        race(confirmed_race, id="manual-race-2027", official_url="https://b.example/", monitoring="manual"),
        race(confirmed_race, id="done-race-2027", official_url="https://c.example/", status="done"),
        race(confirmed_race, id="no-url-race-2027", official_url=None, source_url=None, confidence="estimated",
             last_verified=None),
    ]
    pages = watched_pages(races)
    assert [p.url for p in pages] == ["https://example.com/test-marathon"]
    assert pages[0].label == "Test Marathon, Other Race"


def test_page_key():
    assert page_key("https://www.greatrun.org/events/great-north-run") == "greatrun-org-events-great-north-run"


def test_baseline_then_unchanged_then_changed(tmp_path, confirmed_race):
    pages = watched_pages([race(confirmed_race)])
    url = pages[0].url
    store_dir = tmp_path / "state"

    first = check_pages(pages, FakeFetcher({url: "<p>Race day 25 April</p>"}), StateStore(store_dir), NOW)
    assert first[0].outcome == "baseline"

    second = check_pages(pages, FakeFetcher({url: "<p>Race  day 25 April</p>\n"}), StateStore(store_dir), NOW)
    assert second[0].outcome == "unchanged"

    third = check_pages(
        pages, FakeFetcher({url: "<p>Race day 25 April</p><p>Ballot opens 1 May</p>"}), StateStore(store_dir), NOW
    )
    assert third[0].outcome == "changed"
    assert "+Ballot opens 1 May" in third[0].diff

    state = StateStore(store_dir).get(pages[0])
    assert state.last_changed == NOW.isoformat()
    assert (store_dir / "pages" / f"{pages[0].key}.txt").read_text(encoding="utf-8").endswith("Ballot opens 1 May\n")


def test_failures_are_counted_and_keep_the_last_snapshot(tmp_path, confirmed_race):
    pages = watched_pages([race(confirmed_race)])
    url = pages[0].url
    store_dir = tmp_path / "state"
    check_pages(pages, FakeFetcher({url: "<p>Race day</p>"}), StateStore(store_dir), NOW)

    for _ in range(2):
        result = check_pages(pages, FakeFetcher({url: 403}), StateStore(store_dir), NOW)
    assert result[0].outcome == "failed" and result[0].detail == "HTTP 403"
    state = StateStore(store_dir).get(pages[0])
    assert state.consecutive_failures == 2

    recovered = check_pages(pages, FakeFetcher({url: "<p>Race day</p>"}), StateStore(store_dir), NOW)
    assert recovered[0].outcome == "unchanged"
    assert StateStore(store_dir).get(pages[0]).consecutive_failures == 0


def test_empty_page_counts_as_failure(tmp_path, confirmed_race):
    pages = watched_pages([race(confirmed_race)])
    result = check_pages(pages, FakeFetcher({pages[0].url: "<script>app()</script>"}), StateStore(tmp_path), NOW)
    assert result[0].outcome == "failed" and result[0].detail == "empty page"


def test_failing_days_count_by_date_and_reset_on_recovery(tmp_path, confirmed_race):
    from datetime import timedelta

    pages = watched_pages([race(confirmed_race)])
    url = pages[0].url
    store_dir = tmp_path / "state"
    check_pages(pages, FakeFetcher({url: "<p>Race day</p>"}), StateStore(store_dir), NOW)

    first_fail = NOW.replace(hour=14)
    result = check_pages(pages, FakeFetcher({url: 403}), StateStore(store_dir), first_fail)
    assert result[0].failing_days == 0
    week_later = (NOW + timedelta(days=7)).replace(hour=6)  # earlier in the day than the first failure
    result = check_pages(pages, FakeFetcher({url: 403}), StateStore(store_dir), week_later)
    assert result[0].failing_days == 7

    back = check_pages(pages, FakeFetcher({url: "<p>Race day</p>"}), StateStore(store_dir), week_later)
    assert back[0].recovered and back[0].outcome == "unchanged"
    assert StateStore(store_dir).get(pages[0]).failing_since is None
    again = check_pages(pages, FakeFetcher({url: "<p>Race day</p>"}), StateStore(store_dir), week_later)
    assert not again[0].recovered


def test_a_different_source_page_is_watched_too(confirmed_race):
    from tracker.watch import race_urls

    r = Race.model_validate(confirmed_race)  # fixture has a separate /ballot source page
    assert race_urls(r) == ["https://example.com/test-marathon", "https://example.com/test-marathon/ballot"]
    assert [p.url for p in watched_pages([r])] == race_urls(r)
