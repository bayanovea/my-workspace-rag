import numpy as np
import pytest

from wrag import indexer
from wrag.chunk import Chunk
from wrag.embed import FakeEmbedder
from wrag.errors import WragError
from wrag.retrieve import Searcher
from wrag.store import Store


class FixedEmbedder:
    """Embeds by lookup, so ranking is fully controlled by the test."""

    model = "fixed"

    def __init__(self, table):
        self.table = table

    def embed(self, texts):
        return np.array([self.table[t] for t in texts], dtype=np.float32)


@pytest.fixture
def searcher(tmp_path):
    store = Store(tmp_path / "index.db")
    store.set_meta("embed_model", "fixed")
    chunks = [
        Chunk("alpha", "README.md", "doc", "A", "one", 0),
        Chunk("alpha", "README.md", "doc", "B", "two", 0),
        Chunk("beta", "go.mod", "manifest", "", "three", 0),
        Chunk("alpha", "abc", "commit", "Add x", "four", 0, ("x.go",)),
    ]
    vectors = np.array([[0.9, 0.1], [0.8, 0.2], [0.7, 0.3], [0.1, 0.9]], dtype=np.float32)
    store.add_chunks(chunks, vectors)
    yield Searcher(store, FixedEmbedder({"q": [1.0, 0.0]}))
    store.close()


def test_chunks_are_ranked_by_similarity(searcher):
    hits = searcher.chunks("q", 3)
    assert [h.chunk.text for h in hits] == ["one", "two", "three"]
    assert hits[0].score == pytest.approx(0.9)


def test_locations_dedupe_chunks_of_one_file_at_best_rank(searcher):
    locs = searcher.locations("q", 10)
    assert [(loc.project, loc.path) for loc in locs] == [
        ("alpha", "README.md"),
        ("beta", "go.mod"),
        ("alpha", "abc"),
    ]
    assert locs[0].best.heading == "A"
    assert locs[2].files == ("x.go",)


def test_locations_respect_limit(searcher):
    assert len(searcher.locations("q", 2)) == 2


def test_model_mismatch_is_an_error(tmp_path):
    store = Store(tmp_path / "index.db")
    store.set_meta("embed_model", "bge-m3")
    with pytest.raises(WragError, match="run wrag index"):
        Searcher(store, FakeEmbedder())


def test_empty_index_is_an_error(tmp_path):
    with pytest.raises(WragError, match="empty"):
        Searcher(Store(tmp_path / "index.db"), FakeEmbedder()).chunks("q", 3)


def test_fixture_question_finds_the_rate_limit_plan(cfg):
    store = Store(cfg.index_file)
    indexer.run(cfg, store, FakeEmbedder(), log=lambda _: None)
    locs = Searcher(store, FakeEmbedder()).locations("per-client rate limiting plan", 5)
    assert ("alpha", "docs/plans/rate-limit.md") in [(loc.project, loc.path) for loc in locs[:3]]
