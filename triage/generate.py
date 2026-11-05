"""Stage 6: build the answer-generation request, send it via the Gate, check citations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import config
from .load import Tenant
from .outbound import Gate
from .redact import redact
from .retrieve import Retrieval

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
CITE_RE = re.compile(r"\b(RP\d{2}|R\d{3})\b")

SYSTEM = (
    "You are a housing repair triage assistant. Answer ONLY from the repair timeline and "
    "procedure sections provided. Cite every fact with its ID in square brackets, e.g. [R201] "
    "or [RP01], one ID per bracket. Do not mention or speculate about any other unit. "
    "Be concise: a short chronological summary, then the required next step."
)


def build_payload(r: Retrieval, tenants: dict[str, Tenant]) -> dict[str, Any]:
    timeline = "\n".join(
        f"[{c.chunk_id}] {c.metadata['date']} | unit {c.metadata['unit_id']} | {c.metadata['issue']} | "
        f"status: {c.metadata['status']} | {c.metadata['detail']}"
        for c in r.timeline
    )
    procedure = "\n".join(f"[{c.chunk_id}] {c.text}" for c, _ in r.procedure)
    user = (
        f"Question: {r.question}\n\n"
        f"Repair timeline for unit {r.unit_id}, issue '{r.issue}' (date order):\n{timeline}\n\n"
        f"Procedure sections:\n{procedure}\n\n"
        "Describe the history of this issue, then state what follow-up the procedure requires. Cite IDs."
    )
    return {
        "model": config.anthropic_model(),
        "max_tokens": 600,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": redact(user, tenants)}],
    }


def inject_leak(payload: dict[str, Any], email: str) -> dict[str, Any]:
    """--leak-test only: deliberately place the tenant email in this one request."""
    leaked = dict(payload)
    msg = dict(payload["messages"][0])
    msg["content"] = msg["content"] + f"\n\nTenant contact on file: {email}"
    leaked["messages"] = [msg]
    return leaked


def _send_anthropic(payload: dict[str, Any]) -> str:
    import anthropic

    key = config.setting("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is empty in .env")
    resp = anthropic.Anthropic(api_key=key).messages.create(**payload)
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


@dataclass
class AnswerCheck:
    cited: list[str]
    unresolved: list[str]
    missing_expected: list[str] = field(default_factory=list)
    forbidden_present: list[str] = field(default_factory=list)
    mentions_inspection: bool = False

    @property
    def ok(self) -> bool:
        return not (self.unresolved or self.missing_expected or self.forbidden_present) and self.mentions_inspection


def check_answer(answer: str, r: Retrieval, expected: list[str] | None = None, forbidden: list[str] | None = None) -> AnswerCheck:
    cited = sorted(set(CITE_RE.findall(answer)))
    context_ids = {c.chunk_id for c in r.timeline} | {c.chunk_id for c, _ in r.procedure}
    forbidden = forbidden or []
    present = [f for f in forbidden if re.search(rf"\b{re.escape(f)}\b", answer, re.IGNORECASE)]
    return AnswerCheck(
        cited=cited,
        unresolved=[c for c in cited if c not in context_ids],
        missing_expected=[e for e in (expected or []) if e not in cited],
        forbidden_present=present,
        mentions_inspection="inspection" in answer.lower(),
    )


def generate(r: Retrieval, tenants: dict[str, Tenant], gate: Gate, *, leak_test: bool = False) -> str | None:
    payload = build_payload(r, tenants)
    if leak_test:
        payload = inject_leak(payload, tenants[r.unit_id].email)
        print("[generate] --leak-test: tenant email deliberately injected into this ONE generation request")
    return gate.send("llm:generate", ANTHROPIC_URL, payload, _send_anthropic, allow_pii=leak_test)
