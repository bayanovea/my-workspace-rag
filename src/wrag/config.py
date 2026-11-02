import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from wrag.errors import WragError

DEFAULT_HOME = "~/.config/workspace-rag"


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    exclude: tuple[str, ...] = ()  # globs relative to the root; a match on a directory covers it


@dataclass
class Config:
    home: Path
    projects: list[Project] = field(default_factory=list)
    embed_url: str = "http://localhost:11434"
    embed_model: str = "bge-m3"
    generate_model: str = "sonnet"
    generate_timeout: float = 120.0
    k: int = 8
    max_file_bytes: int = 1_048_576
    max_chunk_chars: int = 2000

    @property
    def config_file(self) -> Path:
        return self.home / "config.yaml"

    @property
    def index_file(self) -> Path:
        return self.home / "index.db"

    @property
    def denylist_file(self) -> Path:
        return self.home / "denylist.txt"

    @property
    def questions_file(self) -> Path:
        return self.home / "eval" / "questions.yaml"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def claude_dir(self) -> Path:
        return self.home / "claude"


def resolve_home(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    home = Path(env.get("WRAG_HOME") or DEFAULT_HOME).expanduser().resolve()
    check_outside_git(home)
    return home


def check_outside_git(path: Path) -> None:
    probe = path
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=probe,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise WragError(
            f"data directory {path} is inside the git working tree {result.stdout.strip()}; "
            "private data must live outside any repository (set WRAG_HOME elsewhere)"
        )


def load(home: Path) -> Config:
    cfg = Config(home=home)
    if not cfg.config_file.exists():
        return cfg
    raw = yaml.safe_load(cfg.config_file.read_text()) or {}
    if not isinstance(raw, dict):
        raise WragError(f"{cfg.config_file}: expected a mapping at the top level")

    seen: set[str] = set()
    for i, p in enumerate(raw.get("projects") or []):
        name, path = (p or {}).get("name"), (p or {}).get("path")
        if not name or not path:
            raise WragError(f"{cfg.config_file}: projects[{i}] needs both name and path")
        if name in seen:
            raise WragError(f"{cfg.config_file}: duplicate project name at projects[{i}]")
        seen.add(name)
        exclude = p.get("exclude") or []
        if not isinstance(exclude, list):
            raise WragError(f"{cfg.config_file}: projects[{i}].exclude must be a list of globs")
        cfg.projects.append(
            Project(str(name), Path(path).expanduser().resolve(), tuple(map(str, exclude)))
        )

    embed = raw.get("embed") or {}
    generate = raw.get("generate") or {}
    retrieve = raw.get("retrieve") or {}
    limits = raw.get("limits") or {}
    cfg.embed_url = embed.get("url", cfg.embed_url).rstrip("/")
    cfg.embed_model = embed.get("model", cfg.embed_model)
    cfg.generate_model = generate.get("model", cfg.generate_model)
    cfg.generate_timeout = float(generate.get("timeout", cfg.generate_timeout))
    cfg.k = int(retrieve.get("k", cfg.k))
    cfg.max_file_bytes = int(limits.get("max_file_bytes", cfg.max_file_bytes))
    cfg.max_chunk_chars = int(limits.get("max_chunk_chars", cfg.max_chunk_chars))
    return cfg


def require_projects(cfg: Config) -> None:
    if not cfg.projects:
        raise WragError(f"no projects configured; add them under 'projects:' in {cfg.config_file}")
