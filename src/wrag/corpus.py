"""Which files of a project get indexed, and why the rest are skipped."""

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from wrag.config import Project

SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".next",
    ".nuxt",
    "bower_components",
}
SECRET_NAMES = [
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "credentials*",
    "secrets.*",
    ".npmrc",
    ".pypirc",
    ".netrc",
]
MANIFESTS = {
    "go.mod",
    "package.json",
    "composer.json",
    "pyproject.toml",
    "Cargo.toml",
    "requirements.txt",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
}
DOC_SUFFIXES = {".md", ".markdown"}
SNIFF_BYTES = 8192


@dataclass(frozen=True)
class SourceFile:
    rel: str
    abs: Path
    kind: str  # "doc" | "manifest"


@dataclass(frozen=True)
class Skipped:
    rel: str
    reason: str  # "secret-name" | "too-large" | "binary"


def is_git(root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def candidates(root: Path) -> list[str]:
    if is_git(root):
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
        ).stdout
        return sorted(p for p in out.split("\0") if p)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = Path(dirpath).relative_to(root)
        found += [(rel_dir / f).as_posix() for f in filenames]
    return sorted(found)


def kind_of(rel: str) -> str | None:
    name = PurePosixPath(rel).name
    if name in MANIFESTS:
        return "manifest"
    if PurePosixPath(rel).suffix.lower() in DOC_SUFFIXES:
        return "doc"
    return None


def is_secret_name(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_NAMES)


def is_excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    parts = rel.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    return any(fnmatch.fnmatch(p, pattern.rstrip("/")) for p in prefixes for pattern in patterns)


def select(project: Project, max_bytes: int) -> tuple[list[SourceFile], list[Skipped]]:
    files, skipped = [], []
    for rel in candidates(project.path):
        if any(part in SKIP_DIRS for part in PurePosixPath(rel).parts[:-1]):
            continue
        if is_excluded(rel, project.exclude):
            continue
        if is_secret_name(rel):
            skipped.append(Skipped(rel, "secret-name"))
            continue
        kind = kind_of(rel)
        if kind is None:
            continue
        path = project.path / rel
        # A symlink may point outside the allowlisted root.
        if not path.is_file() or not path.resolve().is_relative_to(project.path):
            continue
        if path.stat().st_size > max_bytes:
            skipped.append(Skipped(rel, "too-large"))
            continue
        with path.open("rb") as f:
            if b"\0" in f.read(SNIFF_BYTES):
                skipped.append(Skipped(rel, "binary"))
                continue
        files.append(SourceFile(rel, path, kind))
    return files, skipped
