"""Open (or update) a GitHub issue when an official race page changes."""

from __future__ import annotations

from datetime import datetime

import httpx

from tracker.watch import CheckResult

API = "https://api.github.com"
LABEL = "page-change"
LABEL_COLOUR = "d97706"


def marker(url: str) -> str:
    """Hidden tag that ties an issue to one watched page, so repeat changes become comments."""
    return f"<!-- page-watch: {url} -->"


def issue_title(result: CheckResult) -> str:
    return f"Page changed: {result.page.label}"


def change_report(result: CheckResult, now: datetime) -> str:
    page = result.page
    races = "\n".join(f"- {race.name} (`{race.id}`)" for race in page.races)
    diff = "\n".join(result.diff) or "(no line-level differences)"
    return f"""{marker(page.url)}
The official page changed on {now:%a %d %b %Y}: {page.url}

**Races using this page**
{races}

**What changed** (lines starting `-` were removed, `+` were added)

```diff
{diff}
```

**To do**
- [ ] Open the page and check whether any dates, prices or entry details changed
- [ ] If they did, update `races.yaml` (including `status`, `confidence`, `source_url` and `last_verified`)
- [ ] Close this issue

Menus, footers and scripts are ignored, so this is the page's visible text only.
"""


class GitHubIssues:
    def __init__(self, repo: str, token: str, client: httpx.Client | None = None) -> None:
        self.repo = repo
        self._client = client or httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._label_ready = False

    def report_change(self, result: CheckResult, now: datetime) -> str:
        """Comment on the page's open issue if there is one, else open a new one. Returns its URL."""
        body = change_report(result, now)
        existing = self._find_open_issue(result.page.url)
        if existing:
            response = self._client.post(f"/repos/{self.repo}/issues/{existing['number']}/comments", json={"body": body})
            response.raise_for_status()
            return response.json()["html_url"]

        self._ensure_label()
        response = self._client.post(
            f"/repos/{self.repo}/issues",
            json={"title": issue_title(result), "body": body, "labels": [LABEL]},
        )
        response.raise_for_status()
        return response.json()["html_url"]

    def _find_open_issue(self, url: str) -> dict | None:
        tag = marker(url)
        response = self._client.get(
            f"/repos/{self.repo}/issues", params={"state": "open", "labels": LABEL, "per_page": 100}
        )
        response.raise_for_status()
        for issue in response.json():
            if tag in (issue.get("body") or ""):
                return issue
        return None

    def _ensure_label(self) -> None:
        if self._label_ready:
            return
        response = self._client.post(
            f"/repos/{self.repo}/labels",
            json={"name": LABEL, "color": LABEL_COLOUR, "description": "An official race page changed"},
        )
        if response.status_code not in (201, 422):  # 422: label already exists
            response.raise_for_status()
        self._label_ready = True
