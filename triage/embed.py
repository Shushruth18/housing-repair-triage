"""Stage 4: embeddings. Providers: voyage | openai (external APIs) | local (no network).

Anthropic does not offer an embeddings endpoint; Voyage AI is its recommended
partner. `local` is a deterministic hashed bag-of-words fallback for when no
embeddings key is available - nothing leaves the machine for it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import numpy as np
import requests

from . import config
from .outbound import Gate

LOCAL_DIM = 512
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
OPENAI_URL = "https://api.openai.com/v1/embeddings"
STOP = {"the", "a", "an", "of", "and", "to", "in", "for", "is", "has", "been", "what", "does", "did", "be", "it", "s", "same"}


class EmbeddingConfigError(RuntimeError):
    pass


def _tokens(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]
    words = [w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words]  # crude plural strip
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def local_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), LOCAL_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for tok in _tokens(t):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            out[i, h % LOCAL_DIM] += 1.0 if (h >> 64) & 1 else -1.0
        n = np.linalg.norm(out[i])
        if n:
            out[i] /= n
    return out


class Embedder:
    def __init__(self, gate: Gate, provider: str | None = None):
        self.gate = gate
        self.provider = provider or config.embeddings_provider()
        if self.provider == "voyage":
            self.model, self.url, self.key = config.setting("VOYAGE_MODEL", "voyage-3.5"), VOYAGE_URL, config.setting("VOYAGE_API_KEY")
        elif self.provider == "openai":
            self.model, self.url, self.key = config.setting("OPENAI_EMBED_MODEL", "text-embedding-3-small"), OPENAI_URL, config.setting("OPENAI_API_KEY")
        elif self.provider == "local":
            self.model, self.url, self.key = f"local-hash-{LOCAL_DIM}", "local://", ""
        else:
            raise EmbeddingConfigError(f"Unknown EMBEDDINGS_PROVIDER {self.provider!r}")
        if self.provider != "local" and not self.key and not gate.dry_run:
            raise EmbeddingConfigError(f"{self.provider} selected but its API key is empty in .env")

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    def embed(self, texts: list[str], *, input_type: str) -> np.ndarray | None:
        """Returns vectors, or None in dry-run for external providers."""
        if self.provider == "local":
            print(f"[embed] local provider: {len(texts)} text(s) embedded on this machine, no outbound call")
            return local_embed(texts)
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        if self.provider == "voyage":
            payload["input_type"] = input_type
        result = self.gate.send(f"embeddings:{input_type}", self.url, payload, self._post)
        return None if result is None else np.asarray(result, dtype=np.float32)

    def _post(self, payload: dict[str, Any]) -> list[list[float]]:
        r = requests.post(self.url, json=payload, headers={"Authorization": f"Bearer {self.key}"}, timeout=60)
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]
