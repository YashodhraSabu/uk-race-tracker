"""Load and validate races.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from tracker.models import RaceList


class DataError(Exception):
    """races.yaml is missing, malformed or fails validation."""


def load_races(path: Path) -> RaceList:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataError(f"{path} not found") from exc
    except yaml.YAMLError as exc:
        raise DataError(f"{path} is not valid YAML: {exc}") from exc

    try:
        return RaceList.model_validate(raw)
    except ValidationError as exc:
        raise DataError(_format_errors(exc, raw)) from exc


def _format_errors(exc: ValidationError, raw: object) -> str:
    """Name the race each error belongs to, instead of a bare list index."""
    races = raw.get("races") if isinstance(raw, dict) else None
    lines = []
    for error in exc.errors():
        loc = list(error["loc"])
        where = ".".join(str(part) for part in loc) or "races.yaml"
        if len(loc) >= 2 and loc[0] == "races" and isinstance(loc[1], int) and isinstance(races, list):
            index = loc[1]
            race_id = races[index].get("id", "?") if isinstance(races[index], dict) else "?"
            field = ".".join(str(part) for part in loc[2:]) or "(record)"
            where = f"races[{index}] {race_id}: {field}"
        lines.append(f"  {where}: {error['msg']}")
    return f"races.yaml failed validation ({len(lines)} error(s)):\n" + "\n".join(lines)
