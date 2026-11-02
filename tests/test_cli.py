import pytest

from wrag import cli
from wrag.embed import FakeEmbedder
from wrag.errors import WragError
from wrag.generate import Answer, FakeGenerator


@pytest.fixture
def fakes(monkeypatch):
    """Swaps Ollama and Claude Code for fakes; returns a setter for the generator's reply."""
    holder = {"gen": FakeGenerator(Answer(False, "nothing", ()))}
    monkeypatch.setattr(cli, "OllamaEmbedder", lambda url, model: FakeEmbedder())
    monkeypatch.setattr(cli.generate, "ClaudeCLI", lambda *a, **kw: holder["gen"])

    def set_reply(reply):
        holder["gen"] = FakeGenerator(reply)
        return holder["gen"]

    return set_reply


@pytest.fixture
def indexed(cfg, fakes, capsys):
    assert cli.main(["index"]) == 0
    capsys.readouterr()
    return cfg


def test_index_prints_per_project_report(cfg, fakes, capsys):
    assert cli.main(["index"]) == 0
    out = capsys.readouterr().out
    assert "alpha: +4 added, 0 updated, 0 deleted, 1 skipped, 3 commits, 1 redactions" in out
    assert "skipped .env (secret-name)" in out
    assert out.strip().splitlines()[-1].startswith("total: +9 added")


def test_index_with_empty_allowlist_fails(home, fakes, capsys):
    (home / "config.yaml").write_text("projects: []\n")
    assert cli.main(["index"]) == 1
    assert "config.yaml" in capsys.readouterr().err


def test_retrieve_only_never_calls_the_generator(indexed, fakes, capsys):
    gen = fakes(WragError("must not be called"))
    assert cli.main(["ask", "--retrieve-only", "rate limiting token bucket"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Ranked locations:")
    assert "alpha  README.md  (Alpha > Rate limiting)" in out
    assert gen.prompts == []


def test_answer_prints_cited_locations(indexed, fakes, capsys):
    gen = fakes(Answer(True, "In alpha's rate-limit plan.", ("c1",)))
    assert cli.main(["ask", "-k", "3", "per-client rate limiting plan"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("In alpha's rate-limit plan.")
    assert "Cited:" in out
    assert "[c1] project alpha" in gen.prompts[0]


def test_not_found_lists_closest_as_non_answers(indexed, fakes, capsys):
    fakes(Answer(False, "No GraphQL client in these chunks.", ()))
    assert cli.main(["ask", "graphql client"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Not found.")
    assert "Closest locations (not answers):" in out


def test_generator_failure_still_prints_locations(indexed, fakes, capsys):
    fakes(WragError("the generator is not logged in; log in once with: ..."))
    assert cli.main(["ask", "rate limiting"]) == 1
    captured = capsys.readouterr()
    assert "Retrieved locations (no answer, generator failed):" in captured.out
    assert "not logged in" in captured.err


def test_ask_without_index_fails(cfg, fakes, capsys):
    assert cli.main(["ask", "x"]) == 1
    assert "run wrag index" in capsys.readouterr().err
