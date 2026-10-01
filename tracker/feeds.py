"""Build the .ics calendar feeds.

Google Calendar ignores alarms in subscribed feeds, so reminders are their own
events ("Ballot closes in 2 days") rather than VALARMs. Event UIDs are stable,
so a corrected date moves the existing event instead of adding a duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from icalendar import Calendar
from icalendar import Event as IcsEvent

from tracker.events import BALLOT_KINDS, Event, all_events
from tracker.models import Distance, Race, to_utc

UID_DOMAIN = "uk-race-tracker"
TIMED_EVENT_LENGTH = timedelta(minutes=30)


@dataclass(frozen=True)
class Feed:
    filename: str
    title: str
    description: str
    include: Callable[[Event], bool]


FEEDS = [
    Feed("all.ics", "UK races & ballots", "Every race and entry window", lambda e: True),
    Feed("marathons.ics", "UK marathons & ballots", "Marathons only", lambda e: e.race.distance == Distance.marathon),
    Feed("halves.ics", "UK half marathons & ballots", "Half marathons only", lambda e: e.race.distance == Distance.half),
    Feed("ballots-only.ics", "UK race ballots", "Ballot windows only, no race days", lambda e: e.kind in BALLOT_KINDS),
]


def build_calendar(feed: Feed, races: list[Race], generated_at: datetime) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//UK Race & Ballot Tracker//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", feed.title)
    cal.add("x-wr-caldesc", f"{feed.description}. Always confirm dates on the official site.")
    cal.add("x-published-ttl", "PT12H")
    cal.add("refresh-interval", timedelta(hours=12), parameters={"VALUE": "DURATION"})

    for event in all_events(races):
        if feed.include(event):
            cal.add_component(_to_ics(event, generated_at))
    return cal.to_ical()


def _to_ics(event: Event, generated_at: datetime) -> IcsEvent:
    ics = IcsEvent()
    ics.add("uid", f"{event.uid}@{UID_DOMAIN}")
    ics.add("dtstamp", generated_at)
    ics.add("summary", event.summary)
    if event.all_day:
        ics.add("dtstart", event.day)
        ics.add("dtend", event.day + timedelta(days=1))
        ics.add("transp", "TRANSPARENT")
    else:
        start = to_utc(event.at)
        ics.add("dtstart", start)
        ics.add("dtend", start + TIMED_EVENT_LENGTH)

    race = event.race
    lines = [f"{race.name}, {race.location}"]
    if race.race_date:
        lines.append(f"Race day: {race.race_date:%a %d %b %Y}")
    if race.ballot_opens and race.ballot_closes:
        lines.append(f"Ballot: {race.ballot_opens:%d %b %H:%M} to {race.ballot_closes:%d %b %H:%M} (UK time)")
    if race.entry_url:
        lines.append(f"Entry page: {race.entry_url}")
        ics.add("url", race.entry_url)
    lines.append("Always confirm dates on the official site.")
    ics.add("description", "\n".join(lines))
    return ics
