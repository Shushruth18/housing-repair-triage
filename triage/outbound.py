"""Single gate for every request that leaves the machine.

Each payload is: serialised -> scanned for PII -> blocked if dirty (unless the
caller explicitly allows it for --leak-test) -> logged to outbound_log.jsonl ->
printed and NOT sent when dry_run is on, otherwise sent.

The log stores PII *labels* (e.g. "email:U2B") so verification never needs to
grep for the raw value.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from . import config
from .load import Tenant
from .redact import PIILeakError, scan


class Gate:
    def __init__(self, tenants: dict[str, Tenant], *, dry_run: bool = False, run_label: str = "", log: bool = True):
        self.tenants = tenants
        self.dry_run = dry_run
        self.run_label = run_label or "adhoc"
        self.log = log
        self.records: list[dict[str, Any]] = []  # in-memory copy, used by tests and the CLI summary

    def send(
        self,
        channel: str,
        url: str,
        payload: dict[str, Any],
        sender: Callable[[dict[str, Any]], Any],
        *,
        allow_pii: bool = False,
    ) -> Any:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        hits = scan(body, self.tenants)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run": self.run_label,
            "channel": channel,
            "url": url,
            "dry_run": self.dry_run,
            "leak_test": allow_pii,
            "pii_scan": hits,
            "bytes": len(body.encode("utf-8")),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
            "payload": payload,
        }
        if hits and not allow_pii:
            record["blocked"] = True
            self._write(record)
            raise PIILeakError(f"Blocked outbound {channel} payload: contains {hits}")
        self._write(record)

        if self.dry_run:
            print(f"\n----- DRY RUN: outbound {channel} -> {url} (NOT SENT) pii_scan={hits or 'clean'} -----")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            print("----- end payload -----")
            return None
        return sender(payload)

    def _write(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        if self.log:
            with config.OUTBOUND_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
