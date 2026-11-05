"""Streamlit page for the housing repair triage assistant.

Run:  .venv\\Scripts\\streamlit.exe run app.py

Uses the same pipeline as the CLI: every outbound request goes through the
PII gate in triage/outbound.py and is logged to outbound_log.jsonl with the
run label "streamlit".
"""

from __future__ import annotations

import streamlit as st

from triage import chunk, config, generate, load, retrieve
from triage.cli import EXPECTED, FORBIDDEN_FOR_U2B
from triage.embed import Embedder
from triage.outbound import Gate
from triage.redact import PIILeakError
from triage.store import VectorStore

DEFAULT_Q = "Has unit 2B's kitchen sink leak been reported before, and what follow-up does the procedure call for?"

st.set_page_config(page_title="Housing repair triage", page_icon=":material/plumbing:")


def md_table(headers: list[str], rows: list[list]) -> str:
    """Markdown table. Used instead of st.dataframe, whose pandas DLLs are blocked
    by this PC's Windows Application Control policy."""
    cell = lambda v: str(v).replace("|", "\\|")  # noqa: E731
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


@st.cache_resource
def get_data():
    return load.load_all()


@st.cache_resource
def get_store(provider: str) -> VectorStore:
    """Load the vector store; build it with the configured provider if missing or stale."""
    tenants, events = get_data()
    try:
        store = VectorStore.load()
        if store.embedder.startswith(provider + ":"):
            return store
    except FileNotFoundError:
        pass
    embedder = Embedder(Gate(tenants, run_label="streamlit_index"))
    chunks = chunk.build_chunks(events, tenants)
    vecs = embedder.embed([c.text for c in chunks], input_type="document")
    store = VectorStore(chunks, vecs, embedder.name)
    store.save()
    return store


if "result" not in st.session_state:
    st.session_state.result = None

st.title("Housing repair triage")
st.caption(
    "Rebuilds a unit's repair history and finds the next step from the procedure. "
    "Fictional data. Tenant names and emails never leave this machine."
)

with st.form("ask"):
    question = st.text_area("Question", value=DEFAULT_Q, height=90)
    with st.container(horizontal=True, vertical_alignment="center"):
        dry_run = st.toggle("Dry run (show payload, send nothing)", value=True)
        submitted = st.form_submit_button("Ask", type="primary", icon=":material/search:")

if submitted:
    tenants, _ = get_data()
    gate = Gate(tenants, dry_run=dry_run, run_label="streamlit")
    try:
        with st.spinner("Retrieving and generating..."):
            store = get_store(config.embeddings_provider())
            r = retrieve.retrieve(question, store, Embedder(gate))
            answer = generate.generate(r, tenants, gate)
        st.session_state.result = {"r": r, "answer": answer, "records": gate.records, "dry_run": dry_run}
    except (retrieve.RetrievalError, PIILeakError, RuntimeError) as exc:
        st.session_state.result = None
        st.error(str(exc), title="Could not answer")

res = st.session_state.result
if res:
    r = res["r"]
    with st.container(horizontal=True):
        st.badge(f"Unit {r.unit_id}", icon=":material/home:")
        st.badge(r.issue, icon=":material/build:", color="gray")
        st.badge(f"Embeddings: {config.embeddings_provider()}", icon=":material/scatter_plot:", color="violet")

    st.subheader("Repair timeline")
    st.markdown(md_table(
        ["Date", "Event", "Status", "Detail"],
        [[c.metadata["date"], c.chunk_id, c.metadata["status"], c.metadata["detail"]] for c in r.timeline],
    ))

    st.subheader("Procedure")
    for c, score in r.procedure:
        st.markdown(f"**{c.chunk_id}** · {c.text}  \n:gray[similarity {score:.3f}]")
    for note in r.notes:
        st.caption(note)

    st.subheader("Outbound requests")
    rows = [
        [f"`{rec['channel']}`", "no (dry run)" if rec["dry_run"] else "yes", rec["bytes"],
         ", ".join(rec["pii_scan"]) or "clean"]
        for rec in res["records"]
    ]
    if rows:
        st.markdown(md_table(["Channel", "Sent", "Bytes", "PII scan"], rows))
    else:
        st.caption("No outbound requests.")
    with st.expander("Payloads", icon=":material/data_object:"):
        for rec in res["records"]:
            st.markdown(f"`{rec['channel']}` → {rec['url']}")
            st.json(rec["payload"], expanded=False)

    st.subheader("Answer")
    if res["answer"] is None:
        st.info("Dry run: nothing was sent. Turn off dry run to get an answer.", icon=":material/visibility:")
    else:
        with st.container(border=True):
            st.markdown(res["answer"])
        if r.unit_id == "U2B":
            chk = generate.check_answer(res["answer"], r, EXPECTED, FORBIDDEN_FOR_U2B)
        else:
            chk = generate.check_answer(res["answer"], r)
        detail = (
            f"Cited: {', '.join(chk.cited) or 'none'}. "
            f"Unresolved: {', '.join(chk.unresolved) or 'none'}."
        )
        if r.unit_id == "U2B":
            detail += (
                f" Missing expected: {', '.join(chk.missing_expected) or 'none'}."
                f" Other-unit mentions: {', '.join(chk.forbidden_present) or 'none'}."
                f" Mentions inspection: {'yes' if chk.mentions_inspection else 'no'}."
            )
            ok = chk.ok
        else:
            ok = not chk.unresolved
        if ok:
            st.success(detail, title="Citation check passed", icon=":material/check_circle:")
        else:
            st.error(detail, title="Citation check failed", icon=":material/error:")
