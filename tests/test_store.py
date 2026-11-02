import numpy as np

from wrag.chunk import Chunk
from wrag.store import Store


def test_chunks_and_vectors_round_trip(tmp_path):
    store = Store(tmp_path / "index.db")
    chunks = [
        Chunk("alpha", "README.md", "doc", "A > B", "text", 1.5),
        Chunk("alpha", "abc123def456", "commit", "Add x", "msg", 2.0, ("a.go", "b.go")),
    ]
    vectors = np.array([[1, 0, 0], [0, 0.6, 0.8]], dtype=np.float32)
    store.put_file("alpha", "README.md", "sha", 1.5, chunks[:1], vectors[:1])
    store.add_chunks(chunks[1:], vectors[1:])
    store.commit()
    store.close()

    store = Store(tmp_path / "index.db")
    ids, matrix = store.vectors()
    np.testing.assert_array_equal(matrix, vectors)
    assert list(store.chunks(list(ids)).values()) == chunks
    assert store.file_hashes("alpha") == {"README.md": "sha"}
    assert store.counts() == {"commit": 1, "doc": 1}


def test_delete_file_keeps_commit_chunks(tmp_path):
    store = Store(tmp_path / "index.db")
    v = np.ones((1, 2), dtype=np.float32)
    store.put_file("p", "x", "sha", 0, [Chunk("p", "x", "doc", "", "t", 0)], v)
    store.add_chunks([Chunk("p", "x", "commit", "", "t", 0)], v)
    store.delete_file("p", "x")
    assert store.counts() == {"commit": 1}
    assert store.file_hashes("p") == {}


def test_meta_cursor_and_reset(tmp_path):
    store = Store(tmp_path / "index.db")
    store.set_meta("embed_model", "m")
    store.set_cursor("p", "h1")
    store.set_cursor("p", "h2")
    assert (store.get_meta("embed_model"), store.get_cursor("p")) == ("m", "h2")
    assert store.projects() == {"p"}
    store.reset()
    assert (store.get_meta("embed_model"), store.get_cursor("p"), store.projects()) == (
        None,
        None,
        set(),
    )
