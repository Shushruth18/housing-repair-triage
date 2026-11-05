import os

import pytest

from triage import generate, retrieve
from triage.cli import EXPECTED, FORBIDDEN_FOR_U2B
from triage.embed import Embedder
from triage.outbound import Gate

GOOD = (
    "Yes. The leak was first reported on 2026-10-03 [R201]. A contractor replaced the drain seal and "
    "closed it on 2026-10-05 [R202]. It recurred on 2026-10-20 and was reopened [R203]. Because it "
    "recurred within 30 days, request a follow-up inspection [RP01]."
)


@pytest.fixture
def r(data, store, question):
    return retrieve.retrieve(question, store, Embedder(Gate(data[0], dry_run=True, log=False), provider="local"))


def test_prompt_contains_only_u2b_context(data, r):
    content = generate.build_payload(r, data[0])["messages"][0]["content"]
    for eid in EXPECTED:
        assert f"[{eid}]" in content
    assert "R204" not in content and "R205" not in content and "U2D" not in content


def test_good_answer_passes(r):
    chk = generate.check_answer(GOOD, r, EXPECTED, FORBIDDEN_FOR_U2B)
    assert chk.ok, chk


def test_answer_mentioning_u2d_fails(r):
    chk = generate.check_answer(GOOD + " Unit 2D had a similar leak [R204].", r, EXPECTED, FORBIDDEN_FOR_U2B)
    assert not chk.ok
    assert "R204" in chk.forbidden_present and "R204" in chk.unresolved


def test_missing_citation_or_inspection_fails(r):
    assert generate.check_answer(GOOD.replace("[R202]", ""), r, EXPECTED, FORBIDDEN_FOR_U2B).missing_expected == ["R202"]
    assert not generate.check_answer(GOOD.replace("inspection", "visit"), r, EXPECTED, FORBIDDEN_FOR_U2B).ok


@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call the Anthropic API")
def test_live_expected_answer(data, r):
    gate = Gate(data[0], dry_run=False, run_label="pytest_live")
    answer = generate.generate(r, data[0], gate)
    chk = generate.check_answer(answer, r, EXPECTED, FORBIDDEN_FOR_U2B)
    assert chk.ok, (chk, answer)
    assert gate.records[0]["pii_scan"] == []
