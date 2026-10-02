from datetime import date

from evaluate_extraction import report, run, score
from tracker.extract import FIELDS, check
from tracker.models import Race
from tracker.watch import StateStore, watched_pages

PAGE = "Test Marathon\nRace day: Sunday 25 April 2027\nThe ballot opens on 27 April 2026.\nEntry £79"


def raw(**fields):
    empty = {name: {"value": None, "quote": None} for name in FIELDS}
    return {**empty, **{k: {"value": v[0], "quote": v[1]} for k, v in fields.items()}}


def outcomes(scores):
    return {s.name: s.outcome for s in scores}


def test_scores_each_outcome(confirmed_race):
    race = Race.model_validate({**confirmed_race, "price_gbp": 80})
    extraction = check(race, {"https://example.com/test-marathon": PAGE}, raw(
        race_date=("2027-04-25", "Race day: Sunday 25 April 2027"),       # correct
        ballot_opens=("2026-04-27", "The ballot opens on 27 April 2026."),  # correct, date only
        price_gbp=("79", "Entry £79"),                                      # wrong
        general_entry_opens=("2026-01-01T09:00", "not on the page"),        # rejected (expected None too)
        status=("announced", "Test Marathon"),                              # correct
    ))
    result = outcomes(score(extraction))
    assert result["race_date"] == "correct"
    assert result["ballot_opens"] == "correct"
    assert result["price_gbp"] == "wrong"
    assert result["general_entry_opens"] == "rejected"
    assert result["ballot_closes"] == "missed"
    assert result["race_date_end"] == "agree"
    assert result["status"] == "correct"


def test_extra_values_are_reported_not_counted_wrong(confirmed_race):
    race = Race.model_validate(confirmed_race)
    extraction = check(race, {"https://example.com/test-marathon": PAGE}, raw(price_gbp=("79", "Entry £79")))
    assert outcomes(score(extraction))["price_gbp"] == "extra"


def test_run_uses_snapshots_of_confirmed_races_and_reports(tmp_path, confirmed_race):
    races = [Race.model_validate(confirmed_race),
             Race.model_validate({**confirmed_race, "id": "guess-race-2027", "confidence": "estimated",
                                  "source_url": None, "last_verified": None})]
    store = StateStore(tmp_path)
    store.write_text(watched_pages(races)[0], PAGE)

    class FakeLLM:
        model = "fake-model"
        calls = 0

        def generate_json(self, system, prompt, schema):
            FakeLLM.calls += 1
            return raw(race_date=("2027-04-25", "Race day: Sunday 25 April 2027"))

    scores, failures = run(races, store, FakeLLM(), date(2026, 10, 2))
    assert FakeLLM.calls == 1  # the estimated race is skipped
    assert failures == []
    text = report("fake-model", scores, failures)
    assert "## Extraction evaluation: `fake-model`" in text
    assert "| `race_date` | 1 | 0 | 0 | 0 | 0 |" in text
