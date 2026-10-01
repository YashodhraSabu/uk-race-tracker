from datetime import date, datetime, timezone

import yaml
from icalendar import Calendar

from build import build, main
from tracker.feeds import FEEDS

GENERATED_AT = datetime(2026, 4, 1, 6, 0, tzinfo=timezone.utc)


def _build(tmp_path, races):
    data = tmp_path / "races.yaml"
    data.write_text(yaml.safe_dump({"races": races}), encoding="utf-8")
    out = tmp_path / "site"
    build(data, out, "https://example.github.io/tracker", "https://example.com/form", date(2026, 4, 1), GENERATED_AT)
    return out


def _uids(path):
    cal = Calendar.from_ical(path.read_bytes())
    return {str(c["uid"]) for c in cal.walk("VEVENT")}


def test_build_writes_site_and_feeds(tmp_path, confirmed_race):
    out = _build(tmp_path, [confirmed_race])
    for feed in FEEDS:
        assert (out / feed.filename).exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Ballot opens: Test Marathon" in html  # upcoming deadlines panel
    assert "webcal://example.github.io/tracker/all.ics" in html
    assert "https://example.com/form" in html


def test_feed_contents(tmp_path, confirmed_race):
    half = {**confirmed_race, "id": "test-half-2027", "name": "Test Half", "distance": "half"}
    out = _build(tmp_path, [confirmed_race, half])

    assert len(_uids(out / "all.ics")) == 8
    assert all(uid.startswith("test-marathon-2027") for uid in _uids(out / "marathons.ics"))
    assert all(uid.startswith("test-half-2027") for uid in _uids(out / "halves.ics"))
    assert not any("race-day" in uid for uid in _uids(out / "ballots-only.ics"))


def test_ballot_open_time_is_converted_from_uk_time(tmp_path, confirmed_race):
    out = _build(tmp_path, [confirmed_race])
    cal = Calendar.from_ical((out / "all.ics").read_bytes())
    opens = next(c for c in cal.walk("VEVENT") if "ballot-opens" in str(c["uid"]))
    # 10:00 BST on 27 April is 09:00 UTC
    assert opens.decoded("dtstart") == datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc)


def test_multi_day_race_spans_all_days(tmp_path, confirmed_race):
    out = _build(tmp_path, [{**confirmed_race, "race_date": "2027-04-24", "race_date_end": "2027-04-25"}])
    cal = Calendar.from_ical((out / "all.ics").read_bytes())
    race_day = next(c for c in cal.walk("VEVENT") if "race-day" in str(c["uid"]))
    assert race_day.decoded("dtstart") == date(2027, 4, 24)
    assert race_day.decoded("dtend") == date(2027, 4, 26)  # DTEND is exclusive


def test_international_races_are_labelled(tmp_path, confirmed_race):
    out = _build(tmp_path, [{**confirmed_race, "location": "Paris", "country": "France"}])
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'data-region="international"' in html
    assert "Paris, France" in html


def test_goatcounter_is_off_by_default(tmp_path, confirmed_race):
    html = (_build(tmp_path, [confirmed_race]) / "index.html").read_text(encoding="utf-8")
    assert "gc.zgo.at" not in html
    assert "GoatCounter" not in html


def test_goatcounter_when_configured(tmp_path, confirmed_race):
    data = tmp_path / "races.yaml"
    data.write_text(yaml.safe_dump({"races": [confirmed_race]}), encoding="utf-8")
    out = tmp_path / "site"
    url = "https://example.goatcounter.com/count"
    build(data, out, "https://example.github.io/tracker", "#", date(2026, 4, 1), GENERATED_AT, url)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert f'data-goatcounter="{url}"' in html
    assert 'data-goatcounter-click="subscribe-all-google"' in html


def test_main_reports_invalid_data(tmp_path, capsys):
    data = tmp_path / "races.yaml"
    data.write_text("races:\n  - id: nope\n", encoding="utf-8")
    assert main(["--data", str(data), "--check"]) == 1
    assert "failed validation" in capsys.readouterr().err
