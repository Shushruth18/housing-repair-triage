"""Stage 4: tiny local numpy vector store (.store/vectors.npy + chunks.json)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import config
from .chunk import Chunk


class VectorStore:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray, embedder: str):
        assert len(chunks) == len(vectors)
        self.chunks = chunks
        self.vectors = vectors
        self.embedder = embedder

    def save(self, directory: Path = config.STORE_DIR) -> None:
        directory.mkdir(exist_ok=True)
        np.save(directory / "vectors.npy", self.vectors)
        (directory / "chunks.json").write_text(
            json.dumps({"embedder": self.embedder, "chunks": [c.to_dict() for c in self.chunks]}, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: Path = config.STORE_DIR) -> "VectorStore":
        if not (directory / "chunks.json").exists():
            raise FileNotFoundError("No vector store yet. Run: python -m triage index")
        meta = json.loads((directory / "chunks.json").read_text(encoding="utf-8"))
        chunks = [Chunk(**c) for c in meta["chunks"]]
        return cls(chunks, np.load(directory / "vectors.npy"), meta["embedder"])

    def search(self, query_vec: np.ndarray, *, kind: str | None = None, where: dict | None = None, k: int = 3):
        """Cosine top-k with metadata pre-filtering. Returns [(chunk, score)]."""
        idx = [
            i for i, c in enumerate(self.chunks)
            if (kind is None or c.kind == kind) and all(c.metadata.get(f) == v for f, v in (where or {}).items())
        ]
        if not idx:
            return []
        mat = self.vectors[idx]
        q = query_vec / (np.linalg.norm(query_vec) or 1.0)
        scores = mat @ q / np.maximum(np.linalg.norm(mat, axis=1), 1e-9)
        order = np.argsort(-scores)[:k]
        return [(self.chunks[idx[j]], float(scores[j])) for j in order]
