"""Stage 3: one chunk per repair event and one per procedure section.

`text` is what may be sent to the embeddings API (redacted, no IDs).
`metadata` (event_id, unit_id, date, issue) stays on this machine.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config
from .load import RepairEvent, Tenant
from .redact import redact

SECTION_RE = re.compile(r"^##\s*(?P<id>[A-Z]+\d+)\s*\|\s*(?P<title>.+)$")


@dataclass
class Chunk:
    chunk_id: str
    kind: str  # "event" | "procedure"
    text: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def event_chunks(events: list[RepairEvent], tenants: dict[str, Tenant]) -> list[Chunk]:
    return [
        Chunk(
            chunk_id=e.event_id,
            kind="event",
            text=redact(f"{e.issue}. Status: {e.status}. {e.detail}.", tenants),
            metadata={"event_id": e.event_id, "unit_id": e.unit_id, "date": e.date.isoformat(),
                      "issue": e.issue, "status": e.status, "detail": e.detail},
        )
        for e in events
    ]


def procedure_chunks(tenants: dict[str, Tenant], path: Path = config.PROCEDURE_MD) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = SECTION_RE.match(line.strip())
        if m:
            if current:
                chunks.append(current["chunk"])
            current = {"chunk": Chunk(m["id"], "procedure", "", {"section_id": m["id"], "title": m["title"].strip()})}
        elif current and line.strip():
            current["chunk"].text = (current["chunk"].text + " " + line.strip()).strip()
    if current:
        chunks.append(current["chunk"])
    for c in chunks:
        c.text = redact(f"{c.metadata['title']}: {c.text}", tenants)
    return chunks


def build_chunks(events: list[RepairEvent], tenants: dict[str, Tenant]) -> list[Chunk]:
    return event_chunks(events, tenants) + procedure_chunks(tenants)
