import hashlib
import re
from typing import Protocol

import httpx
import numpy as np

from wrag.errors import WragError


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> np.ndarray:
        """Returns an (n, dim) float32 matrix with L2-normalised rows."""
        ...


def normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


class OllamaEmbedder:
    def __init__(self, url: str, model: str, batch: int = 32, client: httpx.Client | None = None):
        self.url, self.model, self.batch = url, model, batch
        self.client = client or httpx.Client(timeout=120)

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = []
        for i in range(0, len(texts), self.batch):
            rows += self._call(texts[i : i + self.batch])
        return normalize(np.array(rows)) if rows else np.zeros((0, 0), dtype=np.float32)

    def _call(self, batch: list[str]) -> list[list[float]]:
        body = {"model": self.model, "input": batch}
        try:
            r = self.client.post(f"{self.url}/api/embed", json=body)
        except httpx.HTTPError as e:
            raise WragError(f"Ollama at {self.url} is unreachable ({e}); run: ollama serve") from e
        if r.status_code == 404:
            raise WragError(f"Ollama has no model {self.model!r}; run: ollama pull {self.model}")
        if r.status_code != 200:
            raise WragError(f"Ollama embed failed: HTTP {r.status_code} {r.text[:200]}")
        return r.json()["embeddings"]


class FakeEmbedder:
    """Deterministic hashed bag of words, for tests without Ollama."""

    model = "fake-bow"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        m = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in re.findall(r"\w+", text.lower()):
                h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
                m[row, h % self.dim] += 1
        return normalize(m)
