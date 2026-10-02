import json
from datetime import datetime, timezone

import httpx

from tracker.issues import LABEL, GitHubIssues, change_report, issue_title, marker
from tracker.models import Race
from tracker.watch import CheckResult, Page

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)


def changed(confirmed_race) -> CheckResult:
    race = Race.model_validate(confirmed_race)
    return CheckResult(Page(str(race.official_url), [race]), "changed", diff=["-Ballot TBC", "+Ballot opens 1 May"])


def fake_github(existing_issues):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.method == "GET":
            return httpx.Response(200, json=existing_issues)
        if request.url.path.endswith("/labels"):
            return httpx.Response(422, json={})
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/issues/7"})

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    return GitHubIssues("o/r", "token", client=client), calls


def test_report_contains_link_races_and_diff(confirmed_race):
    result = changed(confirmed_race)
    body = change_report(result, NOW)
    assert marker("https://example.com/test-marathon") in body
    assert "Test Marathon (`test-marathon-2027`)" in body
    assert "+Ballot opens 1 May" in body
    assert issue_title(result) == "Page changed: Test Marathon"


def test_opens_new_issue_with_label(confirmed_race):
    issues, calls = fake_github([])
    assert issues.report_change(changed(confirmed_race), NOW) == "https://github.com/o/r/issues/7"
    method, path, payload = calls[-1]
    assert (method, path) == ("POST", "/repos/o/r/issues")
    assert payload["labels"] == [LABEL]


def test_comments_on_existing_open_issue_for_same_page(confirmed_race):
    existing = [{"number": 3, "body": "older\n" + marker("https://example.com/test-marathon")}]
    issues, calls = fake_github(existing)
    issues.report_change(changed(confirmed_race), NOW)
    assert calls[-1][:2] == ("POST", "/repos/o/r/issues/3/comments")
    assert not any(path.endswith("/labels") for _, path, _ in calls)
