import json

import httpx
import numpy as np
import pytest

from wrag.embed import FakeEmbedder, OllamaEmbedder
from wrag.errors import WragError


def test_fake_embedder_is_deterministic_and_normalised():
    a = FakeEmbedder().embed(["rate limiting with a token bucket", ""])
    b = FakeEmbedder().embed(["rate limiting with a token bucket", ""])
    np.testing.assert_array_equal(a, b)
    assert a.dtype == np.float32
    assert np.isclose(np.linalg.norm(a[0]), 1.0)
    assert not a[1].any()


def test_fake_embedder_ranks_overlapping_text_higher():
    e = FakeEmbedder()
    q, near, far = e.embed(["token bucket limiter", "a token bucket rate limiter", "pdf invoices"])
    assert q @ near > q @ far


def ollama(handler, batch=32):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaEmbedder("http://ollama", "bge-m3", batch=batch, client=client)


def test_ollama_batches_and_normalises():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0]] * len(body["input"])})

    m = ollama(handler, batch=2).embed(["a", "b", "c"])
    assert [c["input"] for c in calls] == [["a", "b"], ["c"]]
    assert calls[0]["model"] == "bge-m3"
    np.testing.assert_allclose(m, [[0.6, 0.8]] * 3)


def test_ollama_missing_model_says_how_to_pull():
    with pytest.raises(WragError, match="ollama pull bge-m3"):
        ollama(lambda r: httpx.Response(404, json={"error": "model not found"})).embed(["a"])


def test_ollama_unreachable_says_how_to_start():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(WragError, match="ollama serve"):
        ollama(handler).embed(["a"])
