from datetime import date, datetime

from tracker.events import EventKind, race_events, upcoming_deadlines
from tracker.models import Race


def test_confirmed_race_events(confirmed_race):
    events = {e.kind: e for e in race_events(Race.model_validate(confirmed_race))}
    assert set(events) == {
        EventKind.ballot_opens,
        EventKind.ballot_closes_soon,
        EventKind.ballot_closes,
        EventKind.race_day,
    }
    assert events[EventKind.ballot_opens].at == datetime(2026, 4, 27, 10, 0)
    assert events[EventKind.ballot_closes_soon].day == date(2026, 4, 30)
    assert events[EventKind.ballot_closes].summary == "Ballot closes today 12:00: Test Marathon"
    assert events[EventKind.race_day].all_day


def test_uids_are_stable(confirmed_race):
    uids = sorted(e.uid for e in race_events(Race.model_validate(confirmed_race)))
    assert uids == [
        "test-marathon-2027-ballot-closes",
        "test-marathon-2027-ballot-closes-soon",
        "test-marathon-2027-ballot-opens",
        "test-marathon-2027-race-day",
    ]


def test_unconfirmed_races_have_no_events(confirmed_race):
    race = Race.model_validate({**confirmed_race, "confidence": "estimated"})
    assert race_events(race) == []


def test_upcoming_deadlines_window(confirmed_race):
    races = [Race.model_validate(confirmed_race)]
    assert [e.kind for e in upcoming_deadlines(races, date(2026, 4, 5))] == [
        EventKind.ballot_opens,
        EventKind.ballot_closes,
    ]
    assert upcoming_deadlines(races, date(2026, 3, 1)) == []
    assert upcoming_deadlines(races, date(2026, 5, 3)) == []
