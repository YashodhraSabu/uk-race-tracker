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


def test_main_reports_invalid_data(tmp_path, capsys):
    data = tmp_path / "races.yaml"
    data.write_text("races:\n  - id: nope\n", encoding="utf-8")
    assert main(["--data", str(data), "--check"]) == 1
    assert "failed validation" in capsys.readouterr().err
