import pytest


@pytest.fixture
def confirmed_race() -> dict:
    """A fully confirmed ballot race, as it would appear in races.yaml."""
    return {
        "id": "test-marathon-2027",
        "name": "Test Marathon",
        "distance": "marathon",
        "location": "London",
        "race_date": "2027-04-25",
        "entry_type": ["ballot", "charity"],
        "ballot_opens": "2026-04-27T10:00",
        "ballot_closes": "2026-05-02T12:00",
        "ballot_results": "2026-07-01",
        "official_url": "https://example.com/test-marathon",
        "source_url": "https://example.com/test-marathon/ballot",
        "status": "announced",
        "last_verified": "2026-04-20",
        "confidence": "confirmed",
    }
