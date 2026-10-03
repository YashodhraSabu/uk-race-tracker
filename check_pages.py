"""Check each race's official page for changes and report them as GitHub issues.

    python check_pages.py             # check pages, update state/, print what changed
    python check_pages.py --issues    # also open or update GitHub issues (needs GITHUB_TOKEN
                                      # and GITHUB_REPOSITORY, as set in GitHub Actions)

With --issues, a page that has failed for --alert-after-days days gets one
"page-unreachable" issue, which is closed automatically when the page loads
again. A changed page gets a "page-change" issue with the diff, unless
GEMINI_API_KEY is set: then the LLM reads the race's pages and, if it finds new
values, a pull request proposes the races.yaml edit instead.

    python check_pages.py --issues --propose-for cardiff-half-2027
                                      # run the LLM proposal for one race now,
                                      # even though its pages haven't changed
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from tracker.extract import extract
from tracker.fetch import Fetcher
from tracker.issues import GitHubIssues
from tracker.llm import DEFAULT_GEMINI_MODEL, GeminiClient, JsonLLM, LLMError
from tracker.loader import DataError, load_races, parse_races
from tracker.models import Race
from tracker.propose import format_cell, build_proposal, pr_body, pr_title
from tracker.pulls import GitHubPulls
from tracker.watch import CheckResult, Page, StateStore, check_pages, race_urls, watched_pages
from tracker.yamledit import update_race

ROOT = Path(__file__).resolve().parent
DEFAULT_ALERT_AFTER_DAYS = 7


def summary(results: list[CheckResult], issue_links: dict[str, str]) -> str:
    counts = {outcome: sum(r.outcome == outcome for r in results) for outcome in ("changed", "unchanged", "baseline", "failed")}
    lines = [
        "## Race page check",
        "",
        f"{len(results)} pages: {counts['changed']} changed, {counts['unchanged']} unchanged, "
        f"{counts['baseline']} first seen, {counts['failed']} failed.",
        "",
        "| Page | Result |",
        "| --- | --- |",
    ]
    for r in results:
        detail = {"changed": "changed", "unchanged": "no change", "baseline": "first snapshot saved"}.get(r.outcome)
        if r.outcome == "failed":
            days = f"{r.failing_days} day{'s' if r.failing_days != 1 else ''}"
            detail = f"failed ({r.detail}; failing for {days})" if r.failing_days else f"failed ({r.detail})"
        link = issue_links.get(r.page.url)
        if link:
            detail += f" · [{'pull request' if '/pull/' in link else 'issue'}]({link})"
        lines.append(f"| [{r.page.label}]({r.page.url}) | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=ROOT / "races.yaml")
    parser.add_argument("--state", type=Path, default=ROOT / "state")
    parser.add_argument("--issues", action="store_true", help="open or update GitHub issues")
    parser.add_argument("--propose-for", metavar="RACE_ID", help="run the LLM proposal for this race now")
    parser.add_argument(
        "--alert-after-days",
        type=int,
        default=int(os.environ.get("ALERT_AFTER_DAYS") or DEFAULT_ALERT_AFTER_DAYS),
        help="open a page-unreachable issue once a page has failed for this many days (default 7)",
    )
    args = parser.parse_args(argv)

    issues = pulls = llm = None
    if args.issues:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            print("--issues needs GITHUB_TOKEN and GITHUB_REPOSITORY", file=sys.stderr)
            return 2
        issues = GitHubIssues(repo, token)
        pulls = GitHubPulls(repo, token)
    if os.environ.get("GEMINI_API_KEY"):
        llm = GeminiClient(os.environ["GEMINI_API_KEY"], model=os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL)
    if args.propose_for and not (pulls and llm):
        print("--propose-for needs --issues and GEMINI_API_KEY", file=sys.stderr)
        return 2

    try:
        races = load_races(args.data).races
    except DataError as exc:
        print(exc, file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).replace(microsecond=0)
    store = StateStore(args.state)
    with Fetcher() as fetcher:
        results = check_pages(watched_pages(races), fetcher, store, now)

    issue_links: dict[str, str] = {}
    changed = [r for r in results if r.outcome == "changed"]
    to_propose = {race.id: race for r in changed for race in r.page.races}
    if args.propose_for:
        match = [race for race in races if race.id == args.propose_for]
        if not match:
            print(f"no race with id {args.propose_for}", file=sys.stderr)
            return 1
        to_propose[match[0].id] = match[0]

    notes: dict[str, str] = {}  # page url -> note for its change issue
    if pulls and llm:
        for race in to_propose.values():
            diffs = {r.page.url: r.diff for r in changed if race in r.page.races}
            pr_url, note = propose_update(race, store, diffs, llm, pulls, now)
            for url in diffs:
                if pr_url:
                    issue_links[url] = pr_url
                else:
                    notes[url] = notes.get(url, "") + note
            if args.propose_for == race.id:
                print(f"Proposal for {race.id}: {pr_url or note.strip() or 'no pages to read'}")

    for result in results:
        link = None
        if result.outcome == "changed":
            if result.page.url in issue_links:
                pass  # covered by a pull request
            elif issues:
                link = issues.report_change(result, now, notes.get(result.page.url, ""))
            else:
                print(f"\n=== Changed: {result.page.label} ({result.page.url})")
                print("\n".join(result.diff))
        elif result.outcome == "failed" and result.failing_days >= args.alert_after_days:
            if issues:
                link = issues.report_unreachable(result)
            else:
                print(f"\n=== Unreachable for {result.failing_days} days: {result.page.label} ({result.detail})")
        if result.recovered and issues:
            link = issues.close_unreachable(result) or link
        if link:
            issue_links[result.page.url] = link

    report = summary(results, issue_links)
    print(report)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(report)
    return 0


def propose_update(
    race: Race, store: StateStore, diffs: dict[str, list[str]], llm: JsonLLM, pulls: GitHubPulls, now: datetime
) -> tuple[str | None, str]:
    """Run the LLM on the race's pages. Returns (pull request URL, "") or (None, note for the change issue)."""
    pages = {url: store.read_text(Page(url, [race])) for url in race_urls(race)}
    pages = {url: text for url, text in pages.items() if text}
    if not pages:
        return None, ""
    try:
        extraction = extract(race, pages, llm, now.date())
    except LLMError as exc:
        return None, f"**LLM check for {race.name}:** couldn't run ({exc}).\n\n"

    proposal = build_proposal(extraction, pages, now.date())
    for_a_person = "".join(f"- {n}\n" for n in proposal.for_a_person)
    if not proposal.has_changes:
        detail = f"\n{for_a_person}" if for_a_person else ""
        return None, f"**LLM check for {race.name}:** no changes to the race details found.{detail}\n\n"

    try:
        new_text = update_race(pulls.read_data_file(), race.id, proposal.updates)
        parse_races(new_text)
    except (KeyError, DataError) as exc:
        return None, f"**LLM check for {race.name}:** proposed changes didn't pass validation ({exc}).\n\n"
    except httpx.HTTPError as exc:
        return None, f"**LLM check for {race.name}:** couldn't read races.yaml from GitHub ({exc}).\n\n"
    try:
        return pulls.propose(race.id, new_text, pr_title(proposal), pr_body(proposal, diffs, llm.model)), ""
    except httpx.HTTPError as exc:
        changes = "".join(f"- `{c.name}`: {format_cell(c.old)} → {format_cell(c.new)} (“{c.quote}”)\n" for c in proposal.changes)
        return None, (
            f"**LLM check for {race.name}:** proposed these changes, but the pull request couldn't be opened "
            f"({exc}):\n{changes}\n"
        )


if __name__ == "__main__":
    sys.exit(main())
