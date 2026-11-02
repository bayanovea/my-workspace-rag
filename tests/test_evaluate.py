import json

import pytest

from wrag import cli, evaluate, indexer
from wrag.chunk import Chunk
from wrag.embed import FakeEmbedder
from wrag.errors import WragError
from wrag.evaluate import Expect, Question
from wrag.generate import Answer, FakeGenerator
from wrag.retrieve import Location, Searcher
from wrag.store import Store

QUESTIONS = """\
- id: limiter
  q: per-client rate limiting plan token bucket
  lang: en
  expect:
    - {project: alpha, path: docs/plans}
- id: zod
  q: где валидация форм через zod?
  lang: ru
  expect:
    - {project: beta, path: README.md}
- id: graphql
  q: graphql client subscriptions
  absent: true
"""


def loc(project, path, kind="doc", files=()):
    return Location(project, path, kind, 0.5, Chunk(project, path, kind, "", "", 0, files))


def q(*expect, absent=False):
    return Question("q", "text", None, tuple(expect), absent)


def test_load_questions_and_hash(tmp_path):
    path = tmp_path / "questions.yaml"
    path.write_text(QUESTIONS)
    questions, sha = evaluate.load_questions(path)
    assert [x.id for x in questions] == ["limiter", "zod", "graphql"]
    assert questions[0].expect == (Expect("alpha", "docs/plans"),)
    assert questions[2].absent and not questions[2].expect
    assert len(sha) == 64


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("- {id: x, q: hello}", "question x: needs either"),
        ("- {id: x, q: hello, absent: true, expect: [{project: a, path: b}]}", "needs either"),
        ("- {id: x, q: hello, expect: [{project: a}]}", "question x: each expect"),
        ("- {id: x}", "question x: missing q"),
        ("- {id: x, q: a, absent: true}\n- {id: x, q: b, absent: true}", "duplicate"),
    ],
)
def test_invalid_question_names_its_id(tmp_path, body, match):
    path = tmp_path / "questions.yaml"
    path.write_text(body)
    with pytest.raises(WragError, match=match):
        evaluate.load_questions(path)


def test_path_prefix_matches_whole_segments_only():
    e = Expect("alpha", "internal/ratelimit")
    assert evaluate.is_hit(loc("alpha", "internal/ratelimit/limiter.go"), e)
    assert evaluate.is_hit(loc("alpha", "internal/ratelimit"), e)
    assert not evaluate.is_hit(loc("alpha", "internal/ratelimiter.go"), e)
    assert not evaluate.is_hit(loc("beta", "internal/ratelimit/limiter.go"), e)


def test_commit_hits_by_hash_or_changed_files():
    c = loc("alpha", "0123456789ab", "commit", ("internal/ratelimit/limiter.go",))
    assert evaluate.is_hit(c, Expect("alpha", commit="0123456"))
    assert evaluate.is_hit(c, Expect("alpha", commit="0123456789abcdef"))
    assert evaluate.is_hit(c, Expect("alpha", path="internal/ratelimit"))
    assert not evaluate.is_hit(c, Expect("alpha", path="docs"))


def test_first_hit_rank():
    locations = [loc("a", "x.md"), loc("a", "y.md"), loc("a", "docs/z.md")]
    assert evaluate.first_hit(locations, q(Expect("a", "docs"))) == 3
    assert evaluate.first_hit(locations, q(Expect("a", "nope"))) is None


def test_metrics_match_hand_computed_values():
    # ranks 1, 3, 6, miss: Recall@5 = 2/4; MRR@10 = (1 + 1/3 + 1/6 + 0) / 4 = 0.375
    r = evaluate.retrieval_metrics([1, 3, 6, None])
    assert (r.n, r.recall_at_5, r.mrr_at_10) == (4, 0.5, 0.375)
    assert evaluate.retrieval_metrics([11]).mrr_at_10 == 0


@pytest.fixture
def searcher(cfg):
    store = Store(cfg.index_file)
    indexer.run(cfg, store, FakeEmbedder(), log=lambda _: None)
    yield Searcher(store, FakeEmbedder())
    store.close()


def fixture_questions(tmp_path):
    path = tmp_path / "questions.yaml"
    path.write_text(QUESTIONS)
    return evaluate.load_questions(path)


def test_run_retrieval_only_never_generates(searcher, tmp_path):
    questions, sha = fixture_questions(tmp_path)
    rows = evaluate.run(searcher, questions, k=4)
    assert rows[0].rank == 1
    assert rows[2].rank is None and rows[2].answer is None
    s = evaluate.summarize(rows, sha, 3, {"doc": 1}, {"k": 4})
    assert s.answers is None
    assert s.retrieval.n == 2
    assert set(s.retrieval_by_lang) == {"en", "ru"}


def test_answer_metrics_with_fake_generator(searcher, tmp_path):
    questions, sha = fixture_questions(tmp_path)

    class ByQuestion(FakeGenerator):
        def generate(self, prompt):
            self.prompts.append(prompt)
            if "graphql" in prompt.splitlines()[0]:
                return Answer(False, "no", ())
            if "zod" in prompt.splitlines()[0]:
                return Answer(False, "no", ())  # a false abstention
            return Answer(True, "plan", ("c1",))

    rows = evaluate.run(searcher, questions, k=4, generator=ByQuestion(None))
    a = evaluate.summarize(rows, sha, 3, {}, {}).answers
    assert (a.correct_abstention, a.false_abstention, a.cited_hit) == (1.0, 0.5, 0.5)


def test_summary_has_no_identifiers(searcher, cfg, tmp_path):
    questions, sha = fixture_questions(tmp_path)
    rows = evaluate.run(
        searcher, questions, k=4, generator=FakeGenerator(Answer(True, "x", ("c1",)))
    )
    summary = evaluate.summarize(rows, sha, 3, searcher.store.counts(), {"k": 4})
    run_dir = evaluate.write_run(cfg.runs_dir, rows, summary)
    text = (run_dir / "summary.json").read_text()
    needles = [p.name for p in cfg.projects] + [str(p.path) for p in cfg.projects]
    needles += [x.q for x in questions] + [x.id for x in questions] + ["README", "docs/"]
    assert [n for n in needles if n in text] == []
    assert "alpha" in (run_dir / "report.md").read_text()


def test_compare_warns_on_different_question_sets(cfg, tmp_path):
    base = {
        "questions_sha256": "a",
        "params": {"k": 8},
        "retrieval": {"recall_at_5": 0.5, "mrr_at_10": 0.4},
        "answers": None,
    }
    other = {
        **base,
        "questions_sha256": "b",
        "params": {"k": 4},
        "retrieval": {"recall_at_5": 0.75, "mrr_at_10": 0.4},
    }
    out = evaluate.compare(base, other)
    assert out.splitlines()[0].startswith("warning: the runs used different question sets")
    assert "param k: 8 -> 4" in out
    assert "recall_at_5          0.500 -> 0.750  (+0.250)" in out


def test_cli_eval_writes_run_and_compares(cfg, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OllamaEmbedder", lambda url, model: FakeEmbedder())
    cfg.questions_file.parent.mkdir(parents=True)
    cfg.questions_file.write_text(QUESTIONS)
    assert cli.main(["index"]) == 0
    assert cli.main(["eval"]) == 0
    out = capsys.readouterr().out
    assert "Recall@5" in out
    [run_dir] = list(cfg.runs_dir.iterdir())
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["params"]["generate_model"] is None
    assert cli.main(["eval", "--compare", run_dir.name, str(run_dir)]) == 0
    assert "warning" not in capsys.readouterr().out
