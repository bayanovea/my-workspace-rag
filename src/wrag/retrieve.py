from dataclasses import dataclass

import numpy as np

from wrag.chunk import Chunk
from wrag.embed import Embedder
from wrag.errors import WragError
from wrag.store import Store


@dataclass(frozen=True)
class Hit:
    id: int
    score: float
    chunk: Chunk


@dataclass(frozen=True)
class Location:
    project: str
    path: str
    kind: str
    score: float
    best: Chunk  # the highest-scoring chunk at this location

    @property
    def files(self) -> tuple[str, ...]:
        return self.best.files


class Searcher:
    """Brute-force cosine search; vectors are loaded once per process."""

    def __init__(self, store: Store, embedder: Embedder):
        self.store, self.embedder = store, embedder
        self.ids, self.matrix = store.vectors()
        indexed = store.get_meta("embed_model")
        if indexed and indexed != embedder.model:
            raise WragError(
                f"index was built with {indexed}, config says {embedder.model}; run wrag index"
            )

    def ranked(self, question: str) -> list[tuple[int, float]]:
        if not len(self.ids):
            raise WragError("the index is empty; run wrag index first")
        q = self.embedder.embed([question])[0]
        scores = self.matrix @ q
        order = np.argsort(-scores, kind="stable")
        return [(int(self.ids[i]), float(scores[i])) for i in order]

    def chunks(self, question: str, k: int) -> list[Hit]:
        top = self.ranked(question)[:k]
        found = self.store.chunks([i for i, _ in top])
        return [Hit(i, s, found[i]) for i, s in top]

    def locations(self, question: str, limit: int) -> list[Location]:
        """Distinct locations at the rank of their best chunk."""
        result: dict[tuple[str, str], Location] = {}
        ranked = self.ranked(question)
        step = max(limit * 4, 32)
        for start in range(0, len(ranked), step):
            window = ranked[start : start + step]
            found = self.store.chunks([i for i, _ in window])
            for i, score in window:
                c = found[i]
                key = (c.project, c.path)
                if key not in result:
                    result[key] = Location(c.project, c.path, c.kind, score, c)
                    if len(result) == limit:
                        return list(result.values())
        return list(result.values())


def dedupe(hits: list[Hit]) -> list[Location]:
    result: dict[tuple[str, str], Location] = {}
    for h in hits:
        key = (h.chunk.project, h.chunk.path)
        if key not in result:
            result[key] = Location(h.chunk.project, h.chunk.path, h.chunk.kind, h.score, h.chunk)
    return list(result.values())
