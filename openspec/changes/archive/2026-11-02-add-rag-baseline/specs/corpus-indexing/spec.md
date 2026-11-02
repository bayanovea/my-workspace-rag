# Spec Delta

## Purpose

Builds and maintains a searchable index of documents, dependency manifests and git commits from an
explicit allowlist of local projects, so that questions can be answered with a location.

## ADDED Requirements

### Requirement: Only allowlisted projects are indexed
The system SHALL index only the projects listed in the private config. Each project has a name, which
appears in citations, and a root path. No directory outside a listed project root SHALL be read.

#### Scenario: Unlisted sibling directory
- **WHEN** a directory sits next to an allowlisted project but is not listed in the config
- **THEN** `wrag index` reads no files from it and the index contains no chunks from it

#### Scenario: Empty allowlist
- **WHEN** the config lists no projects
- **THEN** `wrag index` exits with a non-zero status and a message naming the config file to edit

### Requirement: Indexed source types
The system SHALL index markdown documents, dependency manifests (such as `go.mod`, `package.json`,
`composer.json`, `pyproject.toml`, `Cargo.toml`) and git commits. Source code files SHALL NOT be indexed.

#### Scenario: Mixed project
- **WHEN** a project contains `README.md`, `docs/plan.md`, `go.mod` and `internal/server.go`
- **THEN** chunks exist for the README, the plan and `go.mod`, and none exist for `internal/server.go`

### Requirement: Excluded paths and files
The system SHALL skip dependency and build directories (`node_modules`, `vendor`, `.git`, `dist`,
`build`, `target`, virtualenvs), binary files, and files larger than the configured size cap. In a git
project, only tracked files SHALL be considered.

#### Scenario: Vendored and untracked files
- **WHEN** a git project has `vendor/x/README.md` and an untracked `notes.md`
- **THEN** neither file produces chunks

#### Scenario: Binary file with a markdown extension
- **WHEN** a file named `*.md` contains NUL bytes
- **THEN** it is skipped and counted as skipped in the index report

### Requirement: Per-project exclusions
A project MAY list exclude globs relative to its root. A file SHALL NOT be indexed when the glob
matches its path or any of its parent directories. A commit SHALL NOT be indexed when every file it
changed is excluded.

#### Scenario: Excluded data directory
- **WHEN** a project excludes `data*` and contains `data-nov26/listing.md`
- **THEN** that file produces no chunks

#### Scenario: Commit touching only excluded paths
- **WHEN** a commit changes only files under an excluded `runs` directory
- **THEN** no chunk is created for that commit

### Requirement: Markdown chunked by headings
Markdown SHALL be split at headings. Each chunk SHALL carry its heading path (for example
`README > Install > macOS`). A section longer than the chunk size limit SHALL be split at paragraph
boundaries.

#### Scenario: Nested headings
- **WHEN** a document has `# Tool`, `## Setup` and `### Linux` with text under each
- **THEN** the chunk for the Linux text carries the heading path `Tool > Setup > Linux`

### Requirement: One commit is one chunk
Each git commit SHALL become one chunk containing its subject, body and list of changed files. The
chunk's location SHALL be the project and the short commit hash, with its commit date.

#### Scenario: Commit that adds a dependency
- **WHEN** a commit with message "add rate limiter" changes `go.mod` and `internal/ratelimit/limiter.go`
- **THEN** one chunk contains the message and both file paths, and it cites that commit's short hash

### Requirement: Chunk metadata
Every chunk SHALL store the project name, path (or commit hash), source type (`doc`, `manifest`,
`commit`) and last-modified time (file mtime or commit date).

#### Scenario: Metadata on a manifest chunk
- **WHEN** `package.json` of project `alpha` is indexed
- **THEN** its chunks record project `alpha`, path `package.json`, type `manifest` and the file's mtime

### Requirement: Incremental reindex
On reindex, the system SHALL re-chunk only files whose content hash changed, delete chunks of files
that no longer exist, and add only commits not yet indexed. A full rebuild SHALL be available on demand
and SHALL happen automatically when the embedding model changes.

#### Scenario: One file edited
- **WHEN** one README changes and nothing else does
- **THEN** only that README's chunks are re-embedded, and the report shows 1 file updated

#### Scenario: File deleted
- **WHEN** an indexed `docs/old.md` is deleted from the project
- **THEN** its chunks are removed from the index on the next `wrag index`

#### Scenario: History rewritten
- **WHEN** the last indexed commit of a project is no longer reachable from its HEAD
- **THEN** that project's commit chunks are rebuilt from scratch

#### Scenario: Embedding model changed
- **WHEN** the configured embedding model differs from the one recorded in the index
- **THEN** `wrag index` rebuilds the whole index and says why

### Requirement: Index report
`wrag index` SHALL print, per project, the counts of files added, updated, deleted and skipped, the
number of commits added, and the number of secret redactions.

#### Scenario: Report after a run
- **WHEN** `wrag index` finishes
- **THEN** the output lists each project with those counts and a total
