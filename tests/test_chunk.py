from wrag import chunk
from wrag.chunk import Commit


def test_nested_headings_build_a_heading_path():
    text = "# Tool\n\nintro\n\n## Setup\n\nsteps\n\n### Linux\n\napt install\n\n## Usage\n\nrun\n"
    assert chunk.split_markdown(text, 1000) == [
        ("Tool", "intro"),
        ("Tool > Setup", "steps"),
        ("Tool > Setup > Linux", "apt install"),
        ("Tool > Usage", "run"),
    ]


def test_text_before_first_heading_has_empty_path_and_empty_sections_are_dropped():
    text = "preamble\n\n# A\n## B\n\nbody\n"
    assert chunk.split_markdown(text, 1000) == [("", "preamble"), ("A > B", "body")]


def test_hash_lines_inside_code_fences_are_not_headings():
    text = "# A\n\n```sh\n# not a heading\n```\n"
    assert chunk.split_markdown(text, 1000) == [("A", "```sh\n# not a heading\n```")]


def test_long_section_splits_at_paragraphs_within_limit():
    paras = [f"para {i} " + "x" * 30 for i in range(6)]
    parts = chunk.split_long("\n\n".join(paras), 90)
    assert all(len(p) <= 90 for p in parts)
    assert "\n\n".join(parts) == "\n\n".join(paras)
    assert len(parts) == 3


def test_oversized_paragraph_splits_by_line_then_chars():
    parts = chunk.split_long("a" * 250, 100)
    assert [len(p) for p in parts] == [100, 100, 50]


def test_doc_chunks_carry_location_in_embedded_text():
    [c] = chunk.doc_chunks("alpha", "README.md", "# Alpha\n\n## Setup\n\nmake dev\n", 1.0, 1000)
    assert (c.kind, c.heading, c.text) == ("doc", "Alpha > Setup", "make dev")
    assert c.embed_text() == "alpha / README.md / Alpha > Setup\nmake dev"


def test_manifest_is_one_chunk_when_it_fits():
    text = '{\n  "dependencies": {"zod": "^3"}\n}\n'
    [c] = chunk.manifest_chunks("beta", "package.json", text, 1.0, 1000)
    assert (c.kind, c.heading, c.text) == ("manifest", "", text.strip())


def test_large_manifest_splits_by_lines():
    text = "\n".join(f"dep{i} v1.0.{i}" for i in range(100))
    parts = chunk.manifest_chunks("p", "go.mod", text, 1.0, 200)
    assert len(parts) > 1
    assert all(len(p.text) <= 200 for p in parts)
    assert "\n".join(p.text for p in parts) == text


def test_commit_chunk_holds_message_and_capped_file_list():
    files = tuple(f"f{i}.go" for i in range(60))
    c = chunk.commit_chunk("alpha", Commit("a" * 40, "a" * 12, 5.0, "Add limiter\n\nbody", files))
    assert (c.path, c.kind, c.heading, c.mtime) == ("a" * 12, "commit", "Add limiter", 5.0)
    assert c.files == files
    assert "f49.go" in c.text and "f50.go" not in c.text
    assert c.text.endswith("... and 10 more")


def test_commits_since_reads_history_with_changed_files(corpus):
    commits = chunk.commits_since(corpus.alpha, None)
    assert [c.message.splitlines()[0] for c in commits] == [
        "Add setup notes and env file",
        "Add per-client rate limiter",
        "Initial README and vendored lib",
    ]
    limiter = commits[1]
    assert set(limiter.files) == {
        "go.mod",
        "docs/plans/rate-limit.md",
        "internal/ratelimit/limiter.go",
    }
    assert len(limiter.short) == chunk.SHORT_HASH
    assert chunk.commits_since(corpus.alpha, commits[1].hash) == commits[:1]
