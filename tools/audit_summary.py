"""Summarise an AgenticAudit /v1/events response read from stdin.

Usage (Git Bash):
    K=$(grep '^AGENTAUDIT_API_KEY' C:/Users/shush/agentic-audit-lab/agentaudit.env | cut -d= -f2- | tr -d '\r')
    curl.exe -s -H "Authorization: Bearer $K" "http://localhost:8000/v1/events?limit=20" \
        | .venv/Scripts/python.exe tools/audit_summary.py run_a

Saves the raw JSON to audit_logs/<label>.json and prints one line per event
(oldest first). Email addresses inside event text are masked in the printout
only, so this summary itself does not re-emit them.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def short(event: dict) -> str:
    data = event.get("data") or {}
    text = data.get("command") or data.get("file_path") or data.get("path") or json.dumps(data)
    text = EMAIL_RE.sub("<email>", str(text)).replace("\n", " ")
    return text[:110]


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "events"
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    body = json.loads(raw)
    out = Path(__file__).resolve().parent.parent / "audit_logs" / f"{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(body, indent=2), encoding="utf-8")

    events = list(reversed(body.get("events", [])))
    print(f"[{label}] {len(events)} events (total stored: {body.get('total')}) -> {out.name}")
    for e in events:
        ctx = e.get("context") or {}
        fw = e.get("frameworks") or {}
        fw_s = ";".join(f"{k}:{','.join(v)}" for k, v in fw.items()) or "-"
        pii = ",".join(e.get("pii_fields") or []) if e.get("pii_detected") else "no"
        print(
            f"{e.get('created_at', '')[11:19]} {ctx.get('hook_event', ''):<11} {e.get('action', ''):<14} "
            f"risk={e.get('risk_level', ''):<8} pii={pii:<14} fw={fw_s:<28} "
            f"decision={e.get('decision')} | {short(e)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
