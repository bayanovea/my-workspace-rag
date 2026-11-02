# Tasks

## 1. Spike: isolated `claude -p` (gate for D7)

- [x] 1.1 Log in once with `CLAUDE_CONFIG_DIR=<tmp-config> claude` on the subscription and verify that `claude -p "say ok"` under the same env var answers without an API key
- [x] 1.2 Run the D7 invocation from an empty temp dir and verify isolation: the user's hooks leave no side effects, the `stream-json` init event lists no tools, MCP servers or plugins, a canary `CLAUDE.md` in the parent dir is not obeyed, and the user's global reply format does not appear
- [x] 1.3 Verify `--json-schema` returns the D7 output shape, and record latency for an 8-chunk prompt
- [x] 1.4 Write `docs/generator.md` (flags, why a separate config dir, one-time login command); if any check failed, stop and bring the options to the user before group 5

## 2. Repository scaffolding and leak guard

- [x] 2.1 Install `uv`, init the package (`src/wrag/`, `pyproject.toml` pinned to Python 3.12+, `uv.lock`, ruff and pytest config), add the `wrag` entry point with `index|ask|eval|guard` subcommand stubs, and verify `uv run wrag --help`, `uv run ruff check` and `uv run pytest` pass
- [x] 2.2 Add `.gitignore` (`*.db`, `runs/`, `.env*`, `.venv/`, `__pycache__/`, `.claude/settings.local.json`) and verify an `index.db` copied into the tree is not listed by `git status`
- [x] 2.3 Implement `wrag.config`: resolve `WRAG_HOME`, refuse a path inside a git working tree, load and validate `config.yaml`; unit tests cover the default path, the in-repo refusal and an empty allowlist
- [x] 2.4 Implement `wrag guard --staged` / `--msg` per D10 with tests for a needle in an added line, in a staged path, in a commit message, a missing denylist (fails closed), and output that never contains the needle
- [x] 2.5 Add `.githooks/pre-commit` and `.githooks/commit-msg`, document `git config core.hooksPath .githooks` in the README, and verify a commit that stages a denylisted string is rejected
- [x] 2.6 Create the real data dir with `config.yaml` (allowlist, aliases for common-word names) and `denylist.txt`, outside the repo, and verify `wrag guard --staged` passes on the clean tree

## 3. Corpus selection and secret handling

- [x] 3.1 Build the synthetic fixture (D11): fake projects in `testdata/corpus/` plus a pytest fixture that creates git history in `tmp_path`; verify the fixture produces the expected commits
- [x] 3.2 Implement file selection (D4): `git ls-files`/walk, skip dirs, secret filename denylist, source-type allowlist, size cap, NUL sniff; tests cover vendored, untracked, `.env`, oversized and binary-as-`.md` files
- [x] 3.3 Implement content redaction (D8) with a table test per pattern kind plus non-secret look-alikes that must survive

- [x] 3.4 Add per-project `exclude` globs (files under a matching path, and commits touching only excluded files, are not indexed); tests cover directory globs, a file glob, config parsing and a dropped commit

## 4. Chunking, embedding, storage, incremental index

- [x] 4.1 Implement the markdown chunker (heading path, paragraph split, location prefix) and verify it with tests for nested headings, a long section, and text before the first heading
- [x] 4.2 Implement the manifest and commit chunkers (D5), including the 50-path cap; verify both with fixture tests
- [x] 4.3 Implement the store (D3 schema on stdlib `sqlite3`, float32 BLOB vectors, `meta`) and verify round-trip tests for chunks and vectors
- [x] 4.4 Implement the Ollama embedder and the fake embedder behind one `Protocol`; verify the fake is deterministic and normalised in unit tests, and the Ollama client against `httpx.MockTransport`
- [x] 4.5 Implement `wrag index` with incremental logic (file sha256, commit cursor, ancestry check, full rebuild on model/chunker-version change) and the per-project report; verify on the fixture with tests for edit, delete, rewritten history, model change, and one secret redaction counted
- [x] 4.6 Install Ollama and `bge-m3`, run `wrag index` on the real allowlist, and verify the report counts look plausible and that searching `index.db` for common token prefixes (`ghp_`, `sk-`, `AKIA`, `PRIVATE KEY`) finds nothing

## 5. Retrieval and answering

- [x] 5.1 Implement numpy brute-force cosine search and location dedup; tests on the fixture cover ranking order and dedup of same-file chunks
- [x] 5.2 Implement `wrag ask --retrieve-only` and verify it prints ranked locations with scores and runs with the network off
- [x] 5.3 Implement the `claude -p` generator per D7 (keep `docs/generator.md` in sync), plus a fake generator; tests cover dropping invented citations, `found` with no valid citation turning into "not found", timeout, unparsable output, and printing locations before the error
- [x] 5.4 Wire `wrag ask` end to end, verify it with a fake-generator test on the fixture and by hand with one real question that has a known answer

## 6. Evaluation harness

- [x] 6.1 Implement the question set loader and validation (D9); tests cover an expected path prefix, an expected commit, `absent`, and an invalid entry naming its id
- [x] 6.2 Implement Recall@5 and MRR@10 over deduped locations, overall and per `lang`, verified against hand-computed values on a tiny fixture
- [x] 6.3 Implement `--with-answers` metrics (correct abstention, false abstention, cited-hit rate) with fake-generator tests
- [x] 6.4 Write `report.md` and the identifier-free `summary.json` per run, and `--compare`; a test serialises a fixture run and asserts that no fixture project name, path or question text occurs in the summary

## 7. Baseline

- [x] 7.1 Write 20–30 real questions in the private data dir (RU and EN, with 4–6 `absent` ones) and verify that `wrag eval` validates the set
- [x] 7.2 Run `wrag eval` and `wrag eval --with-answers`, and verify that both summaries are written and that `--compare` between them runs
- [x] 7.3 Write the README: what it does, the privacy model (data dir, what leaves the machine, leak guard), setup, method, and a baseline table with aggregate numbers and corpus shape only; verify `wrag guard --staged` passes on it
- [x] 7.4 Cleanup pass before commit: no residue or transient state in docs, open questions moved to an explicit section, and `openspec validate add-rag-baseline --strict` passes
