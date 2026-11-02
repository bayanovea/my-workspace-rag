import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from wrag import config

TESTDATA = Path(__file__).parent.parent / "testdata" / "corpus"

# Built at runtime so that no token-shaped literal is ever committed.
FAKE_GITHUB_TOKEN = "ghp" + "_" + "A1b2C3d4" * 5


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch, tmp_path):
    """Keeps the user's git config (signing, hooks, templates) out of every git call in tests."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    (tmp_path / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(root: Path, message: str, *paths: str) -> str:
    git(root, "add", *paths)
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


@dataclass
class Corpus:
    root: Path
    alpha: Path
    beta: Path
    gamma: Path


@pytest.fixture
def corpus(tmp_path) -> Corpus:
    root = tmp_path / "projects"
    shutil.copytree(TESTDATA, root)
    alpha, beta, gamma = root / "alpha", root / "beta", root / "gamma"

    git(alpha, "init", "-q")
    commit(alpha, "Initial README and vendored lib", "README.md", "vendor")
    commit(
        alpha,
        "Add per-client rate limiter\n\nToken bucket per API key.",
        "go.mod",
        "docs/plans/rate-limit.md",
        "internal/ratelimit/limiter.go",
    )
    (alpha / ".env").write_text("DB_PASSWORD=hunter2hunter2\n")
    (alpha / "docs" / "setup.md").write_text(
        f"# Setup\n\n## CI\n\nThe deploy job uses the token {FAKE_GITHUB_TOKEN} for pushes.\n"
    )
    commit(alpha, "Add setup notes and env file", ".env", "docs/setup.md")
    (alpha / "notes.md").write_text("# Untracked\n\nNever indexed.\n")

    git(beta, "init", "-q")
    (beta / "logo.md").write_bytes(b"\x89PNG\x00\x00binary")
    commit(beta, "Initial dashboard", ".")
    return Corpus(root, alpha, beta, gamma)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "wrag-home"
    path.mkdir()
    monkeypatch.setenv("WRAG_HOME", str(path))
    return path


def write_config(home: Path, projects: dict[str, Path], **extra) -> config.Config:
    data = {"projects": [{"name": n, "path": str(p)} for n, p in projects.items()], **extra}
    (home / "config.yaml").write_text(yaml.safe_dump(data))
    return config.load(home)


@pytest.fixture
def cfg(home, corpus) -> config.Config:
    return write_config(home, {"alpha": corpus.alpha, "beta": corpus.beta, "gamma": corpus.gamma})
