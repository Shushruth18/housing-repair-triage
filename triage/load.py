"""Stage 1: load and validate the CSVs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Tenant:
    unit_id: str
    name: str
    email: str


@dataclass(frozen=True)
class RepairEvent:
    event_id: str
    unit_id: str
    date: date
    issue: str
    status: str
    detail: str


def _read_rows(path: Path, required: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise ValidationError(f"{path.name}: missing columns {missing}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def load_tenants(path: Path = config.TENANTS_CSV) -> dict[str, Tenant]:
    tenants: dict[str, Tenant] = {}
    for row in _read_rows(path, ["unit_id", "name", "email"]):
        if row["unit_id"] in tenants:
            raise ValidationError(f"{path.name}: duplicate unit_id {row['unit_id']}")
        tenants[row["unit_id"]] = Tenant(row["unit_id"], row["name"], row["email"])
    return tenants


def load_events(path: Path = config.EVENTS_CSV) -> list[RepairEvent]:
    events: list[RepairEvent] = []
    seen: set[str] = set()
    for row in _read_rows(path, ["event_id", "unit_id", "date", "issue", "status", "detail"]):
        if row["event_id"] in seen:
            raise ValidationError(f"{path.name}: duplicate event_id {row['event_id']}")
        seen.add(row["event_id"])
        try:
            d = date.fromisoformat(row["date"])
        except ValueError as exc:
            raise ValidationError(f"{row['event_id']}: bad date {row['date']!r}") from exc
        events.append(RepairEvent(row["event_id"], row["unit_id"], d, row["issue"], row["status"], row["detail"]))
    return events


def validate(events: list[RepairEvent], tenants: dict[str, Tenant]) -> list[RepairEvent]:
    """Check every event's unit exists in tenants; return events sorted by date."""
    unknown = sorted({e.unit_id for e in events if e.unit_id not in tenants})
    if unknown:
        raise ValidationError(f"repair events reference unknown unit_id(s): {unknown}")
    return sorted(events, key=lambda e: (e.date, e.event_id))


def load_all() -> tuple[dict[str, Tenant], list[RepairEvent]]:
    tenants = load_tenants()
    return tenants, validate(load_events(), tenants)
