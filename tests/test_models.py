from pathlib import Path

import pytest
from pydantic import ValidationError

from tracker.loader import DataError, load_races
from tracker.models import Race, RaceList

ROOT = Path(__file__).resolve().parent.parent


def test_repo_races_yaml_is_valid():
    assert load_races(ROOT / "races.yaml").races


def test_confirmed_race_is_valid(confirmed_race):
    race = Race.model_validate(confirmed_race)
    assert race.year == 2027
    assert race.has_ballot


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"ballot_closes": "2026-04-27T09:00"}, "ballot_closes must be after ballot_opens"),
        ({"ballot_results": "2026-05-01"}, "ballot_results must not be before ballot_closes"),
        ({"race_date": "2028-04-25"}, "does not match race_date"),
        (
            {
                "race_date": "2027-01-01",
                "ballot_opens": "2027-02-01T10:00",
                "ballot_closes": "2027-02-05T10:00",
                "ballot_results": None,
            },
            "must not be after race_date",
        ),
        ({"race_date_end": "2027-04-25"}, "race_date_end must be after race_date"),
        ({"race_date": None, "race_date_end": "2027-04-26"}, "race_date_end needs a race_date"),
        ({"entry_type": ["general"]}, "entry_type does not include ballot"),
        ({"entry_type": ["ballot", "ballot"]}, "duplicates"),
        ({"source_url": None}, "need a source_url"),
        ({"last_verified": None}, "need a last_verified"),
        ({"ballot_opens": "2026-04-27T10:00+01:00"}, "without an offset"),
        ({"id": "Test Marathon"}, "String should match pattern"),
        ({"distance": "5k"}, "Input should be"),
        ({"unknown_field": 1}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_races_are_rejected(confirmed_race, changes, message):
    with pytest.raises(ValidationError, match=message):
        Race.model_validate({**confirmed_race, **changes})


def test_estimated_race_needs_no_source(confirmed_race):
    data = {**confirmed_race, "confidence": "estimated", "source_url": None, "last_verified": None}
    assert Race.model_validate(data).confidence.value == "estimated"


def test_duplicate_ids_are_rejected(confirmed_race):
    with pytest.raises(ValidationError, match="duplicate id"):
        RaceList.model_validate({"races": [confirmed_race, confirmed_race]})


def test_loader_names_the_failing_race(tmp_path):
    path = tmp_path / "races.yaml"
    path.write_text(
        "races:\n"
        "  - id: bad-race-2027\n"
        "    name: Bad\n"
        "    distance: 5k\n"
        "    location: X\n"
        "    entry_type: [general]\n"
        "    status: announced\n"
        "    confidence: estimated\n",
        encoding="utf-8",
    )
    with pytest.raises(DataError, match=r"races\[0\] bad-race-2027: distance"):
        load_races(path)
