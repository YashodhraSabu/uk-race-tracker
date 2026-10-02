"""Check each race's official page for changes and report them as GitHub issues.

    python check_pages.py             # check pages, update state/, print what changed
    python check_pages.py --issues    # also open or update GitHub issues (needs GITHUB_TOKEN
                                      # and GITHUB_REPOSITORY, as set in GitHub Actions)

With --issues, a changed page gets a "page-change" issue, and a page that has
failed for --alert-after-days days gets one "page-unreachable" issue, which is
closed automatically when the page loads again.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from tracker.fetch import Fetcher
from tracker.issues import GitHubIssues
from tracker.loader import DataError, load_races
from tracker.watch import CheckResult, StateStore, check_pages, watched_pages

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
            detail += f" · [issue]({link})"
        lines.append(f"| [{r.page.label}]({r.page.url}) | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=ROOT / "races.yaml")
    parser.add_argument("--state", type=Path, default=ROOT / "state")
    parser.add_argument("--issues", action="store_true", help="open or update GitHub issues")
    parser.add_argument(
        "--alert-after-days",
        type=int,
        default=int(os.environ.get("ALERT_AFTER_DAYS") or DEFAULT_ALERT_AFTER_DAYS),
        help="open a page-unreachable issue once a page has failed for this many days (default 7)",
    )
    args = parser.parse_args(argv)

    issues = None
    if args.issues:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            print("--issues needs GITHUB_TOKEN and GITHUB_REPOSITORY", file=sys.stderr)
            return 2
        issues = GitHubIssues(repo, token)

    try:
        races = load_races(args.data).races
    except DataError as exc:
        print(exc, file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with Fetcher() as fetcher:
        results = check_pages(watched_pages(races), fetcher, StateStore(args.state), now)

    issue_links: dict[str, str] = {}
    for result in results:
        link = None
        if result.outcome == "changed":
            if issues:
                link = issues.report_change(result, now)
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


if __name__ == "__main__":
    sys.exit(main())
