from pathlib import Path

import pytest

from wrag import config
from wrag.errors import WragError

from .conftest import git, write_config


def test_default_home_is_under_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.resolve_home({}) == (tmp_path / ".config" / "workspace-rag").resolve()


def test_wrag_home_overrides_default(tmp_path):
    assert (
        config.resolve_home({"WRAG_HOME": str(tmp_path / "data")}) == (tmp_path / "data").resolve()
    )


def test_home_inside_git_working_tree_is_refused(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    with pytest.raises(WragError, match="inside the git working tree"):
        config.resolve_home({"WRAG_HOME": str(repo / "not-yet-created" / "data")})


def test_empty_allowlist_names_the_config_file(home):
    cfg = write_config(home, {})
    with pytest.raises(WragError, match=str(cfg.config_file)):
        config.require_projects(cfg)


def test_load_parses_projects_and_settings(home, tmp_path):
    cfg = write_config(home, {"alpha": tmp_path}, retrieve={"k": 3}, embed={"model": "m"})
    assert cfg.projects == [config.Project("alpha", tmp_path.resolve())]
    assert (cfg.k, cfg.embed_model) == (3, "m")


def test_missing_config_means_no_projects(home):
    assert config.load(home).projects == []


def test_project_entry_needs_name_and_path(home):
    (home / "config.yaml").write_text("projects:\n  - name: alpha\n")
    with pytest.raises(WragError, match=r"projects\[0\]"):
        config.load(home)


def test_project_path_expands_user(home, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (home / "config.yaml").write_text("projects:\n  - {name: a, path: ~/code/a}\n")
    assert config.load(home).projects[0].path == Path(tmp_path, "code", "a").resolve()


def test_project_exclude_is_parsed(home, tmp_path):
    (home / "config.yaml").write_text(
        f"projects:\n  - {{name: a, path: {tmp_path}, exclude: [data, 'runs/']}}\n"
    )
    assert config.load(home).projects[0].exclude == ("data", "runs/")


def test_project_exclude_must_be_a_list(home, tmp_path):
    (home / "config.yaml").write_text(
        f"projects:\n  - {{name: a, path: {tmp_path}, exclude: data}}\n"
    )
    with pytest.raises(WragError, match="exclude must be a list"):
        config.load(home)
