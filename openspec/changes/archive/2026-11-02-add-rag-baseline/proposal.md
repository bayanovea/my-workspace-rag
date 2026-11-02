# Proposal

## Why

Questions like "a while ago we added some tool, where was it?" span a dozen local projects: their docs,
plans, dependency manifests and git history. Grepping each one by hand is slow and assumes you remember
the exact name. A retrieval-augmented tool can answer with a **location** (project + file or commit) and
gives a real corpus for measuring which retrieval techniques actually help.

The repository is public, but the corpus is private. This change sets the privacy boundary before any
private data exists, and ships the first measurable baseline that later changes improve on one
technique at a time.

## What Changes

- New Python CLI `wrag` with three commands: `index`, `ask`, `eval`.
- Indexing of an explicit allowlist of local projects. Indexed sources: markdown docs, dependency
  manifests, and git commits (message + changed files). Source code is **not** indexed in this change.
- Incremental reindexing: changed files are re-chunked, deleted files lose their chunks, and only new
  commits are added.
- Local embeddings through Ollama. Answer generation through the Claude Code CLI (`claude -p`) in an
  isolated configuration, with no direct API calls. Only the retrieved chunks for a question leave the
  machine.
- Every answer cites locations from the retrieved chunks, or explicitly says "not found".
- An evaluation harness that computes Recall@5, MRR and abstention metrics. It writes a private
  per-question report and a public summary that contains no identifiers.
- A privacy boundary. All per-machine data (config, index, questions, run reports) lives in a data
  directory outside the repository. Secrets are dropped or redacted before anything is stored. A
  commit-time leak guard rejects staged content that matches a private denylist.
- Out of scope, each a later change with its own measurement: hybrid search (BM25), contextual
  embeddings, reranking, indexing source code, and comparison with agentic grep-and-read search.

## Capabilities

### New Capabilities

- `corpus-indexing`: selecting files and commits from allowlisted projects, chunking them, embedding,
  and keeping the index in sync incrementally.
- `question-answering`: retrieving chunks for a question and producing an answer that cites locations
  or abstains.
- `retrieval-eval`: running a question set with known answers, computing metrics, and writing private
  and publishable results.
- `private-data-boundary`: where private data may live, what may leave the machine, and the guard that
  keeps private identifiers out of the public repository.

### Modified Capabilities

None. The project has no existing specs.

## Impact

- New code: Python package (`src/wrag/`, `pyproject.toml`, `uv.lock`), a synthetic test corpus in
  `testdata/`, a pre-commit/commit-msg hook in `.githooks/`, and `.gitignore`.
- New local dependencies: `uv` (which provides Python 3.12+), Ollama with a multilingual embedding
  model, and the Claude Code CLI logged in under a dedicated config directory.
- New per-machine state outside the repo: `~/.config/workspace-rag/` (overridable via `WRAG_HOME`).
- README: method, privacy model, and aggregate baseline numbers only.
