"""Turn races into dated events, shared by the calendar feeds and the website.

Only `confirmed` records produce events, so an estimated date never lands in
someone's calendar looking like a real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from tracker.models import Confidence, Race


class EventKind(str, Enum):
    race_day = "race_day"
    ballot_opens = "ballot_opens"
    ballot_closes_soon = "ballot_closes_soon"
    ballot_closes = "ballot_closes"
    general_entry_opens = "general_entry_opens"


BALLOT_KINDS = {EventKind.ballot_opens, EventKind.ballot_closes_soon, EventKind.ballot_closes}

# Wording for the website, where the date is shown alongside. Calendar
# summaries such as "Ballot closes today" only read right on the day itself.
SITE_LABELS = {
    EventKind.race_day: "Race day",
    EventKind.ballot_opens: "Ballot opens",
    EventKind.ballot_closes_soon: "Ballot closes in 2 days",
    EventKind.ballot_closes: "Ballot closes",
    EventKind.general_entry_opens: "Entry opens",
}


@dataclass(frozen=True)
class Event:
    uid: str
    kind: EventKind
    race: Race
    summary: str
    day: date
    at: datetime | None = None  # UK local time; None for all-day events
    last_day: date | None = None  # for all-day events spanning several days

    @property
    def all_day(self) -> bool:
        return self.at is None

    @property
    def site_label(self) -> str:
        return SITE_LABELS[self.kind]

    @property
    def closing(self) -> bool:
        return self.kind in {EventKind.ballot_closes, EventKind.ballot_closes_soon}

    @property
    def time(self) -> str | None:
        """UK time shown next to the date on the site, if the event has one."""
        if self.at:
            return f"{self.at:%H:%M}"
        if self.kind == EventKind.ballot_closes and self.race.ballot_closes:
            return f"{self.race.ballot_closes:%H:%M}"
        return None


def race_events(race: Race) -> list[Event]:
    if race.confidence != Confidence.confirmed:
        return []

    events: list[Event] = []

    def add(kind: EventKind, summary: str, day: date, at: datetime | None = None, last_day: date | None = None) -> None:
        uid = f"{race.id}-{kind.value.replace('_', '-')}"
        events.append(Event(uid=uid, kind=kind, race=race, summary=summary, day=day, at=at, last_day=last_day))

    if race.ballot_opens:
        add(EventKind.ballot_opens, f"Ballot opens: {race.name}", race.ballot_opens.date(), race.ballot_opens)
    if race.ballot_closes:
        closes = race.ballot_closes
        add(EventKind.ballot_closes_soon, f"Ballot closes in 2 days: {race.name}", closes.date() - timedelta(days=2))
        add(EventKind.ballot_closes, f"Ballot closes today {closes:%H:%M}: {race.name}", closes.date())
    if race.general_entry_opens:
        add(
            EventKind.general_entry_opens,
            f"Entry opens: {race.name}",
            race.general_entry_opens.date(),
            race.general_entry_opens,
        )
    if race.race_date:
        add(EventKind.race_day, f"Race day: {race.name}", race.race_date, last_day=race.race_date_end)
    return events


def all_events(races: list[Race]) -> list[Event]:
    events = [event for race in races for event in race_events(race)]
    return sorted(events, key=lambda e: (e.day, e.at or datetime.min, e.uid))


def upcoming_deadlines(races: list[Race], today: date, days: int = 30) -> list[Event]:
    """Ballot and entry events from today up to `days` ahead, for the top of the site."""
    end = today + timedelta(days=days)
    wanted = {EventKind.ballot_opens, EventKind.ballot_closes, EventKind.general_entry_opens}
    return [e for e in all_events(races) if e.kind in wanted and today <= e.day <= end]
