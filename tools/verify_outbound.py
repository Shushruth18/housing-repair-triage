"""Verify what left (or would have left) the machine for one run label.

Usage: .venv/Scripts/python.exe tools/verify_outbound.py run_b

Reads outbound_log.jsonl, and for every payload logged under that label reports
the channel, dry-run flag, PII scan labels and occurrence COUNTS of each tenant
email/name. Raw PII values are never printed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from triage import config, load  # noqa: E402


def main() -> int:
    label = sys.argv[1]
    tenants = load.load_tenants()
    recs = [json.loads(l) for l in config.OUTBOUND_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r["run"] == label]
    if not recs:
        print(f"no outbound records for {label}")
        return 1
    total_email_hits = 0
    gen_with_email = 0
    for i, r in enumerate(recs, 1):
        body = json.dumps(r["payload"], ensure_ascii=False)
        counts = {}
        for t in tenants.values():
            e = body.count(t.email)
            n = len(re.findall(rf"\b{re.escape(t.name)}\b", body, re.IGNORECASE))
            if e or n:
                counts[t.unit_id] = {"email": e, "full_name": n}
        u2b_email = body.count(tenants["U2B"].email)
        total_email_hits += u2b_email
        gen_with_email += int(r["channel"] == "llm:generate" and u2b_email > 0)
        print(f"  #{i} {r['ts']} {r['channel']:<20} url={r['url']} dry_run={r['dry_run']} leak_test={r['leak_test']} "
              f"bytes={r['bytes']} sha={r['sha256']} pii_scan={r['pii_scan'] or 'clean'} exact_counts={counts or 'none'}")
    gens = sum(r["channel"] == "llm:generate" for r in recs)
    print(f"[{label}] payloads={len(recs)} generation_requests={gens} "
          f"generation_requests_containing_U2B_email={gen_with_email} total_U2B_email_occurrences={total_email_hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
