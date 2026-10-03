"""Edit one race's fields in races.yaml without disturbing the rest of the file.

Re-dumping the file with a YAML library would drop its comments and reorder
things, which makes review diffs noisy. Every record is a flat block of
`    field: value` lines, so we change those lines directly and then check the
result still loads and validates.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum

from tracker.models import Race

FIELD_ORDER = list(Race.model_fields)
RECORD_START = re.compile(r"^  - id: (\S+)\s*$")
FIELD_LINE = re.compile(r"^    ([a-z_]+):")


def format_value(value: object) -> str:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def update_race(text: str, race_id: str, updates: dict[str, object]) -> str:
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if (m := RECORD_START.match(line)) and m.group(1) == race_id), None)
    if start is None:
        raise KeyError(f"race {race_id} not found in races.yaml")
    end = start + 1
    while end < len(lines) and lines[end].startswith("    "):
        end += 1

    block = lines[start:end]
    for name, value in updates.items():
        if name not in FIELD_ORDER or name == "id":
            raise KeyError(f"can't update field {name!r}")
        new_line = f"    {name}: {format_value(value)}"
        existing = next((i for i, line in enumerate(block) if _field(line) == name), None)
        if existing is not None:
            block[existing] = new_line
            continue
        # Insert before the first field that comes later in the model's field order.
        later = set(FIELD_ORDER[FIELD_ORDER.index(name) + 1 :])
        position = next((i for i, line in enumerate(block) if i > 0 and _field(line) in later), len(block))
        block.insert(position, new_line)
    return "\n".join(lines[:start] + block + lines[end:])


def _field(line: str) -> str | None:
    if line.startswith("  - id:"):
        return "id"
    match = FIELD_LINE.match(line)
    return match.group(1) if match else None
