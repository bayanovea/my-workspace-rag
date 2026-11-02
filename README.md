# wrag: RAG over your local projects

`wrag` answers questions about a set of local projects from their docs, plans, dependency manifests
and git history: what was decided, how something was set up, which library a service uses, where a
piece of work lives. Every answer cites the project and file or commit it came from, or says
"not found" instead of guessing.

It is also a measurement bench: every retrieval technique is added one at a time and scored against a
fixed question set.

## How it works

```
allowlisted projects --> select files --> redact secrets --> chunk --> embed (local) --> SQLite
                                                                                          |
question --> embed (local) --> cosine top-k --> claude -p (isolated) --> answer + citations
```

- **Sources:** markdown docs, dependency manifests (`go.mod`, `package.json`, `composer.json`, ...)
  and git history, one chunk per commit (message + changed paths). Source code is not indexed yet.
- **Chunking:** markdown by headings, with the heading path kept on each chunk; manifests whole;
  commits whole.
- **Embeddings:** [Ollama](https://ollama.com) with `bge-m3` (multilingual, so questions and docs can
  be in different languages). Search is brute-force cosine over a numpy matrix.
- **Generation:** the Claude Code CLI (`claude -p`) with no tools, under a dedicated config directory,
  so none of the user's hooks, plugins or instruction files apply. Citations that don't point at a
  retrieved chunk are dropped, and an answer with no valid citation becomes "not found".
- **Incremental:** file hashes and a per-project commit cursor; a model or chunker change rebuilds.

## Privacy model

The code is public; the corpus is not.

- **All private data lives outside the repository** in `$WRAG_HOME` (default
  `~/.config/workspace-rag/`): the project allowlist, the index, the question set, run reports, the
  leak-guard denylist and the generator's login. `wrag` refuses a `WRAG_HOME` inside a git working
  tree.
- **What leaves the machine:** only the question and the retrieved chunks for that question, sent to
  the generator. Indexing and embedding are local.
- **Secrets:** files like `.env*`, `*.pem`, `*.key`, `credentials*` are never opened; only
  git-tracked files are considered; token and key patterns are redacted before anything is embedded or
  stored.
- **Leak guard:** a pre-commit and commit-msg hook rejects any staged line, path or commit message
  containing a configured project name or path, your home directory, or a denylist entry. It prints
  where, never what.
- **Published numbers are aggregates only.** Each eval run writes a private per-question report and a
  `summary.json` that has no field for names, paths or question text.

## Setup

Requires [uv](https://docs.astral.sh/uv/), Ollama and Claude Code.

```sh
uv sync
git config core.hooksPath .githooks
ollama pull bge-m3
```

Create `$WRAG_HOME/config.yaml`:

```yaml
projects:
  - name: alpha              # shown in answers; may be an alias
    path: ~/code/alpha
    exclude: [data, "runs/"]   # optional; matches files and whole directories
embed: { url: http://localhost:11434, model: bge-m3 }
generate: { model: sonnet, timeout: 120 }
retrieve: { k: 8 }
```

After changing `exclude`, run `wrag index --full` once: excluded files drop out on any run, but
commits already indexed stay until a rebuild.

Create `$WRAG_HOME/denylist.txt`, one private string per line (the leak guard refuses to run
without it).
Then log the isolated generator in once (see [docs/generator.md](docs/generator.md)):

```sh
CLAUDE_CONFIG_DIR=~/.config/workspace-rag/claude claude
```

## Usage

```sh
uv run wrag index                     # incremental; --full to rebuild
uv run wrag ask "where did we add rate limiting?"
uv run wrag ask --retrieve-only "..." # ranked locations with scores, nothing leaves the machine
uv run wrag eval                      # Recall@5, MRR@10
uv run wrag eval --with-answers       # + abstention and cited-hit rates
uv run wrag eval --compare RUN_A RUN_B
```

The question set is `$WRAG_HOME/eval/questions.yaml`:

```yaml
- id: q1
  q: where did we add rate limiting?
  lang: en
  expect:
    - { project: alpha, path: internal/ratelimit }
- id: q2
  q: where do we use a GraphQL client?
  absent: true            # not in the corpus: the right answer is "not found"
```

## Results

Measured on the author's own workspace; the corpus and the questions stay private, so only aggregates
are published (each run's `summary.json`, which has no field for names, paths or question text).

**Corpus:** 13 local projects (Go, Python and TypeScript services, plus docs-heavy learning and
tooling repos): 262 markdown docs and dependency manifests and 820 commits, 3,425 chunks.
**Questions:** 31, drafted from the author's own past sessions: 25 with a known location, 6 about
things that are not in the corpus; 20 in Russian, 11 in English, against mostly English docs.

| Run | Recall@5 | MRR@10 | Recall@5 RU / EN | Correct abstention | False abstention | Cited hit |
|---|---|---|---|---|---|---|
| Baseline: `bge-m3`, heading chunks, cosine top-8, Sonnet | 0.72 | 0.53 | 0.75 / 0.67 | 6/6 | 3/25 | 0.80 |

- With 25 answerable questions, one question moves Recall@5 by 0.04; differences below ~0.08 are noise.
- Cited hit exceeds Recall@5 because the generator sees the top 8 chunks, not the top 5 locations.
- Misses fall into three kinds: a gold answer that a neighbouring doc also answers (an eval-set
  ambiguity to fix in the set), changes that live only in commits with terse subjects, and broad hub
  docs (per-repo `CLAUDE.md` files, a planning note about this very tool) that rank high for many
  questions. Exact-token matching (BM25 hybrid search) is the next technique to measure.

## Development

```sh
uv run pytest
uv run ruff check
```

Tests run on a synthetic corpus in `testdata/` with a fake embedder and a fake generator, so they need
neither Ollama nor Claude Code.
