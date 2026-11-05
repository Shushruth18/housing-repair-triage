import pytest

from triage import retrieve
from triage.embed import Embedder
from triage.outbound import Gate


@pytest.fixture
def emb(data):
    return Embedder(Gate(data[0], dry_run=True, log=False), provider="local")


@pytest.mark.parametrize("q,unit", [("unit 2B sink", "U2B"), ("Unit U2D leak?", "U2D"), ("what about U3A", "U3A")])
def test_parse_unit(q, unit):
    assert retrieve.parse_unit(q) == unit


def test_parse_unit_missing():
    with pytest.raises(retrieve.RetrievalError):
        retrieve.parse_unit("is the sink leaking?")


def test_u2b_timeline_filtered_and_ordered(store, emb, question):
    r = retrieve.retrieve(question, store, emb)
    assert r.unit_id == "U2B" and r.issue == "Kitchen sink leak"
    assert [c.chunk_id for c in r.timeline] == ["R201", "R202", "R203"]
    assert all(c.metadata["unit_id"] == "U2B" for c in r.timeline)
    assert not {"R204", "R205"} & {c.chunk_id for c in r.timeline}
    assert [c.chunk_id for c, _ in r.procedure] == ["RP01"]


def test_u2d_gets_only_its_own_leak(store, emb):
    r = retrieve.retrieve("Has unit 2D's kitchen sink leak happened before?", store, emb)
    assert [c.chunk_id for c in r.timeline] == ["R204", "R205"]


def test_issue_filter_excludes_other_issues(store, emb):
    r = retrieve.retrieve("Any heating failure in unit 3A?", store, emb)
    assert [c.chunk_id for c in r.timeline] == ["R206"]
    assert all(c.kind == "procedure" for c, _ in r.procedure)
