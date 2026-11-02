import os

from wrag import corpus
from wrag.config import Project

from .conftest import git


def select(path, max_bytes=1_000_000):
    files, skipped = corpus.select(Project("p", path.resolve()), max_bytes)
    return {f.rel: f.kind for f in files}, {s.rel: s.reason for s in skipped}


def test_fixture_history(corpus):
    log = git(corpus.alpha, "log", "--format=%s").splitlines()
    assert log == [
        "Add setup notes and env file",
        "Add per-client rate limiter",
        "Initial README and vendored lib",
    ]


def test_git_project_selects_tracked_docs_and_manifests(corpus):
    files, skipped = select(corpus.alpha)
    assert files == {
        "README.md": "doc",
        "docs/plans/rate-limit.md": "doc",
        "docs/setup.md": "doc",
        "go.mod": "manifest",
    }
    assert skipped == {".env": "secret-name"}


def test_code_vendored_and_untracked_files_are_ignored(corpus):
    files, _ = select(corpus.alpha)
    assert "internal/ratelimit/limiter.go" not in files
    assert "vendor/example/README.md" not in files
    assert "notes.md" not in files


def test_binary_markdown_is_skipped(corpus):
    files, skipped = select(corpus.beta)
    assert skipped == {"logo.md": "binary"}
    assert set(files) == {"README.md", "docs/notes.md", "package.json"}


def test_plain_directory_is_walked(corpus):
    files, _ = select(corpus.gamma)
    assert files == {"notes.md": "doc", "composer.json": "manifest"}


def test_walk_prunes_skip_dirs(tmp_path):
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "README.md").write_text("# x\n")
    (tmp_path / "README.md").write_text("# root\n")
    files, _ = select(tmp_path)
    assert files == {"README.md": "doc"}


def test_oversized_file_is_skipped(corpus):
    _, skipped = select(corpus.gamma, max_bytes=50)
    assert skipped["notes.md"] == "too-large"


def test_secret_names_are_never_selected(tmp_path):
    for name in (".env.example", "server.pem", "id_rsa", "credentials.json", "secrets.md"):
        (tmp_path / name).write_text("x\n")
    files, skipped = select(tmp_path)
    assert files == {}
    assert set(skipped.values()) == {"secret-name"}


def test_symlink_outside_root_is_not_followed(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# private\n")
    project = tmp_path / "project"
    project.mkdir()
    os.symlink(outside, project / "link.md")
    files, _ = select(project)
    assert files == {}


def test_exclude_globs_cover_directories_and_files(tmp_path):
    for rel in ("data/a.md", "data-nov26/b.md", "database.md", "docs/x.md", "docs/draft.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("# x\n")
    project = Project("p", tmp_path.resolve(), ("data", "data-*/", "docs/draft.md"))
    files, _ = corpus.select(project, 1_000_000)
    assert sorted(f.rel for f in files) == ["database.md", "docs/x.md"]
