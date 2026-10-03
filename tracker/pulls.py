"""Open (or refresh) a pull request that updates one race in races.yaml."""

from __future__ import annotations

import base64

import httpx

from tracker.issues import API

DATA_FILE = "races.yaml"
LABEL = "data-update"
LABEL_COLOUR = "0e7490"


def branch_name(race_id: str) -> str:
    return f"bot/update-{race_id}"


class GitHubPulls:
    def __init__(self, repo: str, token: str, client: httpx.Client | None = None, base: str = "main") -> None:
        self.repo = repo
        self.base = base
        self._client = client or httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def read_data_file(self) -> str:
        response = self._client.get(f"/repos/{self.repo}/contents/{DATA_FILE}", params={"ref": self.base})
        response.raise_for_status()
        return base64.b64decode(response.json()["content"]).decode("utf-8")

    def propose(self, race_id: str, new_text: str, title: str, body: str) -> str:
        """Put new_text on the race's bot branch (fresh from main) and open or update its PR. Returns the PR URL."""
        branch = branch_name(race_id)
        base_sha = self._get(f"/git/ref/heads/{self.base}")["object"]["sha"]
        if self._client.get(f"/repos/{self.repo}/git/ref/heads/{branch}").status_code == 200:
            self._send("PATCH", f"/git/refs/heads/{branch}", {"sha": base_sha, "force": True})
        else:
            self._send("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": base_sha})

        current = self._get(f"/contents/{DATA_FILE}", params={"ref": branch})
        self._send(
            "PUT",
            f"/contents/{DATA_FILE}",
            {
                "message": title,
                "content": base64.b64encode(new_text.encode("utf-8")).decode("ascii"),
                "sha": current["sha"],
                "branch": branch,
            },
        )

        owner = self.repo.split("/")[0]
        open_prs = self._get("/pulls", params={"state": "open", "head": f"{owner}:{branch}"})
        if open_prs:
            number = open_prs[0]["number"]
            self._send("PATCH", f"/pulls/{number}", {"title": title, "body": body})
            self._send("POST", f"/issues/{number}/comments", {"body": "The page changed again; this PR now has the latest proposal."})
            return open_prs[0]["html_url"]

        pr = self._send("POST", "/pulls", {"title": title, "head": branch, "base": self.base, "body": body})
        self._ensure_label()
        self._send("POST", f"/issues/{pr['number']}/labels", {"labels": [LABEL]})
        return pr["html_url"]

    def _get(self, path: str, params: dict | None = None):
        response = self._client.get(f"/repos/{self.repo}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def _send(self, method: str, path: str, payload: dict):
        response = self._client.request(method, f"/repos/{self.repo}{path}", json=payload)
        response.raise_for_status()
        return response.json() if response.content else {}

    def _ensure_label(self) -> None:
        response = self._client.post(
            f"/repos/{self.repo}/labels",
            json={"name": LABEL, "color": LABEL_COLOUR, "description": "Bot-proposed update to races.yaml"},
        )
        if response.status_code not in (201, 422):
            response.raise_for_status()
