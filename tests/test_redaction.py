import json
import re

import pytest

from triage import chunk, generate, retrieve
from triage.embed import Embedder
from triage.outbound import Gate
from triage.redact import PIILeakError, redact, scan


def _all_pii(tenants):
    vals = []
    for t in tenants.values():
        vals += [t.email, t.name, *t.name.split()]
    return vals


def _assert_no_pii(text, tenants):
    for v in _all_pii(tenants):
        assert not re.search(rf"\b{re.escape(v)}\b", text, re.IGNORECASE), f"PII value leaked into outbound text: {v!r}"
    assert "@" not in text
    assert scan(text, tenants) == []


def test_redact_removes_names_and_emails(data):
    tenants, _ = data
    t = tenants["U2B"]
    out = redact(f"Ask {t.name} ({t.email}) or {t.name.split()[0]} directly", tenants)
    _assert_no_pii(out, tenants)
    assert "[REDACTED_EMAIL]" in out and "[REDACTED_NAME]" in out


def test_chunk_text_has_no_pii(data):
    tenants, events = data
    for c in chunk.build_chunks(events, tenants):
        _assert_no_pii(c.text, tenants)


@pytest.mark.parametrize("provider", ["voyage", "openai"])
def test_every_outbound_payload_is_clean(data, store, question, provider):
    tenants, events = data
    gate = Gate(tenants, dry_run=True, log=False)
    emb = Embedder(gate, provider=provider)
    emb.embed([c.text for c in chunk.build_chunks(events, tenants)], input_type="document")
    r = retrieve.retrieve(question, store, emb)
    generate.generate(r, tenants, gate)
    channels = [rec["channel"] for rec in gate.records]
    assert channels == ["embeddings:document", "embeddings:query", "llm:generate"]
    for rec in gate.records:
        _assert_no_pii(json.dumps(rec["payload"]), tenants)
        assert rec["pii_scan"] == []


def test_gate_blocks_pii_and_never_calls_sender(data):
    tenants, _ = data
    gate = Gate(tenants, dry_run=False, log=False)
    called = []
    with pytest.raises(PIILeakError):
        gate.send("llm:generate", "x", {"q": f"mail {tenants['U2B'].email}"}, lambda p: called.append(p))
    assert called == []
    assert gate.records[-1]["blocked"] is True


def test_leak_test_puts_email_in_exactly_one_request(data, store, question):
    tenants, _ = data
    gate = Gate(tenants, dry_run=True, log=False)
    r = retrieve.retrieve(question, store, Embedder(gate, provider="local"))
    generate.generate(r, tenants, gate, leak_test=True)
    leaked = [rec for rec in gate.records if tenants["U2B"].email in json.dumps(rec["payload"])]
    assert len(gate.records) == 1 and len(leaked) == 1
    assert leaked[0]["channel"] == "llm:generate" and "email:U2B" in leaked[0]["pii_scan"]
    assert json.dumps(leaked[0]["payload"]).count(tenants["U2B"].email) == 1
