"""Turn a checked extraction into a proposed races.yaml change for a person to review."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from tracker.extract import Extraction, FieldChange, Pages, _normalise
from tracker.models import Confidence
from tracker.yamledit import format_value


@dataclass
class Proposal:
    race_id: str
    race_name: str
    updates: dict[str, object]  # field -> new value, ready for update_race
    changes: list[FieldChange]
    sources: dict[str, str]  # field -> url of the page its quote came from
    for_a_person: list[str] = field(default_factory=list)  # things the bot won't fill in itself

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)


def quote_source(quote: str, pages: Pages) -> str | None:
    needle = _normalise(quote)
    return next((url for url, text in pages.items() if needle in _normalise(text)), None)


def build_proposal(extraction: Extraction, pages: Pages, today: date) -> Proposal:
    race = extraction.race
    changes = extraction.changes()
    sources = {c.name: quote_source(c.quote, pages) or "" for c in changes}
    updates: dict[str, object] = {c.name: c.new for c in changes}
    if changes:
        updates["last_verified"] = today
        if race.confidence != Confidence.confirmed:
            updates["confidence"] = Confidence.confirmed
            updates["source_url"] = next(iter(sources.values()), None) or str(race.official_url)

    notes = list(extraction.problems)
    for name, extracted in extraction.fields.items():
        old = getattr(race, name)
        if extracted.problem and extracted.value is not None:
            notes.append(f"`{name}`: model said {format_value(extracted.value)}, rejected ({extracted.problem})")
        elif extracted.value is not None and not extracted.time_stated and getattr(old, "date", lambda: old)() != extracted.value:
            notes.append(
                f"`{name}`: page gives {format_value(extracted.value)} with no time "
                f"(“{extracted.quote}”). Add the time by hand if it's known."
            )
    return Proposal(race.id, race.name, updates, changes, sources, notes)


def pr_title(proposal: Proposal) -> str:
    fields = ", ".join(c.name for c in proposal.changes)
    return f"Update {proposal.race_name}: {fields}"


def pr_body(proposal: Proposal, page_diffs: dict[str, list[str]], model: str) -> str:
    rows = "\n".join(
        f"| `{c.name}` | {format_cell(c.old)} | **{format_cell(c.new)}** | “{c.quote}” ([page]({proposal.sources.get(c.name) or '#'})) |"
        for c in proposal.changes
    )
    extra = ""
    if proposal.for_a_person:
        extra = "\n**Not changed automatically. Check these by hand**\n" + "\n".join(f"- {n}" for n in proposal.for_a_person) + "\n"
    diffs = "".join(
        f"\n<details><summary>What changed on {url}</summary>\n\n```diff\n" + "\n".join(lines) + "\n```\n</details>\n"
        for url, lines in page_diffs.items()
        if lines
    )
    return f"""{marker(proposal.race_id)}
An official page for **{proposal.race_name}** changed, and `{model}` read it. Proposed updates to `races.yaml`:

| Field | Now | Proposed | Evidence |
| --- | --- | --- | --- |
{rows}
{extra}
**Before merging:** open each page link and check the quote says what the proposed value says.
If something is wrong, edit the file in this PR or close it. Nothing changes on the site until it's merged.

`last_verified` is set to today because the values come from the official page.
{diffs}"""


def marker(race_id: str) -> str:
    return f"<!-- race-update: {race_id} -->"


def format_cell(value: object) -> str:
    return "—" if value is None else format_value(value)
