from datetime import date, datetime

import pytest

from tracker.loader import parse_races
from tracker.models import Status
from tracker.yamledit import update_race

YAML = """# Comment at the top stays.
races:
  # --- UK halves ---

  - id: cardiff-half-2027
    name: Cardiff Half
    distance: half
    location: Cardiff
    race_date: 2027-10-03
    entry_type: [ballot, charity]
    official_url: https://www.cardiffhalfmarathon.co.uk/
    status: unannounced
    confidence: estimated
    notes: Free to enter

  - id: other-race-2027
    name: Other Race
    distance: 10k
    location: London
    entry_type: [general]
    status: unannounced
    confidence: estimated
"""


def test_replaces_and_inserts_fields_in_model_order():
    new = update_race(YAML, "cardiff-half-2027", {
        "ballot_closes": datetime(2026, 10, 18, 23, 59),
        "status": Status.ballot_open,
        "price_gbp": 59.0,
        "last_verified": date(2026, 10, 3),
    })
    block = new.split("  - id: cardiff-half-2027\n")[1].split("\n\n")[0].splitlines()
    assert block == [
        "    name: Cardiff Half",
        "    distance: half",
        "    location: Cardiff",
        "    race_date: 2027-10-03",
        "    entry_type: [ballot, charity]",
        "    ballot_closes: 2026-10-18T23:59",
        "    price_gbp: 59",
        "    official_url: https://www.cardiffhalfmarathon.co.uk/",
        "    status: ballot_open",
        "    last_verified: 2026-10-03",
        "    confidence: estimated",
        "    notes: Free to enter",
    ]


def test_leaves_everything_else_untouched():
    new = update_race(YAML, "cardiff-half-2027", {"status": Status.announced})
    assert new.replace("status: announced", "status: unannounced", 1) == YAML
    assert new.startswith("# Comment at the top stays.\nraces:\n  # --- UK halves ---\n")


def test_result_still_parses_and_last_record_works():
    new = update_race(YAML, "other-race-2027", {"race_date": date(2027, 5, 9)})
    races = {r.id: r for r in parse_races(new).races}
    assert races["other-race-2027"].race_date == date(2027, 5, 9)
    assert races["cardiff-half-2027"].race_date == date(2027, 10, 3)


@pytest.mark.parametrize("race_id, updates", [("missing-2027", {"status": "done"}), ("cardiff-half-2027", {"id": "x"})])
def test_rejects_unknown_races_and_fields(race_id, updates):
    with pytest.raises(KeyError):
        update_race(YAML, race_id, updates)
