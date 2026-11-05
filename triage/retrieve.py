"""Stage 5: filtered retrieval.

1. Parse the unit (e.g. "unit 2B" -> U2B) and the issue from the question.
2. Event history = every event chunk with that unit_id AND issue, in date order
   (metadata filter, not similarity - so a near-identical leak in another unit
   can never be pulled in).
3. Procedure = vector search restricted to procedure chunks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .chunk import Chunk
from .embed import Embedder, local_embed
from .store import VectorStore

UNIT_RE = re.compile(r"\b(?:unit\s+U?|U)(\d+[A-Za-z])\b", re.IGNORECASE)


class RetrievalError(ValueError):
    pass


@dataclass
class Retrieval:
    question: str
    unit_id: str
    issue: str
    timeline: list[Chunk]
    procedure: list[tuple[Chunk, float]]
    notes: list[str] = field(default_factory=list)


def parse_unit(question: str) -> str:
    m = UNIT_RE.search(question)
    if not m:
        raise RetrievalError("Could not find a unit in the question (e.g. 'unit 2B').")
    return "U" + m.group(1).upper()


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))


def retrieve(question: str, store: VectorStore, embedder: Embedder, *, k_procedure: int = 2) -> Retrieval:
    unit = parse_unit(question)
    unit_events = [c for c in store.chunks if c.kind == "event" and c.metadata["unit_id"] == unit]
    if not unit_events:
        raise RetrievalError(f"No repair events for {unit}.")
    notes: list[str] = []

    qvec = embedder.embed([question], input_type="query")
    if qvec is None:  # dry run with an external provider: fall back to local lexical vectors
        notes.append("dry run: query vector not fetched; used local lexical scoring for ranking")
        qv = local_embed([question])[0]
        vec_of = lambda c: local_embed([c.text])[0]  # noqa: E731
    else:
        qv = qvec[0]
        vec_of = lambda c: store.vectors[store.chunks.index(c)]  # noqa: E731

    issues = sorted({c.metadata["issue"] for c in unit_events})
    named = [i for i in issues if i.lower() in question.lower()]
    if named:
        issue = named[0]
    else:
        issue = max(unit_events, key=lambda c: _cos(qv, vec_of(c))).metadata["issue"]
        notes.append(f"issue not named in question; picked closest for {unit}: {issue}")

    timeline = sorted(
        (c for c in unit_events if c.metadata["issue"] == issue),
        key=lambda c: (c.metadata["date"], c.chunk_id),
    )

    procs = [c for c in store.chunks if c.kind == "procedure"]
    ranked = sorted(((c, _cos(qv, vec_of(c))) for c in procs), key=lambda t: -t[1])
    procedure = [(c, s) for c, s in ranked[:k_procedure] if s > 0] or ranked[:1]
    return Retrieval(question, unit, issue, timeline, procedure, notes)
