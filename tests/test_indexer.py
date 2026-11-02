import pytest

from wrag import config, indexer
from wrag.embed import FakeEmbedder
from wrag.errors import WragError
from wrag.store import Store

from .conftest import FAKE_GITHUB_TOKEN, commit, git, write_config


@pytest.fixture
def store(cfg):
    s = Store(cfg.index_file)
    yield s
    s.close()


def run(cfg, store, embedder=None, **kw):
    logs = []
    reports = indexer.run(cfg, store, embedder or FakeEmbedder(), log=logs.append, **kw)
    return reports, logs


def all_text(store):
    return "\n".join(r[0] for r in store.db.execute("SELECT text || heading FROM chunks"))


def test_first_run_indexes_everything(cfg, store):
    reports, _ = run(cfg, store)
    alpha, beta, gamma = reports["alpha"], reports["beta"], reports["gamma"]
    assert (alpha.added, alpha.skipped, alpha.commits, alpha.redactions) == (4, 1, 3, 1)
    assert (beta.added, beta.skipped, beta.commits) == (3, 1, 1)
    assert (gamma.added, gamma.commits) == (2, 0)
    assert store.counts()["commit"] == 4


def test_secret_never_reaches_the_index(cfg, store):
    run(cfg, store)
    text = all_text(store)
    assert FAKE_GITHUB_TOKEN not in text
    assert "[REDACTED:github-token]" in text
    assert "hunter2" not in text  # .env is never opened


def test_unchanged_reindex_does_nothing(cfg, store):
    run(cfg, store)
    reports, _ = run(cfg, store)
    assert all(
        r.line().startswith("+0 added, 0 updated, 0 deleted") and r.commits == 0
        for r in reports.values()
    )


def test_edited_file_is_reembedded_alone(cfg, store, corpus):
    run(cfg, store)
    readme = corpus.beta / "README.md"
    readme.write_text(readme.read_text() + "\n## Caching\n\nResponses are cached in Redis.\n")
    reports, _ = run(cfg, store)
    assert (reports["beta"].updated, reports["beta"].added) == (1, 0)
    assert reports["alpha"].updated == 0
    assert "Redis" in all_text(store)


def test_deleted_file_loses_its_chunks(cfg, store, corpus):
    run(cfg, store)
    (corpus.gamma / "notes.md").unlink()
    reports, _ = run(cfg, store)
    assert reports["gamma"].deleted == 1
    paths = {r[0] for r in store.db.execute("SELECT path FROM chunks WHERE project = 'gamma'")}
    assert paths == {"composer.json"}


def test_new_commits_are_added_incrementally(cfg, store, corpus):
    run(cfg, store)
    (corpus.beta / "CHANGELOG.md").write_text("# Changelog\n")
    commit(corpus.beta, "Add changelog", "CHANGELOG.md")
    reports, _ = run(cfg, store)
    assert (reports["beta"].commits, reports["beta"].added) == (1, 1)
    assert store.counts()["commit"] == 5


def test_rewritten_history_rebuilds_that_projects_commits(cfg, store, corpus):
    run(cfg, store)
    git(corpus.alpha, "commit", "-q", "--amend", "-m", "Add setup notes (amended)")
    reports, _ = run(cfg, store)
    assert reports["alpha"].commits == 3
    subjects = {
        r[0]
        for r in store.db.execute(
            "SELECT heading FROM chunks WHERE project = 'alpha' AND kind = 'commit'"
        )
    }
    assert "Add setup notes (amended)" in subjects
    assert "Add setup notes and env file" not in subjects
    assert store.counts()["commit"] == 4


def test_embedding_model_change_rebuilds_everything(cfg, store):
    run(cfg, store)
    other = FakeEmbedder()
    other.model = "other-model"
    reports, logs = run(cfg, store, other)
    assert any("embedding model changed" in line for line in logs)
    assert reports["alpha"].added == 4
    assert store.get_meta("embed_model") == "other-model"


def test_project_removed_from_config_is_dropped(home, corpus, store, cfg):
    run(cfg, store)
    smaller = write_config(home, {"alpha": corpus.alpha})
    _, logs = run(smaller, store)
    assert store.projects() == {"alpha"}
    assert any("no longer in the config" in line for line in logs)


def test_unlisted_sibling_directory_is_not_read(home, corpus, store):
    only_beta = write_config(home, {"beta": corpus.beta})
    run(only_beta, store)
    assert store.projects() == {"beta"}
    assert "rate limit" not in all_text(store).lower()


def test_missing_project_dir_is_an_error(home, tmp_path, store):
    bad = write_config(home, {"ghost": tmp_path / "nope"})
    with pytest.raises(WragError, match="ghost"):
        run(bad, store)


def test_excluded_paths_drop_files_and_commits_that_touch_only_them(home, corpus, store):
    (corpus.beta / "runs").mkdir()
    (corpus.beta / "runs" / "r1.md").write_text("# Run 1\n\nscore 0.5\n")
    commit(corpus.beta, "Add run 1", "runs")
    (home / "config.yaml").write_text(
        f"projects:\n  - {{name: beta, path: {corpus.beta}, exclude: [runs, package.json]}}\n"
    )
    reports, _ = run(config.load(home), store)
    paths = {r[0] for r in store.db.execute("SELECT path FROM chunks WHERE kind != 'commit'")}
    assert paths == {"README.md", "docs/notes.md"}
    assert reports["beta"].commits == 1  # "Initial dashboard" stays, "Add run 1" is dropped
