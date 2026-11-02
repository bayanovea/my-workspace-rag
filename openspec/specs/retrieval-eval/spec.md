# retrieval-eval Specification

## Purpose

Measures retrieval and answer quality against a private question set with known answers, producing a
detailed private report and an identifier-free summary that can be published.

## Requirements

### Requirement: Question set format
The question set SHALL live in the data directory. Each question has an id, text, an optional language
tag, and either a list of expected locations (project + path prefix or commit hash) or a marker that
the answer is not in the corpus.

#### Scenario: Directory as expected answer
- **WHEN** a question expects project `alpha` with path prefix `internal/ratelimit`
- **THEN** a retrieved chunk from `alpha/internal/ratelimit/limiter.go` counts as a hit

#### Scenario: Commit as a hit through its files
- **WHEN** a retrieved commit chunk changed a file under an expected path prefix
- **THEN** it counts as a hit for that question

#### Scenario: Invalid question file
- **WHEN** a question has neither expected locations nor the not-in-corpus marker
- **THEN** `wrag eval` exits non-zero naming the question id

### Requirement: Ranking is by location
Metrics SHALL rank distinct locations, not chunks: several chunks of one file count as one location at
the rank of its best chunk.

#### Scenario: Two chunks of one file
- **WHEN** the top two chunks both come from `README.md` of project `alpha`
- **THEN** `alpha/README.md` occupies rank 1 and the next distinct location takes rank 2

### Requirement: Retrieval metrics
`wrag eval` SHALL compute Recall@5 and MRR@10 over the answerable questions, overall and per language
tag, without calling the generator.

#### Scenario: Retrieval-only run
- **WHEN** `wrag eval` runs without `--with-answers`
- **THEN** it reports Recall@5 and MRR@10 and makes no generator calls

### Requirement: Answer metrics
`wrag eval --with-answers` SHALL also run generation and report the abstention rate on not-in-corpus
questions, the false-abstention rate on answerable questions, and the share of answers whose cited
locations include an expected one.

#### Scenario: Correct abstention
- **WHEN** a not-in-corpus question is answered "not found"
- **THEN** it counts toward correct abstention

### Requirement: Private report and public summary
Each run SHALL write, under a timestamped run directory in the data directory, a per-question report
and a summary. The summary SHALL contain only aggregate numbers, question counts, corpus counts and
run parameters (model names, k, chunker version), with no project names, paths, hashes or question text.

#### Scenario: Summary has no identifiers
- **WHEN** a run's summary is checked against the configured project names, paths and question texts
- **THEN** none of them occur in it

### Requirement: Runs are comparable
The summary SHALL record the parameters and the question-set hash it ran with, so that two runs can be
compared and a changed question set is detectable.

#### Scenario: Question set edited between runs
- **WHEN** two summaries record different question-set hashes
- **THEN** `wrag eval --compare <runA> <runB>` warns that the sets differ before printing metric deltas
