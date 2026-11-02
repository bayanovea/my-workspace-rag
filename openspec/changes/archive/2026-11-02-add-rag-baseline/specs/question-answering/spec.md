# Spec Delta

## Purpose

Answers a natural-language question about the indexed projects with the locations where the answer
lives, citing only retrieved chunks, or says that nothing relevant was found.

## ADDED Requirements

### Requirement: Retrieval by semantic similarity
`wrag ask "<question>"` SHALL embed the question with the same model as the index and retrieve the
top-k most similar chunks, with k configurable. Questions and documents MAY be in different languages.

#### Scenario: Cross-language question
- **WHEN** the question is in Russian and the matching README section is in English
- **THEN** that section is among the retrieved chunks

### Requirement: Answer is a location with citations
The answer SHALL name one or more locations (project + path, or project + commit hash), each citing a
chunk that was given to the generator. Citations that do not refer to a retrieved chunk SHALL be
dropped before output.

#### Scenario: Answer with a citation
- **WHEN** the retrieved chunks include the commit that introduced a tool
- **THEN** the output names the project and commit hash and shows the cited chunk's heading or subject

#### Scenario: Invented citation
- **WHEN** the generator cites a chunk id that was not in its context
- **THEN** that citation is removed, and if no valid citation remains the answer becomes "not found"

### Requirement: Abstention
When the retrieved chunks do not contain the answer, the system SHALL answer "not found" and list the
closest locations it considered, labelled as non-answers. It SHALL NOT present an uncited location as
the answer.

#### Scenario: Question about something not in the corpus
- **WHEN** the question asks about a tool that no indexed project uses
- **THEN** the output says "not found" and does not claim any location as the answer

### Requirement: Retrieval-only mode
`wrag ask --retrieve-only` SHALL print the ranked locations with similarity scores and SHALL NOT call
the generator.

#### Scenario: Inspecting retrieval
- **WHEN** the user runs `wrag ask --retrieve-only "where is rate limiting"`
- **THEN** a ranked list of locations with scores is printed and nothing leaves the machine

### Requirement: Generator failures are visible
If the generator is missing, not logged in, times out, or returns output that cannot be parsed, `wrag
ask` SHALL exit non-zero with the reason and SHALL still print the retrieved locations.

#### Scenario: Generator not logged in
- **WHEN** the isolated Claude Code config has no login
- **THEN** the command prints the retrieved locations, then an error that names the login command to run
