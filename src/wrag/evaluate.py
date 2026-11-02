"""`wrag eval`: retrieval and answer metrics over a private question set."""

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from wrag import generate
from wrag.errors import WragError
from wrag.retrieve import Location, Searcher

RECALL_AT = 5
MRR_AT = 10


@dataclass(frozen=True)
class Expect:
    project: str
    path: str | None = None
    commit: str | None = None


@dataclass(frozen=True)
class Question:
    id: str
    q: str
    lang: str | None
    expect: tuple[Expect, ...]
    absent: bool


def load_questions(path: Path) -> tuple[list[Question], str]:
    """Returns the questions and the sha256 of the file they came from."""
    if not path.exists():
        raise WragError(f"no question set at {path}")
    data = path.read_bytes()
    raw = yaml.safe_load(data) or []
    if not isinstance(raw, list):
        raise WragError(f"{path}: expected a list of questions")
    questions, seen = [], set()
    for n, item in enumerate(raw):
        qid = str((item or {}).get("id") or f"#{n + 1}")
        if qid in seen:
            raise WragError(f"question {qid}: duplicate id")
        seen.add(qid)
        if not item.get("q"):
            raise WragError(f"question {qid}: missing q")
        expect = []
        for e in item.get("expect") or []:
            if not e.get("project") or not (e.get("path") or e.get("commit")):
                raise WragError(f"question {qid}: each expect needs project and path or commit")
            expect.append(Expect(str(e["project"]), e.get("path"), e.get("commit")))
        absent = bool(item.get("absent"))
        if absent == bool(expect):
            raise WragError(f"question {qid}: needs either expect locations or absent: true")
        questions.append(Question(qid, str(item["q"]), item.get("lang"), tuple(expect), absent))
    return questions, hashlib.sha256(data).hexdigest()


def under(path: str, prefix: str) -> bool:
    prefix = prefix.strip("/")
    return path == prefix or path.startswith(prefix + "/")


def is_hit(loc: Location, e: Expect) -> bool:
    if loc.project != e.project:
        return False
    if loc.kind == "commit":
        if e.commit and (loc.path.startswith(e.commit) or e.commit.startswith(loc.path)):
            return True
        return bool(e.path) and any(under(f, e.path) for f in loc.files)
    return bool(e.path) and under(loc.path, e.path)


def first_hit(locations: list[Location], q: Question) -> int | None:
    for rank, loc in enumerate(locations, 1):
        if any(is_hit(loc, e) for e in q.expect):
            return rank
    return None


@dataclass
class Retrieval:
    n: int = 0
    recall_at_5: float = 0.0
    mrr_at_10: float = 0.0


@dataclass
class Answers:
    n_absent: int
    n_answerable: int
    correct_abstention: float
    false_abstention: float
    cited_hit: float


@dataclass
class Summary:
    """Publishable: only counts, rates, model names and parameters. Never add free-text fields."""

    created_at: str
    questions_sha256: str
    n_questions: int
    n_answerable: int
    n_absent: int
    corpus_projects: int
    corpus_chunks: dict[str, int]
    params: dict[str, str | int | None]
    retrieval: Retrieval
    retrieval_by_lang: dict[str, Retrieval] = field(default_factory=dict)
    answers: Answers | None = None


def retrieval_metrics(ranks: list[int | None]) -> Retrieval:
    if not ranks:
        return Retrieval()
    recall = sum(1 for r in ranks if r is not None and r <= RECALL_AT) / len(ranks)
    mrr = sum(1 / r for r in ranks if r is not None and r <= MRR_AT) / len(ranks)
    return Retrieval(len(ranks), round(recall, 4), round(mrr, 4))


@dataclass
class Row:
    q: Question
    locations: list[Location]
    rank: int | None
    answer: generate.Answer | None = None
    cited: list[Location] = field(default_factory=list)


def run(
    searcher: Searcher,
    questions: list[Question],
    k: int,
    generator: generate.Generator | None = None,
) -> list[Row]:
    rows = []
    for q in questions:
        locations = searcher.locations(q.q, MRR_AT)
        row = Row(q, locations, None if q.absent else first_hit(locations, q))
        if generator is not None:
            hits = searcher.chunks(q.q, k)
            row.answer, cited_hits = generate.answer(generator, q.q, hits)
            row.cited = [
                Location(h.chunk.project, h.chunk.path, h.chunk.kind, h.score, h.chunk)
                for h in cited_hits
            ]
        rows.append(row)
    return rows


