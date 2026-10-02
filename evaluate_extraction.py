"""Score LLM extraction against the races we verified by hand.

Runs extraction on the page snapshots saved by the daily page check
(state/pages/*.txt) for every confirmed, auto-monitored race, giving the model
all of a race's pages at once, and compares each field with races.yaml.

    python evaluate_extraction.py     # needs GEMINI_API_KEY; GEMINI_MODEL is optional

Outcomes per field:
    correct    matches races.yaml (for a date-only answer, the date matches)
    wrong      both have a value and they differ        <- the dangerous one
    missed     races.yaml has a value, the model found none
    rejected   the model gave a value but the checks threw it out
    extra      the model found a value races.yaml doesn't have (check by hand)
    agree      neither has a value
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from tracker.extract import FIELDS, Extraction, Pages, extract
from tracker.llm import DEFAULT_GEMINI_MODEL, GeminiClient, JsonLLM, LLMError
from tracker.loader import load_races
from tracker.models import Confidence, Monitoring, Race
from tracker.watch import Page, StateStore, race_urls

ROOT = Path(__file__).resolve().parent
OUTCOMES = ("correct", "wrong", "missed", "rejected", "extra", "agree")


@dataclass
class FieldScore:
    race_id: str
    name: str
    outcome: str
    expected: object
    got: object
    note: str = ""


def score(extraction: Extraction) -> list[FieldScore]:
    race = extraction.race
    scores = []
    for name in FIELDS:
        expected = getattr(race, name)
        extracted = extraction.fields[name]
        got = extracted.value
        if extracted.problem:
            outcome = "rejected" if expected is not None or got is not None else "agree"
        elif got is None:
            outcome = "agree" if expected is None else "missed"
        elif expected is None:
            outcome = "extra"
        else:
            outcome = "correct" if _same(expected, got, extracted.time_stated) else "wrong"
        scores.append(FieldScore(race.id, name, outcome, expected, got, extracted.problem or extracted.quote or ""))
    return scores


def _same(expected: object, got: object, time_stated: bool) -> bool:
    if isinstance(expected, datetime) and not time_stated:
        return expected.date() == got
    if isinstance(expected, float) or isinstance(got, float):
        return float(expected) == float(got)
    return expected == got


def cases(races: list[Race], store: StateStore) -> list[tuple[Race, Pages]]:
    out = []
    for race in races:
        if race.confidence != Confidence.confirmed or race.monitoring != Monitoring.auto:
            continue
        pages = {url: store.read_text(Page(url, [race])) for url in race_urls(race)}
        pages = {url: text for url, text in pages.items() if text}
        if pages:
            out.append((race, pages))
    return out


def report(model: str, scores: list[FieldScore], failures: list[str]) -> str:
    races = sorted({s.race_id for s in scores})
    lines = [f"## Extraction evaluation: `{model}`", "", f"{len(races)} races, {len(scores)} fields.", ""]
    totals = Counter(s.outcome for s in scores)
    lines += ["| " + " | ".join(OUTCOMES) + " |", "|" + " --- |" * len(OUTCOMES)]
    lines.append("| " + " | ".join(str(totals[o]) for o in OUTCOMES) + " |")
    known = totals["correct"] + totals["wrong"] + totals["missed"] + sum(
        1 for s in scores if s.outcome == "rejected" and s.expected is not None
    )
    if known:
        lines += ["", f"**Accuracy on known values:** {totals['correct']}/{known} ({totals['correct'] / known:.0%})"]

    lines += ["", "### By field", "", "| Field | correct | wrong | missed | rejected | extra |", "| --- | --- | --- | --- | --- | --- |"]
    for name in FIELDS:
        c = Counter(s.outcome for s in scores if s.name == name)
        lines.append(f"| `{name}` | {c['correct']} | {c['wrong']} | {c['missed']} | {c['rejected']} | {c['extra']} |")

    problems = [s for s in scores if s.outcome in ("wrong", "missed", "rejected", "extra")]
    if problems:
        lines += ["", "### Details", "", "| Race | Field | Outcome | races.yaml | Model | Quote or reason |", "| --- | --- | --- | --- | --- | --- |"]
        for s in problems:
            note = s.note.replace("|", "/").replace("\n", " ")[:160]
            lines.append(f"| {s.race_id} | `{s.name}` | {s.outcome} | {_fmt(s.expected)} | {_fmt(s.got)} | {note} |")
    if failures:
        lines += ["", "### Failed calls", ""] + [f"- {f}" for f in failures]
    return "\n".join(lines) + "\n"


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    return getattr(value, "value", None) or (value.isoformat() if hasattr(value, "isoformat") else str(value))


def run(races: list[Race], store: StateStore, llm: JsonLLM, today: date) -> tuple[list[FieldScore], list[str]]:
    scores, failures = [], []
    for race, pages in cases(races, store):
        try:
            extraction = extract(race, pages, llm, today)
        except LLMError as exc:
            failures.append(f"{race.id}: {exc}")
            continue
        scores.extend(score(extraction))
        if extraction.problems:
            failures.append(f"{race.id}: record checks failed: {'; '.join(extraction.problems)}")
    return scores, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=ROOT / "races.yaml")
    parser.add_argument("--state", type=Path, default=ROOT / "state")
    args = parser.parse_args(argv)

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set", file=sys.stderr)
        return 2
    llm = GeminiClient(key, model=os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL)
    races = load_races(args.data).races
    store = StateStore(args.state)
    if not cases(races, store):
        print("No page snapshots found; run check_pages.py first", file=sys.stderr)
        return 2

    scores, failures = run(races, store, llm, datetime.now(timezone.utc).date())
    text = report(llm.model, scores, failures)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
