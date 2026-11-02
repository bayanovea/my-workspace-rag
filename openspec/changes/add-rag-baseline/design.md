# Design

## Context

Greenfield repository: only the OpenSpec scaffold exists. The repo is public; the corpus (about ten
local projects) is private. See proposal.md for motivation and the specs for required behavior.

Constraints that shape the design:

- Questions are mostly in Russian; docs and commit messages are mostly in English.
- Generation must go through the Claude Code CLI on a subscription login, not an API key. `claude
  --bare` (the clean headless mode) accepts only `ANTHROPIC_API_KEY`, so it is not available.
- The user's normal Claude Code setup has global instructions and hooks (reply formatting, prompt
  logging, a session-end hook) that must not fire on generator calls.
- Every stage should stay visible and easy to change, because later changes swap one technique at a
  time and re-measure.

## Goals / Non-Goals

**Goals:**
- A baseline that is cheap to re-run: retrieval-only eval needs no generator calls.
- Privacy by construction: private data has no path into the working tree, and identifiers have no
  field in the public summary.
- Seams only where tests need them: embedder and generator behind small interfaces with fakes.

**Non-Goals:**
- BM25/hybrid search, reranking, contextual embeddings, source-code chunking: later changes.
- A long-running service, a UI, or watching files. `wrag index` is run by hand or by cron.
- Publishing the question set or any per-question result.

## Decisions

### D1. Python package, no RAG framework
Python 3.12+ managed with `uv`; package `src/wrag/` with modules `config, corpus, chunk, embed, store,
retrieve, generate, evaluate, guard`; console entry point `wrag` (`index | ask | eval | guard`) on
stdlib `argparse`. Runtime deps: `httpx`, `numpy`, `pyyaml`. Dev: `pytest`, `ruff`.

- Python over Go: the later stages are much cheaper in Python. Local cross-encoder reranking via
  `sentence-transformers`, tree-sitter wheels for code chunking, sqlite-vec as a pip package, and
  pandas for comparing runs. In Go each of these is cgo or an extra service.
- No LangChain/LlamaIndex: each stage stays a plain function over dataclasses, so a technique swap is
  a visible diff, which is the point of a measurement project.
- The macOS system `python3` (3.9, built without `enable_load_extension`) is not supported; `uv`
  provides the interpreter.

### D2. One data directory, outside the repo
`$WRAG_HOME`, default `~/.config/workspace-rag/`:

```
config.yaml        projects allowlist, models, k, size caps
denylist.txt       extra strings the leak guard rejects (one per line)
index.db           SQLite: files, chunks, vectors, meta
eval/questions.yaml
runs/<UTC-timestamp>/report.md, summary.json
claude/            isolated Claude Code config dir (D7)
```

One directory, not XDG config/data/state splits, so it can be backed up, excluded and reasoned about
as a single private unit. Startup resolves the path and refuses it if `git rev-parse` finds a working
tree there.

Config shape:

```yaml
projects:
  - name: alpha            # appears in citations; may be an alias
    path: /abs/path/to/alpha
    exclude: [data, "runs/"] # optional globs; a match on a directory covers everything under it
embed: { url: http://localhost:11434, model: bge-m3 }
generate: { model: sonnet, timeout: 120s }
retrieve: { k: 8 }
limits: { max_file_bytes: 1048576, max_chunk_chars: 2000 }
```

### D3. Stdlib `sqlite3`, brute-force vector search with numpy
Vectors are stored as float32 BLOBs in a `chunks` table. Search loads them once per process into one
numpy matrix and takes a matrix-vector product. With docs and commits only, the corpus is on the order
of 10^4 chunks × 1024 dims, about 40 MB, which takes milliseconds per query.

- Over sqlite-vec: no extension to load, and the KNN step is one readable line. Stdlib `sqlite3`
  already has FTS5, which the hybrid-search change will need.
- Over Postgres/pgvector or Chroma: no server to run for a single-user CLI.
- Revisit when source code is indexed and query latency exceeds ~200 ms. sqlite-vec then replaces only
  the search function.

Schema: `files(project, path, sha256, mtime)`, `chunks(id, project, path, kind, heading, text, mtime,
vector)`, `commits_cursor(project, last_hash)`, `meta(key, value)` holding the embedding model and
dimension, and the chunker version.

### D4. File selection
Git projects: `git ls-files`, so only tracked files are considered and `.gitignore` is honored for free.
Non-git projects: a directory walk with the same skip list. Then filters in order: skip dirs →
per-project `exclude` globs → secret filename denylist (never opened) → extension/name allowlist
(`*.md`, known manifests) → size cap → NUL sniff on the first 8 KB. The source type allowlist is the switch the code-indexing change will extend.

### D5. Chunking
- Markdown: split at ATX headings into sections carrying the heading path. Sections above
  `max_chunk_chars` split at blank lines. The embedded text is prefixed with `project / path /
  heading path` so that short sections stay findable by where they live.
- Manifests: the whole file as one chunk when under the cap, otherwise split by lines. Dependency names
  are exact tokens, and keeping the file whole keeps them together.
- Commits: `git log --name-only` from the cursor to HEAD, one chunk per commit: subject, body and up to
  50 changed paths. If the cursor is not an ancestor of HEAD (`git merge-base --is-ancestor`), drop
  that project's commit chunks and rebuild them.
- A `chunker_version` in `meta` changes whenever chunking changes; a mismatch forces a full rebuild,
  like an embedding model change does.

### D6. Embeddings: Ollama + `bge-m3`
Calls go to `POST /api/embed` in batches over `httpx`. `bge-m3` is multilingual (RU↔EN retrieval), has 1024 dims and
an 8k-token context. Vectors are L2-normalised at write time, so cosine is a dot product. Model name
and dimension live in `meta`; a mismatch triggers a full rebuild. Tests use a deterministic
hashed-bag-of-words fake embedder, so CI never needs Ollama.