def summarize(
    rows: list[Row],
    questions_sha256: str,
    corpus_projects: int,
    corpus_chunks: dict[str, int],
    params: dict,
) -> Summary:
    answerable = [r for r in rows if not r.q.absent]
    absent = [r for r in rows if r.q.absent]
    by_lang: dict[str, list[int | None]] = defaultdict(list)
    for r in answerable:
        by_lang[r.q.lang or "unspecified"].append(r.rank)
    summary = Summary(
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        questions_sha256=questions_sha256,
        n_questions=len(rows),
        n_answerable=len(answerable),
        n_absent=len(absent),
        corpus_projects=corpus_projects,
        corpus_chunks=dict(sorted(corpus_chunks.items())),
        params=params,
        retrieval=retrieval_metrics([r.rank for r in answerable]),
        retrieval_by_lang={lang: retrieval_metrics(rs) for lang, rs in sorted(by_lang.items())},
    )
    if rows and rows[0].answer is not None:

        def rate(n: int, d: int) -> float:
            return round(n / d, 4) if d else 0.0

        summary.answers = Answers(
            n_absent=len(absent),
            n_answerable=len(answerable),
            correct_abstention=rate(sum(not r.answer.found for r in absent), len(absent)),
            false_abstention=rate(sum(not r.answer.found for r in answerable), len(answerable)),
            cited_hit=rate(
                sum(any(is_hit(c, e) for c in r.cited for e in r.q.expect) for r in answerable),
                len(answerable),
            ),
        )
    return summary


def report(rows: list[Row], summary: Summary) -> str:
    """Private per-question report."""
    out = [
        f"# Eval run {summary.created_at}",
        "",
        "```json",
        json.dumps(asdict(summary), indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    for r in rows:
        status = "absent" if r.q.absent else (f"rank {r.rank}" if r.rank else "miss")
        out += [f"## {r.q.id} ({status})", "", f"> {r.q.q}", ""]
        if r.q.expect:
            exp = ", ".join(f"{e.project}/{e.path or e.commit}" for e in r.q.expect)
            out += [f"Expected: {exp}", ""]
        for rank, loc in enumerate(r.locations[:RECALL_AT], 1):
            mark = " **hit**" if any(is_hit(loc, e) for e in r.q.expect) else ""
            label = f" ({loc.best.heading})" if loc.best.heading else ""
            out.append(f"{rank}. `{loc.project}/{loc.path}`{label} {loc.score:.3f}{mark}")
        if r.answer is not None:
            verdict = "found" if r.answer.found else "not found"
            cited = ", ".join(f"`{c.project}/{c.path}`" for c in r.cited) or "none"
            out += ["", f"Answer ({verdict}): {r.answer.text}", f"Cited: {cited}"]
        out.append("")
    return "\n".join(out)


def write_run(runs_dir: Path, rows: list[Row], summary: Summary) -> Path:
    run_dir = runs_dir / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "report.md").write_text(report(rows, summary))
    (run_dir / "summary.json").write_text(json.dumps(asdict(summary), indent=2) + "\n")
    return run_dir


def load_summary(runs_dir: Path, ref: str) -> dict:
    path = Path(ref)
    if not path.exists():
        path = runs_dir / ref
    if path.is_dir():
        path = path / "summary.json"
    if not path.exists():
        raise WragError(f"no summary at {ref}")
    return json.loads(path.read_text())


def compare(a: dict, b: dict) -> str:
    lines = []
    if a["questions_sha256"] != b["questions_sha256"]:
        lines.append("warning: the runs used different question sets; deltas are not comparable")
    if a["params"] != b["params"]:
        changed = sorted(
            k
            for k in a["params"].keys() | b["params"].keys()
            if a["params"].get(k) != b["params"].get(k)
        )
        for k in changed:
            lines.append(f"param {k}: {a['params'].get(k)} -> {b['params'].get(k)}")
    metrics = [("retrieval", k) for k in ("recall_at_5", "mrr_at_10")]
    if a.get("answers") and b.get("answers"):
        metrics += [("answers", k) for k in ("correct_abstention", "false_abstention", "cited_hit")]
    for group, k in metrics:
        va, vb = a[group][k], b[group][k]
        lines.append(f"{k:20} {va:.3f} -> {vb:.3f}  ({vb - va:+.3f})")
    return "\n".join(lines)
