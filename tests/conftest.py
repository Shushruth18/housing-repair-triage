import pytest

from triage import chunk, load
from triage.embed import local_embed
from triage.store import VectorStore

QUESTION = "Has unit 2B's kitchen sink leak been reported before, and what follow-up does the procedure call for?"


@pytest.fixture
def data():
    return load.load_all()


@pytest.fixture
def store(data):
    tenants, events = data
    chunks = chunk.build_chunks(events, tenants)
    return VectorStore(chunks, local_embed([c.text for c in chunks]), "local:test")


@pytest.fixture
def question():
    return QUESTION
