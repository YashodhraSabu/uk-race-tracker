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
from tracker.loader import DataError, load_races
from tracker.models import RaceList
from tracker.site import render_site

ROOT = Path(__file__).resolve().parent
DEFAULT_SITE_URL = "https://yashodhrasabu.github.io/uk-race-tracker"
DEFAULT_SUGGEST_URL = "https://github.com/YashodhraSabu/uk-race-tracker/issues/new"
SCHEMA_PATH = ROOT / "schema" / "races.schema.json"


def write_schema(path: Path = SCHEMA_PATH) -> None:
    schema = RaceList.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "races.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8", newline="\n")


def build(data: Path, out: Path, site_url: str, suggest_url: str, today: date, generated_at: datetime) -> int:
    races = load_races(data).races
    out.mkdir(parents=True, exist_ok=True)
    for feed in FEEDS:
        (out / feed.filename).write_bytes(build_calendar(feed, races, generated_at))
    html = render_site(races, today, generated_at, site_url, suggest_url)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return len(races)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=ROOT / "races.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", DEFAULT_SITE_URL))
    parser.add_argument("--suggest-url", default=os.environ.get("SUGGEST_URL", DEFAULT_SUGGEST_URL))
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
        count = build(args.data, args.out, args.site_url, args.suggest_url, today, generated_at)
    except DataError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Built {count} races into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
