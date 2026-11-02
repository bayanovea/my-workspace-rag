import argparse
import sys
from pathlib import Path

from wrag import config, evaluate, generate, guard, indexer
from wrag.chunk import CHUNKER_VERSION
from wrag.embed import OllamaEmbedder
from wrag.errors import WragError
from wrag.retrieve import Location, Searcher, dedupe
from wrag.store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wrag", description="Ask where something lives across your local projects."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("index", help="index or reindex the allowlisted projects")
    p.add_argument("--full", action="store_true", help="rebuild from scratch")

    p = sub.add_parser("ask", help="ask where something is")
    p.add_argument("question")
    p.add_argument("--retrieve-only", action="store_true", help="rank locations, no generator")
    p.add_argument("-k", type=int, help="chunks to retrieve (default from config)")

    p = sub.add_parser("eval", help="run the question set")
    p.add_argument("--with-answers", action="store_true", help="also measure generated answers")
    p.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"), help="compare two runs")

    p = sub.add_parser("guard", help="leak guard for git hooks")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="scan staged changes")
    g.add_argument("--msg", type=Path, metavar="FILE", help="scan a commit message file")

    args = parser.parse_args(argv)
    try:
        cfg = config.load(config.resolve_home())
        return COMMANDS[args.command](cfg, args)
    except WragError as e:
        print(f"wrag: {e}", file=sys.stderr)
        return 1


def cmd_index(cfg: config.Config, args) -> int:
    config.require_projects(cfg)
    cfg.home.mkdir(parents=True, exist_ok=True)
    store = Store(cfg.index_file)
    try:
        reports = indexer.run(
            cfg, store, OllamaEmbedder(cfg.embed_url, cfg.embed_model), full=args.full
        )
    finally:
        store.close()
    total = indexer.Report()
    for name, r in reports.items():
        print(f"{name}: {r.line()}")
        for s in r.skipped_files:
            print(f"  skipped {s.rel} ({s.reason})")
        for f in ("added", "updated", "deleted", "skipped", "commits", "redactions"):
            setattr(total, f, getattr(total, f) + getattr(r, f))
    print(f"total: {total.line()}")
    return 0


def open_searcher(cfg: config.Config) -> tuple[Store, Searcher]:
    if not cfg.index_file.exists():
        raise WragError("no index yet; run wrag index first")
    store = Store(cfg.index_file)
    return store, Searcher(store, OllamaEmbedder(cfg.embed_url, cfg.embed_model))


def print_locations(locations: list[Location], title: str) -> None:
    print(title)
    for loc in locations:
        label = f"  ({loc.best.heading})" if loc.best.heading else ""
        print(f"  {loc.score:.3f}  {loc.project}  {loc.path}{label}")


def cmd_ask(cfg: config.Config, args) -> int:
    store, searcher = open_searcher(cfg)
    try:
        hits = searcher.chunks(args.question, args.k or cfg.k)
        locations = dedupe(hits)
        if args.retrieve_only:
            print_locations(locations, "Ranked locations:")
            return 0
        gen = generate.ClaudeCLI(cfg.claude_dir, cfg.generate_model, cfg.generate_timeout)
        try:
            answer, cited = generate.answer(gen, args.question, hits)
        except WragError:
            print_locations(locations, "Retrieved locations (no answer, generator failed):")
            raise
    finally:
        store.close()
    if answer.found:
        print(answer.text)
        print_locations(dedupe(cited), "\nCited:")
    else:
        print(f"Not found. {answer.text}")
        print_locations(locations[:3], "\nClosest locations (not answers):")
    return 0


def cmd_eval(cfg: config.Config, args) -> int:
    if args.compare:
        a, b = (evaluate.load_summary(cfg.runs_dir, r) for r in args.compare)
        print(evaluate.compare(a, b))
        return 0
    questions, sha = evaluate.load_questions(cfg.questions_file)
    store, searcher = open_searcher(cfg)
    try:
        gen = None
        if args.with_answers:
            gen = generate.ClaudeCLI(cfg.claude_dir, cfg.generate_model, cfg.generate_timeout)
        rows = evaluate.run(searcher, questions, cfg.k, gen)
        params = {
            "embed_model": cfg.embed_model,
            "chunker_version": CHUNKER_VERSION,
            "k": cfg.k,
            "max_chunk_chars": cfg.max_chunk_chars,
            "generate_model": cfg.generate_model if gen else None,
        }
        summary = evaluate.summarize(rows, sha, len(store.projects()), store.counts(), params)
    finally:
        store.close()
    run_dir = evaluate.write_run(cfg.runs_dir, rows, summary)
    r = summary.retrieval
    print(f"Recall@5 {r.recall_at_5:.3f}  MRR@10 {r.mrr_at_10:.3f}  ({r.n} answerable)")
    if summary.answers:
        a = summary.answers
        print(
            f"correct abstention {a.correct_abstention:.3f}  false abstention "
            f"{a.false_abstention:.3f}  cited hit {a.cited_hit:.3f}"
        )
    print(f"run written to {run_dir}")
    return 0


def cmd_guard(cfg: config.Config, args) -> int:
    found = guard.needles(cfg)
    lines = guard.staged_lines(Path.cwd()) if args.staged else guard.message_lines(args.msg)
    findings = guard.scan(lines, found)
    for f in findings:
        print(f"leak guard: {f}", file=sys.stderr)
    if findings:
        print("leak guard: commit rejected; remove the private strings above", file=sys.stderr)
        return 1
    return 0


COMMANDS = {"index": cmd_index, "ask": cmd_ask, "eval": cmd_eval, "guard": cmd_guard}

if __name__ == "__main__":
    sys.exit(main())
