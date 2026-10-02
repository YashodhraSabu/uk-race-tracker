"""Render the static website from races.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tracker.events import upcoming_deadlines
from tracker.feeds import FEEDS
from tracker.models import Confidence, Race

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

DISTANCE_LABELS = {"marathon": "Marathon", "half": "Half", "10k": "10K", "ultra": "Ultra", "other": "Other"}
ENTRY_LABELS = {"ballot": "Ballot", "general": "General", "charity": "Charity", "gfa": "Good for age"}
STATUS_LABELS = {
    "unannounced": "Not announced",
    "announced": "Announced",
    "ballot_open": "Ballot open",
    "ballot_closed": "Ballot closed",
    "sold_out": "Sold out",
    "done": "Done",
}


@dataclass(frozen=True)
class SubscribeLinks:
    filename: str
    title: str
    description: str
    https: str
    webcal: str
    google: str
    outlook: str


def subscribe_links(site_url: str) -> list[SubscribeLinks]:
    base = site_url.rstrip("/")
    links = []
    for feed in FEEDS:
        https = f"{base}/{feed.filename}"
        webcal = "webcal://" + https.split("://", 1)[1]
        links.append(
            SubscribeLinks(
                filename=feed.filename,
                title=feed.title,
                description=feed.description,
                https=https,
                webcal=webcal,
                google=f"https://calendar.google.com/calendar/render?cid={quote(webcal, safe='')}",
                outlook=(
                    "https://outlook.live.com/calendar/0/addfromweb"
                    f"?url={quote(https, safe='')}&name={quote(feed.title, safe='')}"
                ),
            )
        )
    return links


def render_site(
    races: list[Race],
    today: date,
    generated_at: datetime,
    site_url: str,
    suggest_url: str | None,
    goatcounter_url: str | None = None,
) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(
        distance_label=lambda d: DISTANCE_LABELS[d.value],
        entry_label=lambda e: ENTRY_LABELS[e.value],
        status_label=lambda s: STATUS_LABELS[s.value],
    )
    ordered = sorted(races, key=lambda r: (r.race_date is None, r.race_date or date.max, r.name))
    return env.get_template("index.html.j2").render(
        races=ordered,
        deadlines=upcoming_deadlines(races, today),
        feeds=subscribe_links(site_url),
        today=today,
        generated_at=generated_at,
        suggest_url=suggest_url,
        goatcounter_url=goatcounter_url,
        confirmed=Confidence.confirmed,
    )
