import base64
import json

import httpx

from tracker.pulls import LABEL, GitHubPulls, branch_name


def fake_github(branch_exists=False, open_prs=()):
    calls = []

    def handler(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        path = request.url.path
        if request.method == "GET" and path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "main-sha"}})
        if request.method == "GET" and "/git/ref/heads/bot/" in path:
            return httpx.Response(200 if branch_exists else 404, json={})
        if request.method == "GET" and path.endswith("/contents/races.yaml"):
            content = base64.b64encode(b"races: []\n").decode()
            return httpx.Response(200, json={"sha": "file-sha", "content": content})
        if request.method == "GET" and path.endswith("/pulls"):
            return httpx.Response(200, json=list(open_prs))
        if path.endswith("/labels") and "/issues/" not in path:
            return httpx.Response(422, json={})
        if request.method == "POST" and path.endswith("/pulls"):
            return httpx.Response(201, json={"number": 12, "html_url": "https://github.com/o/r/pull/12"})
        return httpx.Response(200, json={})

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    return GitHubPulls("o/r", "token", client=client), calls


def test_reads_the_data_file_from_main():
    pulls, calls = fake_github()
    assert pulls.read_data_file() == "races: []\n"
    assert calls[0][1] == "/repos/o/r/contents/races.yaml"


def test_new_branch_commit_and_labelled_pull_request():
    pulls, calls = fake_github()
    url = pulls.propose("cardiff-half-2027", "new yaml\n", "Update Cardiff Half: status", "body")
    assert url == "https://github.com/o/r/pull/12"
    sent = [(m, p, b) for m, p, b in calls if m != "GET"]
    assert sent[0] == ("POST", "/repos/o/r/git/refs", {"ref": f"refs/heads/{branch_name('cardiff-half-2027')}", "sha": "main-sha"})
    put = sent[1]
    assert put[0] == "PUT" and put[2]["branch"] == "bot/update-cardiff-half-2027" and put[2]["sha"] == "file-sha"
    assert base64.b64decode(put[2]["content"]) == b"new yaml\n"
    assert sent[2] == ("POST", "/repos/o/r/pulls", {"title": "Update Cardiff Half: status",
                                                    "head": "bot/update-cardiff-half-2027", "base": "main", "body": "body"})
    assert sent[-1] == ("POST", "/repos/o/r/issues/12/labels", {"labels": [LABEL]})


def test_existing_branch_is_reset_and_open_pull_request_updated():
    pulls, calls = fake_github(branch_exists=True, open_prs=[{"number": 5, "html_url": "https://github.com/o/r/pull/5"}])
    url = pulls.propose("cardiff-half-2027", "newer yaml\n", "Update Cardiff Half: status", "new body")
    assert url == "https://github.com/o/r/pull/5"
    sent = [(m, p, b) for m, p, b in calls if m != "GET"]
    assert sent[0] == ("PATCH", "/repos/o/r/git/refs/heads/bot/update-cardiff-half-2027", {"sha": "main-sha", "force": True})
    assert ("PATCH", "/repos/o/r/pulls/5", {"title": "Update Cardiff Half: status", "body": "new body"}) in sent
    assert sent[-1][1] == "/repos/o/r/issues/5/comments"
    assert not any(p.endswith("/pulls") and m == "POST" for m, p, _ in sent)
