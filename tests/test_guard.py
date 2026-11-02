import pytest

from wrag import cli, guard
from wrag.errors import WragError

from .conftest import git, write_config

SECRET = "Zanzibar-Project"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    monkeypatch.chdir(path)
    return path


@pytest.fixture
def guarded(home, tmp_path):
    (home / "denylist.txt").write_text(f"# comment\n\n{SECRET}\n")
    return write_config(home, {"alpha": tmp_path / "work" / "alpha"})


def test_missing_denylist_fails_closed(home):
    cfg = write_config(home, {})
    with pytest.raises(WragError, match="denylist"):
        guard.needles(cfg)


def test_needles_cover_denylist_projects_and_home(guarded, tmp_path):
    values = {n.value for n in guard.needles(guarded, home_dir=tmp_path / "me")}
    assert values == {SECRET, "alpha", str(tmp_path / "work" / "alpha"), str(tmp_path / "me")}


def test_staged_added_line_is_found_with_its_line_number(repo, guarded):
    (repo / "README.md").write_text("intro\n\nbuilt for zanzibar-project users\n")
    git(repo, "add", "README.md")
    findings = guard.scan(guard.staged_lines(repo), guard.needles(guarded))
    assert [(f.where, f.line, f.label) for f in findings] == [("README.md", 3, "denylist entry #1")]


def test_staged_path_is_found(repo, guarded):
    (repo / "notes").mkdir()
    (repo / "notes" / "alpha.md").write_text("nothing here\n")
    git(repo, "add", ".")
    findings = guard.scan(guard.staged_lines(repo), guard.needles(guarded))
    assert ("notes/alpha.md", 0, "project name #1") in [
        (f.where, f.line, f.label) for f in findings
    ]


def test_removed_lines_are_not_scanned(repo, guarded):
    (repo / "a.md").write_text(f"{SECRET}\n")
    git(repo, "add", "a.md")
    git(repo, "commit", "-q", "--no-verify", "-m", "x")
    (repo / "a.md").write_text("clean\n")
    git(repo, "add", "a.md")
    assert guard.scan(guard.staged_lines(repo), guard.needles(guarded)) == []


def test_commit_message_is_scanned_without_git_comments(tmp_path, guarded):
    msg = tmp_path / "MSG"
    msg.write_text(f"Fix the importer\n\n# {SECRET} in a git comment is ignored\nfor alpha\n")
    findings = guard.scan(guard.message_lines(msg), guard.needles(guarded))
    assert [(f.where, f.line) for f in findings] == [("commit message", 4)]


def test_cli_rejects_and_never_prints_the_needle(repo, guarded, capsys):
    (repo / "doc.md").write_text(f"see {SECRET}\n")
    git(repo, "add", "doc.md")
    assert cli.main(["guard", "--staged"]) == 1
    err = capsys.readouterr().err
    assert "doc.md:1: matches denylist entry #1" in err
    assert SECRET.lower() not in err.lower()


def test_cli_passes_clean_tree(repo, guarded):
    (repo / "doc.md").write_text("nothing private\n")
    git(repo, "add", "doc.md")
    assert cli.main(["guard", "--staged"]) == 0
