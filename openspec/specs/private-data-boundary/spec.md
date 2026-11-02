# private-data-boundary Specification

## Purpose

Keeps the private corpus and everything derived from it out of the public repository, and limits what
leaves the machine to the retrieved chunks of a question, with secrets removed.

## Requirements

### Requirement: Private data lives outside the repository
Config, index, question set, run reports and the leak-guard denylist SHALL live in the data directory,
`~/.config/workspace-rag/` by default or `$WRAG_HOME` when set. The tool SHALL refuse a data directory
inside a git working tree.

#### Scenario: Default location
- **WHEN** `WRAG_HOME` is unset
- **THEN** all files the tool creates are under `~/.config/workspace-rag/`

#### Scenario: Data directory inside a repository
- **WHEN** `WRAG_HOME` points inside a git working tree
- **THEN** every command exits non-zero before writing anything and says why

### Requirement: Secret files are never read
Files whose names match the secret denylist (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `*.p12`,
`credentials*`, `secrets.*` and the like) SHALL NOT be opened, even when tracked by git.

#### Scenario: Tracked env file
- **WHEN** a project tracks `.env.example` and `config/.env`
- **THEN** neither is opened or indexed

### Requirement: Secrets are redacted before storage
Chunk text SHALL be scanned for secret patterns (private key blocks, cloud and VCS tokens, API keys,
credential assignments), and each match SHALL be replaced with a redaction marker before the chunk is
embedded or stored.

#### Scenario: Token in a README
- **WHEN** a README contains a line with a GitHub personal access token
- **THEN** the stored chunk contains the redaction marker in its place, and the index report counts one
  redaction

### Requirement: Only retrieved chunks leave the machine
Indexing and embedding SHALL run locally. A generator call SHALL receive only the question and the
retrieved chunks with their metadata. The generator SHALL run without tools, hooks, MCP servers, user
or project instruction files, or session persistence.

#### Scenario: Indexing offline
- **WHEN** `wrag index` runs with the network disabled but the local embedding server up
- **THEN** it completes successfully

#### Scenario: Generator isolation
- **WHEN** `wrag ask` calls the generator
- **THEN** no user hook runs, no instruction file from the user's normal setup is loaded, and the
  generator has no tools

### Requirement: Commit-time leak guard
The repository SHALL ship a git hook that rejects a commit when its staged added lines, staged file
paths or commit message contain any denylist entry, a configured project name or root path, or the
user's home directory path. The hook SHALL fail closed when the denylist is missing.

#### Scenario: Project name in a doc
- **WHEN** a staged change to `README.md` mentions a configured project name
- **THEN** the commit is rejected, and the message shows the file and line but not the matched value

#### Scenario: Denylist missing
- **WHEN** the denylist file does not exist in the data directory
- **THEN** the commit is rejected with instructions to create it

### Requirement: Generated artifacts are gitignored
The repository's `.gitignore` SHALL exclude index files, run outputs, env files and local agent
settings as a second line of defense.

#### Scenario: Accidental index copy
- **WHEN** an `index.db` file is copied into the working tree
- **THEN** `git status` does not list it
