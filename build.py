"""Validate races.yaml and build the website and calendar feeds into site/.

    python build.py                  # validate and build
    python build.py --check          # validate only
    python build.py --write-schema   # regenerate schema/races.schema.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from tracker.feeds import FEEDS, build_calendar
from tracker.freshness import race_freshness, states_by_url
from tracker.loader import DataError, load_races
from tracker.models import RaceList
from tracker.site import render_site
from tracker.watch import PageState, StateStore

ROOT = Path(__file__).resolve().parent
# CI sets this from the GitHub Pages config; the default is for local builds.
DEFAULT_SITE_URL = "http://localhost:8000"
SCHEMA_PATH = ROOT / "schema" / "races.schema.json"


def write_schema(path: Path = SCHEMA_PATH) -> None:
    schema = RaceList.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "races.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8", newline="\n")


def build(
    data: Path,
    out: Path,
    site_url: str,
    suggest_url: str | None,
    today: date,
    generated_at: datetime,
    goatcounter_url: str | None = None,
    page_states: dict[str, PageState] | None = None,
) -> int:
    races = load_races(data).races
    states = states_by_url(page_states or {})
    freshness = {race.id: race_freshness(race, states, today) for race in races}
    out.mkdir(parents=True, exist_ok=True)
    for feed in FEEDS:
        (out / feed.filename).write_bytes(build_calendar(feed, races, generated_at))
    html = render_site(races, today, generated_at, site_url, suggest_url, goatcounter_url, freshness)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return len(races)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=ROOT / "races.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL") or DEFAULT_SITE_URL)
    parser.add_argument(
        "--suggest-url",
        default=os.environ.get("SUGGEST_URL") or None,
        help='link for "Suggest a race or report a change"; hidden when unset',
    )
    parser.add_argument(
        "--goatcounter-url",
        default=os.environ.get("GOATCOUNTER_URL") or None,
        help="GoatCounter /count endpoint; visit counting is off when unset",
    )
    parser.add_argument(
        "--page-state",
        type=Path,
        default=ROOT / "state",
        help="the daily page check's state folder; used to show when pages were last checked",
    )
    parser.add_argument("--today", type=date.fromisoformat, help="override today's date (YYYY-MM-DD)")
    parser.add_argument("--check", action="store_true", help="validate races.yaml and stop")
    parser.add_argument("--write-schema", action="store_true", help="regenerate the JSON Schema and stop")
    args = parser.parse_args(argv)

    if args.write_schema:
        write_schema()
        print(f"Wrote {SCHEMA_PATH.relative_to(ROOT)}")
        return 0

    try:
        if args.check:
            count = len(load_races(args.data).races)
            print(f"OK: {count} races valid")
            return 0
        generated_at = datetime.now(timezone.utc).replace(microsecond=0)
        today = args.today or generated_at.date()
        count = build(
            args.data,
            args.out,
            args.site_url,
            args.suggest_url,
            today,
            generated_at,
            args.goatcounter_url,
            StateStore(args.page_state).pages,
        )
    except DataError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Built {count} races into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