### D7. Generation: `claude -p` in an isolated config dir
Each call runs:

```
CLAUDE_CONFIG_DIR=$WRAG_HOME/claude  claude -p --model <m> --tools "" \
  --strict-mcp-config --setting-sources "" --no-session-persistence \
  --system-prompt <ours> --output-format json --json-schema <schema>
```

via `subprocess.run` with the working directory set to a fresh `TemporaryDirectory`, a timeout, and
the prompt on stdin.

- A dedicated `CLAUDE_CONFIG_DIR` isolates by construction: it holds no hooks, plugins, MCP servers,
  user `CLAUDE.md` or memory, only its own login, made once with `claude` run under the same env var.
  The empty cwd keeps any project `CLAUDE.md` out of the context, and `--setting-sources ""` stops
  the walk up to ancestor directories: the spike showed a `CLAUDE.md` in the temp dir's parent is
  otherwise obeyed.
- Rejected: reusing the normal config with `--setting-sources` and similar flags. Isolation would then
  depend on every feature honoring those flags, and a new hook type would leak silently.
- Output schema: `{found: bool, answer: string, citations: [chunk_id]}`. Chunks are sent with short
  ids (`c1..ck`) plus project/path/heading. Citations outside the sent ids are dropped; `found` with no
  valid citation becomes "not found" (spec: invented citation).
- The isolation has to be verified on this machine before anything is built on it: the first task is a
  spike, and the approach is revisited if the spike fails.

### D8. Secret handling: two layers before storage
1. The filename denylist (D4) means secret files are never opened.
2. Content regexes for PEM private key blocks, AWS access keys, GitHub/GitLab tokens, Slack tokens,
   `sk-`-style API keys, JWTs, and `password|secret|token|api_key\s*[:=]\s*\S{8,}` assignments. Matches
   are replaced with `[REDACTED:<kind>]` before embedding, so the index never holds them and neither
   does a generator prompt.

A built-in list rather than gitleaks: no external binary, and the corpus is docs and commit messages,
where these patterns cover the realistic cases. The residual risk is in Risks.

### D9. Eval
- `questions.yaml`: `{id, q, lang?, expect: [{project, path?|commit?}] | absent: true}`.
- Hit rule: same project, and the location path has the expected path as a prefix, or the expected
  commit hash. A commit chunk also hits when any of its changed paths matches.
- Ranking dedupes chunks to locations at the best chunk's rank, then computes Recall@5 and MRR@10 over
  `expect` questions, overall and per `lang`.
- `--with-answers` adds generator calls and computes correct abstention (on `absent`), false abstention
  and cited-hit rate.
- `report.md` holds everything per question (private). `summary.json` is serialised from a struct that
  only has numeric fields, model names, parameters and hashes, so identifiers have no field to land in.
  A test also scans a summary for fixture project names and paths.
- The summary records `questions_sha256`; `--compare` warns when two runs' hashes differ.

### D10. Leak guard
`wrag guard --staged` scans `git diff --cached` added lines and staged paths, and `wrag guard --msg
<file>` scans the commit message. Needles are the `denylist.txt` entries, every configured project name
and path, and `$HOME`; matching is case-insensitive on fixed strings. `.githooks/pre-commit` and
`.githooks/commit-msg` call `uv run --frozen wrag guard ...`, and `git config core.hooksPath
.githooks` enables them. A missing denylist, or a missing `uv`, fails closed. Findings print file:line and the needle's index in the
list, never the needle itself, so the guard's own output is safe to paste.

Project names that are common words would cause false positives. The fix is to alias them in
`config.yaml` (the alias is what citations show) and keep the real name only in the denylist when it
matters.

### D11. Synthetic test corpus
`testdata/corpus/` holds two or three fake projects (markdown, manifests, one secret-bearing README, a
binary disguised as `.md`). Git history is built at test time by a pytest fixture that runs `git
init/commit` in `tmp_path`, because nested `.git` directories can't be committed. The same fixture backs unit tests,
the summary-leak test and a fake end-to-end `ask`.

## Risks / Trade-offs

- [Regex misses a secret format] → only tracked files are read, secret files are never opened, and
  only k chunks per question leave the machine. Patterns are extended whenever the index report or a
  manual spot-check finds a miss.
- [`claude -p` isolation fails, or the subscription login won't work under a custom config dir] → the
  spike task decides this before anything depends on it. The fallback is a decision for the user (e.g.
  an API key), not a silent workaround.
- [Generator latency of a few seconds per call makes eval with answers slow] → retrieval metrics,
  which most iterations need, run without the generator.
- [Commit messages are terse ("fix", "wip")] → changed paths are in the chunk, so path tokens still
  match. The baseline numbers show whether that is enough.
- [Leak guard false positives on short or common project names] → aliases (D10).
- [Brute-force search won't scale to code] → isolated behind one search function (D3).
- [Aggregate numbers aren't reproducible by readers] → accepted. The README describes corpus shape and
  method, and the synthetic fixture shows the pipeline runs.

## Migration Plan

None: new repository, no existing users or data.

## Open Questions

- The generator sometimes answers an English question in German, even with the language named at
  the end of the prompt (1 of 31 in the baseline run). It does not affect the metrics, but it shows
  that prompt-only language control is unreliable under `--system-prompt`.
- Some eval questions have a second legitimate answer that the gold set does not list. Widening the
  gold after seeing results biases the metric, so it needs a rule (e.g. review the gold blind, before
  each technique change) rather than ad-hoc edits.
