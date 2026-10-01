"""The races.yaml data model.

One `Race` is one year's edition of a race. All datetimes in races.yaml are
UK local time (Europe/London) and are written without an offset.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

UK_TZ = ZoneInfo("Europe/London")

ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*-(\d{4})$"


class Distance(str, Enum):
    marathon = "marathon"
    half = "half"
    ten_k = "10k"
    ultra = "ultra"
    other = "other"


class EntryType(str, Enum):
    ballot = "ballot"
    general = "general"
    charity = "charity"
    gfa = "gfa"


class Status(str, Enum):
    unannounced = "unannounced"
    announced = "announced"
    ballot_open = "ballot_open"
    ballot_closed = "ballot_closed"
    sold_out = "sold_out"
    done = "done"


class Confidence(str, Enum):
    confirmed = "confirmed"  # read from the official page
    expected = "expected"  # organisers have given a rough date only
    estimated = "estimated"  # based on last year's edition


class Race(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    id: str = Field(pattern=ID_PATTERN, description="slug + year, e.g. london-marathon-2027")
    name: str = Field(min_length=1)
    distance: Distance
    location: str = Field(min_length=1)
    country: str = Field(default="UK", min_length=1)
    race_date: date | None = None
    race_date_end: date | None = Field(default=None, description="last day of a multi-day race")
    entry_type: list[EntryType] = Field(min_length=1)
    ballot_opens: datetime | None = None
    ballot_closes: datetime | None = None
    ballot_results: date | None = None
    general_entry_opens: datetime | None = None
    price_gbp: float | None = Field(default=None, ge=0)
    official_url: HttpUrl | None = None
    source_url: HttpUrl | None = None
    status: Status
    last_verified: date | None = None
    confidence: Confidence
    notes: str | None = None

    @field_validator("ballot_opens", "ballot_closes", "general_entry_opens")
    @classmethod
    def _naive_uk_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("write UK local time without an offset, e.g. 2026-04-27T10:00")
        return value

    @field_validator("entry_type")
    @classmethod
    def _unique_entry_types(cls, value: list[EntryType]) -> list[EntryType]:
        if len(set(value)) != len(value):
            raise ValueError("entry_type has duplicates")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> Race:
        year = int(re.match(ID_PATTERN, self.id).group(1))
        if self.race_date and self.race_date.year != year:
            raise ValueError(f"id year {year} does not match race_date {self.race_date}")
        if self.race_date_end:
            if not self.race_date:
                raise ValueError("race_date_end needs a race_date")
            if self.race_date_end <= self.race_date:
                raise ValueError("race_date_end must be after race_date")

        if self.ballot_opens and self.ballot_closes and self.ballot_closes <= self.ballot_opens:
            raise ValueError("ballot_closes must be after ballot_opens")
        if self.ballot_closes and self.ballot_results and self.ballot_results < self.ballot_closes.date():
            raise ValueError("ballot_results must not be before ballot_closes")
        if self.race_date:
            for name in ("ballot_opens", "ballot_closes", "general_entry_opens"):
                value = getattr(self, name)
                if value and value.date() > self.race_date:
                    raise ValueError(f"{name} must not be after race_date")

        has_ballot_dates = self.ballot_opens or self.ballot_closes or self.ballot_results
        if has_ballot_dates and EntryType.ballot not in self.entry_type:
            raise ValueError("ballot dates are set but entry_type does not include ballot")

        if self.confidence == Confidence.confirmed:
            if not self.source_url:
                raise ValueError("confirmed records need a source_url")
            if not self.last_verified:
                raise ValueError("confirmed records need a last_verified date")
        return self

    @property
    def year(self) -> int:
        return int(self.id.rsplit("-", 1)[1])

    @property
    def is_uk(self) -> bool:
        return self.country == "UK"

    @property
    def has_ballot(self) -> bool:
        return EntryType.ballot in self.entry_type

    @property
    def entry_url(self) -> str | None:
        url = self.official_url or self.source_url
        return str(url) if url else None


class RaceList(BaseModel):
    """The whole of races.yaml."""

    model_config = ConfigDict(extra="forbid")

    races: list[Race]

    @model_validator(mode="after")
    def _unique_ids(self) -> RaceList:
        seen: set[str] = set()
        for race in self.races:
            if race.id in seen:
                raise ValueError(f"duplicate id: {race.id}")
            seen.add(race.id)
        return self


def to_utc(value: datetime) -> datetime:
    """Treat a naive races.yaml datetime as UK local time and convert to UTC."""
    return value.replace(tzinfo=UK_TZ).astimezone(ZoneInfo("UTC"))
