"""Stage 2: keep contact details local; strip names and emails from outbound text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .load import RepairEvent, Tenant

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
NAME_TOKEN = "[REDACTED_NAME]"
EMAIL_TOKEN = "[REDACTED_EMAIL]"


class PIILeakError(RuntimeError):
    pass


@dataclass
class LocalCaseRecord:
    """Joined view used ONLY on this machine (CLI display). Never serialised outbound."""

    unit_id: str
    tenant_name: str
    tenant_email: str
    events: list[RepairEvent]


def join_local(unit_id: str, tenants: dict[str, Tenant], events: list[RepairEvent]) -> LocalCaseRecord:
    t = tenants[unit_id]
    return LocalCaseRecord(unit_id, t.name, t.email, [e for e in events if e.unit_id == unit_id])


def _name_patterns(tenants: dict[str, Tenant]) -> list[tuple[str, re.Pattern[str]]]:
    pats: list[tuple[str, re.Pattern[str]]] = []
    for t in tenants.values():
        parts = [t.name] + t.name.split()  # full name first, then each part
        for part in parts:
            if len(part) >= 2:
                pats.append((t.unit_id, re.compile(rf"\b{re.escape(part)}\b", re.IGNORECASE)))
    return pats


def scan(text: str, tenants: dict[str, Tenant]) -> list[str]:
    """Return labels (never the values) of PII found in text, e.g. ['email:U2B', 'name:U2B']."""
    hits: list[str] = []
    known = {t.email.lower(): t.unit_id for t in tenants.values()}
    for m in EMAIL_RE.finditer(text):
        hits.append(f"email:{known.get(m.group(0).lower(), 'unknown')}")
    for unit, pat in _name_patterns(tenants):
        if pat.search(text):
            hits.append(f"name:{unit}")
    return sorted(set(hits))


def redact(text: str, tenants: dict[str, Tenant]) -> str:
    out = EMAIL_RE.sub(EMAIL_TOKEN, text)
    for _, pat in _name_patterns(tenants):
        out = pat.sub(NAME_TOKEN, out)
    return out


def assert_clean(text: str, tenants: dict[str, Tenant], where: str) -> None:
    hits = scan(text, tenants)
    if hits:
        raise PIILeakError(f"Blocked outbound payload ({where}): contains {hits}")
