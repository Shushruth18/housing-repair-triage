"""Command-line interface: python -m triage <command> ..."""

from __future__ import annotations

import argparse
import sys

from . import chunk, config, generate, load, redact, retrieve
from .embed import Embedder
from .outbound import Gate
from .store import VectorStore


def cmd_validate(args: argparse.Namespace) -> int:
    tenants, events = load.load_all()
    print(f"OK: {len(tenants)} tenants, {len(events)} repair events; every unit_id resolves to a tenant.")
    print("Events sorted by date:")
    for e in events:
        print(f"  {e.date}  {e.event_id}  {e.unit_id}  {e.issue:<18} {e.status:<9} {e.detail}")
    return 0


def cmd_redact(args: argparse.Namespace) -> int:
    tenants, events = load.load_all()
    rec = redact.join_local(args.unit, tenants, events)
    print(f"LOCAL ONLY (never sent): unit {rec.unit_id} contact = {rec.tenant_name} <{rec.tenant_email}>")
    print("Outbound text for this unit (after redaction + scan):")
    for e in rec.events:
        text = redact.redact(f"{e.event_id} {e.date} {e.issue} [{e.status}] {e.detail}", tenants)
        print(f"  {text}    scan={redact.scan(text, tenants) or 'clean'}")
    demo = f"Call {rec.tenant_name} at {rec.tenant_email} about the sink."
    print(f"Demo input scan  : {redact.scan(demo, tenants)}")
    print(f"Demo after redact: {redact.redact(demo, tenants)!r}  scan={redact.scan(redact.redact(demo, tenants), tenants) or 'clean'}")
    return 0


def cmd_chunk(args: argparse.Namespace) -> int:
    tenants, events = load.load_all()
    for c in chunk.build_chunks(events, tenants):
        print(f"{c.chunk_id:<5} {c.kind:<9} text={c.text!r}")
        print(f"      local metadata={c.metadata}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    tenants, events = load.load_all()
    gate = Gate(tenants, dry_run=args.dry_run, run_label=args.run_label)
    embedder = Embedder(gate)
    chunks = chunk.build_chunks(events, tenants)
    vecs = embedder.embed([c.text for c in chunks], input_type="document")
    if vecs is None:
        print("[index] dry run: store not written")
        return 0
    VectorStore(chunks, vecs, embedder.name).save()
    print(f"[index] stored {len(chunks)} chunks x {vecs.shape[1]} dims using {embedder.name} in {config.STORE_DIR.name}/")
    return 0


def print_retrieval(r: retrieve.Retrieval) -> None:
    print(f"[retrieve] unit={r.unit_id} issue={r.issue!r}")
    for n in r.notes:
        print(f"[retrieve] note: {n}")
    print("[retrieve] timeline (date order, filtered by unit + issue):")
    for c in r.timeline:
        m = c.metadata
        print(f"  {m['date']}  {c.chunk_id}  {m['status']:<9} {m['detail']}")
    print("[retrieve] procedure (vector search over procedure sections only):")
    for c, s in r.procedure:
        print(f"  {c.chunk_id}  score={s:.3f}  {c.text}")


def cmd_retrieve(args: argparse.Namespace) -> int:
    tenants, _ = load.load_all()
    gate = Gate(tenants, dry_run=args.dry_run, run_label=args.run_label)
    print_retrieval(retrieve.retrieve(args.question, VectorStore.load(), Embedder(gate)))
    return 0


EXPECTED = ["R201", "R202", "R203", "RP01"]
FORBIDDEN_FOR_U2B = ["R204", "R205", "U2D", "2D"]


def cmd_ask(args: argparse.Namespace) -> int:
    tenants, events = load.load_all()
    gate = Gate(tenants, dry_run=args.dry_run, run_label=args.run_label)
    r = retrieve.retrieve(args.question, VectorStore.load(), Embedder(gate))
    print_retrieval(r)
    rec = redact.join_local(r.unit_id, tenants, events)
    print(f"[local] tenant contact for {r.unit_id}: {rec.tenant_name} (kept local, not sent)")

    answer = generate.generate(r, tenants, gate, leak_test=args.leak_test)
    print("\n[outbound summary]")
    for rec_ in gate.records:
        print(f"  {rec_['channel']:<20} dry_run={rec_['dry_run']} leak_test={rec_['leak_test']} "
              f"bytes={rec_['bytes']} pii_scan={rec_['pii_scan'] or 'clean'}")
    if not gate.records:
        print("  (no outbound payloads)")
    if answer is None:
        return 0

    print("\n===== ANSWER =====")
    print(answer)
    print("==================")
    if r.unit_id == "U2B":
        chk = generate.check_answer(answer, r, EXPECTED, FORBIDDEN_FOR_U2B)
        print(f"[check] cited={chk.cited} unresolved={chk.unresolved or 'none'} "
              f"missing_expected={chk.missing_expected or 'none'} forbidden_present={chk.forbidden_present or 'none'} "
              f"mentions_inspection={chk.mentions_inspection} -> {'PASS' if chk.ok else 'FAIL'}")
        return 0 if chk.ok else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="triage", description="Housing repair triage assistant (fictional data).")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Stage 1: load CSVs, check unit_ids, sort by date").set_defaults(func=cmd_validate)
    r = sub.add_parser("redact", help="Stage 2: show local join vs redacted outbound text")
    r.add_argument("--unit", default="U2B")
    r.set_defaults(func=cmd_redact)
    sub.add_parser("chunk", help="Stage 3: show chunks and local metadata").set_defaults(func=cmd_chunk)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="print every outgoing payload without sending it")
    common.add_argument("--run-label", default="", help="tag written to outbound_log.jsonl (e.g. run_b)")
    sub.add_parser("index", parents=[common], help="Stage 4: embed chunks and save vectors locally").set_defaults(func=cmd_index)
    rt = sub.add_parser("retrieve", parents=[common], help="Stage 5: show retrieved timeline + procedure")
    rt.add_argument("question")
    rt.set_defaults(func=cmd_retrieve)
    a = sub.add_parser("ask", parents=[common], help="Stages 5-6: retrieve and generate a cited answer")
    a.add_argument("question")
    a.add_argument("--leak-test", action="store_true",
                   help="COMPLIANCE TEST ONLY: put the unit's tenant email into the one LLM request")
    a.set_defaults(func=cmd_ask)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
