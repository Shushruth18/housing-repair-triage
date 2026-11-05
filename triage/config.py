"""Paths and settings. Secrets come from .env (git-ignored)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STORE_DIR = ROOT / ".store"
OUTBOUND_LOG = ROOT / "outbound_log.jsonl"

TENANTS_CSV = DATA_DIR / "tenants.csv"
EVENTS_CSV = DATA_DIR / "repair_events.csv"
PROCEDURE_MD = DATA_DIR / "repair-procedure.md"

load_dotenv(ROOT / ".env")


def setting(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def anthropic_model() -> str:
    return setting("ANTHROPIC_MODEL", "claude-opus-5-5")


def embeddings_provider() -> str:
    return setting("EMBEDDINGS_PROVIDER", "local").lower()
